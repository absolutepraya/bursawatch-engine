from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import config
import discord
import state
from delivery_handoff import XAccountWatchHandoffAdapter
from models import PostKind, SourceMedia, SourcePost
from bursawatch_discord_delivery.handoff import plan_handoff


class SourceResponse:
    status_code = 200
    headers = {"Content-Type": "image/png"}
    content = b"x-source-image-bytes"

    @staticmethod
    def raise_for_status():
        return None


def test_plan_preserves_known_text_receipt_and_source_media_payload(tmp_path, config_path, monkeypatch):
    profile = config.load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "101",
        "https://x.com/Kutekians/status/101",
        datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        "Company revenue rose after guidance.",
        PostKind.NORMAL,
        None,
        None,
        (SourceMedia("https://img.example/chart.png", 0),),
        (),
    )
    event = {
        "profile_id": profile.id,
        "post_id": post.post_id,
        "thread_root_id": post.post_id,
        "post": state.serialize_post(post),
        "thread_posts": [state.serialize_post(post)],
        "ready_after": None,
        "text_index": 1,
        "media_index": 0,
        "media_skipped_urls": [],
        "media_errors": [],
        "delivery_at": None,
        "title": None,
        "summary": None,
        "route": None,
        "agent_phase": "ready",
        "agent_lease_until": None,
        "text_message_ids": ["7001"],
        "media_message_ids": [],
        "board_phase": "pending",
        "board_attempts": 0,
        "board_next_attempt_at": None,
        "board_last_error": None,
    }
    source = tmp_path / "x-state.json"
    value = state.new_state()
    value["outbox"].append(event)
    state.save_state(source, value)
    original = source.read_bytes()
    monkeypatch.setattr(discord.requests, "get", lambda *_args, **_kwargs: SourceResponse())
    plan_path = tmp_path / "x-handoff.json"
    adapter = XAccountWatchHandoffAdapter(source, plan_path, {profile.id: profile})

    plan = plan_handoff(adapter, plan_path=plan_path)
    snapshot = adapter.build_handoff_snapshot()

    assert plan.operation_count == 2
    assert plan.completed_count == 1
    assert plan.pending_count == 1
    assert snapshot.items[0].receipt == {"channel_id": profile.discord_channels[0].channel_id, "message_id": "7001"}
    assert snapshot.items[1].operation.attachments[0].data == SourceResponse.content
    assert snapshot.items[0].operation.key != snapshot.items[1].operation.key
    assert source.read_bytes() == original
    assert "x-source-image-bytes" not in plan_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o600

    import sys

    support = str(Path(__file__).resolve().parents[2] / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    owner = SyntheticDeliveryOwner()
    identities = rehearse_legacy_handoff(
        adapter, owner, restore_source=lambda: source.write_bytes(original)
    )
    assert len(identities) == 2
    assert len(owner.new_pending_acceptances) == 1


def test_plan_requires_reconciliation_for_first_unacknowledged_x_create(tmp_path, config_path, monkeypatch):
    profile = config.load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "102",
        "https://x.com/Kutekians/status/102",
        datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        "A source post with no remote receipt.",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id,
        "post_id": post.post_id,
        "thread_root_id": post.post_id,
        "post": state.serialize_post(post),
        "thread_posts": [state.serialize_post(post)],
        "ready_after": None,
        "text_index": 0,
        "media_index": 0,
        "media_skipped_urls": [],
        "media_errors": [],
        "delivery_at": None,
        "title": None,
        "summary": None,
        "route": None,
        "agent_phase": "ready",
        "agent_lease_until": None,
        "text_message_ids": [],
        "media_message_ids": [],
        "board_phase": "pending",
        "board_attempts": 0,
        "board_next_attempt_at": None,
        "board_last_error": None,
    })
    source = tmp_path / "x-state.json"
    state.save_state(source, value)
    adapter = XAccountWatchHandoffAdapter(source, tmp_path / "plan.json", {profile.id: profile})

    item = adapter.build_handoff_snapshot().items[0]

    assert item.receipt is None
    assert item.operation.reconcile_before_first_create is True
    assert item.operation.legacy_nonce
