"""Bounded delivery draining (2026-10-16: a Board run held the Hermes serial lane for 36 minutes).

The Delivery Owner stalled, so every drain attempt took a client timeout. The outbox loop,
the heartbeat loop, the publication projection and the receipt wait were each bounded
(or not) on their own, and a run drained three times. These tests pin one shared budget.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

import board
import board_publication_projection as projection
import discord_forum
import engine as engine_module
from conftest import example_buy_event
from discord_forum import DiscordForumClient, DiscordForumError
from engine import BoardEngine
from store import BoardStore

ORIGIN = datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)


class FakeClock:
    """One simulated clock for wall time and the monotonic budget clock."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def monotonic(self) -> float:
        return self.seconds

    def wall(self) -> datetime:
        return ORIGIN + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()

    class SimulatedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake.wall() if tz is None else fake.wall().astimezone(tz)

    monkeypatch.setattr(engine_module, "datetime", SimulatedDatetime)
    return fake


def stalled_client(clock, *, seconds=40.0):
    """A Delivery Owner that answers every operation only after a client timeout."""
    client = Mock(spec=DiscordForumClient)
    client.prepare_payload.side_effect = lambda _op, payload: dict(payload)

    def stalled(*_args, **_kwargs):
        clock.advance(seconds)
        raise DiscordForumError("Delivery Owner acceptance could not be confirmed")

    client.execute.side_effect = stalled
    client.post_heartbeat.side_effect = stalled
    return client


def board_with_pending_replies(tmp_path, client, episodes):
    """Independent episodes, each with a materialised topic and one waiting reply."""
    store = BoardStore(tmp_path / "board.sqlite3")
    for index in range(episodes):
        ticker = f"TK{chr(65 + index)}"
        event = replace(example_buy_event(f"phintraco:setup:{index}", ticker),
                        source_title=f"{ticker}: Trading Buy")
        submitted = store.submit_event(event, ORIGIN)
        episode = store.create_episode(ticker, "primary", f"{ticker} - Fri, 16 Oct 2026", ORIGIN)
        with store.transaction() as tx:
            tx.update_episode(replace(episode, starter_source_event_id=submitted.id))
            tx.enqueue_outbox("create_thread", episode.id,
                              {"name": episode.title, "content": "Starter card", "applied_tag_ids": []},
                              f"board:starter:{index}", ORIGIN)
        created = store.claim_due_outbox(ORIGIN)
        store.complete_outbox(created.id, created.claim_token, {
            "thread_id": str(1525102458253217000 + index),
            "starter_message_id": str(1525102458253218000 + index)}, ORIGIN)
        store.enqueue_outbox("post_source_reply", episode.id, {"content": f"reply {index}"},
                             f"board:reply:{index}", ORIGIN)
    return BoardEngine(store, client)


def test_failing_heartbeat_is_attempted_once_per_drain_even_when_the_attempt_outlasts_its_backoff(tmp_path, clock):
    # Real incident shape: the attempt takes 70 s, longer than the first 1 minute backoff.
    client = stalled_client(clock, seconds=70.0)
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.enqueue_heartbeat("1505162000420835388", "🫀 board", "heartbeat:1", clock.wall())

    def guarded(*args, **kwargs):
        if client.post_heartbeat.call_count > 20:
            raise AssertionError("heartbeat re-claimed within one drain")
        clock.advance(70.0)
        raise DiscordForumError("stalled")

    client.post_heartbeat.side_effect = guarded
    engine.drain()

    assert client.post_heartbeat.call_count == 1
    assert engine.store.pending_heartbeat_count() == 1
    assert engine.store.outbox_health() == {"pending": 1, "failed": 1}


def test_drain_stops_at_the_elapsed_budget_and_keeps_every_pending_operation(tmp_path, clock):
    from drain_budget import DrainBudget

    client = stalled_client(clock, seconds=40.0)
    engine = board_with_pending_replies(tmp_path, client, episodes=10)
    engine.budget = DrainBudget(max_attempts=100, max_seconds=100, clock=clock.monotonic)

    engine.drain()

    # Attempts begin at 0 s, 40 s and 80 s; the one starting at 120 s is refused.
    assert client.execute.call_count == 3
    assert engine.budget.reason == "elapsed"
    assert engine.store.outbox_health() == {"pending": 10, "failed": 3}
    assert engine.store.count_rows("outbox") == 20  # 10 completed topic creates + 10 retained replies
    # A second drain in the same process cannot extend the run.
    engine.drain()
    assert client.execute.call_count == 3


def test_drain_stops_at_the_attempt_budget(tmp_path, clock):
    from drain_budget import DrainBudget

    client = stalled_client(clock, seconds=0.5)
    engine = board_with_pending_replies(tmp_path, client, episodes=10)
    engine.budget = DrainBudget(max_attempts=4, max_seconds=600, clock=clock.monotonic)

    engine.drain()

    assert client.execute.call_count == 4
    assert engine.budget.reason == "attempts"
    assert engine.store.outbox_health()["pending"] == 10


def test_heartbeats_share_the_budget_and_an_exhausted_run_still_gets_one_reserved_attempt(tmp_path, clock):
    from drain_budget import DrainBudget

    client = stalled_client(clock, seconds=40.0)
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.budget = DrainBudget(max_attempts=100, max_seconds=50, clock=clock.monotonic)
    for index in range(6):
        engine.enqueue_heartbeat("1505162000420835388", f"🫀 board {index}", f"heartbeat:{index}", clock.wall())

    engine.drain()
    assert client.post_heartbeat.call_count == 2
    assert engine.budget.reason == "elapsed"

    # The scheduled run's own heartbeat is reserved separate headroom.
    engine.drain(heartbeats_only=True)
    assert 3 <= client.post_heartbeat.call_count <= 2 + 2
    assert engine.store.pending_heartbeat_count() == 6


class PendingForever:
    """Delivery Owner double whose accepted operations never become terminal."""

    def __init__(self, clock):
        self.clock = clock
        self.waits = []

    def status(self, key):
        return None

    def submit(self, operation):
        from bursawatch_discord_delivery import OperationReceipt

        return OperationReceipt(id="op", key=operation.key, digest=operation.digest, status="pending", receipt=None)

    def wait(self, key, timeout_seconds):
        from bursawatch_discord_delivery import OperationReceipt

        self.waits.append(timeout_seconds)
        self.clock.advance(timeout_seconds)
        raise discord_forum.DeliveryClientError("timeout")


def test_receipt_wait_is_clamped_to_the_remaining_budget(clock):
    from drain_budget import DrainBudget

    delivery = PendingForever(clock)
    adapter = DiscordForumClient(delivery_client=delivery, no_post=False)
    adapter.budget = DrainBudget(max_attempts=10, max_seconds=13, clock=clock.monotonic)
    payload = {"thread_id": "1525102458253217890", "content": "reply", "nonce_value": "board:reply:1"}

    for _ in range(3):
        with pytest.raises(Exception):
            adapter.execute("post_source_reply", payload)

    # Full 10 s wait, then the 3 s that remain, then nothing.
    assert delivery.waits == [10, 3, 0]


def test_publication_projection_stops_at_the_budget_and_keeps_intents(tmp_path, clock, monkeypatch):
    from drain_budget import DrainBudget

    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")
    store = BoardStore(tmp_path / "board.sqlite3")
    intents = [{"owner_key": f"owner:{index}", "snapshot": {"_operation": "patch_thread", "_payload": {},
                                                           "owner_key": f"owner:{index}"}} for index in range(12)]
    monkeypatch.setattr(store, "pending_publication_intents", lambda _now: list(intents))
    monkeypatch.setattr(store, "fail_publication_intent", lambda *_a, **_k: None)
    monkeypatch.setattr(store, "all_publication_intents", lambda: [])
    seen = []

    def slow_snapshot(saved, _owner):
        seen.append(saved["owner_key"])
        clock.advance(30)
        return None

    monkeypatch.setattr(projection, "_build_snapshot", slow_snapshot)
    budget = DrainBudget(max_attempts=100, max_seconds=70, clock=clock.monotonic)

    projection.drain(store, clock.wall(), publication_client=Mock(), delivery_owner=Mock(), budget=budget)

    assert seen == ["owner:0", "owner:1", "owner:2"]
    assert budget.reason == "elapsed"


def test_one_budget_covers_every_drain_in_a_scheduled_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(tmp_path / "board.sqlite3"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_DRAIN_MAX_ATTEMPTS", "2")
    seeded = board_with_pending_replies(tmp_path, Mock(spec=DiscordForumClient), episodes=6)
    assert seeded.store.outbox_health()["pending"] == 6

    status = board.main(["drain"])

    report = json.loads(capsys.readouterr().out)
    assert status == 1
    assert report["drained"] == 2
    assert report["pending"] == 4
    assert report["stopped"] == "attempts"


def test_budget_exhaustion_is_visible_in_the_scheduled_heartbeat(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(tmp_path / "board.sqlite3"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_DRAIN_MAX_ATTEMPTS", "1")
    board_with_pending_replies(tmp_path, Mock(spec=DiscordForumClient), episodes=4)

    assert board.main(["reconcile-lifecycle"]) == 0

    heartbeat = capsys.readouterr().out
    assert "⚠️" in heartbeat
    assert "drain=attempts" in heartbeat


def test_an_empty_outbox_does_not_consume_the_attempt_a_due_heartbeat_needs(tmp_path, clock):
    from drain_budget import DrainBudget

    client = stalled_client(clock, seconds=1.0)
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.budget = DrainBudget(max_attempts=1, max_seconds=600, clock=clock.monotonic)
    engine.enqueue_heartbeat("1505162000420835388", "🫀 board", "heartbeat:1", clock.wall())

    engine.drain()

    assert client.post_heartbeat.call_count == 1
    assert engine.budget.reason is None


def test_a_drained_queue_is_not_reported_as_stopped(tmp_path, clock):
    from drain_budget import DrainBudget

    client = Mock(spec=DiscordForumClient)
    client.post_heartbeat.return_value = {"message_id": "1"}
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.budget = DrainBudget(max_attempts=1, max_seconds=600, clock=clock.monotonic)
    engine.enqueue_heartbeat("1505162000420835388", "🫀 board", "heartbeat:1", clock.wall())

    assert engine.drain() == 1
    assert engine.drain_stopped() is None


def test_the_scheduled_heartbeat_is_reached_before_older_due_heartbeats(tmp_path, clock):
    from drain_budget import DrainBudget

    client = stalled_client(clock, seconds=1.0)
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.budget = DrainBudget(max_attempts=100, max_seconds=600, clock=clock.monotonic)
    for index in range(5):
        engine.enqueue_heartbeat("1505162000420835388", f"🫀 old {index}", f"old:{index}", clock.wall())
    engine.enqueue_heartbeat("1505162000420835388", "🫀 scheduled", "scheduled:1", clock.wall())
    sent = []
    client.post_heartbeat.side_effect = lambda _channel, content, operation_key: (
        sent.append(operation_key), {"message_id": str(len(sent))})[1]

    engine.drain(heartbeats_only=True, priority_heartbeat="scheduled:1")

    assert sent[0] == "scheduled:1"
    assert len(sent) == 2  # reserved headroom is two attempts


def test_budget_stop_with_publication_work_pending_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(tmp_path / "board.sqlite3"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_DRAIN_MAX_ATTEMPTS", "1")
    monkeypatch.setattr(BoardStore, "outbox_health", lambda self: {"pending": 0, "failed": 0})
    monkeypatch.setattr(engine_module.BoardEngine, "drain_stopped", lambda self: "attempts")

    assert board.main(["drain"]) == 1
    assert json.loads(capsys.readouterr().out)["stopped"] == "attempts"


def test_checkpoint_is_not_called_after_the_budget_stops_projection(tmp_path, clock, monkeypatch):
    from drain_budget import DrainBudget

    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")
    store = BoardStore(tmp_path / "board.sqlite3")
    intents = [{"owner_key": f"owner:{index}", "snapshot": {}} for index in range(3)]
    monkeypatch.setattr(store, "pending_publication_intents", lambda _now: list(intents))
    monkeypatch.setattr(store, "fail_publication_intent", lambda *_a, **_k: None)
    monkeypatch.setattr(store, "all_publication_intents", lambda: [])
    monkeypatch.setattr(projection, "_build_snapshot", lambda *_a: None)
    publication = Mock()
    budget = DrainBudget(max_attempts=1, max_seconds=600, clock=clock.monotonic)

    projection.drain(store, clock.wall(), publication_client=publication, delivery_owner=Mock(), budget=budget)

    assert budget.reason == "attempts"
    publication.checkpoint.assert_not_called()
