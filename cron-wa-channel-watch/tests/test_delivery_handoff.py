from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"))

import discord
from bursawatch_discord_delivery import OperationReceipt
import archive
import config
from event_queue import serialize_event
from normalize import normalize_bridge_event


class Owner:
    def __init__(self, *, query_result=None, message_id="987654321098765432"):
        self.query_result = query_result
        self.message_id = message_id
        self.queries = []
        self.submitted = []

    def query(self, query):
        self.queries.append(query)
        return self.query_result

    def status(self, key):
        return None

    def submit(self, operation):
        self.submitted.append(operation)
        return OperationReceipt(
            id="op-1",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={"channel_id": operation.target["channel_id"], "message_id": self.message_id},
        )

    def wait(self, key, timeout):
        raise AssertionError("delivered operation must not need a wait")


def test_backfill_reads_are_bounded_delivery_owner_queries():
    messages = [{"id": "123456789012345678", "content": "old body"}]
    owner = Owner(query_result=messages)

    assert discord.list_messages("42", limit=25, before="123456789012345679", client=owner) == messages
    assert owner.queries[0].kind == "channel_messages"
    assert owner.queries[0].channel_id == "42"
    assert owner.queries[0].before == "123456789012345679"
    assert owner.queries[0].limit == 25


def test_backfill_edit_uses_edit_operation_and_never_creates_a_replacement():
    owner = Owner(
        query_result=[{"id": "123456789012345678", "content": "old body"}],
        message_id="123456789012345678",
    )

    assert discord.edit_message_content(
        "42", "123456789012345678", "corrected body", client=owner
    ) is True
    assert len(owner.submitted) == 1
    assert owner.submitted[0].kind == "channel_message_edit"
    assert owner.submitted[0].target == {"channel_id": "42", "message_id": "123456789012345678"}


def test_media_upload_keeps_archive_bytes_and_presentation_name(tmp_path):
    owner = Owner()
    archive_media = tmp_path / "archive-owned-media"
    archive_media.write_bytes(b"immutable-chart")
    try:
        assert discord.post_media(
            archive_media,
            "42",
            False,
            discord.nonce("source-event", "media:0"),
            filename="bri-chart-0.jpg",
            mime="image/jpeg",
            client=owner,
        ) == "987654321098765432"
    finally:
        archive_media.unlink(missing_ok=True)

    attachment = owner.submitted[0].attachments[0]
    assert attachment.filename == "bri-chart-0.jpg"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.data == b"immutable-chart"


def test_handoff_plan_reconstructs_archive_media_in_source_order_without_state_writes(tmp_path):
    import delivery_handoff
    import json

    staging = tmp_path / "staging"
    staging.mkdir()
    first = staging / "first.jpg"
    second = staging / "second.mp4"
    first.write_bytes(b"first chart")
    second.write_bytes(b"second clip")
    profile_data = {
        "id": "bri-danareksa-sekuritas", "enabled": True, "mode": "forward",
        "channel_jid": "1@newsletter", "channel_url": "https://whatsapp.com/channel/example",
        "display_name": "BRI", "emoji": "<:bri:12345678901234567>",
        "status_emojis": {"up": None, "down": None, "hold": None},
        "discord_channels": [{"key": "macro_news", "channel_id": "1525102508714889257", "description": "Macro"}],
        "forward_media": True, "enable_llm_title": True, "enable_llm_summary": True,
        "enable_llm_routing": True, "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market", "additional_prompt_instruction": "", "max_items_per_poll": 5,
    }
    profile = config.load_data({"version": 2, "profiles": [profile_data]}).profiles[0]
    event = normalize_bridge_event({
        "channel_jid": profile.channel_jid, "message_id": "wa-1",
        "published_at": "2026-09-22T04:26:00Z", "text": "Source post",
        "media": [
            {"kind": "image", "mime": "image/jpeg", "path": str(first)},
            {"kind": "video", "mime": "video/mp4", "path": str(second)},
        ],
    })
    archive_root = tmp_path / "archive"
    archive.ensure(archive_root, profile.id, event, 1, staging_root=staging)
    state_path = tmp_path / "state.json"
    source_state = {
        "version": 1, "profiles": {},
        "outbox": [{
            "event_key": event.event_key, "profile_id": profile.id,
            "event": serialize_event(event), "agent_phase": "ready",
            "items": [{"title": "Source title", "summary": "Source summary", "route": "macro_news"}],
            "item_index": 0, "text_index": 0, "text_message_ids": [],
            "media_index": 0, "media_skipped_indexes": [], "board_phase": "pending",
        }],
    }
    state_path.write_text(json.dumps(source_state), encoding="utf-8")
    original = state_path.read_bytes()
    adapter = delivery_handoff.WhatsAppChannelWatchHandoffAdapter(
        state_path, tmp_path / "handoff.json", archive_root=archive_root, profiles={profile.id: profile}
    )

    snapshot = adapter.build_handoff_snapshot()

    assert [item.operation.kind for item in snapshot.items] == [
        "channel_message_create", "channel_message_create", "channel_message_create"
    ]
    assert [item.operation.attachments[0].filename for item in snapshot.items[1:]] == [
        "whatsapp-channel-0.jpg", "whatsapp-channel-1.mp4"
    ]
    assert [item.operation.attachments[0].data for item in snapshot.items[1:]] == [b"first chart", b"second clip"]
    assert all(item.operation.reconcile_before_first_create for item in snapshot.items)
    assert state_path.read_bytes() == original

    import sys

    support = str(Path(__file__).resolve().parents[2] / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    owner = SyntheticDeliveryOwner()
    identities = rehearse_legacy_handoff(
        adapter, owner, restore_source=lambda: state_path.write_bytes(original)
    )
    assert len(identities) == 3
    assert len(owner.new_pending_acceptances) == 3


def test_handoff_plan_keeps_existing_text_receipt_and_does_not_replay_it(tmp_path):
    import delivery_handoff
    import json

    profile_data = {
        "id": "bri-danareksa-sekuritas", "enabled": True, "mode": "forward",
        "channel_jid": "1@newsletter", "channel_url": "https://whatsapp.com/channel/example",
        "display_name": "BRI", "emoji": "<:bri:12345678901234567>",
        "status_emojis": {"up": None, "down": None, "hold": None},
        "discord_channels": [{"key": "macro_news", "channel_id": "1525102508714889257", "description": "Macro"}],
        "forward_media": False, "enable_llm_title": True, "enable_llm_summary": True,
        "enable_llm_routing": True, "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market", "additional_prompt_instruction": "", "max_items_per_poll": 5,
    }
    profile = config.load_data({"version": 2, "profiles": [profile_data]}).profiles[0]
    event = normalize_bridge_event({
        "channel_jid": profile.channel_jid, "message_id": "wa-2",
        "published_at": "2026-09-22T04:26:00Z", "text": "Source post", "media": [],
    })
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"version": 1, "profiles": {}, "outbox": [{
        "event_key": event.event_key, "profile_id": profile.id,
        "event": serialize_event(event), "agent_phase": "ready",
        "items": [{"title": "Source title", "summary": "Source summary", "route": "macro_news"}],
        "item_index": 1, "text_index": 0, "text_message_ids": ["123456789012345678"],
        "media_index": 0, "media_skipped_indexes": [], "board_phase": "pending",
    }]}), encoding="utf-8")
    adapter = delivery_handoff.WhatsAppChannelWatchHandoffAdapter(
        state_path, tmp_path / "handoff.json", archive_root=tmp_path / "archive", profiles={profile.id: profile}
    )

    snapshot = adapter.build_handoff_snapshot()

    assert len(snapshot.items) == 1
    assert snapshot.items[0].receipt == {"channel_id": "1525102508714889257", "message_id": "123456789012345678"}
    assert snapshot.items[0].operation.payload["content"]


def test_handoff_plan_reconstructs_patched_board_link_edit_receipt(tmp_path):
    import delivery_handoff
    import json
    import render

    staging = tmp_path / "staging"
    staging.mkdir()
    chart = staging / "chart.jpg"
    chart.write_bytes(b"synthetic chart")
    profile_data = {
        "id": "bri-danareksa-sekuritas", "enabled": True, "mode": "forward",
        "channel_jid": "120363419226413141@newsletter",
        "channel_url": "https://whatsapp.com/channel/example",
        "display_name": "BRI", "emoji": "<:bri:12345678901234567>",
        "status_emojis": {"up": None, "down": None, "hold": None},
        "discord_channels": [
            {"key": "id_stocks_swing", "channel_id": "1525102508714889257", "description": "All Swing"},
        ],
        "forward_media": True, "enable_llm_title": True, "enable_llm_summary": True,
        "enable_llm_routing": True, "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market", "additional_prompt_instruction": "", "max_items_per_poll": 5,
    }
    profile = config.load_data({"version": 2, "profiles": [profile_data]}).profiles[0]
    event = normalize_bridge_event({
        "channel_jid": profile.channel_jid, "message_id": "wa-board-edit",
        "published_at": "2026-09-22T04:26:00Z",
        "text": "#TechnicalReview TINS breakout with one archived chart.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(chart)}],
    })
    archive_root = tmp_path / "archive"
    archive.ensure(archive_root, profile.id, event, 1, staging_root=staging)
    item = {
        "title": "TINS: Breakout",
        "summary": "TINS confirms a bullish breakout.",
        "route": "id_stocks_swing",
        "ticker": "TINS",
        "sentiment": "Bullish",
    }
    channel_id = "1525102508714889257"
    text_message_id = "123456789012345678"
    media_message_id = "123456789012345679"
    board_url = "https://discord.com/channels/940285152335110204/1548273399069933720/999"
    original_text = render.render_post(
        profile, event, title=item["title"], summary=item["summary"],
        route=item["route"], sentiment=item["sentiment"], board_url=None,
    )[0]
    expected_edit = discord.board_link_edit_operation(
        channel_id, text_message_id, original_text, board_url,
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"version": 1, "profiles": {}, "outbox": [{
        "event_key": event.event_key,
        "profile_id": profile.id,
        "event": serialize_event(event),
        "agent_phase": "delivered",
        "items": [item],
        "item_index": 1,
        "text_index": 0,
        "text_message_ids": [text_message_id],
        "media_index": 1,
        "media_message_ids": [media_message_id],
        "media_skipped_indexes": [],
        "media_delivery_status": "delivered",
        "board_phase": "accepted",
        "board_link_phase": "patched",
        "board_acknowledgement": {"board_url": board_url, "board_pending": False},
        "delivered_at": "2026-09-22T04:27:00+00:00",
    }]}), encoding="utf-8")
    adapter = delivery_handoff.WhatsAppChannelWatchHandoffAdapter(
        state_path, tmp_path / "handoff.json", archive_root=archive_root, profiles={profile.id: profile},
    )

    snapshot = adapter.build_handoff_snapshot()

    assert [entry.operation.kind for entry in snapshot.items] == [
        "channel_message_create", "channel_message_create", "channel_message_edit",
    ]
    edit = snapshot.items[-1]
    assert expected_edit is not None
    assert edit.operation.key == expected_edit.key
    assert edit.operation.digest == expected_edit.digest
    assert edit.operation.payload["content"] == discord._replace_board_topic_link(original_text, board_url)
    assert edit.receipt == {"channel_id": channel_id, "message_id": text_message_id}


def _legacy_bri_profile():
    profile_data = {
        "id": "bri-danareksa-sekuritas", "enabled": True, "mode": "forward",
        "channel_jid": "1@newsletter", "channel_url": "https://whatsapp.com/channel/example",
        "display_name": "BRI", "emoji": "<:bri:12345678901234567>",
        "status_emojis": {"up": None, "down": None, "hold": None},
        "discord_channels": [{"key": "macro_news", "channel_id": "1525102508714889257", "description": "Macro"}],
        "forward_media": False, "enable_llm_title": True, "enable_llm_summary": True,
        "enable_llm_routing": True, "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market", "additional_prompt_instruction": "", "max_items_per_poll": 5,
    }
    return config.load_data({"version": 2, "profiles": [profile_data]}).profiles[0]


def _legacy_bri_state(tmp_path, phase):
    import json

    profile = _legacy_bri_profile()
    event = normalize_bridge_event({
        "channel_jid": profile.channel_jid, "message_id": "wa-legacy-1",
        "published_at": "2026-09-15T04:26:00Z", "text": "Source post", "media": [],
    })
    record = {
        "event_key": event.event_key,
        "profile_id": profile.id,
        "event": serialize_event(event),
        "agent_phase": phase,
        "analysis": {
            "event_key": event.event_key, "is_relevant": True,
            "route": "macro_news", "title": "Source title", "summary": "Source summary",
        },
        "text_index": 1,
    }
    if phase == "delivered":
        record["delivered_at"] = "2026-09-15T04:27:00+00:00"
    state_path = tmp_path / "legacy-wa-state.json"
    state_path.write_text(
        json.dumps({"version": 1, "profiles": {}, "outbox": [record]}),
        encoding="utf-8",
    )
    return profile, state_path


def test_handoff_skips_terminal_legacy_record_without_reconstructable_items(tmp_path):
    import delivery_handoff

    profile, state_path = _legacy_bri_state(tmp_path, "delivered")
    original = state_path.read_bytes()
    plan_path = tmp_path / "legacy-wa-plan.json"
    adapter = delivery_handoff.WhatsAppChannelWatchHandoffAdapter(
        state_path, plan_path, archive_root=tmp_path / "archive", profiles={profile.id: profile},
    )

    plan = delivery_handoff.plan_handoff(adapter, plan_path=plan_path)

    assert plan.operation_count == 0
    assert adapter.skipped_terminal_legacy_count == 1
    assert state_path.read_bytes() == original


def test_handoff_still_rejects_ready_legacy_record_without_items(tmp_path):
    import delivery_handoff
    from bursawatch_discord_delivery.handoff import HandoffError

    profile, state_path = _legacy_bri_state(tmp_path, "ready")
    adapter = delivery_handoff.WhatsAppChannelWatchHandoffAdapter(
        state_path, tmp_path / "ready-wa-plan.json", archive_root=tmp_path / "archive",
        profiles={profile.id: profile},
    )

    with pytest.raises(HandoffError, match="outbox cannot be reconstructed"):
        adapter.build_handoff_snapshot()
