from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-wa-channel-watch" / "bin"))
sys.path.insert(0, str(ROOT / "cron-wa-source-ingest" / "bin"))

import archive
import pipeline_owner
import source_work_routes
import state
from config import LoadedWatchConfig, load

NOW = datetime(2026, 9, 25, 8, tzinfo=timezone.utc)


class Inbox:
    def __init__(self, envelope: dict, capabilities: tuple[str, ...] = ("swing_chart_context",)):
        identity = [envelope["platform"], envelope["endpoint_id"], envelope["provider_event_id"]]
        self.event_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        self.envelope = envelope
        self.rows = []
        for capability in capabilities:
            work_key = hashlib.sha256(f"{self.event_key}:1:{capability}".encode()).hexdigest()
            self.rows.append({
                "work_key": work_key, "effect_key": work_key, "event_key": self.event_key,
                "version": 1, "capability_id": capability, "pipeline_id": capability,
                "catalog_revision": 7, "settings": {}, "status": "executing",
                "lease_token": f"lease-{capability}",
            })

    def inspect(self, event_key: str) -> dict:
        assert event_key == self.event_key
        return {
            "event": {"event_key": event_key, "versions": [{"version": 1, "envelope": self.envelope}]},
            "work": self.rows,
        }

    def work(self, capability: str) -> dict:
        row = next(item for item in self.rows if item["pipeline_id"] == capability)
        return {**row, "event_kind": "original", "envelope": self.envelope}


class MediaStore:
    def __init__(self, content: bytes, reference: dict):
        self.content = content
        self.reference = reference
        self.downloads: list[str] = []

    def download(self, ref: str):
        self.downloads.append(ref)
        assert ref == self.reference["ref"]
        return SimpleNamespace(data=self.content, content_type="image/jpeg", kind="image")


def make_work(*, with_media: bool = True) -> tuple[dict, Inbox, MediaStore | None, tuple]:
    watch = load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json")
    profile = next(row for row in watch.profiles if row.id == "bri-danareksa-sekuritas")
    endpoint_id = f"whatsapp:{profile.channel_url.rstrip('/').rsplit('/', 1)[-1]}"
    media_refs = []
    manifest = []
    store = None
    if with_media:
        content = b"\xff\xd8\xffverified BRI chart"
        reference = {
            "ref": "30000000-0000-4000-8000-000000000001",
            "sha256": hashlib.sha256(content).hexdigest(),
            "kind": "image", "content_type": "image/jpeg", "size_bytes": len(content),
            "filename": "whatsapp-media-0.jpg", "durable": True,
        }
        media_refs = [reference]
        manifest = [{"index": 0, "kind": "image", "mime": "image/jpeg", "ref_id": reference["ref"]}]
        store = MediaStore(content, reference)
    envelope = {
        "version": 1, "platform": "whatsapp", "endpoint_id": endpoint_id,
        "publisher_id": "bri-danareksa", "provider_event_id": "bri-message-1",
        "published_at": NOW.isoformat(), "observed_at": NOW.isoformat(),
        "source_url": profile.channel_url, "parser_version": "whatsapp-bridge-queue-1",
        "content_hash": "a" * 64,
        "payload": {
            "channel_jid": profile.channel_jid,
            "text": "#TechnicalReview CPIN support and resistance chart",
            "links": [], "owner_config_revision": 3,
            "media_ref_ids": [row["ref"] for row in media_refs], "media_manifest": manifest,
        },
        "media_refs": media_refs, "media_required": bool(media_refs),
    }
    inbox = Inbox(envelope)
    work = inbox.work("swing_chart_context")
    return work, inbox, store, watch.profiles


def test_whatsapp_source_work_hands_verified_chart_to_existing_watcher_without_posting(tmp_path, monkeypatch):
    work, inbox, media, profiles = make_work()
    state_path = tmp_path / "watcher" / "state.json"
    archive_root = tmp_path / "watcher" / "archive"
    staging_root = tmp_path / "watcher" / "staging"
    monkeypatch.setattr(pipeline_owner.config, "load_for_run", lambda *_args: LoadedWatchConfig(load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json"), 3))
    monkeypatch.setattr(pipeline_owner.scan.discord, "post_text", lambda *_args, **_kwargs: pytest.fail("Discord post attempted"))
    monkeypatch.setattr(pipeline_owner.scan.discord, "post_media", lambda *_args, **_kwargs: pytest.fail("Discord media attempted"))

    outcome = pipeline_owner.submit(
        work, no_post=True, inbox=inbox, media_store=media,
        state_path=state_path, archive_root=archive_root, staging_root=staging_root,
    )
    assert outcome == "accepted"
    assert media is not None and media.downloads == [work["envelope"]["media_refs"][0]["ref"]]

    saved = state.load(state_path)
    assert len(saved["outbox"]) == 1
    record = saved["outbox"][0]
    assert record["event_key"] == "120363419226413141@newsletter:bri-message-1"
    assert record["source_pipeline_capabilities"] == ["swing_chart_context"]
    assert record["source_pipeline_route_keys"] == ["id_stocks_swing"]
    assert record["event"]["media"][0]["path"] is None
    archived = archive.query(archive_root, event_key=record["event_key"])
    assert len(archived) == 1 and archived[0].data["media"][0]["capture_status"] == "captured"
    assert pipeline_owner.submit(
        work, no_post=True, inbox=inbox, media_store=media,
        state_path=state_path, archive_root=archive_root, staging_root=staging_root,
    ) == "accepted"
    assert len(state.load(state_path)["outbox"]) == 1
    assert media.downloads == [work["envelope"]["media_refs"][0]["ref"]]

    wake = pipeline_owner.claim_agent(
        no_post=True, state_path=state_path, archive_root=archive_root,
        config_path=ROOT / "cron-wa-channel-watch" / "config" / "watches.json", now=NOW,
    )
    assert wake["wakeAgent"] is True
    assert wake["item"]["event_key"] == record["event_key"]
    assert "#TechnicalReview" in wake["item"]["post_text"]
    assert wake["item"]["media_kinds"] == ["image"]


def test_source_scope_records_no_match_and_delivers_only_subscribed_classifications():
    record = {"source_pipeline_route_keys": ["macro_news"]}
    items = [
        {"route": "id_stocks_news", "title": "CPIN: issuer update"},
        {"route": "macro_news", "title": "Market conditions"},
    ]
    selected, outcome, dropped = source_work_routes.filter_items(record, items)
    assert selected == [items[1]]
    assert outcome == "partially_subscribed"
    assert dropped == ["id_stocks_news"]

    selected, outcome, dropped = source_work_routes.filter_items(record, [items[0]])
    assert selected == []
    assert outcome == "route_not_subscribed"
    assert dropped == ["id_stocks_news"]


def test_legacy_whatsapp_records_keep_their_existing_route_behavior():
    items = [{"route": "macro_news", "title": "Market conditions"}]
    selected, outcome, dropped = source_work_routes.filter_items({}, items)
    assert selected == items
    assert outcome is None and dropped == []
