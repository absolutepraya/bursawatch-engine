from __future__ import annotations

from datetime import UTC, datetime

import publication_projection as projection
import state
import config
import render
from models import PublicationKind, SourcePost


NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)


def _snapshot(owner_key: str, confirmed: str = "2026-09-30T04:00:00+00:00") -> dict:
    return {
        "api_version": 1,
        "owner_key": owner_key,
        "version": 1,
        "delivery_confirmed_at": confirmed,
        "required_operation_keys": ["bursawatch-ig-account-watch:leg"],
        "legs": [{"operation_key": "bursawatch-ig-account-watch:leg", "status": "delivered"}],
    }


class ProjectionClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.submissions = []
        self.checkpoints = []

    def submit(self, snapshot):
        self.submissions.append(snapshot)
        if self.fail:
            raise OSError("read model unavailable")
        return {"publication_id": "a" * 64, "version": snapshot["version"], "digest": "b" * 64}

    def checkpoint(self, value):
        self.checkpoints.append(value)
        return {"ok": True}


class DeliveryReadClient:
    def __init__(self) -> None:
        self.status_reads = 0
        self.sends = 0

    def status(self, _key):
        self.status_reads += 1
        return None

    def submit(self, *_args, **_kwargs):
        self.sends += 1
        raise AssertionError("projection retry must never submit a Discord operation")


def test_confirmed_news_output_builds_publication_from_saved_render(config_path, tmp_path, monkeypatch):
    monkeypatch.setenv("BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    profile = config.load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "post-100", "https://www.instagram.com/p/100/", NOW, "Source caption", PublicationKind.POST, ())
    event = state._event_for_publication(
        profile,
        post,
        {"post": post, "downloaded_publication": None, "ocr_results": (), "vision_decision": None},
    )
    event.update({"route": "macro_news", "title": "Macro: Growth", "summary": "Source grounded summary.", "is_relevant": True})
    messages = render.render_publication(profile, post, event["summary"], event["title"])
    event["text_index"] = len(messages)
    event["text_message_ids"] = [str(10_000_000_000_000_000 + index) for index, _ in enumerate(messages)]
    value = state.new_state()

    assert projection.record_intent(value, event, profile, NOW)
    candidate = state.pending_publication_intents(value)[0][1]

    class ConfirmedOwner:
        def status(self, key):
            descriptor = next(item for item in candidate["_operation_descriptors"] if item["operation_key"] == key)
            return {"id": "delivery-1", "key": key, "digest": descriptor["operation_digest"], "status": "delivered",
                    "receipt": {"channel_id": descriptor["destination"], "message_id": "10000000000000001"}}

    pub = ProjectionClient()
    result = projection.drain(value, NOW, pub, ConfirmedOwner())

    assert result == {"accepted": 1, "pending": 0}
    published = pub.submissions[0]
    assert published["type"] == "macro_news"
    assert published["route"] == "macro_news"
    assert published["source_url"] == post.url
    assert published["legs"][0]["text"] == messages[0]
    state.record_delivery(value, event, NOW)
    state.prune_deliveries(value, NOW)
    assert value["publication_ledger"][event["event_key"]]["ack"] is not None


def test_projection_outage_retries_saved_intent_without_discord_send(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()
    state.record_publication_intent(value, _snapshot("profile:post"))
    discord = DeliveryReadClient()
    outage = ProjectionClient(fail=True)

    first = projection.drain(value, NOW, outage, discord)
    second_client = ProjectionClient()
    second = projection.drain(value, NOW, second_client, discord)

    assert first["pending"] == 1
    assert second["pending"] == 0
    assert len(outage.submissions) == 1
    assert len(second_client.submissions) == 1
    assert outage.submissions[0] == second_client.submissions[0]
    assert discord.sends == 0
    assert value["publication_ledger"]["profile:post"]["ack"] is not None


def test_pending_media_receipt_keeps_intent_out_of_publication(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    candidate = _snapshot("profile:post")
    candidate["_receipt_pending"] = True
    candidate["_operation_descriptors"] = [{
        "operation_key": "bursawatch-ig-account-watch:media",
        "operation_digest": "c" * 64,
        "destination": "1525102508714889257",
        "text": None,
        "attachments": [{"filename": "post.jpg", "content_type": "image/jpeg", "discord_url": None}],
    }]
    candidate["required_operation_keys"] = ["bursawatch-ig-account-watch:media"]
    value = state.new_state()
    state.record_publication_intent(value, candidate)

    class PendingDelivery(DeliveryReadClient):
        def status(self, key):
            return {"id": "operation-1", "key": key, "digest": "c" * 64, "status": "pending", "receipt": None}

    pub = ProjectionClient()
    result = projection.drain(value, NOW, pub, PendingDelivery())

    assert result == {"accepted": 0, "pending": 1}
    assert pub.submissions == []


def test_irrelevant_instagram_post_creates_no_publication(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_ENABLED", "1")
    value = state.new_state()

    created = projection.record_intent(
        value,
        {"is_relevant": False, "route": None},
        object(),
        NOW,
    )

    assert created is False
    assert state.pending_publication_intents(value) == []
