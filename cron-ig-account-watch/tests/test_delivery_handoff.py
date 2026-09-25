from __future__ import annotations

import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

import config
import state
from delivery_handoff import InstagramAccountWatchHandoffAdapter
from models import DownloadedAsset, DownloadedPublication, MediaKind, PublicationKind, SourceMedia, SourcePost
from bursawatch_discord_delivery.handoff import HandoffError, plan_handoff


def make_state(media_root: Path, config_path: Path, *, message_ids: bool = True):
    profile = config.load_watch_config(config_path).profiles[0]
    media_root.mkdir(parents=True, exist_ok=True)
    asset_path = media_root / "DcaLqsggXrE" / "image-0.png"
    asset_path.parent.mkdir(parents=True)
    payload = b"instagram-source-image"
    asset_path.write_bytes(payload)
    source_media = SourceMedia("https://cdn.example/image.png", MediaKind.IMAGE, 0)
    post = SourcePost(
        profile.id,
        "DcaLqsggXrE",
        "https://www.instagram.com/p/DcaLqsggXrE/",
        datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        "Caption from the archived source.",
        PublicationKind.POST,
        (source_media,),
    )
    asset = DownloadedAsset(
        source_media,
        asset_path,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        "image/png",
    )
    downloaded = DownloadedPublication((asset,), media_root)
    event = state._event_for_publication(profile, post, {"downloaded_publication": downloaded})
    event.update({
        "agent_phase": "ready",
        "text_index": 1 if message_ids else 0,
        "text_message_ids": ["7002"] if message_ids else [],
        "title": "Accepted market title",
        "summary": "Accepted market summary",
        "route": "macro_news",
        "is_relevant": True,
    })
    value = state.new_state()
    value["outbox"].append(event)
    return profile, value, asset_path, payload


def test_plan_preserves_instagram_text_receipt_and_ordered_local_media_bytes(tmp_path, monkeypatch, config_path):
    media_root = tmp_path / "media"
    profile, value, asset_path, payload = make_state(media_root, config_path)
    state_path = tmp_path / "ig-state.json"
    state.save_state(state_path, value)
    original = state_path.read_bytes()
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    plan_path = tmp_path / "ig-handoff.json"
    adapter = InstagramAccountWatchHandoffAdapter(
        state_path,
        plan_path,
        {profile.id: profile},
    )

    snapshot = adapter.build_handoff_snapshot()
    plan = plan_handoff(adapter, plan_path=plan_path)

    assert plan.operation_count == 2
    assert plan.completed_count == 1
    assert plan.pending_count == 1
    assert snapshot.items[0].receipt == {"channel_id": profile.channel_for("macro_news").channel_id, "message_id": "7002"}
    assert "View on Instagram" in snapshot.items[0].operation.payload["content"]
    assert snapshot.items[1].operation.target == {"channel_id": profile.channel_for("macro_news").channel_id}
    assert snapshot.items[1].operation.attachments[0].data == payload
    assert asset_path.read_bytes() == payload
    assert state_path.read_bytes() == original
    assert payload.decode() not in plan_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o600


def test_plan_rejects_instagram_media_symlink_before_owner_handoff(tmp_path, monkeypatch, config_path):
    media_root = tmp_path / "media"
    profile, value, asset_path, _payload = make_state(media_root, config_path, message_ids=False)
    state_path = tmp_path / "ig-state.json"
    state.save_state(state_path, value)
    original = state_path.read_bytes()
    real_path = tmp_path / "outside.png"
    real_path.write_bytes(b"outside image")
    asset_path.unlink()
    asset_path.symlink_to(real_path)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    adapter = InstagramAccountWatchHandoffAdapter(
        state_path,
        tmp_path / "ig-handoff.json",
        {profile.id: profile},
    )

    with pytest.raises(HandoffError):
        plan_handoff(adapter)

    assert state_path.read_bytes() == original
    assert not (tmp_path / "ig-handoff.json").exists()


def test_synthetic_rollback_retry_reuses_instagram_operation_and_media(tmp_path, monkeypatch, config_path):
    import sys

    support = str(Path(__file__).resolve().parents[2] / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    media_root = tmp_path / "media"
    profile, value, _asset_path, _payload = make_state(media_root, config_path)
    state_path = tmp_path / "ig-state.json"
    state.save_state(state_path, value)
    original = state_path.read_bytes()
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    plan_path = tmp_path / "ig-handoff.json"
    adapter = InstagramAccountWatchHandoffAdapter(state_path, plan_path, {profile.id: profile})
    owner = SyntheticDeliveryOwner()

    identities = rehearse_legacy_handoff(
        adapter, owner, restore_source=lambda: state_path.write_bytes(original)
    )

    assert len(identities) == 2
