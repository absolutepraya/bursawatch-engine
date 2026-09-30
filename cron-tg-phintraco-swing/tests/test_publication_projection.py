from __future__ import annotations

from dataclasses import replace
import datetime as dt

import pytest

import publication_projection as projection
import scan


NOW = dt.datetime(2026, 9, 30, 10, 0, tzinfo=scan.WIB)


def _call(*, has_chart: bool = False, status: bool = False):
    call = scan.parse_swing_call(
        33655,
        (scan.Path(__file__).parent / "fixtures" / "trading_buy.txt").read_text(),
        has_photo=has_chart,
        source_posted_at=NOW,
    )
    assert call is not None
    if status:
        return replace(
            call,
            source_message_id=33656,
            call_subtype="",
            entry="",
            stop_loss="",
            targets=(),
            event_kind="STATUS",
            status="On track",
            has_source_chart=False,
            source_text="SCMA on track",
        )
    return call


def _event(state, call, *, key=None):
    event = scan.enqueue_call(state, call, NOW, event_key=key)
    event["phase"] = scan.PHASE_PENDING_BOARD
    event["text_output"] = scan.format_swing_alert(call, include_board=True)
    event["text_destination"] = scan.config.default_watch_config().alert_discord_channel_id
    event["source_url"] = scan.source_message_url(call.source_message_id)
    operation = scan._channel_message_operation(
        event["text_output"], event["text_destination"], event["event_key"], leg="text"
    )
    event["text_receipt"] = {
        "id": f"operation-{call.source_message_id}",
        "key": operation.key,
        "digest": operation.digest,
        "status": "delivered",
        "receipt": {"channel_id": event["text_destination"], "message_id": str(111111111111111111 + call.source_message_id)},
    }
    return event


def test_complete_setup_projects_only_source_validated_broker_fields():
    state = scan.empty_state()
    event = _event(state, _call())

    record = projection.publication_snapshot(state, event, NOW)

    assert record is not None
    assert record["type"] == "broker_swing_plan"
    assert record["route"] == "id_stocks_swing"
    assert record["ticker"] == "SCMA"
    assert record["broker_levels"] == {
        "entry": "208 to 212",
        "stop": "<200",
        "targets": ["230"],
        "units": "Not stated by source",
        "attribution": "Alrich Paskalis T, Investment Advisor at Phintraco Sekuritas",
    }
    assert record["legs"][0]["text"] == event["text_output"]
    assert record["legs"][0]["operation_key"] == event["text_receipt"]["key"]


def test_chart_plan_waits_for_every_required_delivery_receipt():
    state = scan.empty_state()
    event = _event(state, _call(has_chart=True))

    with pytest.raises(projection.IncompletePublication, match="chart has no confirmed"):
        projection.publication_snapshot(state, event, NOW)


def test_source_update_is_linked_and_does_not_claim_complete_plan_levels():
    state = scan.empty_state()
    original = _event(state, _call(), key="pdf:35448:SCMA")
    original["matched_setup_event_key"] = None
    plan = projection.publication_snapshot(state, original, NOW)
    assert plan is not None
    plan_owner_key = plan["owner_key"]
    state["publication_projection"]["records"][plan_owner_key] = {"snapshot": plan, "ack": None}

    update = _event(
        state,
        _call(status=True),
        key="33656",
    )
    update["matched_setup_event_key"] = "phintraco:1444713822:weekly:35448:SCMA"
    record = projection.publication_snapshot(state, update, NOW)

    assert record is not None
    assert record["type"] == "broker_swing_update"
    assert record["parent_publication_id"] == projection.publication_id(plan_owner_key)
    assert record["broker_levels"] is None


def test_projection_outage_retries_saved_intent_without_touching_discord(monkeypatch):
    monkeypatch.setenv("IDX_SWING_WATCH_PHINTRACO_DAILY_PUBLICATION_ENABLED", "1")
    state = scan.empty_state()
    event = _event(state, _call())
    assert projection.record_confirmed_outbox(state, NOW) == 1
    owner_key, saved = next(iter(projection.pending_publication_intents(state)))

    class OfflineClient:
        def __init__(self):
            self.submitted = []

        def submit(self, snapshot):
            self.submitted.append(snapshot)
            raise OSError("synthetic API outage")

        def checkpoint(self, _comparison):
            raise OSError("synthetic API outage")

    offline = OfflineClient()
    monkeypatch.setattr(scan, "post_discord_text", lambda *_a, **_k: pytest.fail("projection retried Discord"))
    result = projection.drain(state, NOW, client=offline)

    assert result == {"accepted": 0, "pending": 1}
    assert offline.submitted == [saved]
    assert projection.pending_publication_intents(state) == [(owner_key, saved)]
