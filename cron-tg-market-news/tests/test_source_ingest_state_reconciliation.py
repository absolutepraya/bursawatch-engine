from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

import config
import delivery
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


def _attach_pending_delivery_payload(state, candidate, *, saved_receipt=None):
    record = state["candidates"][candidate.key]
    record["phase"] = "pending_delivery"
    record["agent_lease_until"] = None
    content = "Previously accepted Market News output"
    channel_id = "123"
    operation = delivery._channel_message_operation(
        content, channel_id, f"{candidate.key}:text"
    )
    delivery_payloads = state["stats"].setdefault("delivery_payloads", {})
    delivery_payloads[candidate.key] = {
        "content": content,
        "nonce": "safe-test-nonce",
        "enforce_nonce": True,
        "channel_id": channel_id,
        "required_operation_keys": [operation.key],
        "text_discord_id": None,
        "image_discord_id": None,
        "image_error": None,
        "delivery_handoff": {
            "state": "accepted" if saved_receipt is not None else "unknown",
            "operation_key": operation.key,
            "receipt": saved_receipt,
        }
    }
    return operation


class _StatusOnlyDeliveryClient:
    def __init__(self, receipts):
        self.receipts = receipts
        self.status_calls = []

    def status(self, operation_key):
        self.status_calls.append(operation_key)
        return self.receipts.get(operation_key)

    def submit(self, *_args, **_kwargs):
        raise AssertionError("reconciliation must never submit a delivery operation")

    def wait(self, *_args, **_kwargs):
        raise AssertionError("reconciliation must never wait on a delivery operation")


def _owner_delivered_receipt(operation, message_id="456"):
    return delivery.OperationReceipt(
        id="owner-receipt",
        key=operation.key,
        digest=operation.digest,
        status="delivered",
        receipt={"message_id": message_id, "channel_id": operation.target["channel_id"]},
    )


def _write_legacy_applied_merge(source_state, source_path, canonical_state, canonical_path, plan_path):
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    canonical_sha256 = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    merged, report = reconcile.merge_states(source_state, canonical_state)
    assert state_module.abandon_active_candidates(merged, reconcile._FORWARD_ONLY_ABANDON_REASON) == (
        report["active_candidate_abandonment_count"]
    )
    legacy_plan = {
        "version": 1,
        "source_state_path": str(source_path),
        "canonical_state_path": str(canonical_path),
        "source_state_sha256": source_sha256,
        "canonical_state_sha256": canonical_sha256,
        **{field: report[field] for field in reconcile._LEGACY_REPORT_FIELDS_V1},
        "created_at": NOW.isoformat(),
    }
    legacy_plan["plan_sha256"] = reconcile._plan_digest(legacy_plan)
    plan_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(legacy_plan), encoding="utf-8")
    os.chmod(plan_path, 0o600)
    receipt = {
        "version": 1,
        "plan_sha256": legacy_plan["plan_sha256"],
        "source_state_sha256": source_sha256,
        "canonical_base_sha256": canonical_sha256,
        **{field: report[field] for field in reconcile._LEGACY_REPORT_FIELDS_V1},
        "applied_at": NOW.isoformat(),
    }
    merged["stats"][reconcile.RECEIPT_KEY] = receipt
    save_state(merged, canonical_path, migrate=False)
    return receipt


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
        "canonical_pending_delivery_count": 0,
        "canonical_pending_delivery_confirmed_count": 0,
        "canonical_pending_delivery_not_found_count": 0,
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


def test_merge_keeps_canonical_pending_stock_status_as_a_blocker(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    canonical_state["stats"]["stock_status_events"] = {
        "phintraco-stock-status:35530": _stock_status_event(35530)
    }

    with pytest.raises(StateBlockedError, match="canonical stock-status delivery is unresolved"):
        reconcile.merge_states(source_state, canonical_state)


def test_merge_blocks_unresolved_canonical_candidate_delivery(
    tmp_path, candidate, later_candidate
):
    source_state, _ = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, _ = _canonical_state(candidate, tmp_path)
    canonical_state["candidates"][candidate.key]["phase"] = "pending_delivery"
    canonical_state["candidates"][candidate.key]["agent_lease_until"] = None

    with pytest.raises(StateBlockedError, match="complete Delivery Owner verification"):
        reconcile.merge_states(source_state, canonical_state)


def test_preview_and_apply_verify_delivered_and_missing_owner_operations_without_sending(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    delivered_operation = _attach_pending_delivery_payload(canonical_state, candidate)
    local_pending_receipt = {
        "id": "local-pending-receipt",
        "key": delivered_operation.key,
        "digest": delivered_operation.digest,
        "status": "pending",
        "receipt": None,
    }
    canonical_state["stats"]["delivery_payloads"][candidate.key]["delivery_handoff"] = {
        "state": "accepted",
        "operation_key": delivered_operation.key,
        "receipt": local_pending_receipt,
    }
    _add_candidate(canonical_state, later_candidate, phase="pending_delivery")
    missing_operation_key = delivery._operation_key(later_candidate.key, "text")
    save_state(canonical_state, canonical_path)

    client = _StatusOnlyDeliveryClient(
        {delivered_operation.key: _owner_delivered_receipt(delivered_operation)}
    )
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    source_before = source_path.read_bytes()
    canonical_before = canonical_path.read_bytes()

    plan = reconcile.preview(
        source_path, canonical_path, plan_path, delivery_client=client
    )

    assert plan["canonical_pending_delivery_count"] == 2
    assert plan["canonical_pending_delivery_confirmed_count"] == 1
    assert plan["canonical_pending_delivery_not_found_count"] == 1
    assert len(plan["delivery_resolution_sha256"]) == 64
    assert source_path.read_bytes() == source_before
    assert canonical_path.read_bytes() == canonical_before
    assert set(client.status_calls) == {delivered_operation.key, missing_operation_key}

    applied = reconcile.apply(plan_path, delivery_client=client)
    persisted = state_module.load_state(canonical_path, migrate=False)
    delivered_record = persisted["stats"]["delivery_payloads"][candidate.key]
    assert applied["status"] == "applied"
    assert applied["active_candidate_abandonment_count"] == 1
    assert persisted["candidates"][candidate.key]["phase"] == "delivered"
    assert persisted["candidates"][later_candidate.key]["phase"] == "abandoned"
    assert delivered_record["text_discord_id"] == "456"
    assert delivered_record["delivery_handoff"]["receipt"] == {
        "id": "owner-receipt",
        "key": delivered_operation.key,
        "digest": delivered_operation.digest,
        "status": "delivered",
        "receipt": {"message_id": "456", "channel_id": "123"},
    }
    assert persisted["stats"][reconcile.RECEIPT_KEY]["delivery_resolution_sha256"] == plan[
        "delivery_resolution_sha256"
    ]
    assert persisted["stats"][reconcile.RECEIPT_KEY]["version"] == 2
    assert persisted["stats"][reconcile.RECEIPT_KEY]["prior_receipt_sha256"] is None
    assert source_path.read_bytes() == source_before
    assert reconcile.apply(plan_path, delivery_client=client)["status"] == "already_applied"
    assert len(client.status_calls) == 4


def test_finalize_legacy_receipt_preserves_delivered_work_and_abandons_not_found_work(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    legacy_plan_path = tmp_path / "plans" / "market-news-state-reconciliation-v1.json"
    legacy_receipt = _write_legacy_applied_merge(
        source_state, source_path, canonical_state, canonical_path, legacy_plan_path
    )

    delivered_candidate = replace(
        candidate, source_message_id=candidate.source_message_id + 1000, candidate_id=""
    )
    missing_candidate = replace(
        later_candidate, source_message_id=later_candidate.source_message_id + 1000, candidate_id=""
    )
    canonical = state_module.load_state(canonical_path, migrate=False)
    _add_candidate(canonical, delivered_candidate, phase="pending_delivery")
    delivered_operation = _attach_pending_delivery_payload(canonical, delivered_candidate)
    _add_candidate(canonical, missing_candidate, phase="pending_delivery")
    missing_operation = _attach_pending_delivery_payload(canonical, missing_candidate)
    save_state(canonical, canonical_path, migrate=False)

    client = _StatusOnlyDeliveryClient(
        {delivered_operation.key: _owner_delivered_receipt(delivered_operation, "456")}
    )
    plan_path = tmp_path / "plans" / "market-news-state-reconciliation-v3.json"
    source_before = source_path.read_bytes()
    canonical_before = canonical_path.read_bytes()

    plan = reconcile.preview(
        source_path,
        canonical_path,
        plan_path,
        legacy_plan_file=legacy_plan_path,
        delivery_client=client,
    )

    assert plan["mode"] == "finalize_legacy"
    assert plan["prior_receipt_sha256"] == hashlib.sha256(
        reconcile._json_bytes(legacy_receipt)
    ).hexdigest()
    assert plan["prior_plan_sha256"] == legacy_receipt["plan_sha256"]
    assert plan["canonical_pending_delivery_count"] == 2
    assert plan["canonical_pending_delivery_confirmed_count"] == 1
    assert plan["canonical_pending_delivery_not_found_count"] == 1
    assert plan["active_candidate_abandonment_count"] == 1
    assert source_path.read_bytes() == source_before
    assert canonical_path.read_bytes() == canonical_before

    result = reconcile.apply(plan_path, delivery_client=client)
    persisted = state_module.load_state(canonical_path, migrate=False)
    assert result["status"] == "legacy_finalized"
    assert persisted["candidates"][delivered_candidate.key]["phase"] == "delivered"
    assert persisted["candidates"][missing_candidate.key]["phase"] == "abandoned"
    assert persisted["candidates"][missing_candidate.key]["retry"]["last_error"] == (
        reconcile._FORWARD_ONLY_ABANDON_REASON
    )
    assert persisted["candidates"][candidate.key]["phase"] == "abandoned"
    assert persisted["candidates"][later_candidate.key]["phase"] == "abandoned"
    assert persisted["stats"][reconcile.RECEIPT_KEY]["version"] == 2
    assert persisted["stats"][reconcile.RECEIPT_KEY]["prior_receipt_sha256"] == plan[
        "prior_receipt_sha256"
    ]
    assert source_path.read_bytes() == source_before
    applied_state = canonical_path.read_bytes()
    assert reconcile.apply(plan_path, delivery_client=client)["status"] == "already_applied"
    assert canonical_path.read_bytes() == applied_state
    assert len(client.status_calls) == 4
    assert set(client.status_calls) == {delivered_operation.key, missing_operation.key}


def test_apply_rejects_delivery_owner_receipt_change_after_preview(
    tmp_path, candidate, later_candidate
):
    _, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    operation = _attach_pending_delivery_payload(canonical_state, candidate)
    save_state(canonical_state, canonical_path)
    client = _StatusOnlyDeliveryClient(
        {operation.key: _owner_delivered_receipt(operation, "456")}
    )
    plan_path = tmp_path / "plans" / "market-news-merge.json"
    reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    canonical_before = canonical_path.read_bytes()
    client.receipts[operation.key] = _owner_delivered_receipt(operation, "789")

    with pytest.raises(StateBlockedError, match="Delivery Owner outcomes changed"):
        reconcile.apply(plan_path, delivery_client=client)
    assert canonical_path.read_bytes() == canonical_before


def test_preview_and_apply_accept_saved_legacy_handoff_operation(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    ordinary_operation = _attach_pending_delivery_payload(canonical_state, candidate)
    payload = canonical_state["stats"]["delivery_payloads"][candidate.key]
    legacy_operation = delivery._channel_message_operation(
        payload["content"],
        payload["channel_id"],
        f"{candidate.key}:text",
        reconcile_before_first_create=True,
        legacy_nonce=payload["nonce"],
    )
    assert legacy_operation.key == ordinary_operation.key
    assert legacy_operation.digest != ordinary_operation.digest
    saved_receipt = _owner_delivered_receipt(legacy_operation)
    payload["delivery_handoff"] = {
        "state": "accepted",
        "operation_key": legacy_operation.key,
        "receipt": {
            "id": saved_receipt.id,
            "key": saved_receipt.key,
            "digest": saved_receipt.digest,
            "status": saved_receipt.status,
            "receipt": saved_receipt.receipt,
        },
    }
    save_state(canonical_state, canonical_path)
    client = _StatusOnlyDeliveryClient({legacy_operation.key: saved_receipt})
    plan_path = tmp_path / "plans" / "market-news-merge.json"

    plan = reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    assert plan["canonical_pending_delivery_confirmed_count"] == 1
    assert reconcile.apply(plan_path, delivery_client=client)["status"] == "applied"
    assert client.status_calls == [legacy_operation.key, legacy_operation.key]


@pytest.mark.parametrize("local_evidence", ["saved_receipt", "text_discord_id"])
def test_preview_blocks_conflicting_confirmed_message_ids(
    tmp_path, candidate, later_candidate, local_evidence
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    operation = _attach_pending_delivery_payload(canonical_state, candidate)
    payload = canonical_state["stats"]["delivery_payloads"][candidate.key]
    if local_evidence == "saved_receipt":
        local_receipt = _owner_delivered_receipt(operation, "456")
        payload["delivery_handoff"]["state"] = "accepted"
        payload["delivery_handoff"]["receipt"] = {
            "id": local_receipt.id,
            "key": local_receipt.key,
            "digest": local_receipt.digest,
            "status": local_receipt.status,
            "receipt": local_receipt.receipt,
        }
    else:
        pending_receipt = {
            "id": "local-pending-receipt",
            "key": operation.key,
            "digest": operation.digest,
            "status": "pending",
            "receipt": None,
        }
        payload["delivery_handoff"]["state"] = "accepted"
        payload["delivery_handoff"]["receipt"] = pending_receipt
        payload["text_discord_id"] = "456"
    save_state(canonical_state, canonical_path)
    client = _StatusOnlyDeliveryClient(
        {operation.key: _owner_delivered_receipt(operation, "789")}
    )
    plan_path = tmp_path / "plans" / "market-news-merge.json"

    with pytest.raises(StateBlockedError, match="confirmed Discord message ID conflicts"):
        reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    assert not plan_path.exists()


@pytest.mark.parametrize(
    "owner_outcome",
    ["not_found", "wrong_key", "wrong_digest", "wrong_channel", "pending", "lookup_error"],
)
def test_preview_fails_closed_for_unconfirmed_accepted_handoff(
    tmp_path, candidate, later_candidate, owner_outcome
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    operation = _attach_pending_delivery_payload(canonical_state, candidate)
    payload = canonical_state["stats"]["delivery_payloads"][candidate.key]
    saved_receipt = {
        "id": "local-pending-receipt",
        "key": operation.key,
        "digest": operation.digest,
        "status": "pending",
        "receipt": None,
    }
    payload["delivery_handoff"] = {
        "state": "accepted",
        "operation_key": operation.key,
        "receipt": saved_receipt,
    }
    save_state(canonical_state, canonical_path)

    if owner_outcome == "not_found":
        client = _StatusOnlyDeliveryClient({})
    elif owner_outcome == "wrong_key":
        other_operation = delivery._channel_message_operation(
            payload["content"], payload["channel_id"], "different-candidate:text"
        )
        client = _StatusOnlyDeliveryClient(
            {operation.key: _owner_delivered_receipt(other_operation)}
        )
    elif owner_outcome == "wrong_digest":
        client = _StatusOnlyDeliveryClient(
            {
                operation.key: delivery.OperationReceipt(
                    id="owner-receipt",
                    key=operation.key,
                    digest="a" * 64,
                    status="delivered",
                    receipt={"message_id": "789", "channel_id": "123"},
                )
            }
        )
    elif owner_outcome == "wrong_channel":
        client = _StatusOnlyDeliveryClient(
            {
                operation.key: delivery.OperationReceipt(
                    id="owner-receipt",
                    key=operation.key,
                    digest=operation.digest,
                    status="delivered",
                    receipt={"message_id": "789", "channel_id": "999"},
                )
            }
        )
    elif owner_outcome == "pending":
        client = _StatusOnlyDeliveryClient(
            {
                operation.key: delivery.OperationReceipt(
                    id="owner-receipt",
                    key=operation.key,
                    digest=operation.digest,
                    status="pending",
                    receipt=None,
                )
            }
        )
    else:
        class FailingStatusClient(_StatusOnlyDeliveryClient):
            def status(self, _operation_key):
                raise RuntimeError("status unavailable")

        client = FailingStatusClient({})

    plan_path = tmp_path / "plans" / "market-news-merge.json"
    with pytest.raises(StateBlockedError):
        reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    assert not plan_path.exists()


def test_preview_blocks_owner_operation_without_payload_for_digest_validation(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    _add_candidate(canonical_state, later_candidate, phase="pending_delivery")
    save_state(canonical_state, canonical_path)
    operation = delivery._channel_message_operation(
        "unverifiable output", "123", f"{later_candidate.key}:text"
    )
    client = _StatusOnlyDeliveryClient(
        {operation.key: _owner_delivered_receipt(operation)}
    )
    plan_path = tmp_path / "plans" / "market-news-merge.json"

    with pytest.raises(StateBlockedError, match="payload is unavailable"):
        reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    assert not plan_path.exists()


def test_reapply_accepts_source_pending_candidate_abandoned_by_same_plan(
    tmp_path, candidate, later_candidate
):
    source_state, source_path = _source_state(candidate, later_candidate, tmp_path)
    source_state["candidates"][candidate.key]["phase"] = "pending_delivery"
    source_state["candidates"][candidate.key]["agent_lease_until"] = None
    save_state(source_state, source_path)

    canonical_state, canonical_path = _canonical_state(candidate, tmp_path)
    operation = _attach_pending_delivery_payload(canonical_state, candidate)
    save_state(canonical_state, canonical_path)
    client = _StatusOnlyDeliveryClient(
        {operation.key: _owner_delivered_receipt(operation)}
    )
    plan_path = tmp_path / "plans" / "market-news-merge.json"

    reconcile.preview(source_path, canonical_path, plan_path, delivery_client=client)
    assert reconcile.apply(plan_path, delivery_client=client)["status"] == "applied"

    assert reconcile.apply(plan_path, delivery_client=client)["status"] == "already_applied"


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
