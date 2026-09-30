from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import delivery
import news_source_work
import publication_projection as projection
import scan
import state
from bursawatch_discord_delivery import OperationReceipt
from domain import CompanyCandidate, Destination, EventClass, Provider, SourceKind
from selection import SelectionCandidate


def _item(kind=SourceKind.CORPORATE_ENTRY, route=Destination.ID_STOCKS_NEWS, ticker="DEWA"):
    candidate = CompanyCandidate(
        provider=Provider.TUNTUN,
        source_message_id=13597,
        ticker=ticker,
        source_kind=kind,
        published_at=datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc),
        source_text="DEWA secured a source-grounded contract.",
        direct_image=False,
        candidate_id="candidate-1",
    )
    return SelectionCandidate(
        candidate=candidate,
        event_class=EventClass.MATERIAL_CONTRACT,
        ranking_band=1,
        material_facts=("contract awarded",),
        dedupe_facts=("DEWA", "contract"),
        summary="A source-grounded contract update.",
        title="DEWA: Contract update",
        route=route,
    )


def _source(item):
    return {
        "candidate_key": item.key,
        "event_key": "a" * 64,
        "version": 1,
        "source_url": f"https://t.me/tuntunsekuritas/{item.candidate.source_message_id}",
        "watch_config_revision": 3,
    }


def _operation_and_receipt(content, key="market-news-test"):
    operation = delivery._channel_message_operation(content, "12345678901234567", key)
    receipt = OperationReceipt(
        id="delivery-operation-1",
        key=operation.key,
        digest=operation.digest,
        status="delivered",
        receipt={"channel_id": "12345678901234567", "message_id": "23456789012345678"},
    )
    return operation, delivery._receipt_document(receipt)


@pytest.mark.parametrize(
    ("kind", "route", "ticker", "expected_type", "expected_route"),
    [
        (SourceKind.CORPORATE_ENTRY, Destination.ID_STOCKS_NEWS, "DEWA", "idx_company_news", "id_stocks_news"),
        (SourceKind.TUNTUN_UPDATE_INDUSTRY, Destination.MACRO_NEWS, None, "industry_news", "id_industry_news"),
        (SourceKind.CORPORATE_ENTRY, Destination.MACRO_NEWS, "DEWA", "macro_news", "macro_news"),
    ],
)
def test_news_routes_keep_distinct_publication_types(kind, route, ticker, expected_type, expected_route):
    item = _item(kind, route, ticker)
    content = delivery.format_news_item(item)
    operation, receipt = _operation_and_receipt(content, f"{item.key}:text")
    snapshot = projection.news_snapshot(
        _source(item), item, content, operation, receipt,
        datetime(2026, 9, 30, 1, 1, tzinfo=timezone.utc), [operation.key],
    )
    assert (snapshot["type"], snapshot["route"]) == (expected_type, expected_route)
    assert snapshot["legs"][0]["text"] == content
    assert snapshot["legs"][0]["receipt_operation_id"] == "delivery-operation-1"
    assert snapshot["source_event_key"] == "a" * 64


def test_stock_status_is_a_distinct_news_publication():
    content = "Stock Status: Wed, 30 Sep 2026\nUMA\n(None)"
    operation, receipt = _operation_and_receipt(content, "phintraco-stock-status:42")
    snapshot = projection.stock_status_snapshot(
        "b" * 64, 42, "https://t.me/phintasprofits/42", content, None,
        operation, receipt, datetime(2026, 9, 30, 1, 1, tzinfo=timezone.utc), [operation.key],
    )
    assert snapshot["type"] == "stock_status"
    assert snapshot["route"] == "id_stocks_news"
    assert snapshot["ticker"] is None


def test_incomplete_multi_leg_delivery_cannot_become_a_publication():
    operation, _receipt = _operation_and_receipt("confirmed text")
    leg = {
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt_operation_id": "delivery-operation-1",
        "destination": "12345678901234567",
        "receipt_id": "23456789012345678",
        "status": "delivered",
        "receipt_key": operation.key,
        "receipt_digest": operation.digest,
        "receipt_destination": "12345678901234567",
        "receipt_message_id": "23456789012345678",
    }
    with pytest.raises(projection.IncompletePublication, match="missing a required"):
        projection.validate_required_legs([operation.key, "required-image-leg"], [leg])


def test_projection_outage_retries_snapshot_without_reposting(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BURSAWATCH_TG_MARKET_NEWS_PUBLICATION_ENABLED", "1")
    item = _item()
    state_data = state.empty_state()
    state_data["candidates"][item.key] = {
        "candidate": state._candidate_payload(item.candidate),
        "phase": "pending_delivery",
        "enqueued_at": "2026-09-30T01:00:00+00:00",
        "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
        "agent_lease_until": None,
        "classification": item.event_class.value,
        "selection": {
            "summary": item.summary,
            "ranking_band": item.ranking_band,
            "material_facts": list(item.material_facts),
            "dedupe_facts": list(item.dedupe_facts),
            "title": item.title,
            "route": item.route.value,
        },
    }
    monkeypatch.setattr(news_source_work, "provenance", lambda _state, _key: _source(item))
    class DeliveryOwner:
        def __init__(self):
            self.submissions = []

        def status(self, _key):
            return None

        def submit(self, operation):
            self.submissions.append(operation)
            return OperationReceipt(
                id="delivery-operation-1", key=operation.key, digest=operation.digest,
                status="delivered", receipt={
                    "channel_id": operation.target["channel_id"],
                    "message_id": "23456789012345678",
                },
            )

    owner = DeliveryOwner()
    save_before_terminal = []
    original_mark_terminal = delivery.mark_terminal

    def assert_intent_precedes_terminal(current, key, phase):
        save_before_terminal.append(f"news:{key}" in current["stats"].get("publication_projection", {}))
        original_mark_terminal(current, key, phase)

    monkeypatch.setattr(delivery, "mark_terminal", assert_intent_precedes_terminal)
    now = datetime(2026, 9, 30, 1, 1, tzinfo=timezone.utc)
    assert asyncio.run(delivery.deliver_event(state_data, item, "12345678901234567", now, delivery_client=owner))
    assert save_before_terminal == [True]
    assert len(owner.submissions) == 1

    class ProjectionClient:
        def __init__(self):
            self.submissions = []
            self.checkpoints = []

        def submit(self, snapshot):
            self.submissions.append(snapshot)
            if len(self.submissions) == 1:
                raise OSError("offline")
            return {"publication_id": "c" * 64, "version": 1, "digest": "d" * 64}

        def checkpoint(self, comparison):
            self.checkpoints.append(comparison)
            return {"accepted": True}

    projection_client = ProjectionClient()
    first = projection.drain(state_data, now, projection_client)
    assert first == {"accepted": 0, "pending": 1}
    assert asyncio.run(scan._drain_delivery(state_data, None, now, False, delivery_client=owner)) == 0
    second = projection.drain(state_data, now, projection_client)
    assert second == {"accepted": 1, "pending": 0}
    assert len(owner.submissions) == 1
    assert projection_client.submissions[0] == projection_client.submissions[1]
    assert projection_client.checkpoints[-1]["outstanding_count"] == 0
    assert projection_client.checkpoints[-1]["confirmed_through_at"] == projection_client.checkpoints[-1]["accepted_through_at"]
