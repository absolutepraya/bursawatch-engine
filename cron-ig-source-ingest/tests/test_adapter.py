from __future__ import annotations

import json
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
    def accept(self, _event):
        raise AssertionError("media publication must not reach the inbox")


def test_media_publication_stays_pending_at_endpoint_cursor(tmp_path):
    profile = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json").profiles[0]
    row = {"platform": "instagram", "endpoint_id": f"instagram:{profile.handle}", "publisher_id": "instagram-beyondthefundamental", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 4, "subscriptions": [row]}
    post = lambda identity, media, when=NOW: SourcePost(profile.id, identity, f"https://www.instagram.com/p/{identity}/", when, "caption", PublicationKind.POST, media)
    posts = [post("old", ())]
    assert run_once(snapshot, (profile,), tmp_path, Inbox(), NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["status"] == "bootstrapped"
    posts.append(post("new", (SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0),), NOW + timedelta(minutes=1)))
    assert run_once(snapshot, (profile,), tmp_path, Inbox(), NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["status"] == "blocked"
    cursor = json.loads((tmp_path / f"instagram-{profile.handle}" / "cursor.json").read_text())
    assert cursor["order"][1] == "old"
    marker = json.loads((tmp_path / f"instagram-{profile.handle}" / "blocked-media.json").read_text())
    assert marker["provider_event_id"] == "new"
    assert marker["payload"]["caption_html"] == "caption"
    assert "cdn.example" not in json.dumps(marker)
