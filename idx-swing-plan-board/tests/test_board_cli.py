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
    engine = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    engine.submit(example_buy_event(), at("2026-09-21T09:00:00+07:00"))
    return engine


def test_initial_close_is_durable_and_only_transitions_write_history(owner, monkeypatch):
    fetch = Mock(return_value=Decimal("210"))
    monkeypatch.setattr("engine.fetch_session_close", fetch)
    result = owner.after_close("initial", at())
    assert result["checked"] == 1
    assert owner.store.count_rows("checkpoints") == 1
    assert owner.store.count_rows("history_events") == 1
    owner.after_close("initial", at())
    assert fetch.call_count == 1
    owner.after_close("initial", at("2026-09-22T16:30:00+07:00"))
    assert owner.store.count_rows("checkpoints") == 2
    assert owner.store.count_rows("history_events") == 1
    edit = [op for op in owner.store.operations_for_ticker("SCMA") if op.operation == "edit_starter"][-1]
    assert edit.payload["chart"] is None
    assert not edit.payload.get("clear_attachments", False)


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
    assert owner.store.active_episode("SCMA").market_tag == "TP1 reached"


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
    assert store.operations_for_ticker("SCMA")[0].status == "pending"


def test_no_post_cli_prints_one_heartbeat_without_http(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_NO_POST", "1")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(tmp_path / "isolated.sqlite3"))
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setattr("requests.Session.request", Mock(side_effect=AssertionError("HTTP forbidden")))
    assert board.main(["after-close", "--phase", "initial"]) == 0
    output = capsys.readouterr().out
    assert output.count("🫀 idx-swing-plan-board") == 1
    assert "active=0 checked=0 unavailable=0 pending=0" in output


def test_cli_rejects_watcher_supplied_database_path():
    with pytest.raises(SystemExit):
        board.main(["submit-source-event", "--stdin", "--database", "/tmp/not-owned.sqlite3"])


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
        [str(root / "bin/idx-swing-plan-board.sh"), "after-close", "--phase", "initial"],
        check=True, capture_output=True, text=True, env=env,
    )

    assert completed.stdout.count("🫀 idx-swing-plan-board") == 1
    assert "active=0 checked=0 unavailable=0 pending=0" in completed.stdout
