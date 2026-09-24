from __future__ import annotations

import json
import hashlib
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-ig-source-ingest" / "bin"))
from adapter import run_once

sys.path.insert(0, str(ROOT / "cron-ig-account-watch" / "bin"))
from config import load_watch_config
from models import MediaKind, PublicationKind, SourceMedia, SourcePost

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []
    def accept(self, _event):
        self.events.append(_event)
        return {"event_key": "fake", "version": 1, "duplicate": False, "work_keys": []}


class MediaStore:
    def __init__(self):
        self.uploads = []
    def upload(self, key, data, *, kind, content_type, filename):
        self.uploads.append((key, data, kind, content_type, filename))
        return {"ref": "30000000-0000-4000-8000-000000000001", "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True}


def fake_download(post, root):
    from models import DownloadedAsset, DownloadedPublication
    assets = []
    for source in post.media:
        suffix = ".jpg" if source.kind is MediaKind.IMAGE else ".mp4"
        content_type = "image/jpeg" if source.kind is MediaKind.IMAGE else "video/mp4"
        path = root / post.publication_id / f"{source.index}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"\xff\xd8\xffimage" if source.kind is MediaKind.IMAGE else b"video-bytes"
        path.write_bytes(data)
        assets.append(DownloadedAsset(source, path, hashlib.sha256(data).hexdigest(), len(data), content_type))
    return DownloadedPublication(tuple(assets), root / post.publication_id)


def test_media_publication_uploads_refs_before_inbox_acceptance(tmp_path):
    profile = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json").profiles[0]
    row = {"platform": "instagram", "endpoint_id": f"instagram:{profile.handle}", "publisher_id": "instagram-beyondthefundamental", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 4, "subscriptions": [row]}
    post = lambda identity, media, when=NOW: SourcePost(profile.id, identity, f"https://www.instagram.com/p/{identity}/", when, "caption", PublicationKind.POST, media)
    posts = [post("old", ())]
    inbox = Inbox()
    store = MediaStore()
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: list(reversed(posts)), media_store=store, media_downloader=fake_download)[0]["status"] == "bootstrapped"
    assert store.uploads == []
    posts.append(post("new", (SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0),), NOW + timedelta(minutes=1)))
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: list(reversed(posts)), media_store=store, media_downloader=fake_download)[0]
    assert result["accepted"] == 1
    assert store.uploads[0][0] == f"instagram:instagram:{profile.handle}:new:attachment:0"
    event = inbox.events[0]
    assert event["provider_event_id"] == "new"
    assert event["media_refs"][0]["ref"] == "30000000-0000-4000-8000-000000000001"
    assert "cdn.example" not in json.dumps(event["payload"])
    assert event["payload"]["media_ref_ids"] == [event["media_refs"][0]["ref"]]


def test_media_without_durable_upload_keeps_cursor_pending(tmp_path):
    profile = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json").profiles[0]
    row = {"platform": "instagram", "endpoint_id": f"instagram:{profile.handle}", "publisher_id": "instagram-beyondthefundamental", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 4, "subscriptions": [row]}
    post = lambda identity, media, when=NOW: SourcePost(profile.id, identity, f"https://www.instagram.com/p/{identity}/", when, "caption", PublicationKind.POST, media)
    posts = [post("old", ())]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: list(reversed(posts)))
    posts.append(post("new", (SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0),), NOW + timedelta(minutes=1)))
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: list(reversed(posts)))[0]
    assert result["status"] == "blocked"
    cursor = json.loads((tmp_path / f"instagram-{profile.handle}" / "cursor.json").read_text())
    assert cursor["anchor"] == "old"
    marker = json.loads((tmp_path / f"instagram-{profile.handle}" / "blocked-media.json").read_text())
    assert marker["provider_event_id"] == "new"
    assert marker["payload"]["caption_html"] == "caption"
    assert "cdn.example" not in json.dumps(marker)
