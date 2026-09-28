from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

import board
import config
import discord_forum
from calendar import CalendarCoverageError
from conftest import example_buy_event
from discord_forum import DiscordForumClient
from engine import BoardEngine
from store import BoardStore


def at(value="2026-09-21T16:30:00+07:00"):
    return datetime.fromisoformat(value)


@pytest.fixture
def owner(tmp_path):
    client = Mock(spec=DiscordForumClient)
    client.execute.side_effect = lambda op, payload: {"thread_id": "123", "starter_message_id": "456"} if op == "create_thread" else {"message_id": "789"}
    client.prepare_payload.side_effect = lambda _op, payload: dict(payload)
    client.post_heartbeat.return_value = {"message_id": "1550000000000000001"}
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.submit(example_buy_event(), at("2026-09-21T09:00:00+07:00"))
    return engine


def test_initial_close_is_durable_without_synthetic_history(owner, monkeypatch):
    fetch = Mock(return_value=Decimal("210"))
    monkeypatch.setattr("engine.fetch_session_close", fetch)
    result = owner.after_close("initial", at())
    assert result["checked"] == 1
    assert owner.store.count_rows("checkpoints") == 1
    assert owner.store.count_rows("history_events") == 0
    owner.after_close("initial", at())
    assert fetch.call_count == 1
    owner.after_close("initial", at("2026-09-22T16:30:00+07:00"))
    assert owner.store.count_rows("checkpoints") == 2
    assert owner.store.count_rows("history_events") == 0
    edit = [op for op in owner.store.operations_for_ticker("SCMA") if op.operation == "edit_starter"][-1]
    assert edit.payload["chart"] is None
    assert not edit.payload.get("clear_attachments", False)


def test_lifecycle_command_queues_noop_heartbeat_and_drains(owner, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(owner.store.path))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(owner.store.path.parent / "media"))
    assert board.main(["reconcile-lifecycle"]) == 0
    output = capsys.readouterr().out
    assert "swing-board-lifecycle" in output
    assert "resolved=0" in output
    assert owner.store.count_rows("channel_outbox") == 1
    assert owner.store.pending_heartbeat_count() == 0


def test_retry_unavailable_keeps_last_facts_tags_and_no_history(owner, monkeypatch):
    monkeypatch.setattr("engine.fetch_session_close", lambda *args: Decimal("210"))
    owner.after_close("initial", at())
    before = owner.store.count_rows("history_events")
    monkeypatch.setattr("engine.fetch_session_close", lambda *args: None)
    owner.after_close("initial", at("2026-09-22T16:30:00+07:00"))
    assert owner.store.count_rows("checkpoints") == 1
    restarted = BoardEngine(BoardStore(owner.store.path), owner.client)
    restarted.after_close("retry", at("2026-09-22T17:00:00+07:00"))
    assert owner.store.count_rows("checkpoints") == 2
    assert owner.store.count_rows("history_events") == before
    assert owner.store.active_episode("SCMA").market_tag == "Entry zone"
    ops = owner.store.operations_for_ticker("SCMA")
    content = [op.payload["content"] for op in ops if op.operation == "edit_starter"][-1]
    assert "Market check unavailable" in content
    assert "210" in content and "21 Sep 2026 16:30 WIB" in content
    assert ops[-1].operation == "edit_starter"
    assert owner.store.count_rows("close_attempts") == 3


def test_retry_only_runs_after_an_unavailable_initial_for_the_same_plan(owner, monkeypatch):
    fetch = Mock(return_value=Decimal("210"))
    monkeypatch.setattr("engine.fetch_session_close", fetch)
    owner.after_close("retry", at("2026-09-21T17:00:00+07:00"))
    fetch.assert_not_called()
    assert owner.store.count_rows("close_attempts") == 0

    fetch.return_value = None
    owner.after_close("initial", at("2026-09-21T16:30:00+07:00"))
    fetch.return_value = Decimal("230")
    result = owner.after_close("retry", at("2026-09-21T17:00:00+07:00"))

    assert result["checked"] == 1
    assert owner.store.count_rows("close_attempts") == 2
    assert owner.store.count_rows("checkpoints") == 1
    assert owner.store.active_episode("SCMA") is None
    assert owner.store.episode(1).market_tag == "TP1 reached"


def test_initial_close_accepts_a_delayed_scheduler_start(owner, monkeypatch):
    fetch = Mock(return_value=Decimal("210"))
    monkeypatch.setattr("engine.fetch_session_close", fetch)

    result = owner.after_close("initial", at("2026-09-21T16:32:00+07:00"))

    assert result["checked"] == 1
    assert fetch.call_count == 1
    assert owner.store.count_rows("close_attempts") == 1


def test_retry_accepts_a_delayed_scheduler_start_after_initial_unavailable(owner, monkeypatch):
    fetch = Mock(side_effect=[None, Decimal("210")])
    monkeypatch.setattr("engine.fetch_session_close", fetch)

    owner.after_close("initial", at("2026-09-21T16:30:00+07:00"))
    result = owner.after_close("retry", at("2026-09-21T17:02:00+07:00"))

    assert result["checked"] == 1
    assert fetch.call_count == 2
    assert owner.store.count_rows("close_attempts") == 2


def test_initial_close_after_lateness_grace_is_a_noop(owner, monkeypatch):
    fetch = Mock(return_value=Decimal("210"))
    monkeypatch.setattr("engine.fetch_session_close", fetch)

    result = owner.after_close("initial", at("2026-09-21T16:35:00+07:00"))

    assert result["active"] == 0
    fetch.assert_not_called()
    assert owner.store.count_rows("close_attempts") == 0


def test_retry_after_lateness_grace_is_a_noop(owner, monkeypatch):
    fetch = Mock(return_value=None)
    monkeypatch.setattr("engine.fetch_session_close", fetch)

    owner.after_close("initial", at("2026-09-21T16:30:00+07:00"))
    result = owner.after_close("retry", at("2026-09-21T17:05:00+07:00"))

    assert result["active"] == 0
    assert fetch.call_count == 1
    assert owner.store.count_rows("close_attempts") == 1


@pytest.mark.parametrize("phase,instant", [("initial", "2026-09-21T16:29:00+07:00"), ("retry", "2026-09-21T17:00:00+07:00"), ("initial", "2026-09-19T16:30:00+07:00"), ("initial", "2026-12-25T16:30:00+07:00")])
def test_phase_gates_do_not_fetch_or_mutate(owner, monkeypatch, phase, instant):
    fetch = Mock()
    monkeypatch.setattr("engine.fetch_session_close", fetch)
    before = owner.store.operations_for_ticker("SCMA")
    owner.after_close(phase, at(instant))
    fetch.assert_not_called()
    assert owner.store.operations_for_ticker("SCMA") == before
    assert owner.store.count_rows("checkpoints") == 0


def test_cli_durable_acceptance_owns_media_even_when_delivery_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.png"
    source.write_bytes(b"image bytes")
    state = tmp_path / "owner.sqlite3"
    media = tmp_path / "media"
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(media))
    event = asdict(replace(example_buy_event(), media_path=str(source)))
    event["published_at"] = event["published_at"].isoformat()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    monkeypatch.setattr(DiscordForumClient, "execute", Mock(side_effect=RuntimeError("offline")))
    assert board.main(["submit-source-event", "--stdin"]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True
    store = BoardStore(state)
    plan = store.active_plan(store.active_episode("SCMA").id)
    assert Path(plan.media_path).parent == media
    assert Path(plan.media_path).read_bytes() == b"image bytes"
    assert Path(plan.media_path).stat().st_mode & 0o777 == 0o600
    assert media.stat().st_mode & 0o777 == 0o700
    assert store.operations_for_ticker("SCMA")[0].status == "pending"


def test_cli_acknowledgement_includes_the_materialized_topic_url(tmp_path, monkeypatch, capsys):
    state = tmp_path / "owner.sqlite3"
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "0")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setattr(
        discord_forum,
        "delivery_client_from_environment",
        lambda: discord_forum._FakeDeliveryClient(),
    )
    monkeypatch.setattr(
        DiscordForumClient,
        "execute",
        lambda _self, operation, _payload: (
            {"thread_id": "1549000000000000000", "starter_message_id": "1549000000000000001"}
            if getattr(operation, "operation", operation) == "create_thread"
            else {"message_id": "1549000000000000002"}
        ),
    )
    event = asdict(example_buy_event())
    event["published_at"] = event["published_at"].isoformat()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))

    assert board.main(["submit-source-event", "--stdin"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "accepted": True,
        "board_url": "https://discord.com/channels/940285152335110204/1549000000000000000",
    }


def test_no_post_cli_prints_one_heartbeat_without_http(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(tmp_path / "isolated.sqlite3"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setattr("requests.Session.request", Mock(side_effect=AssertionError("HTTP forbidden")))
    assert board.main(["after-close", "--phase", "initial"]) == 0
    output = capsys.readouterr().out
    assert output.count("🫀 bursawatch-dc-swing-board") == 1
    assert "active=0 checked=0 unavailable=0 pending=0" in output


def test_live_after_close_uses_its_frozen_heartbeat_route_and_reports_events(owner, monkeypatch, capsys):
    loaded = config.LoadedBoardConfig(
        config.BoardConfig(heartbeat_discord_channel_id="1505162000420835389"),
        13,
    )

    class CapturedRun:
        started: list[tuple[object, ...]] = []
        events: list[str] = []
        finished: list[tuple[str, str | None]] = []

        @classmethod
        def begin(cls, *args, **kwargs):
            cls.started.append((*args, kwargs))
            return cls()

        def event(self, event_id, **_kwargs):
            type(self).events.append(event_id)

        def finish(self, status, error=None):
            type(self).finished.append((status, error))

    class CloseClock:
        @staticmethod
        def now(_timezone):
            return at()

    monkeypatch.setattr(board, "ControlPlaneRun", CapturedRun)
    monkeypatch.setattr(board, "datetime", CloseClock)
    monkeypatch.setattr("engine.fetch_session_close", lambda *_args: None)

    assert board._after_close(owner, "initial", loaded) == 0

    owner.client.post_heartbeat.assert_called_once()
    assert owner.client.post_heartbeat.call_args.args[0] == "1505162000420835389"
    assert CapturedRun.started == [
        ("IDX_SWING_PLAN_BOARD", 13, {"scheduler_job_id": "bursawatch-dc-swing-board-close"})
    ]
    assert CapturedRun.events == [
        "run-started",
        "after-close-evaluated",
        "delivery-drain-completed",
        "run-completed",
    ]
    assert CapturedRun.finished == [("degraded", None)]
    assert "🫀 bursawatch-dc-swing-board" in capsys.readouterr().out


def test_live_config_failure_stops_before_the_board_store_opens(tmp_path, monkeypatch):
    state_path = tmp_path / "board.sqlite3"
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state_path))

    def unavailable():
        raise ValueError("control-plane is unavailable")

    monkeypatch.setattr(config, "load_board_config_for_run", unavailable)

    with pytest.raises(ValueError, match="control-plane"):
        board.main(["after-close", "--phase", "initial"])

    assert not state_path.exists()


def test_missing_calendar_coverage_emits_one_fatal_heartbeat_without_mutation(
    tmp_path, monkeypatch, capsys
):
    state = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(state))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    class MissingCoverageClock:
        @staticmethod
        def now(_timezone):
            return datetime.fromisoformat("2099-09-21T16:30:00+07:00")

    monkeypatch.setattr(board, "datetime", MissingCoverageClock)
    monkeypatch.setattr(
        "engine.is_idx_trading_day",
        Mock(side_effect=CalendarCoverageError("IDX holiday calendar is missing 2099")),
    )
    assert board.main(["after-close", "--phase", "initial"]) == 0

    output = capsys.readouterr().out
    assert output == "❌ bursawatch-dc-swing-board · 16:30 WIB · failed: calendar coverage unavailable\n"
    assert BoardStore(state).count_rows("checkpoints") == 0
    assert not hasattr(discord_forum, "requests")


def test_cli_rejects_watcher_supplied_database_path():
    with pytest.raises(SystemExit):
        board.main(["submit-source-event", "--stdin", "--database", "/tmp/not-owned.sqlite3"])


def test_title_migration_cli_requires_apply(monkeypatch, owner, capsys):
    owner.drain(now=at())
    with owner.store.transaction() as tx:
        episode = tx.episode(1)
        tx.update_episode(replace(episode, title="SCMA: Buy"))
    monkeypatch.setattr(board, "BoardStore", lambda _: owner.store)
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(owner.store.path))

    assert board.main(["migrate-titles"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "apply_required": True,
        "planned_episodes": 1,
    }


def test_no_post_wrapper_preserves_arguments_and_uses_isolated_owner_paths(tmp_path):
    root = Path(__file__).resolve().parent.parent
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "IDX_SWING_PLAN_BOARD_NO_POST": "1",
        "IDX_SWING_PLAN_BOARD_STATE_PATH": str(tmp_path / "isolated.sqlite3"),
        "IDX_SWING_PLAN_BOARD_MEDIA_ROOT": str(tmp_path / "media"),
        "IDX_SWING_PLAN_BOARD_PY": sys.executable,
        "IDX_SWING_PLAN_BOARD_SCRIPT": str(root / "bin/board.py"),
    }
    completed = subprocess.run(
        [str(root / "bin/bursawatch-dc-swing-board.sh"), "after-close", "--phase", "initial"],
        check=True, capture_output=True, text=True, env=env,
    )

    assert completed.stdout.count("🫀 bursawatch-dc-swing-board") == 1
    assert "active=0 checked=0 unavailable=0 pending=0" in completed.stdout
    assert BoardStore(env["IDX_SWING_PLAN_BOARD_STATE_PATH"]).pending_heartbeat_count() == 0
    assert BoardStore(env["IDX_SWING_PLAN_BOARD_STATE_PATH"]).count_rows("channel_outbox") == 1


def test_wrapper_optionally_loads_only_the_board_control_plane_settings():
    wrapper = (Path(__file__).resolve().parent.parent / "bin/bursawatch-dc-swing-board.sh").read_text()

    assert 'CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"' in wrapper
    assert 'DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"' in wrapper
    assert "DISCORD_BOT_TOKEN" not in wrapper
    for key in (
        "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL",
        "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_WATCHER_ID",
        "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_TOKEN",
        "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_TIMEOUT_SECONDS",
        "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_SPOOL_PATH",
    ):
        assert key in wrapper
