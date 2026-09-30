from __future__ import annotations

from datetime import datetime, timezone

from config import ChannelProfile, DiscordChannel, StatusEmojis
from event_queue import serialize_event
from normalize import normalize_bridge_event
import publication_projection as projection
import state


NOW = datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)


def test_whatsapp_route_types_preserve_news_and_swing_context():
    assert projection.publication_type_for_route("id_stocks_news") == "idx_company_news"
    assert projection.publication_type_for_route("id_industry_news") == "industry_news"
    assert projection.publication_type_for_route("macro_news") == "macro_news"
    assert projection.publication_type_for_route("id_stocks_swing") == "swing_context"


def test_confirmed_forwarded_news_snapshot_keeps_exact_channel_output(tmp_path):
    profile = ChannelProfile(
        id="bri", enabled=True, mode="forward", channel_jid="12345@newsletter",
        channel_url="https://whatsapp.com/channel/example", display_name="BRI Danareksa",
        emoji="<:bri:123456789012345678>", status_emojis=StatusEmojis(None, None, None),
        discord_channels=(DiscordChannel("macro_news", "1531655369884045382", "Macro"),),
        forward_media=True, enable_llm_title=True, enable_llm_summary=True,
        enable_llm_routing=True, enable_llm_relevance_filter=True,
        relevance_scope="financial_market", additional_prompt_instruction="", max_items_per_poll=10,
    )
    event = normalize_bridge_event({
        "channel_jid": profile.channel_jid, "message_id": "message-100",
        "published_at": NOW.isoformat(), "text": "Sumber menyebut pertumbuhan ekonomi.", "media": [],
    })
    record = {
        "event_key": event.event_key, "profile_id": profile.id, "event": serialize_event(event),
        "agent_phase": "delivered", "delivered_at": NOW.isoformat(),
        "items": [{"title": "Ekonomi: Pertumbuhan", "summary": "*(Ringkasan)* Proyeksi tumbuh.", "route": "macro_news"}],
        "media_skipped_indexes": [],
    }

    snapshots = projection._capture_record({"outbox": [record]}, record, {profile.id: profile}, tmp_path / "archive", NOW)

    assert len(snapshots) == 1
    assert snapshots[0]["type"] == "macro_news"
    assert snapshots[0]["route"] == "macro_news"
    assert snapshots[0]["source_url"] == profile.channel_url
    assert snapshots[0]["_operation_descriptors"][0]["text"]


def test_observe_only_run_cannot_create_publications(monkeypatch, tmp_path):
    monkeypatch.setenv("BURSAWATCH_WA_CHANNEL_WATCH_PUBLICATION_ENABLED", "1")
    value = state.empty_state()
    observe_profile = type("ObserveProfile", (), {"id": "ins", "is_forwarding": False})()
    value["outbox"].append({"profile_id": "ins", "agent_phase": "delivered"})

    created = projection.record_intents(value, {"ins": observe_profile}, tmp_path, NOW)

    assert created == 0
    assert state.pending_publication_intents(value) == []


def test_api_outage_retries_projection_only_and_keeps_checkpoint_pending(monkeypatch):
    monkeypatch.setenv("BURSAWATCH_WA_CHANNEL_WATCH_PUBLICATION_ENABLED", "1")
    value = state.empty_state()
    snapshot = {
        "api_version": 1,
        "owner_key": "120363419226413141@newsletter:123:item:0",
        "version": 1,
        "delivery_confirmed_at": NOW.isoformat(),
        "required_operation_keys": ["bursawatch-wa-channel-watch:leg"],
        "legs": [{"operation_key": "bursawatch-wa-channel-watch:leg", "status": "delivered"}],
    }
    state.record_publication_intent(value, snapshot)

    class ProjectionClient:
        def __init__(self, fail=False):
            self.fail = fail
            self.submissions = []
            self.comparisons = []

        def submit(self, candidate):
            self.submissions.append(candidate)
            if self.fail:
                raise OSError("read model unavailable")
            return {"publication_id": "a" * 64, "version": 1, "digest": "b" * 64}

        def checkpoint(self, comparison):
            self.comparisons.append(comparison)
            return {"ok": True}

    class DeliveryOwner:
        sends = 0

        def status(self, _key):
            raise AssertionError("resolved publication does not need another Discord send")

        def submit(self, *_args, **_kwargs):
            self.sends += 1
            raise AssertionError("publication projection cannot post to Discord")

    delivery = DeliveryOwner()
    outage, recovery = ProjectionClient(fail=True), ProjectionClient()
    assert projection.drain(value, NOW, outage, delivery) == {"accepted": 0, "pending": 1}
    assert projection.drain(value, NOW, recovery, delivery) == {"accepted": 1, "pending": 0}
    assert outage.submissions == recovery.submissions
    assert outage.comparisons[0]["accepted_through_at"] is None
    assert delivery.sends == 0
