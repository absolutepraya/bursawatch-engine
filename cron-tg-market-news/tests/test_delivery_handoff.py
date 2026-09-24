from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

import delivery_handoff
from bursawatch_discord_delivery.handoff import APPLY_ENVIRONMENT_VARIABLE, HandoffError
from bursawatch_discord_delivery.models import OperationReceipt
from domain import CompanyCandidate, EventClass, Provider, SourceKind
from state import empty_state, enqueue_candidate, save_state


NOW = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)


class HandoffOwner:
    def __init__(self):
        self.calls = []

    def adopt_completed(self, operation, receipt):
        self.calls.append(("completed", operation, dict(receipt), None))
        return OperationReceipt(
            id=f"accepted-{len(self.calls)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt=dict(receipt),
        )

    def adopt_pending(self, operation, *, preflight=None):
        self.calls.append(("pending", operation, None, preflight))
        return OperationReceipt(
            id=f"accepted-{len(self.calls)}",
            key=operation.key,
            digest=operation.digest,
            status="pending_reconciliation",
            receipt=None,
        )


class RejectingOwner:
    def adopt_pending(self, operation, *, preflight=None):
        raise delivery_handoff.DeliveryClientError("timeout")


def _state_with_payloads(state_path: Path, payload_specs):
    state = empty_state()
    payloads = {}
    candidates = []
    for spec in payload_specs:
        candidate = CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=spec["source_message_id"],
            ticker=spec["ticker"],
            source_kind=SourceKind.CORPORATE_ENTRY,
            published_at=NOW,
            source_text=f"source evidence for {spec['ticker']}",
            direct_image=spec.get("image_discord_id") is not None,
        )
        enqueue_candidate(state, candidate, NOW)
        record = state["candidates"][candidate.key]
        record["phase"] = "pending_delivery"
        record["classification"] = EventClass.MATERIAL_CONTRACT.value
        record["selection"] = {
            "summary": "The issuer disclosed a material contract.",
            "ranking_band": 1,
            "material_facts": ["A material contract was disclosed."],
            "dedupe_facts": ["material contract"],
            "title": f"{candidate.ticker}: Material contract disclosed",
            "route": "id_stocks_news",
        }
        payload = {
            "content": f"PRIVATE SAVED BODY {candidate.ticker}",
            "nonce": f"legacy-{candidate.source_message_id}",
            "enforce_nonce": True,
            "channel_id": "123456789012345678",
            "text_discord_id": spec.get("text_discord_id"),
            "image_discord_id": spec.get("image_discord_id"),
            "image_error": None,
        }
        if "preflight" in spec:
            payload["text_preflight"] = spec["preflight"]
        payloads[candidate.key] = payload
        candidates.append(candidate)
    state["stats"]["delivery_payloads"] = payloads
    save_state(state, state_path)
    return state, candidates


def test_plan_is_private_read_only_and_preserves_receipts_preflight_and_cached_bytes(tmp_path):
    state_path = tmp_path / "legacy-state.json"
    media_path = tmp_path / "media" / "tuntun-701.jpg"
    media_path.parent.mkdir()
    media_path.write_bytes(b"EXACT-CACHED-JPEG-BYTES")
    state, candidates = _state_with_payloads(
        state_path,
        [
            {"source_message_id": 701, "ticker": "DEWA", "text_discord_id": "7001", "image_discord_id": "7002"},
            {
                "source_message_id": 702,
                "ticker": "CBRE",
                "text_discord_id": None,
                "preflight": {"boundary_observed": True, "boundary": "6999"},
            },
            {"source_message_id": 703, "ticker": "ADRO", "text_discord_id": None},
        ],
    )
    before = state_path.read_bytes()
    plan_path = tmp_path / "market-news-plan.json"
    adapter = delivery_handoff.MarketNewsHandoffAdapter(state_path, plan_path)

    plan = delivery_handoff.plan_handoff(adapter, plan_path=plan_path)
    plan_document = json.loads(plan_path.read_text())
    snapshot = adapter.build_handoff_snapshot()

    assert state_path.read_bytes() == before
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o600
    assert plan.operation_count == 4
    assert plan.completed_count == 2
    assert plan.pending_count == 2
    assert plan_document["receipts"] == [
        {"channel_id": "123456789012345678", "message_id": "7001"},
        {"channel_id": "123456789012345678", "message_id": "7002"},
        None,
        None,
    ]
    assert plan_document["preflight"] == [
        None,
        None,
        {"boundary_observed": True, "boundary": "6999"},
        None,
    ]
    image_operation = next(item.operation for item in snapshot.items if item.operation.key.endswith(":image"))
    assert image_operation.attachments[0].data == b"EXACT-CACHED-JPEG-BYTES"
    serialized = plan_path.read_text()
    assert "PRIVATE SAVED BODY" not in serialized
    assert "EXACT-CACHED-JPEG-BYTES" not in serialized
    assert candidates[1].key not in serialized
    assert candidates[2].key not in serialized
    assert str(state_path) not in serialized


def test_apply_requires_both_gates_and_acks_only_after_owner_acceptance(tmp_path):
    state_path = tmp_path / "legacy-state.json"
    preflight = {"boundary_observed": True, "boundary": None}
    state, candidates = _state_with_payloads(
        state_path,
        [
            {"source_message_id": 711, "ticker": "DEWA", "text_discord_id": None, "preflight": preflight},
            {"source_message_id": 712, "ticker": "CBRE", "text_discord_id": None},
        ],
    )
    plan_path = tmp_path / "market-news-plan.json"
    adapter = delivery_handoff.MarketNewsHandoffAdapter(state_path, plan_path)
    delivery_handoff.plan_handoff(adapter, plan_path=plan_path)
    original_bytes = state_path.read_bytes()
    owner = HandoffOwner()

    with pytest.raises(HandoffError, match="requires --apply"):
        delivery_handoff.apply_market_news_handoff(
            plan_path,
            adapter,
            owner,
            apply=False,
            environment={APPLY_ENVIRONMENT_VARIABLE: "1"},
        )
    assert owner.calls == []
    assert state_path.read_bytes() == original_bytes

    with pytest.raises(HandoffError, match="requires --apply"):
        delivery_handoff.apply_market_news_handoff(
            plan_path,
            adapter,
            owner,
            apply=True,
            environment={},
        )
    assert owner.calls == []

    result = delivery_handoff.apply_market_news_handoff(
        plan_path,
        adapter,
        owner,
        apply=True,
        environment={APPLY_ENVIRONMENT_VARIABLE: "1"},
    )

    assert [call[0] for call in owner.calls] == ["pending", "pending"]
    assert owner.calls[0][3] == preflight
    assert owner.calls[1][3] is None
    assert result.acknowledged_count == 2
    assert result.skipped_count == 0
    assert result.backup_path.read_bytes() == original_bytes
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600
    updated = json.loads(state_path.read_text())
    for candidate in candidates:
        handoff = updated["stats"]["delivery_payloads"][candidate.key]["delivery_handoff"]
        accepted = next(call[1] for call in owner.calls if call[1].key == handoff["operation_key"])
        assert handoff["state"] == "accepted"
        assert handoff["receipt"]["key"] == accepted.key
        assert handoff["receipt"]["digest"] == accepted.digest


def test_rejected_service_import_leaves_source_without_handoff_ack(tmp_path):
    state_path = tmp_path / "legacy-state.json"
    state, candidates = _state_with_payloads(
        state_path,
        [{"source_message_id": 721, "ticker": "DEWA", "text_discord_id": None}],
    )
    plan_path = tmp_path / "market-news-plan.json"
    adapter = delivery_handoff.MarketNewsHandoffAdapter(state_path, plan_path)
    delivery_handoff.plan_handoff(adapter, plan_path=plan_path)

    with pytest.raises(HandoffError, match="did not acknowledge"):
        delivery_handoff.apply_market_news_handoff(
            plan_path,
            adapter,
            RejectingOwner(),
            apply=True,
            environment={APPLY_ENVIRONMENT_VARIABLE: "1"},
        )

    updated = json.loads(state_path.read_text())
    payload = updated["stats"]["delivery_payloads"][candidates[0].key]
    assert "delivery_handoff" not in payload
    assert "image_delivery_handoff" not in payload
