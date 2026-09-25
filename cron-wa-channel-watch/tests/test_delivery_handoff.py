from __future__ import annotations

import sys
from pathlib import Path

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
