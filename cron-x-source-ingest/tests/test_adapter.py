from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-x-source-ingest" / "bin"))
from adapter import endpoints, run_once

sys.path.insert(0, str(ROOT / "cron-x-account-watch" / "bin"))
from config import load_watch_config
from models import PostKind, SourceMedia, SourcePost

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []
    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}


class MediaStore:
    def __init__(self):
        self.uploads = []
    def upload(self, key, data, *, kind, content_type, filename):
        self.uploads.append((key, data, kind, content_type, filename))
        return {"ref": "20000000-0000-4000-8000-000000000001", "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True}


def fake_image_prepare(post, root):
    from vision_media import VisionAsset, VisionBundle
    directory = root / post.profile_id / post.post_id
    directory.mkdir(parents=True)
    assets = []
    media = [("tweet", item) for item in post.media] + [("quoted_tweet", item) for item in post.quoted_media]
    seen = set()
    for role, source in media:
        if source.url in seen:
            continue
        seen.add(source.url)
        path = directory / f"{len(assets)}.jpg"
        path.write_bytes(b"\xff\xd8\xffimage")
        assets.append(VisionAsset(role, post.post_id, source.index, path))
    return VisionBundle(directory, tuple(assets), 0)


def test_x_parser_identity_and_future_only_ingest(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    row = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 3, "subscriptions": [row]}
    post = lambda identity: SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, "<p>Market</p>", PostKind.NORMAL, None, None, (), ())
    posts = [post("10")]
    inbox = Inbox()
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["status"] == "bootstrapped"
    posts.append(post("11"))
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["accepted"] == 1
    assert inbox.events[0]["payload"]["post"]["content_html"] == "<p>Market</p>"
    assert inbox.events[0]["provider_event_id"] == "11"


def test_x_rejects_unverified_catalog(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    row = {"platform": "x", "endpoint_id": f"x:{profile.handle.casefold()}", "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "pending", "enabled": True}
    with pytest.raises(Exception):
        endpoints({"revision": 3, "subscriptions": [row]}, (profile,))


def test_full_rsshub_page_without_old_anchor_blocks_unseen_gap(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    row = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 3, "subscriptions": [row]}
    post = lambda identity: SourcePost(profile.id, str(identity), f"https://x.com/{profile.handle}/status/{identity}", NOW, "text", PostKind.NORMAL, None, None, (), ())
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: [post(10)])
    # The old anchor has already fallen off a saturated RSSHub page. Treat
    # the missing interval as unknown even though all returned IDs are newer.
    full_page = [post(identity) for identity in range(11, 11 + profile.max_items_per_poll)]
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: full_page)
    assert result == [{"endpoint_id": endpoint_id, "status": "blocked", "reason": "page_truncated"}]
    cursor = json.loads((tmp_path / endpoint_id.replace(":", "-") / "cursor.json").read_text())
    assert cursor["anchor"] == "10"
    assert inbox.events == []


def test_x_media_upload_is_durable_and_payload_keeps_no_media_locator(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    row = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 3, "subscriptions": [row]}
    url = "https://pbs.twimg.com/media/chart.jpg"
    make_post = lambda identity, media=(): SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, f"<p>Market</p><img src='{url}'>" if media else "<p>Market</p>", PostKind.NORMAL, None, None, tuple(media), ())
    posts = [make_post("10", (SourceMedia(url, 0),))]
    inbox = Inbox()
    store = MediaStore()
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts, media_store=store, media_preparer=fake_image_prepare)[0]["status"] == "bootstrapped"
    assert store.uploads == []
    posts.append(make_post("11", (SourceMedia(url, 0),)))
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts, media_store=store, media_preparer=fake_image_prepare)[0]
    assert result["accepted"] == 1
    assert store.uploads[0][0] == f"x:{endpoint_id}:11:attachment:0"
    event = inbox.events[0]
    assert event["provider_event_id"] == "11"
    assert event["media_refs"][0]["ref"] == "20000000-0000-4000-8000-000000000001"
    assert "pbs.twimg.com" not in json.dumps(event["payload"])
    assert event["payload"]["post"]["media"][0]["media_ref_id"] == event["media_refs"][0]["ref"]


def test_unsupported_x_video_media_holds_cursor(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    row = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 3, "subscriptions": [row]}
    post = lambda identity, media=(): SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, "Video post", PostKind.NORMAL, None, None, tuple(media), ())
    posts = [post("10")]
    inbox = Inbox()
    store = MediaStore()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(post("11", (SourceMedia("https://video.twimg.com/ext_tw_video/11/pu/vid/avc1/480x270/video.mp4", 0),)))
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts, media_store=store, media_preparer=fake_image_prepare)[0]
    assert result == {"endpoint_id": endpoint_id, "status": "blocked", "reason": "media_blocked"}
    cursor = json.loads((tmp_path / endpoint_id.replace(":", "-") / "cursor.json").read_text())
    assert cursor["anchor"] == "10"
    assert store.uploads == []
