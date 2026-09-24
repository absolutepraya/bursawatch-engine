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
from models import PostKind, SourcePost

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []
    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}


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
