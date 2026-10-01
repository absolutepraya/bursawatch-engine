from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

import config
import reconcile_source_ingest_state as reconcile
import state as state_module
from domain import Provider
from news_source_work import put_provenance
from state import StateBlockedError, empty_state, save_state


NOW = datetime.fromisoformat("2026-10-01T03:00:00+00:00")


def _add_candidate(state, candidate, *, phase="pending_analysis", event_key=None):
    key = candidate.key
    if event_key is None:
        event_key = hashlib.sha256(f"event:{key}".encode()).hexdigest()
    state["candidates"][key] = {
        "candidate": state_module._candidate_payload(candidate),
        "phase": phase,
        "enqueued_at": NOW.isoformat(),
        "retry": {"attempts": 0, "next_attempt_at": NOW.isoformat(), "last_error": None},
        "agent_lease_until": "2026-10-01T03:02:00+00:00" if phase == "awaiting_agent" else None,
        "classification": None,
        "selection": None,
    }
    return event_key


def _add_source_provenance(state, candidate, *, event_key=None, config_revision=7):
    if event_key is None:
        event_key = hashlib.sha256(f"event:{candidate.key}".encode()).hexdigest()
    capability = "company_news"
    work_key = hashlib.sha256(f"{event_key}:1:{capability}".encode()).hexdigest()
    handle = "tuntunsekuritas" if candidate.provider is Provider.TUNTUN else "phintasprofits"
    put_provenance(
        state,
        candidate.key,
        event_key=event_key,
        version=1,
        content_hash=hashlib.sha256(f"content:{candidate.key}".encode()).hexdigest(),
        source_url=f"https://t.me/{handle}/{candidate.source_message_id}",
        work_keys={capability: work_key},
        loaded_config=config.LoadedWatchConfig(config.default_watch_config(), config_revision),
    )


def _stock_status_event(message_id, *, phase="pending_delivery", provenance_fields=True):
    delivered = phase == "delivered"
    event = {
        "source_message_id": message_id,
        "source_url": f"https://t.me/phintasprofits/{message_id}",
        "phase": phase,
        "effective_date": "2026-09-30",
        "uma": ["DEWA"],
        "suspend_in": [],
        "suspend_out": [],
        "fca_in": [],
        "fca_out": [],
        "channel_id": "123",
        "content": f"Stock Status: Wed, 30 Sep 2026\\nDEWA",
        "enqueued_at": NOW.isoformat(),
        "retry": {"attempts": 0, "next_attempt_at": NOW.isoformat(), "last_error": None},
        "discord_message_id": "456" if delivered else None,
        "delivered_at": NOW.isoformat() if delivered else None,
        "rejection_code": None,
    }
    if provenance_fields:
        event["source_event_key"] = hashlib.sha256(f"event:{message_id}".encode()).hexdigest()
        event["config_revision"] = 7
    return event


def _source_state(candidate, source_only, tmp_path):
    state = empty_state()
    for item in (candidate, source_only):
        _add_candidate(state, item)
        _add_source_provenance(state, item)
    path = tmp_path / "package-local" / "state.json"
    path.parent.mkdir(mode=0o700)
    save_state(state, path)
    return state, path


def _canonical_state(candidate, tmp_path):
    state = empty_state()
    _add_candidate(state, candidate, phase="awaiting_agent")
    state["dedupe"]["existing"] = {"preserved": True}
    state["digest_windows"]["existing"] = [candidate.key]
    state["stats"]["delivery_payloads"] = {"existing": {"content": "already recorded"}}
    path = tmp_path / "canonical" / "idx-market-news.json"
    path.parent.mkdir(mode=0o700)
    save_state(state, path)
    return state, path


def test_merge_imports_source_only_candidate_and_provenance_without_changing_canonical(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    source_before = deepcopy(source_state)
    canonical_before = deepcopy(canonical_state)
    overlapping_record = deepcopy(canonical_state["candidates"][candidate.key])

    merged, report = reconcile.merge_states(source_state, canonical_state)

    assert report == {
        "source_candidate_count": 2,
        "source_provenance_count": 2,
        "new_candidate_count": 1,
        "overlap_count": 1,
        "phase_difference_count": 1,
        "provenance_added_count": 2,
        "source_status_event_count": 0,
        "new_status_event_count": 0,
        "overlap_status_event_count": 0,
        "status_event_phase_difference_count": 0,
        "status_event_provenance_added_count": 0,
        "active_candidate_abandonment_count": 2,
    }
    assert merged["candidates"][candidate.key] == overlapping_record
    assert merged["candidates"][later_candidate.key] == source_state["candidates"][later_candidate.key]
    assert set(merged["stats"]["news_source_work"]) == {candidate.key, later_candidate.key}
    assert merged["dedupe"] == canonical_before["dedupe"]
    assert merged["digest_windows"] == canonical_before["digest_windows"]
    assert merged["stats"]["delivery_payloads"] == canonical_before["stats"]["delivery_payloads"]
    assert merged["stats"].get("stock_status_events") == canonical_before["stats"].get(
        "stock_status_events"
    )
    assert source_state == source_before
    assert canonical_state == canonical_before


def test_merge_imports_terminal_stock_status_event_when_canonical_has_no_event_ledger(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    canonical_state["stats"].pop("stock_status_events", None)
    key = "phintraco-stock-status:35530"
    source_state["stats"]["stock_status_events"] = {
        key: _stock_status_event(35530, phase="delivered")
    }

    merged, report = reconcile.merge_states(source_state, canonical_state)

    assert merged["stats"]["stock_status_events"][key] == source_state["stats"]["stock_status_events"][key]
    assert report["source_status_event_count"] == 1
    assert report["new_status_event_count"] == 1
    assert report["overlap_status_event_count"] == 0


def test_merge_blocks_source_only_pending_stock_status_event(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    key = "phintraco-stock-status:35530"
    source_state["stats"]["stock_status_events"] = {
        key: _stock_status_event(35530, phase="pending_delivery")
    }

    with pytest.raises(StateBlockedError, match="unresolved delivery outcome"):
        reconcile.merge_states(source_state, canonical_state)


def test_merge_blocks_unresolved_canonical_candidate_delivery(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    canonical_state["candidates"][candidate.key]["phase"] = "pending_delivery"
    canonical_state["candidates"][candidate.key]["agent_lease_until"] = None

    with pytest.raises(StateBlockedError, match="canonical candidate delivery is unresolved"):
        reconcile.merge_states(source_state, canonical_state)


def test_merge_preserves_canonical_delivered_status_and_adds_missing_provenance(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    key = "phintraco-stock-status:35530"
    source_state["stats"]["stock_status_events"] = {
        key: _stock_status_event(35530, phase="pending_delivery")
    }
    canonical_event = _stock_status_event(
        35530, phase="delivered", provenance_fields=False
    )
    canonical_event["delivery_handoff"] = {
        "state": "accepted",
        "operation_key": "stock-status:35530",
        "receipt": {
            "id": "receipt-1",
            "key": "stock-status:35530",
            "digest": "a" * 64,
            "status": "delivered",
            "receipt": {"message_id": "456"},
        },
    }
    canonical_state["stats"]["stock_status_events"] = {key: canonical_event}

    merged, report = reconcile.merge_states(source_state, canonical_state)

    assert merged["stats"]["stock_status_events"][key]["phase"] == "delivered"
    assert merged["stats"]["stock_status_events"][key]["delivery_handoff"] == canonical_event["delivery_handoff"]
    assert merged["stats"]["stock_status_events"][key]["source_event_key"] == source_state["stats"]["stock_status_events"][key]["source_event_key"]
    assert report["status_event_phase_difference_count"] == 1
    assert report["status_event_provenance_added_count"] == 1


def test_merge_blocks_conflicting_stock_status_payload(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    key = "phintraco-stock-status:35530"
    source_state["stats"]["stock_status_events"] = {
        key: _stock_status_event(35530)
    }
    canonical_event = _stock_status_event(
        35530, phase="delivered", provenance_fields=False
    )
    canonical_event["content"] = "Different source payload"
    canonical_state["stats"]["stock_status_events"] = {key: canonical_event}

    with pytest.raises(StateBlockedError, match="identity or payload conflicts"):
        reconcile.merge_states(source_state, canonical_state)


def test_merge_rejects_non_boolean_source_migration_marker(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    source_state["stats"]["immediate_delivery_contract_v1"]["complete"] = 1

    with pytest.raises(StateBlockedError, match="expected completed default"):
        reconcile.merge_states(source_state, canonical_state)


def test_overlap_with_existing_provenance_preserves_canonical_config_snapshot(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    _add_source_provenance(canonical_state, candidate, config_revision=3)
    expected_origin = deepcopy(canonical_state["stats"]["news_source_work"][candidate.key])

    merged, report = reconcile.merge_states(source_state, canonical_state)

    assert report["provenance_added_count"] == 1
    assert merged["stats"]["news_source_work"][candidate.key] == expected_origin


def test_overlap_with_conflicting_candidate_payload_blocks(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    canonical_state["candidates"][candidate.key]["candidate"]["source_text"] = "different payload"

    with pytest.raises(StateBlockedError, match="payload conflicts"):
        reconcile.merge_states(source_state, canonical_state)


def test_overlap_with_conflicting_provenance_blocks(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    _add_source_provenance(canonical_state, candidate, event_key="f" * 64)

    with pytest.raises(StateBlockedError, match="provenance conflicts"):
        reconcile.merge_states(source_state, canonical_state)


def test_source_candidate_without_provenance_blocks(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    del source_state["stats"]["news_source_work"][later_candidate.key]
    canonical_state, _ = _canonical_state(candidate, tmp_path)

    with pytest.raises(StateBlockedError, match="every source candidate"):
        reconcile.merge_states(source_state, canonical_state)


def test_orphan_source_provenance_blocks(tmp_path, candidate, later_candidate):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    del source_state["candidates"][later_candidate.key]
    canonical_state, _ = _canonical_state(candidate, tmp_path)

    with pytest.raises(StateBlockedError, match="provenance has no candidate"):
        reconcile.merge_states(source_state, canonical_state)


def test_preview_is_read_only_private_and_omits_candidate_content(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    source_before = source_path.read_bytes()
    canonical_before = canonical_path.read_bytes()

    plan = reconcile.preview(source_path, canonical_path, plan_path)

    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan == saved_plan
    assert plan["new_candidate_count"] == 1
    assert plan["overlap_count"] == 1
    assert plan["active_candidate_abandonment_count"] == 2
    assert plan_path.stat().st_mode & 0o777 == 0o600
    assert source_path.read_bytes() == source_before
    assert canonical_path.read_bytes() == canonical_before
    serialized = plan_path.read_text(encoding="utf-8")
    assert candidate.source_text not in serialized
    assert later_candidate.source_text not in serialized
    assert "https://t.me/" not in serialized


def test_apply_merges_atomically_and_reapplying_same_plan_is_idempotent(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    plan = reconcile.preview(source_path, canonical_path, plan_path)
    source_before = source_path.read_bytes()
    canonical_record_before = deepcopy(canonical_state["candidates"][candidate.key])

    first = reconcile.apply(plan_path)
    merged = state_module.load_state(canonical_path, migrate=False)
    after_apply = canonical_path.read_bytes()
    second = reconcile.apply(plan_path)

    assert first["status"] == "applied"
    assert first["new_candidate_count"] == 1
    assert second["status"] == "already_applied"
    assert canonical_path.read_bytes() == after_apply
    assert source_path.read_bytes() == source_before
    assert merged["candidates"][candidate.key]["candidate"] == canonical_record_before["candidate"]
    assert merged["candidates"][candidate.key]["phase"] == "abandoned"
    assert merged["candidates"][candidate.key]["retry"]["last_error"] == (
        reconcile._FORWARD_ONLY_ABANDON_REASON
    )
    assert merged["candidates"][later_candidate.key]["phase"] == "abandoned"
    assert set(merged["stats"]["news_source_work"]) == {candidate.key, later_candidate.key}
    assert merged["stats"][reconcile.RECEIPT_KEY]["plan_sha256"] == plan["plan_sha256"]


def test_reapply_blocks_when_source_status_event_is_missing_after_receipt(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    key = "phintraco-stock-status:35530"
    source_state["stats"]["stock_status_events"] = {
        key: _stock_status_event(35530, phase="delivered")
    }
    save_state(source_state, source_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path)
    reconcile.apply(plan_path)

    canonical = state_module.load_state(canonical_path, migrate=False)
    canonical["stats"]["stock_status_events"].pop(key)
    save_state(canonical, canonical_path, migrate=False)

    with pytest.raises(
        StateBlockedError, match="source candidate or status-event data is incomplete"
    ):
        reconcile.apply(plan_path)


def test_apply_rejects_changed_source_after_preview_without_writing_target(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path)
    canonical_before = canonical_path.read_bytes()

    source_state["stats"]["news_source_work"].pop(later_candidate.key)
    save_state(source_state, source_path)

    with pytest.raises(StateBlockedError, match="source state changed"):
        reconcile.apply(plan_path)
    assert canonical_path.read_bytes() == canonical_before


def test_apply_rejects_changed_canonical_state_without_overwriting_it(
    tmp_path, candidate, later_candidate
):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path)

    canonical_state["dedupe"]["changed"] = {"after_preview": True}
    save_state(canonical_state, canonical_path)
    canonical_before = canonical_path.read_bytes()

    with pytest.raises(StateBlockedError, match="canonical state changed"):
        reconcile.apply(plan_path)
    assert canonical_path.read_bytes() == canonical_before


def test_apply_rejects_a_tampered_plan(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    plan = reconcile.preview(source_path, canonical_path, plan_path)
    plan["created_at"] = "2026-10-02T03:00:00+00:00"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    os.chmod(plan_path, 0o600)

    with pytest.raises(StateBlockedError, match="plan digest does not match"):
        reconcile.apply(plan_path)


def test_apply_rejects_inconsistent_status_event_plan_counts(
    tmp_path, candidate, later_candidate
):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    plan = reconcile.preview(source_path, canonical_path, plan_path)
    plan["new_status_event_count"] = 1
    plan["plan_sha256"] = reconcile._plan_digest(plan)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    os.chmod(plan_path, 0o600)

    with pytest.raises(StateBlockedError, match="plan counts are inconsistent"):
        reconcile.apply(plan_path)


def test_apply_can_resume_after_atomic_replace_before_directory_fsync(
    tmp_path, monkeypatch, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path)
    original_fsync = state_module._fsync_directory

    def fail_after_replace(directory):
        if Path(directory) == canonical_path.parent:
            raise OSError("simulated interruption after atomic replace")
        original_fsync(directory)

    monkeypatch.setattr(state_module, "_fsync_directory", fail_after_replace)
    with pytest.raises(StateBlockedError, match="unable to save state"):
        reconcile.apply(plan_path)
    monkeypatch.setattr(state_module, "_fsync_directory", original_fsync)

    result = reconcile.apply(plan_path)
    assert result["status"] == "already_applied"
    persisted = state_module.load_state(canonical_path, migrate=False)
    assert set(persisted["stats"]["news_source_work"]) == {
        candidate.key, later_candidate.key
    }


def test_preview_rejects_plan_inside_a_state_directory(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)

    with pytest.raises(StateBlockedError, match="outside both state directories"):
        reconcile.preview(source_path, canonical_path, source_path.parent / "plan.json")


def test_apply_fails_closed_when_source_state_lock_is_held(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path)
    canonical_before = canonical_path.read_bytes()

    with state_module.run_lock(source_path):
        with pytest.raises(StateBlockedError, match="run lock is already held"):
            reconcile.apply(plan_path)
    assert canonical_path.read_bytes() == canonical_before


def test_preview_rejects_symlinked_source_state(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    symlink = tmp_path / "source-link.json"
    symlink.symlink_to(source_path)

    with pytest.raises(StateBlockedError, match="regular non-symlink file"):
        reconcile.preview(symlink, canonical_path, tmp_path / "plans" / "plan.json")


def test_apply_rejects_symlinked_plan(tmp_path, candidate, later_candidate):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    _, canonical_path = _canonical_state(candidate, tmp_path)
    plan_path = tmp_path / "plans" / "plan.json"
    reconcile.preview(source_path, canonical_path, plan_path)
    symlink = tmp_path / "plan-link.json"
    symlink.symlink_to(plan_path)

    with pytest.raises(StateBlockedError, match="regular non-symlink file"):
        reconcile.apply(symlink)
