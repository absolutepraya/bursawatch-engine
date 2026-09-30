from __future__ import annotations

from datetime import datetime, timezone

import publication_projection as projection


NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def _event(*, text_index: int = 1, next_media_index: int = 0) -> dict:
    return {
        "event_key": "12345:BBCA", "ticker": "BBCA", "header_message_id": 12345,
        "source_published_at": "2026-09-30T10:00:00+07:00", "title": "BBCA: Sumber menyebut area menarik",
        "summary": "*(Ringkasan)* Sumber menyebut area yang perlu dicermati.",
        "all_delivery_completed_at": "2026-09-30T12:00:00+00:00",
        "text_index": text_index, "text_message_ids": ["940285152335110201"] if text_index else [],
        "next_media_index": next_media_index, "media": [],
    }


def test_gtw_bundle_has_no_invented_broker_levels(monkeypatch, tmp_path):
    monkeypatch.setenv(projection._FLAG, "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")
    monkeypatch.setattr(projection.discord, "render_event", lambda _event: ["rendered source bundle"])
    snapshot, operations = projection._descriptor(
        _event(), tmp_path / "state.json", tmp_path / "media", "1525102458253217803"
    )

    assert snapshot["type"] == "swing_bundle"
    assert snapshot["broker_levels"] is None
    assert snapshot["route"] == "id_stocks_swing"
    assert len(operations) == 1
    assert snapshot["_operation_descriptors"][0]["text"] == "rendered source bundle"


def test_incomplete_delivery_never_creates_publication_intent(monkeypatch, tmp_path):
    monkeypatch.setenv(projection._FLAG, "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")
    monkeypatch.setattr(projection.discord, "render_event", lambda _event: ["one", "two"])
    value = {"publication_projection": {"records": {}, "checkpoint_ack": None},
             "outbox": [_event(text_index=1)]}

    created = projection.record_confirmed_outbox(value, tmp_path / "state.json", NOW,
                                                 channel_id="1525102458253217803")

    assert created == 0
    assert value["publication_projection"]["records"] == {}


def test_api_outage_retries_projection_without_any_discord_operation(monkeypatch, tmp_path):
    monkeypatch.setenv(projection._FLAG, "1")
    monkeypatch.setenv("BURSAWATCH_PUBLICATION_CUTOVER_AT", "2026-09-30T00:00:00Z")
    monkeypatch.setattr(projection.discord, "render_event", lambda _event: ["rendered source bundle"])
    value = {"publication_projection": {"records": {}, "checkpoint_ack": None},
             "outbox": [_event()]}
    projection.record_confirmed_outbox(value, tmp_path / "state.json", NOW,
                                       channel_id="1525102458253217803")

    class ApiOutage:
        def submit(self, _snapshot):
            raise OSError("unavailable")

        def checkpoint(self, _comparison):
            raise OSError("unavailable")

    class DeliveryLookup:
        operations = 0

        def status(self, _key):
            self.operations += 1
            return None

    delivery = DeliveryLookup()
    first = projection.drain(value, tmp_path / "state.json", NOW,
                             publication_client=ApiOutage(), delivery_owner=delivery)
    second = projection.drain(value, tmp_path / "state.json", NOW,
                              publication_client=ApiOutage(), delivery_owner=delivery)

    assert first["pending"] == second["pending"] == 1
    assert delivery.operations == 2
