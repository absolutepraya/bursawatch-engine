from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import state as state_module

from domain import Classification, EventClass
from state import (
    StateBlockedError,
    advance_provider_cursor,
    complete_provider_bootstrap,
    claim_oldest_pending_analysis,
    clear_retry,
    empty_state,
    enqueue_candidate,
    expire_agent_leases,
    load_state,
    mark_terminal,
    mark_provider_bootstrap_complete,
    provider_bootstrap_complete,
    provider_cursor,
    run_lock,
    save_state,
    schedule_retry,
    submit_classification,
)


def test_state_round_trip_is_private_and_provider_cursors_are_independent(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    state = empty_state()

    advance_provider_cursor(state, "tuntun", 13597)
    assert mark_provider_bootstrap_complete(state, "phintraco") is True
    save_state(state)

    restored = load_state()
    assert set(restored) == {
        "version",
        "providers",
        "candidates",
        "dedupe",
        "digest_windows",
        "last_poll_success",
        "last_delivery_success",
        "last_heartbeat_hour",
        "last_error_notice",
        "stats",
    }
    assert restored["providers"]["tuntun"]["observed_message_id"] == 13597
    assert restored["providers"]["phintraco"]["observed_message_id"] == 0
    assert provider_cursor(restored, "tuntun") == 13597
    assert provider_bootstrap_complete(restored, "tuntun") is False
    assert provider_bootstrap_complete(restored, "phintraco") is True
    assert path.stat().st_mode & 0o777 == 0o600



def test_bootstrap_cursor_and_completion_are_saved_in_one_transition(monkeypatch):
    state = empty_state()
    writes = []

    monkeypatch.setattr(
        state_module,
        "save_state",
        lambda current_state: writes.append(
            (
                current_state["providers"]["tuntun"]["observed_message_id"],
                current_state["providers"]["tuntun"]["bootstrap_complete"],
            )
        ),
    )

    assert complete_provider_bootstrap(state, "tuntun", 13597) is True
    assert writes == [(13597, True)]


def test_load_state_migrates_valid_legacy_provider_lanes(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    legacy_state = empty_state()
    legacy_state["providers"]["tuntun"]["observed_message_id"] = 13597
    for lane in legacy_state["providers"].values():
        del lane["bootstrap_complete"]
    path.write_text(json.dumps(legacy_state), encoding="utf-8")
    os.chmod(path, 0o600)

    restored = load_state()
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert provider_bootstrap_complete(restored, "tuntun") is True
    assert provider_bootstrap_complete(restored, "phintraco") is False
    assert persisted["providers"]["tuntun"]["bootstrap_complete"] is True
    assert persisted["providers"]["phintraco"]["bootstrap_complete"] is False

def test_terminal_rank_suppression_never_requeues(tmp_path, monkeypatch, candidate):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime.fromisoformat("2026-07-14T08:00:00+07:00")

    enqueue_candidate(state, candidate, now)
    mark_terminal(state, candidate.key, "suppressed_rank")

    assert state["candidates"][candidate.key]["phase"] == "suppressed_rank"
    assert claim_oldest_pending_analysis(state, now + timedelta(days=1)) is None


def test_expired_agent_lease_returns_candidate_to_bounded_retry(tmp_path, monkeypatch, candidate):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime.fromisoformat("2026-07-14T08:00:00+07:00")

    enqueue_candidate(state, candidate, now)
    claimed = claim_oldest_pending_analysis(state, now)

    assert claimed is not None
    assert claimed.key == candidate.key
    assert state["candidates"][candidate.key]["phase"] == "awaiting_agent"

    expired = expire_agent_leases(state, datetime.fromisoformat("2026-07-14T08:03:00+07:00"))

    assert [item.key for item in expired] == [candidate.key]
    assert state["candidates"][candidate.key]["phase"] == "pending_analysis"
    assert state["candidates"][candidate.key]["retry"]["attempts"] == 1
    assert state["candidates"][candidate.key]["retry"]["next_attempt_at"] == "2026-07-14T08:04:00+07:00"


def test_claim_persists_one_oldest_due_candidate_before_returning(tmp_path, monkeypatch, candidate, later_candidate):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    state = empty_state()
    now = datetime.fromisoformat("2026-07-14T08:00:00+07:00")

    enqueue_candidate(state, later_candidate, now)
    enqueue_candidate(state, candidate, now - timedelta(minutes=1))
    save_state(state)

    claimed = claim_oldest_pending_analysis(state, now)

    assert claimed is not None
    assert claimed.key == candidate.key
    assert load_state()["candidates"][candidate.key]["phase"] == "awaiting_agent"
    assert state["candidates"][later_candidate.key]["phase"] == "pending_analysis"


def test_only_matching_unexpired_agent_lease_accepts_classification(tmp_path, monkeypatch, candidate, later_candidate):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime.fromisoformat("2026-07-14T08:00:00+07:00")
    selection = {
        "ranking_band": 1,
        "material_facts": ["contract value"],
        "dedupe_facts": ["counterparty", "contract duration"],
    }
    enqueue_candidate(state, candidate, now - timedelta(minutes=1))
    enqueue_candidate(state, later_candidate, now)
    claim_oldest_pending_analysis(state, now)

    with pytest.raises(StateBlockedError, match="not awaiting agent classification"):
        submit_classification(
            state,
            Classification(later_candidate, EventClass.CORPORATE_ACTION),
            now,
            selection,
        )

    submit_classification(
        state,
        Classification(candidate, EventClass.CORPORATE_ACTION),
        now + timedelta(minutes=1),
        selection,
    )

    record = state["candidates"][candidate.key]
    assert record["phase"] == "pending_selection"
    assert record["classification"] == "corporate_action"
    assert record["agent_lease_until"] is None
    assert record["selection"] == {**selection, "summary": "contract value"}


def test_retry_schedule_is_bounded_and_clearable(tmp_path, monkeypatch, candidate):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime.fromisoformat("2026-07-14T08:00:00+07:00")
    enqueue_candidate(state, candidate, now)

    for _ in range(10):
        retry = schedule_retry(state, candidate.key, now, "transient provider error")

    assert retry.attempt == 10
    assert state["candidates"][candidate.key]["retry"] == {
        "attempts": 10,
        "next_attempt_at": "2026-07-14T09:00:00+07:00",
        "last_error": "transient provider error",
    }

    clear_retry(state, candidate.key)

    assert state["candidates"][candidate.key]["retry"] == {
        "attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
    }


def test_nonempty_malformed_or_insecure_state_blocks_execution(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    path.write_text("{not json}", encoding="utf-8")
    os.chmod(path, 0o600)

    with pytest.raises(StateBlockedError, match="malformed"):
        load_state()

    path.write_text(json.dumps(empty_state()), encoding="utf-8")
    os.chmod(path, 0o644)

    with pytest.raises(StateBlockedError, match="permissions"):
        load_state()



def test_nonempty_whitespace_only_state_blocks_execution(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    path.write_text(" \t\n", encoding="utf-8")
    os.chmod(path, 0o600)

    with pytest.raises(StateBlockedError, match="malformed"):
        load_state()


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity", "1e999"))
def test_nonfinite_json_numbers_block_execution(tmp_path, monkeypatch, constant):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    state = empty_state()
    state["stats"] = {"nonfinite": 0.0}
    path.write_text(
        json.dumps(state).replace("0.0", constant),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)

    with pytest.raises(StateBlockedError, match="malformed"):
        load_state()
def test_run_lock_is_nonblocking_and_exclusive(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(state_path))
    bin_directory = Path(__file__).resolve().parents[1] / "bin"
    child_environment = os.environ | {
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(bin_directory), os.environ.get("PYTHONPATH")))
        )
    }
    child_script = (
        "from state import StateBlockedError, run_lock\n"
        "try:\n"
        "    with run_lock():\n"
        "        pass\n"
        "except StateBlockedError:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )

    with run_lock():
        result = subprocess.run(
            [sys.executable, "-c", child_script],
            check=False,
            env=child_environment,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
