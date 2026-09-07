from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import config
import state
from models import (
    DownloadedAsset,
    DownloadedPublication,
    MediaKind,
    PublicationKind,
    SourceMedia,
    SourcePost,
    source_locator_digest,
)
from ocr import OCRResult, OCRStatus
from vision_gate import VisionDecision, VisionMode


NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def _profile(config_path: Path):
    return config.load_watch_config(config_path).profiles[0]


def _publication(profile_id: str, shortcode: str, minutes: int, *, caption: str = "Caption") -> SourcePost:
    return SourcePost(
        profile_id,
        f"media-{shortcode}",
        f"https://instagram.com/p/{shortcode}/",
        NOW + timedelta(minutes=minutes),
        caption,
        PublicationKind.POST,
        (SourceMedia("https://cdn.example/signed.jpg?token=secret", MediaKind.IMAGE, 0),),
    )


def _prepared(post: SourcePost, root: Path) -> dict:
    media_root = root / post.publication_id
    asset_path = media_root / "0.jpg"
    downloaded = DownloadedPublication(
        (
            DownloadedAsset(
                SourceMedia("https://cdn.example/signed.jpg?token=secret", MediaKind.IMAGE, 0),
                asset_path,
                "a" * 64,
                123,
                "image/jpeg",
            ),
        ),
        media_root,
    )
    ocr_result = OCRResult(
        OCRStatus.SUCCESS,
        text="Soeharto to Prabowo",
        confidence=0.99,
        min_confidence=0.98,
        engine_id="tesseract",
        model_version="system-psm3-fallback11",
        languages=("ind", "eng"),
    )
    vision = VisionDecision(
        VisionMode.VISION_PARTIAL,
        "partial_uncertain_assets",
        (0,),
        (asset_path,),
        ("image:0:aaaaaaaaaaaa",),
    )
    return {
        "post": post,
        "downloaded_publication": downloaded,
        "ocr_results": (ocr_result,),
        "vision_decision": vision,
    }


def test_new_state_has_version_two_and_empty_delivery_ledgers():
    value = state.new_state()

    assert value == {
        "version": 2,
        "profiles": {},
        "outbox": [],
        "deliveries": [],
        "cleanup": [],
        "filtered_since_last_heartbeat": 0,
    }


def test_first_observation_initializes_cursor_without_backfill(config_path):
    profile = _profile(config_path)
    value = state.new_state()
    publications = [_publication(profile.id, "OLDER", 1), _publication(profile.id, "NEWEST", 2)]

    created = state.observe_publications(
        value,
        profile,
        publications,
        now=NOW,
        prepare_event=lambda item: pytest.fail("first observation must not prepare an event"),
    )

    assert created == 0
    assert value["profiles"][profile.id]["cursor"] == "media-NEWEST"
    assert value["outbox"] == []


def test_later_observation_queues_unseen_publications_in_chronological_order(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    newer = [_publication(profile.id, "102", 2), _publication(profile.id, "101", 1)]

    created = state.observe_publications(value, profile, newer, NOW + timedelta(minutes=3), lambda item: _prepared(item, tmp_path))

    assert created == 2
    assert [event["publication_id"] for event in value["outbox"]] == ["media-101", "media-102"]
    assert value["profiles"][profile.id]["cursor"] == "media-102"
    assert value["outbox"][0]["source_publication_url"] == value["outbox"][0]["post"]["url"]


def test_duplicate_publication_is_not_queued_twice(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    post = _publication(profile.id, "101", 1)
    calls = []

    assert state.observe_publications(value, profile, [post], NOW + timedelta(minutes=1), lambda item: calls.append(item) or _prepared(item, tmp_path)) == 1
    assert state.observe_publications(value, profile, [post], NOW + timedelta(minutes=2), lambda item: calls.append(item) or _prepared(item, tmp_path)) == 0

    assert len(calls) == 1
    assert len(value["outbox"]) == 1


def test_delivered_publication_key_is_not_requeued(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    post = _publication(profile.id, "101", 1)
    state.observe_publications(value, profile, [post], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    event = value["outbox"].pop()
    state.record_delivery(value, event, NOW + timedelta(minutes=2))

    assert state.observe_publications(value, profile, [post], NOW + timedelta(minutes=3), lambda item: pytest.fail("delivered event must not prepare again")) == 0
    assert value["outbox"] == []


def test_disabled_profile_does_not_create_or_update_cursor(config_path):
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["profiles"][0]["enabled"] = False
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    profile = _profile(config_path)
    value = state.new_state()

    assert state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW, lambda item: pytest.fail("disabled profile must not prepare")) == 0
    assert value["profiles"] == {}


def test_prepare_failure_does_not_advance_cursor_or_append_partial_events(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    posts = [_publication(profile.id, "101", 1), _publication(profile.id, "102", 2)]

    def fail_on_second(item):
        if item.publication_id == "media-102":
            raise RuntimeError("private path must not escape")
        return _prepared(item, tmp_path)

    with pytest.raises(ValueError, match="publication preparation failed"):
        state.observe_publications(value, profile, posts, NOW + timedelta(minutes=3), fail_on_second)

    assert value["profiles"][profile.id]["cursor"] == "media-100"
    assert value["outbox"] == []


def test_serialized_post_drops_media_url_but_preserves_timezone_and_order():
    post = _publication("beyondthefundamental", "ABC123", 1)
    post = SourcePost(
        post.profile_id,
        post.publication_id,
        post.url,
        post.published_at,
        post.caption_html,
        post.kind,
        (
            SourceMedia("https://cdn.example/first.jpg?sig=secret", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/second.jpg?sig=secret", MediaKind.IMAGE, 1),
        ),
    )

    serialized = state.serialize_post(post)
    restored = state.deserialize_post(serialized)

    assert "sig=secret" not in json.dumps(serialized)
    assert all(item["url"] == "" for item in serialized["media"])
    assert serialized["media"][0]["locator_digest"] == source_locator_digest(
        "https://cdn.example/first.jpg?sig=secret"
    )
    assert restored.published_at == post.published_at
    assert restored.published_at.tzinfo is not None
    assert [(item.kind, item.index) for item in restored.media] == [
        (MediaKind.IMAGE, 0),
        (MediaKind.IMAGE, 1),
    ]
    assert all(item.kind is MediaKind.IMAGE for item in restored.media)


def test_downloaded_ocr_and_vision_metadata_roundtrip_without_signed_urls(tmp_path):
    post = _publication("beyondthefundamental", "ABC123", 1)
    prepared = _prepared(post, tmp_path)
    downloaded = state.serialize_downloaded_publication(prepared["downloaded_publication"])
    restored_downloaded = state.deserialize_downloaded_publication(downloaded)
    ocr = state.serialize_ocr_result(prepared["ocr_results"][0])
    restored_ocr = state.deserialize_ocr_result(ocr)
    vision = state.serialize_vision_decision(prepared["vision_decision"])
    restored_vision = state.deserialize_vision_decision(vision)

    assert "token=secret" not in json.dumps(downloaded)
    assert "cdn.example" not in json.dumps(downloaded)
    assert downloaded["assets"][0]["source"]["url"] == ""
    assert downloaded["assets"][0]["source"]["locator_digest"] == source_locator_digest(
        "https://cdn.example/signed.jpg?token=secret"
    )
    assert restored_downloaded.media_root == prepared["downloaded_publication"].media_root
    assert restored_downloaded.assets[0].path == prepared["downloaded_publication"].assets[0].path
    assert restored_ocr == prepared["ocr_results"][0]
    assert restored_vision.mode is VisionMode.VISION_PARTIAL
    assert restored_vision.asset_paths == prepared["vision_decision"].asset_paths


def test_source_media_state_requires_a_locator_digest():
    serialized = state.serialize_post(_publication("beyondthefundamental", "ABC123", 1))
    del serialized["media"][0]["locator_digest"]

    with pytest.raises(ValueError, match="state is invalid"):
        state.deserialize_post(serialized)


def test_source_media_digest_must_match_the_transient_url():
    post = _publication("beyondthefundamental", "ABC123", 1)
    mismatched_media = SourceMedia(
        post.media[0].url,
        MediaKind.IMAGE,
        0,
        "a" * 64,
    )
    mismatched = SourcePost(
        post.profile_id,
        post.publication_id,
        post.url,
        post.published_at,
        post.caption_html,
        post.kind,
        (mismatched_media,),
    )

    with pytest.raises(ValueError, match="state is invalid"):
        state.serialize_post(mismatched)


def test_state_version_mismatch_is_rejected_without_migration(tmp_path):
    path = tmp_path / "state.json"
    legacy = state.new_state()
    legacy["version"] = 1
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.raises(ValueError, match="state is invalid"):
        state.load_state(path)

    future = state.new_state()
    future["version"] = state.STATE_VERSION + 1
    path.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(ValueError, match="state is invalid"):
        state.load_state(path)


def test_event_rejects_swapped_downloaded_locator_identity(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    post = SourcePost(
        profile.id,
        "media-swapped",
        "https://instagram.com/p/SWAPPED/",
        NOW + timedelta(minutes=1),
        "Caption",
        PublicationKind.POST,
        (
            SourceMedia("https://cdn.example/first.jpg?token=first", MediaKind.IMAGE, 0),
            SourceMedia("https://cdn.example/second.jpg?token=second", MediaKind.IMAGE, 1),
        ),
    )
    media_root = tmp_path / post.publication_id
    media_root.mkdir(parents=True)
    downloaded = DownloadedPublication(
        (
            DownloadedAsset(
                SourceMedia(post.media[1].url, MediaKind.IMAGE, 0),
                media_root / "0.jpg",
                "a" * 64,
                1,
                "image/jpeg",
            ),
            DownloadedAsset(
                SourceMedia(post.media[0].url, MediaKind.IMAGE, 1),
                media_root / "1.jpg",
                "b" * 64,
                1,
                "image/jpeg",
            ),
        ),
        media_root,
    )

    with pytest.raises(ValueError, match="publication preparation failed"):
        state.observe_publications(
            value,
            profile,
            [post],
            NOW + timedelta(minutes=2),
            lambda item: {"downloaded_publication": downloaded},
        )

    assert value["profiles"][profile.id]["cursor"] == "media-100"
    assert value["outbox"] == []


def test_event_keeps_text_and_media_progress_independent(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    event = value["outbox"][0]
    event["text_index"] = 2
    event["media_index"] = 1
    path = tmp_path / "nested" / "state.json"

    state.save_state(path, value)
    restored = state.load_state(path)

    assert restored["outbox"][0]["text_index"] == 2
    assert restored["outbox"][0]["media_index"] == 1


def test_claim_sets_a_fifteen_minute_lease_and_returns_stable_event_key(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))

    claimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=2))

    assert claimed is value["outbox"][0]
    assert claimed["event_key"] == f"{profile.id}:media-101"
    assert claimed["agent_phase"] == "awaiting_agent"
    assert datetime.fromisoformat(claimed["agent_lease_until"]) == NOW + timedelta(minutes=17)
    assert state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=3)) is None


def test_elapsed_or_malformed_lease_is_reclaimed_before_next_claim(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    first = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=2))
    assert first is not None

    first["agent_lease_until"] = "not-a-timestamp"
    reclaimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=3))
    assert reclaimed is first
    assert reclaimed["agent_phase"] == "awaiting_agent"

    reclaimed["agent_lease_until"] = (NOW + timedelta(minutes=3)).isoformat()
    reclaimed_again = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=4))
    assert reclaimed_again is first


def test_submission_requires_exact_active_event_key_and_valid_analysis(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=2))
    assert claimed is not None
    analysis = {"title": "Macro: Uji", "summary": "Ringkasan sumber", "route": "macro", "is_relevant": True}

    with pytest.raises(ValueError):
        state.submit_analysis(value, f"{claimed['event_key']}:extra", analysis, NOW + timedelta(minutes=2))
    with pytest.raises(ValueError):
        state.submit_analysis(value, claimed["event_key"], {**analysis, "unexpected": "field"}, NOW + timedelta(minutes=2))

    submitted = state.submit_analysis(value, claimed["event_key"], analysis, NOW + timedelta(minutes=2))

    assert submitted["agent_phase"] == "ready"
    assert submitted["agent_lease_until"] is None
    assert submitted["title"] == "Macro: Uji"
    assert submitted["route"] == "macro"


def test_expired_lease_cannot_be_submitted_or_discarded(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW)
    assert claimed is not None
    expired_at = NOW + timedelta(minutes=16)

    with pytest.raises(ValueError, match="not active"):
        state.submit_analysis(value, claimed["event_key"], {"title": "Expired"}, expired_at)
    with pytest.raises(ValueError, match="not active"):
        state.discard_analysis(value, claimed["event_key"], expired_at)
    assert len(value["outbox"]) == 1


def test_discard_removes_only_active_event_and_increments_filtered_count(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    posts = [_publication(profile.id, "101", 1), _publication(profile.id, "102", 2)]
    state.observe_publications(value, profile, posts, NOW + timedelta(minutes=3), lambda item: _prepared(item, tmp_path))
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, NOW + timedelta(minutes=4))
    assert claimed is not None

    state.discard_analysis(value, claimed["event_key"], NOW + timedelta(minutes=4))

    assert [event["publication_id"] for event in value["outbox"]] == ["media-102"]
    assert value["cleanup"] == [{
        "event_key": f"{profile.id}:media-101",
        "profile_id": profile.id,
        "publication_id": "media-101",
        "media_root": str(tmp_path / "media-101"),
        "attempts": 0,
        "last_error": None,
    }]
    assert value["filtered_since_last_heartbeat"] == 1
    assert state.take_filtered_since_last_heartbeat(value) == 1
    assert value["filtered_since_last_heartbeat"] == 0


def test_delivery_ledger_retains_recent_entries_and_prunes_older_than_ninety_days(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    state.observe_publications(value, profile, [_publication(profile.id, "101", 1)], NOW + timedelta(minutes=1), lambda item: _prepared(item, tmp_path))
    event = value["outbox"][0]
    old = dict(
        event,
        event_key=f"{profile.id}:media-old",
        publication_id="media-old",
        post=state.serialize_post(_publication(profile.id, "OLD", -2000)),
    )
    old["text_message_ids"] = []
    old["media_message_ids"] = []
    old["delivered_at"] = (NOW - timedelta(days=91)).isoformat()
    value["deliveries"].append({
        "event_key": old["event_key"],
        "profile_id": profile.id,
        "publication_id": "media-old",
        "text_message_ids": [],
        "media_message_ids": [],
        "delivered_at": old["delivered_at"],
        "cleanup_pending": False,
    })
    state.record_delivery(value, event, NOW, text_message_ids=["text-1"], media_message_ids=["media-1"])

    assert [item["event_key"] for item in value["deliveries"]] == [event["event_key"]]
    assert value["deliveries"][0]["text_message_ids"] == ["text-1"]


def test_load_missing_and_malformed_state_are_safe(tmp_path):
    missing = state.load_state(tmp_path / "missing" / "state.json")
    assert missing == state.new_state()

    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps({"version": 2, "profiles": {}, "outbox": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="state is invalid"):
        state.load_state(malformed)

    malformed.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="state is invalid"):
        state.load_state(malformed)


def test_save_is_atomic_creates_parent_and_rejects_symlink_target_or_parent(tmp_path):
    value = state.new_state()
    path = tmp_path / "nested" / "state.json"
    state.save_state(path, value)
    assert state.load_state(path) == value
    assert not list(path.parent.glob("*.tmp"))

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link_target = tmp_path / "target-link.json"
    link_target.symlink_to(target)
    with pytest.raises(ValueError, match="state is invalid"):
        state.save_state(link_target, value)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="state is invalid"):
        state.save_state(link_parent / "state.json", value)


def test_save_rejects_oversized_serialized_bytes_before_replacing_target(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(state, "MAX_STATE_BYTES", 16)

    with pytest.raises(ValueError, match="exceeds the size limit"):
        state.save_state(path, state.new_state())

    assert path.read_text(encoding="utf-8") == "sentinel"
    assert not list(tmp_path.glob(".*.tmp"))


def test_downloaded_asset_rejects_symlink_and_resolved_escape(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "image.jpg"
    target.write_bytes(b"image")
    linked_file = root / "linked.jpg"
    linked_file.symlink_to(target)

    downloaded = DownloadedPublication(
        (DownloadedAsset(SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0), linked_file, "a" * 64, 5, "image/jpeg"),),
        root,
    )
    with pytest.raises(ValueError, match="state is invalid"):
        state.serialize_downloaded_publication(downloaded)

    linked_directory = root / "linked-directory"
    linked_directory.symlink_to(outside, target_is_directory=True)
    escaped_path = linked_directory / "image.jpg"
    escaped = DownloadedPublication(
        (DownloadedAsset(SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0), escaped_path, "a" * 64, 5, "image/jpeg"),),
        root,
    )
    with pytest.raises(ValueError, match="state is invalid"):
        state.serialize_downloaded_publication(escaped)


def test_vision_paths_require_downloaded_root_and_cannot_escape_it(config_path, tmp_path):
    profile = _profile(config_path)
    value = state.new_state()
    state.observe_publications(value, profile, [_publication(profile.id, "100", 0)], NOW, lambda item: {})
    post = _publication(profile.id, "101", 1)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"image")
    root = tmp_path / "media-101"
    root.mkdir()
    downloaded = DownloadedPublication(
        (DownloadedAsset(SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0), root / "0.jpg", "a" * 64, 5, "image/jpeg"),),
        root,
    )
    vision = VisionDecision(VisionMode.VISION_PARTIAL, "partial_uncertain_assets", (0,), (outside,), ("image:0:aaaaaaaaaaaa",))

    with pytest.raises(ValueError, match="publication preparation failed"):
        state.observe_publications(
            value,
            profile,
            [post],
            NOW + timedelta(minutes=1),
            lambda item: {"post": item, "downloaded_publication": downloaded, "vision_decision": vision},
        )
    assert value["profiles"][profile.id]["cursor"] == "media-100"
    assert value["outbox"] == []

    inside = root / "0.jpg"
    vision_without_download = VisionDecision(VisionMode.VISION_PARTIAL, "partial_uncertain_assets", (0,), (inside,), ("image:0:aaaaaaaaaaaa",))
    with pytest.raises(ValueError, match="publication preparation failed"):
        state.observe_publications(
            value,
            profile,
            [post],
            NOW + timedelta(minutes=1),
            lambda item: {"post": item, "vision_decision": vision_without_download},
        )
    assert value["profiles"][profile.id]["cursor"] == "media-100"
    assert value["outbox"] == []
