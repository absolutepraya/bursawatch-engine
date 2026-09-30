from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import board_publication_projection as projection
import discord_forum
from conftest import example_buy_event
from store import BoardStore


def at(value: str | int = "2026-09-30T12:00:00+00:00") -> datetime:
    if isinstance(value, int):
        return datetime.fromisoformat("2026-09-30T12:00:00+00:00").replace(minute=value)
    return datetime.fromisoformat(value)


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")


def _completed_starter(store: BoardStore) -> tuple[int, str]:
    event = replace(example_buy_event("phintraco:setup:1"), source_title="BBCA: Trading Buy")
    submitted = store.submit_event(event, at())
    episode = store.create_episode("BBCA", "primary", "BBCA - Wed, 30 Sep 2026", at())
    with store.transaction() as tx:
        tx.update_episode(replace(episode, starter_source_event_id=submitted.id))
        op = tx.enqueue_outbox("create_thread", episode.id,
            {"name": episode.title, "content": "Confirmed starter card", "applied_tag_ids": []},
            "board:starter:1", at())
    claimed = store.claim_due_outbox(at())
    assert claimed is not None
    store.complete_outbox(claimed.id, claimed.claim_token, {
        "thread_id": "1525102458253217890", "starter_message_id": "1525102458253217891"
    }, at())
    return episode.id, op.dedupe_key


def test_board_reply_links_parent_publication_and_store_recovery(monkeypatch, tmp_path):
    _enable(monkeypatch)
    path = tmp_path / "board.sqlite3"
    store = BoardStore(path)
    episode_id, starter_key = _completed_starter(store)
    reply = store.enqueue_outbox("post_source_reply", episode_id,
        {"content": "Source history reply", "thread_id": "1525102458253217890"},
        "event:phintraco:setup:1:post_source_reply:0", at())
    claimed = store.claim_due_outbox(at())
    assert claimed is not None and claimed.id == reply.id
    store.complete_outbox(claimed.id, claimed.claim_token, {"message_id": "1525102458253217892"}, at())

    reopened = BoardStore(path)
    rows = reopened.all_publication_intents()
    starter = next(row for row in rows if row["owner_key"] == starter_key)
    reply_row = next(row for row in rows if row["owner_key"] == "event:phintraco:setup:1:post_source_reply:0")
    assert starter["snapshot"]["parent_publication_id"] == _publication_identity(
        "bursawatch-tg-phintraco-swing", "phintraco:phintraco:setup:1"
    )
    assert reply_row["snapshot"]["parent_publication_id"] == projection.publication_id(starter_key)
    assert reply_row["snapshot"]["source_event_key"] == "phintraco:setup:1"
    assert len(rows) == 2


def _publication_identity(owner_id: str, owner_key: str) -> str:
    from store import _publication_identity as identity
    return identity(owner_id, owner_key)


def test_board_projection_failure_does_not_repost(monkeypatch, tmp_path):
    _enable(monkeypatch)
    store = BoardStore(tmp_path / "board.sqlite3")
    _completed_starter(store)

    from bursawatch_discord_delivery import OperationReceipt

    class DeliveryLookup:
        status_calls = 0
        send_calls = 0

        def status(self, key):
            self.status_calls += 1
            saved = store.pending_publication_intents(at())[0]["snapshot"]
            intent = discord_forum.DiscordForumClient(no_post=True)._intent(
                saved["_operation"], saved["_payload"], saved["owner_key"]
            )
            assert intent.key == key
            return OperationReceipt(
                id="receipt-operation-1", key=intent.key, digest=intent.digest,
                status="delivered", receipt={"thread_id": "1525102458253217890", "message_id": "1525102458253217891"},
            )

        def submit(self, *_args, **_kwargs):
            self.send_calls += 1
            raise AssertionError("projection must never submit Discord operations")

    class ApiOutage:
        def submit(self, _snapshot):
            raise OSError("API down")

        def checkpoint(self, _comparison):
            raise OSError("API down")

    delivery = DeliveryLookup()
    before = store.count_rows("outbox")
    result = projection.drain(store, at(), publication_client=ApiOutage(), delivery_owner=delivery)

    assert result["pending"] == 1
    assert delivery.status_calls == 1
    assert delivery.send_calls == 0
    assert store.count_rows("outbox") == before


def test_board_lifecycle_intent_and_incomplete_outbox(monkeypatch, tmp_path):
    _enable(monkeypatch)
    store = BoardStore(tmp_path / "board.sqlite3")
    episode_id, starter_key = _completed_starter(store)
    incomplete = store.enqueue_outbox("edit_starter", episode_id,
        {"content": "Lifecycle card", "thread_id": "1525102458253217890", "message_id": "1525102458253217891"},
        "board:lifecycle:pending", at())
    pending = store.claim_due_outbox(at())
    assert pending is not None and pending.id == incomplete.id
    assert not any(row["owner_key"] == "board:lifecycle:pending" for row in store.all_publication_intents())
    store.complete_outbox(pending.id, pending.claim_token, {}, at())
    lifecycle = store.enqueue_outbox("patch_thread", episode_id,
        {"name": "BBCA - Wed, 30 Sep 2026", "thread_id": "1525102458253217890", "applied_tag_ids": [], "archived": False},
        "board:lifecycle:complete", at())
    completed = store.claim_due_outbox(at(6))
    assert completed is not None and completed.id == lifecycle.id
    store.complete_outbox(completed.id, completed.claim_token, {}, at(6))

    rows = store.all_publication_intents()
    lifecycle_row = next(row for row in rows if row["owner_key"] == "board:lifecycle:complete")
    assert lifecycle_row["snapshot"]["parent_publication_id"] == projection.publication_id(starter_key)
    assert any(row["owner_key"] == "board:lifecycle:pending" for row in rows)
