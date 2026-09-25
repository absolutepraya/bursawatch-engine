from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

import board
from conftest import example_buy_event, social_event
from discord_forum import DiscordForumClient
from engine import BoardEngine, source_outcome_state
from models import Checkpoint, MarketState, PlanLevels, SourceEvent
from render import discord_length, render_primary_card, render_source_replies, render_source_reply
from store import BoardStore


def at(day=21, hour=16, minute=30):
    return datetime.fromisoformat(f"2026-09-{day:02}T{hour:02}:{minute:02}:00+07:00")


@pytest.fixture
def owner(tmp_path):
    client = Mock(spec=DiscordForumClient)
    client.execute.side_effect = lambda op, payload: {"thread_id": "123", "starter_message_id": "456"} if op == "create_thread" else {"message_id": "789"}
    client.prepare_payload.side_effect = lambda _op, payload: dict(payload)
    client.post_heartbeat.return_value = {"message_id": "1550000000000000001"}
    return BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)


def test_each_session_delivers_its_own_tag_without_synthetic_history(owner, monkeypatch):
    event = replace(example_buy_event(), plan=PlanLevels("208 to 212", "<200", ("230", "240", "250")))
    owner.submit(event, at(hour=9, minute=0))
    for day, close in [(21, "210"), (22, "230"), (23, "240")]:
        monkeypatch.setattr("engine.fetch_session_close", lambda *_, close=close: Decimal(close))
        owner.after_close("initial", at(day))
        owner.drain(now=at(day))
    ops = owner.store.operations_for_ticker("SCMA")
    patches = [op for op in ops if op.operation == "patch_thread"]
    history = [op for op in ops if op.operation == "post_history_reply"]
    assert [op.payload["tag_names"] for op in patches] == [
        ["Primary plan", "Entry zone"], ["Primary plan", "TP1 reached"], ["Primary plan", "TP2 reached"]]
    assert history == []
    assert all(op.status == "complete" for op in patches)


@pytest.mark.parametrize("close,market", [("199", "Stop-loss breached"), ("230", "TP1 reached")])
def test_terminal_close_finishes_plan_and_delivers_resolution_once(owner, monkeypatch, close, market):
    owner.submit(example_buy_event(), at(hour=9, minute=0))
    original = owner.store.active_episode("SCMA")
    fetch = Mock(return_value=Decimal(close))
    monkeypatch.setattr("engine.fetch_session_close", fetch)
    owner.after_close("initial", at())
    resolved = owner.store.episode(original.id)
    assert (resolved.lifecycle, resolved.lifecycle_tag, resolved.market_tag) == ("resolved", "Resolved", market)
    assert owner.store.active_episode("SCMA") is None
    assert owner.store.active_plan(original.id) is None
    owner.after_close("retry", at(hour=17, minute=0))
    owner.after_close("initial", at(22))
    assert fetch.call_count == 1
    owner.drain(now=at(22))
    ops = owner.store.operations_for_ticker("SCMA")
    assert not any("Resolved:" in op.payload.get("content", "") for op in ops)
    assert not any(op.operation == "post_history_reply" for op in ops)
    assert [op.payload["tag_names"] for op in ops if op.operation == "patch_thread"] == [["Resolved", market]]
    assert not any(op.payload.get("archived") for op in ops)
    owner.submit(replace(example_buy_event(), event_key="later-buy"), at(22, 9, 0))
    assert owner.store.active_episode("SCMA").id != original.id


def test_final_target_beyond_tp5_resolves_with_the_tp6_market_tag(owner, monkeypatch):
    owner.submit(replace(example_buy_event(), plan=PlanLevels("208 to 212", "<200", ("230", "240", "250", "260", "270", "280"))), at(hour=9, minute=0))
    monkeypatch.setattr("engine.fetch_session_close", lambda *_: Decimal("270"))
    owner.after_close("initial", at())
    episode = owner.store.active_episode("SCMA")
    assert episode.lifecycle == "primary" and episode.market_tag == "TP5 reached"
    monkeypatch.setattr("engine.fetch_session_close", lambda *_: Decimal("280"))
    owner.after_close("initial", at(22))
    assert owner.store.active_episode("SCMA") is None
    ops = owner.store.operations_for_ticker("SCMA")
    assert not any(op.operation == "post_history_reply" for op in ops)
    assert [op.payload["tag_names"] for op in ops if op.operation == "patch_thread"][-1] == ["Resolved", "TP6 reached"]
    assert "**Target 6:** 280" in [op.payload["content"] for op in ops if op.operation == "edit_starter"][-1]


def test_invalid_plan_keeps_facts_and_other_ticker_still_reconciles_with_warning(owner, monkeypatch, capsys):
    bad = replace(example_buy_event(), plan=PlanLevels("208/212", "<200", ("230",)))
    owner.submit(bad, at(hour=9, minute=0))
    episode = owner.store.active_episode("SCMA")
    old = Checkpoint.market(session_date="2026-09-21", checked_at=at(hour=10, minute=0).isoformat(), close_price="210", state=MarketState.ENTRY_ZONE)
    owner.store.record_checkpoint(episode.id, old)
    owner.submit(example_buy_event("second", "RAJA"), at(hour=9, minute=0))
    monkeypatch.setattr("engine.fetch_session_close", lambda *_: Decimal("215"))
    monkeypatch.setattr(board, "BoardEngine", lambda *_: owner)
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(owner.store.path))
    clock = type("Clock", (), {"now": staticmethod(lambda _: at())})
    monkeypatch.setattr(board, "datetime", clock)
    assert board.main(["after-close", "--phase", "initial"]) == 0
    heartbeat = capsys.readouterr().out
    assert "checked=1" in heartbeat and "invalid=1" in heartbeat and heartbeat.rstrip().endswith("⚠️")
    with owner.store.transaction() as tx:
        assert tx.latest_checkpoints(episode.id) == (old, old)
    assert owner.store.count_rows("close_attempts") == 1
    assert owner.store.active_episode("RAJA").market_tag == "Above entry"


def test_fatal_reconciliation_emits_sanitized_heartbeat(owner, monkeypatch, capsys):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(owner.store.path))
    monkeypatch.setattr(board, "BoardEngine", lambda *_: owner)
    monkeypatch.setattr(owner, "after_close", Mock(side_effect=RuntimeError("raw secret value")))
    assert board.main(["after-close", "--phase", "initial"]) == 1
    assert capsys.readouterr().out == "❌ bursawatch-dc-swing-board · 16:30 WIB · failed: reconciliation failed\n"
    owner.client.post_heartbeat.assert_called_once()


def test_drain_reports_retained_failure_and_backoff_health(owner, monkeypatch, capsys):
    owner.submit(example_buy_event(), at(hour=9, minute=0))
    owner.client.execute.side_effect = RuntimeError("offline")
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_STATE_PATH", str(owner.store.path))
    monkeypatch.setattr(board, "BoardEngine", lambda *_: owner)
    # Explicit test time makes the pending event due without network calls.
    real_drain = owner.drain
    monkeypatch.setattr(owner, "drain", lambda: real_drain(now=at()))
    assert board.main(["drain"]) == 1
    assert json.loads(capsys.readouterr().out) == {"drained": 0, "pending": 1, "failed": 1}
    assert board.main(["drain"]) == 1
    assert json.loads(capsys.readouterr().out)["pending"] == 1
    assert owner.client.execute.call_count == 1


@pytest.mark.parametrize("source", ["x", "kelas-investasi", "phintraco"])
def test_all_adapter_replies_chunk_losslessly_at_utf16_boundary(source):
    event = replace(social_event("long", "SCMA", "SCMA: Source"), source=source,
                    all_content="A" * 1998 + "📊" + "B" * 2050 + "\n" + "words " * 300)
    chunks = render_source_replies(event)
    assert len(chunks) >= 3
    assert all(discord_length(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks) == render_source_reply(event)


def test_near_limit_primary_keeps_source_type_escaping_and_reserves_close_fields(owner):
    event = replace(example_buy_event(), all_content=(
        "### <:phintraco:1531272488645038091> SCMA: Buy\n-# Analyst, Investment Advisor\n\n"
        "**Type:** Trading Buy<:up:1531285100346740766>\n**Reasons:** " + r"support \*held\* " * 105))
    assert len(event.all_content) < 2000
    owner.submit(event, at(hour=9, minute=0))
    for checkpoint in (None, Checkpoint.market(session_date="2026-09-21", checked_at=at().isoformat(), close_price="225", state=MarketState.ABOVE_ENTRY),
                       Checkpoint.unavailable_at(session_date="2026-09-21", checked_at=at().isoformat())):
        card = render_primary_card(replace(event, source_status="Long source confirmation " * 30), checkpoint)
        assert discord_length(card) <= 2000
        assert "**Type:** Trading Buy <:up:1531285100346740766>" in card
        assert r"support \*held\*" in card and r"support \\\*held" not in card
    assert "**Entry:** 208 to 212" in card and "**Target 1:** 230" in card
    replies = [op.payload["content"] for op in owner.store.operations_for_ticker("SCMA") if op.operation == "post_source_reply"]
    assert "".join(replies) == render_source_reply(event)


def test_phintraco_source_reply_migration_uses_shared_shell_and_source_footer_analyst():
    event = replace(
        example_buy_event(),
        media_path="/tmp/source-chart.jpg",
        all_content=(
            "### <:phintraco:1531272488645038091> BUY: **SCMA**\n\n"
            "**Type:** Trading Buy<:up:1531285100346740766>\n"
            "**Entry:** 208 to 212\n**Stop-loss:** <200\n**Target:** 230\n"
            "**Signal date:** Fri, Sep 11 2026, 06:50 WIB\n\n"
            "**Reasons:** Support held.\n\n"
            "**Source:** [Phintraco Sekuritas](<https://t.me/phintraprofits/33655>) | "
            "Alrich Paskalis T, Investment Advisor"
        ),
    )
    rendered = render_source_reply(event)

    assert "### <:phintraco:1531272488645038091> SCMA: Buy" in rendered
    assert "-# Alrich Paskalis T, Phintraco Sekuritas" in rendered
    assert "**Type:** Trading Buy <:up:1531285100346740766>" in rendered
    assert "**Board:**" not in rendered
    assert rendered.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_source_reply_removes_the_all_swing_board_marker_when_status_cannot_be_canonicalized():
    event = replace(
        example_buy_event(),
        kind="status",
        plan=None,
        source_url="https://t.me/phintraprofits/35101",
        all_content=(
            "### <:phintraco:1531272488645038091> COIN: On support\n"
            "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
            "**Entry:** 800 to 815\n"
            "**Source status:** On support <:hold:1531284248235868333>\n"
            "**Last updated:** 9 Sep 2026 11:44 WIB\n"
            "**Board:** <#1548273399069933720>\n\n"
            "[View in Telegram](<https://t.me/phintraprofits/35101>)"
        ),
    )

    rendered = render_source_reply(event)

    assert "**Board:**" not in rendered
    assert rendered.endswith("[View in Telegram](<https://t.me/phintraprofits/35101>)")


def test_phintraco_outcome_fallback_keeps_blank_line_before_telegram_footer():
    event = replace(
        example_buy_event(),
        kind="social",
        plan=None,
        source_url="https://t.me/phintraprofits/35197",
        source_status="Second target 5000 achieved; All targets achieved",
        all_content=(
            "### <:phintraco:1531272488645038091> AMMN: Second target 5000 achieved\n"
            "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
            "**Source status:** Second target 5000 achieved <:green:1531274822221434911>\n"
            "**Last updated:** 14 Sep 2026 09:23 WIB\n"
            "[View in Telegram](<https://t.me/phintraprofits/35197>)"
        ),
    )

    rendered = render_source_reply(event)

    assert "**Last updated:** 14 Sep 2026 09:23 WIB\n\n[View in Telegram]" in rendered


def _phintraco_adapter():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "lib-telegram-resilience/bin"))
    spec = importlib.util.spec_from_file_location("phintraco_adapter", root / "cron-tg-phintraco-swing/bin/scan.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_large_target_ladder_compacts_labels_without_dropping_levels(owner):
    targets = tuple(str(1000 + index * 10) for index in range(70))
    event = replace(example_buy_event(), plan=PlanLevels("990", "900", targets),
                    all_content="**Chart:** Unavailable from source\n" + "\n".join(f"**Target {index}:** {level}" for index, level in enumerate(targets, 1)))
    checkpoint = Checkpoint.market(session_date="2026-09-21", checked_at=at().isoformat(), close_price="1010", state=MarketState.TP2_REACHED)
    card = render_primary_card(event, checkpoint)
    assert discord_length(card) <= 2000
    assert "**Targets:**" in card and "**Chart:** Unavailable from source" in card
    assert all(f"{index}: {level}" in card for index, level in enumerate(targets, 1))
    assert "**Market checkpoint:** TP2 reached" in card


@pytest.mark.parametrize("outcomes,expected,terminal", [
    (("First target 230 achieved", "Second target 240 achieved"), "TP2 reached", False),
    (("First target 230 achieved", "All targets achieved"), "TP3 reached", True),
    (("First target 230 achieved", "Stop-loss hit"), "Stop-loss breached", True),
    (("Target 250 achieved",), "TP3 reached", True),
])
def test_watcher_reminder_payload_is_interpreted_by_owner(owner, outcomes, expected, terminal):
    adapter = _phintraco_adapter()
    source = (Path(adapter.__file__).parent.parent / "tests/fixtures/trading_buy.txt").read_text()
    call = adapter.parse_swing_call(33655, source, has_photo=False)
    call = replace(call, event_kind="REMINDER", outcomes=outcomes)
    payload, _ = adapter.board_event_payload({}, call)
    incoming = SourceEvent.from_json(payload)
    plan = replace(example_buy_event("original-buy"), plan=PlanLevels("208 to 212", "<200", ("230", "240", "250")))
    assert source_outcome_state(incoming, plan).value == expected
    owner.submit(plan, at(hour=9, minute=0))
    owner.submit(incoming, at(hour=10, minute=0))
    assert (owner.store.active_episode("SCMA") is None) is terminal
    assert owner.store.episode(1).market_tag == expected


@pytest.mark.parametrize("script,clock", [("close", "16:30"), ("retry", "17:00")])
def test_scheduler_script_runs_without_arguments(tmp_path, script, clock):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "HOME": str(tmp_path), "IDX_SWING_PLAN_BOARD_NO_POST": "1",
           "IDX_SWING_PLAN_BOARD_STATE_PATH": str(tmp_path / "isolated.sqlite3"),
           "IDX_SWING_PLAN_BOARD_MEDIA_ROOT": str(tmp_path / "media"),
           "IDX_SWING_PLAN_BOARD_PY": sys.executable,
           "IDX_SWING_PLAN_BOARD_SCRIPT": str(root / "bin/board.py")}
    result = subprocess.run(["bash", str(root / f"bin/bursawatch-dc-swing-board-{script}.sh")], capture_output=True, text=True, env=env, check=True)
    assert result.stdout.count("🫀 bursawatch-dc-swing-board") == 1
    assert f"{clock} WIB" in result.stdout


@pytest.mark.parametrize("level", ["1.250", "1,250"])
def test_exact_source_target_confirmation_normalizes_thousands(level):
    plan = replace(example_buy_event(), plan=PlanLevels("1.100", "<1.000", ("1.250",)))
    confirmation = replace(example_buy_event(), kind="reminder", plan=None, source_status=f"Target {level} achieved")
    assert source_outcome_state(confirmation, plan) == MarketState.TP1_REACHED
