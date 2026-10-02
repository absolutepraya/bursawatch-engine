from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-ig-account-watch" / "bin"))
sys.path.insert(0, str(ROOT / "cron-ig-source-ingest" / "bin"))

import pipeline_owner
import runner
import scan
import source_work_routes
import state
from config import LoadedWatchConfig, load_watch_config
from models import MediaKind, PublicationKind, SourceMedia, SourcePost
from ocr import OCRResult, OCRStatus

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []
        self.rows = []

    def accept(self, envelope):
        self.events.append(envelope)
        identity = json.dumps(["instagram", envelope["endpoint_id"], envelope["provider_event_id"]], separators=(",", ":"))
        event_key = hashlib.sha256(identity.encode()).hexdigest()
        capability = "company_news"
        work_key = hashlib.sha256(f"{event_key}:1:{capability}".encode()).hexdigest()
        self.rows.append({
            "work_key": work_key, "effect_key": work_key, "event_key": event_key, "version": 1,
            "capability_id": capability, "pipeline_id": capability, "capability_version": 1,
            "catalog_revision": 4,
            "settings": {}, "status": "pending", "lease_token": None,
        })
        return {"event_key": event_key, "version": 1, "duplicate": False, "work_keys": [work_key]}

    def claim(self, capabilities, limit):
        claimed = []
        for row in self.rows:
            if row["pipeline_id"] in capabilities and row["status"] == "pending":
                row["status"] = "leased"
                row["lease_token"] = "lease-1"
                claimed.append({**row, "event_kind": "original", "envelope": self.events[0]})
        return claimed[:limit]

    def begin(self, work_key, token):
        row = next(row for row in self.rows if row["work_key"] == work_key)
        if row["lease_token"] != token:
            return False
        row["status"] = "executing"
        return True

    def settle(self, work_key, token, success, error_code=None):
        row = next(row for row in self.rows if row["work_key"] == work_key)
        assert row["lease_token"] == token
        row["status"] = "done" if success else "pending"
        return {"status": row["status"]}

    def inspect(self, event_key):
        assert all(row["event_key"] == event_key for row in self.rows)
        return {
            "event": {"event_key": event_key, "versions": [{"version": 1, "envelope": self.events[0]}]},
            "work": self.rows,
        }


class MediaStore:
    def __init__(self):
        self.content = b"\xff\xd8\xffsample-original"
        self.reference = "30000000-0000-4000-8000-000000000001"
        self.downloads = []

    def upload(self, _key, data, *, kind, content_type, filename):
        assert data == self.content
        return {
            "ref": self.reference, "sha256": hashlib.sha256(data).hexdigest(), "kind": kind,
            "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True,
        }

    def download(self, ref):
        self.downloads.append(ref)
        assert ref == self.reference
        return SimpleNamespace(data=self.content, content_type="image/jpeg", kind="image")


@pytest.mark.parametrize("irrelevant", [False, True])
def test_source_work_uses_existing_analysis_and_records_unsubscribed_route_without_delivery(tmp_path, monkeypatch, irrelevant):
    watch = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json")
    profile = watch.profiles[0]
    storage = tmp_path / "owner" / "state.json"
    media_root = tmp_path / "owner" / "media"
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_OCR_CACHE_PATH", str(tmp_path / "owner" / "ocr-cache"))
    monkeypatch.setattr(pipeline_owner.config, "load_watch_config_for_run", lambda *_args: LoadedWatchConfig(watch, 4))
    monkeypatch.setattr(scan, "_ocr_backend_for_run", lambda: SimpleNamespace(engine_id="fake", model_version="fake-v1"))
    monkeypatch.setattr(scan.ocr, "extract_cached", lambda asset, *_args: OCRResult(
        OCRStatus.SUCCESS, text=f"Broad earnings outlook in asset {asset.source.index}", confidence=0.99,
        min_confidence=0.90, engine_id="fake", model_version="fake-v1", languages=profile.ocr_languages,
    ))
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: pytest.fail("Discord post was attempted"))
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: pytest.fail("Discord media post was attempted"))
    row = {
        "platform": "instagram", "endpoint_id": f"instagram:{profile.handle}",
        "publisher_id": f"instagram-{profile.id}", "address": profile.handle, "provider_id": None,
        "capability_id": "company_news", "verification_status": "verified", "enabled": True,
    }
    snapshot = {"revision": 4, "subscriptions": [row]}
    old = SourcePost(profile.id, "old", "https://www.instagram.com/p/old/", NOW, "old", PublicationKind.POST, ())
    current = SourcePost(
        profile.id, "new", "https://www.instagram.com/p/new/", NOW + timedelta(minutes=1),
        "Aggregate earnings indicate broad equity market pressure", PublicationKind.POST,
        (SourceMedia("https://cdn.example/original.jpg", MediaKind.IMAGE, 0),),
    )
    posts = [old]
    inbox = Inbox()
    media = MediaStore()

    def fake_download(post, root):
        from models import DownloadedAsset, DownloadedPublication
        event_root = root / post.publication_id
        event_root.mkdir(parents=True, exist_ok=True)
        path = event_root / "0.jpg"
        path.write_bytes(media.content)
        asset = DownloadedAsset(post.media[0], path, hashlib.sha256(media.content).hexdigest(), len(media.content), "image/jpeg")
        return DownloadedPublication((asset,), event_root)

    def fetch_profile(*_args, **_kwargs):
        return list(reversed(posts))

    handler = lambda item: pipeline_owner.submit(item, no_post=True, inbox=inbox, media_store=media)
    dispatch = lambda: pipeline_owner.claim_agent(no_post=True)
    first = runner.run_once(snapshot, (profile,), tmp_path / "source", inbox, NOW, fetch_profile=fetch_profile, media_store=media, media_downloader=fake_download, handlers={"company_news": handler}, owner_drain=lambda: pipeline_owner.drain(no_post=True), agent_claim=dispatch)
    assert first["source"][0]["status"] == "bootstrapped"
    assert first["work"] == [] and first["wakeAgent"] is False

    posts.append(current)
    result = runner.run_once(snapshot, (profile,), tmp_path / "source", inbox, NOW, fetch_profile=fetch_profile, media_store=media, media_downloader=fake_download, handlers={"company_news": handler}, owner_drain=lambda: pipeline_owner.drain(no_post=True), agent_claim=dispatch)
    assert result["source"][0]["accepted"] == 1
    assert result["work"][0]["status"] == "done"
    assert result["wakeAgent"] is True
    assert result["item"]["event_key"] == f"{profile.id}:new"
    assert result["item"]["ocr_assets"][0]["text"] == "Broad earnings outlook in asset 0"
    assert "macro_news" in result["item"]["instruction"]
    assert media.downloads == [media.reference]
    assert source_work_routes.allowed_routes(storage, f"{profile.id}:new") == frozenset({"id_stocks_news"})

    if irrelevant:
        result = scan.submit_analysis_payload({"event_key": f"{profile.id}:new", "is_relevant": False}, dry_run=True)
        assert result == {"submitted": True, "ignored": True, "delivered": 0}
    else:
        result = scan.submit_analysis_payload({
            "event_key": f"{profile.id}:new", "is_relevant": True,
            "title": "Pelemahan prospek laba di pasar saham", "summary": "Prospek laba agregat menekan pasar saham.",
            "route": "macro_news",
        }, dry_run=True)
        assert result == {"submitted": True, "ignored": True, "delivered": 0, "outcome": "route_not_subscribed"}
    assert state.load_state(storage)["outbox"] == []
    audit_path = next((storage.parent / "source-work").glob("*.outcome.json"))
    audit = json.loads(audit_path.read_text())
    assert audit["outcome"] == ("irrelevant" if irrelevant else "route_not_subscribed")
    if not irrelevant:
        assert audit["classified_route"] == "macro_news"

    # Retry of the already settled source work does not fetch or enqueue it.
    item = {**inbox.rows[0], "event_kind": "original", "envelope": inbox.events[0]}
    inbox.rows[0]["status"] = "executing"
    assert pipeline_owner.submit(item, no_post=True, inbox=inbox, media_store=media) == "accepted"
    assert media.downloads == [media.reference]
    assert state.load_state(storage)["outbox"] == []


def test_source_work_holds_retry_when_original_cannot_be_retrieved(tmp_path, monkeypatch):
    watch = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json")
    profile = watch.profiles[0]
    storage = tmp_path / "owner" / "state.json"
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(tmp_path / "owner" / "media"))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_OCR_CACHE_PATH", str(tmp_path / "owner" / "ocr-cache"))
    monkeypatch.setattr(pipeline_owner.config, "load_watch_config_for_run", lambda *_args: LoadedWatchConfig(watch, 4))
    media = MediaStore()
    envelope = {
        "platform": "instagram", "endpoint_id": f"instagram:{profile.handle}", "publisher_id": f"instagram-{profile.id}",
        "provider_event_id": "new", "published_at": NOW.isoformat(), "source_url": "https://www.instagram.com/p/new/",
        "payload": {"caption_html": "Broad earnings outlook", "kind": "post", "media_ref_ids": [media.reference]},
        "media_required": True, "media_refs": [media.upload("unused", media.content, kind="image", content_type="image/jpeg", filename="0.jpg")],
        "content_hash": "a" * 64,
    }
    event_key = hashlib.sha256(json.dumps(
        [envelope["platform"], envelope["endpoint_id"], envelope["provider_event_id"]],
        separators=(",", ":"),
    ).encode()).hexdigest()
    work_key = hashlib.sha256(f"{event_key}:1:company_news".encode()).hexdigest()
    work = {
        "work_key": work_key, "effect_key": work_key, "event_key": event_key, "version": 1,
        "pipeline_id": "company_news", "capability_id": "company_news", "event_kind": "original",
        "capability_version": 1, "catalog_revision": 4, "lease_token": "lease-1", "envelope": envelope,
    }
    inbox = Inbox()
    inbox.events = [envelope]
    inbox.rows = [{"work_key": work_key, "effect_key": work_key, "event_key": event_key, "version": 1, "capability_id": "company_news", "pipeline_id": "company_news", "capability_version": 1, "catalog_revision": 4, "settings": {}, "status": "executing", "lease_token": "lease-1"}]

    class MissingOriginal:
        def download(self, _ref):
            raise RuntimeError("object unavailable")

    with pytest.raises(ValueError, match="Instagram source work identity is invalid"):
        pipeline_owner.submit({**work, "capability_version": 2}, no_post=True, inbox=inbox, media_store=media)
    with pytest.raises(ValueError, match="Instagram source work identity is invalid"):
        pipeline_owner.submit({**work, "catalog_revision": True}, no_post=True, inbox=inbox, media_store=media)
    inbox.rows[0]["capability_version"] = 2
    with pytest.raises(ValueError, match="Instagram sibling work identity is invalid"):
        pipeline_owner.submit(work, no_post=True, inbox=inbox, media_store=media)
    inbox.rows[0]["capability_version"] = 1
    assert source_work_routes.read(storage, f"{profile.id}:new") is None
    assert not storage.exists()

    with pytest.raises(RuntimeError, match="object unavailable"):
        pipeline_owner.submit(work, no_post=True, inbox=inbox, media_store=MissingOriginal())
    assert state.load_state(storage)["outbox"] == []
    assert source_work_routes.read(storage, f"{profile.id}:new") is None

    # A crash after the route record but before the outbox save must not
    # acknowledge a publication that the owner never committed.
    monkeypatch.setattr(scan, "_ocr_backend_for_run", lambda: SimpleNamespace(engine_id="fake", model_version="fake-v1"))
    monkeypatch.setattr(scan.ocr, "extract_cached", lambda _asset, *_args: OCRResult(
        OCRStatus.SUCCESS, text="Broad earnings outlook", confidence=0.99, min_confidence=0.90,
        engine_id="fake", model_version="fake-v1", languages=profile.ocr_languages,
    ))
    original_save = state.save_state
    monkeypatch.setattr(state, "save_state", lambda *_args: (_ for _ in ()).throw(OSError("state write interrupted")))
    with pytest.raises(OSError, match="state write interrupted"):
        pipeline_owner.submit(work, no_post=True, inbox=inbox, media_store=media)
    monkeypatch.setattr(state, "save_state", original_save)
    assert source_work_routes.read(storage, f"{profile.id}:new") is not None
    assert state.load_state(storage)["outbox"] == []

    assert pipeline_owner.submit(work, no_post=True, inbox=inbox, media_store=media) == "accepted"
    assert len(state.load_state(storage)["outbox"]) == 1

    # Delivery uses the unchanged watcher renderer, text-before-media order,
    # and durable owner receipts. The transport is fully faked here.
    value = state.load_state(storage)
    event = value["outbox"][0]
    event.update({
        "agent_phase": "ready", "is_relevant": True, "route": "id_stocks_news",
        "title": "BBCA: Prospek laba membaik", "summary": "*(Ringkasan)* Prospek laba emiten membaik.",
    })
    state.save_state(storage, value)
    calls = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args: calls.append("text") or "111111111111111111")
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args: calls.append("media") or "222222222222222222")
    drained = pipeline_owner.drain(no_post=False)
    assert drained["delivered"] == 1
    assert calls[0] == "text" and calls[-1] == "media"
    assert calls.count("media") == 1
    assert len(state.load_state(storage)["deliveries"]) == 1
    assert source_work_routes.terminal(storage, f"{profile.id}:new")["outcome"] == "delivered"


def test_source_work_rejects_mismatched_event_key_before_watcher_ledger_write(tmp_path, monkeypatch):
    watch = load_watch_config(ROOT / "cron-ig-account-watch" / "config" / "watches.json")
    profile = watch.profiles[0]
    storage = tmp_path / "owner" / "state.json"
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(tmp_path / "owner" / "media"))
    monkeypatch.setattr(pipeline_owner.config, "load_watch_config_for_run", lambda *_args: LoadedWatchConfig(watch, 4))
    envelope = {
        "platform": "instagram", "endpoint_id": f"instagram:{profile.handle}",
        "publisher_id": f"instagram-{profile.id}", "provider_event_id": "wrong-key",
        "published_at": NOW.isoformat(), "source_url": "https://www.instagram.com/p/wrong-key/",
        "payload": {"caption_html": "No original media", "kind": "post", "media_ref_ids": []},
        "media_required": False, "media_refs": [], "content_hash": "a" * 64,
    }
    event_key = "b" * 64
    expected_key = hashlib.sha256(json.dumps(
        [envelope["platform"], envelope["endpoint_id"], envelope["provider_event_id"]],
        separators=(",", ":"),
    ).encode()).hexdigest()
    assert event_key != expected_key
    work_key = hashlib.sha256(f"{event_key}:1:company_news".encode()).hexdigest()
    work = {
        "work_key": work_key, "effect_key": work_key, "event_key": event_key, "version": 1,
        "pipeline_id": "company_news", "capability_id": "company_news", "event_kind": "original",
        "capability_version": 1, "catalog_revision": 4, "lease_token": "lease-1", "envelope": envelope,
    }
    inbox = Inbox()
    inbox.events = [envelope]
    inbox.rows = [{
        "work_key": work_key, "effect_key": work_key, "event_key": event_key, "version": 1,
        "capability_id": "company_news", "pipeline_id": "company_news", "capability_version": 1,
        "catalog_revision": 4,
        "settings": {}, "status": "executing", "lease_token": "lease-1",
    }]

    with pytest.raises(ValueError, match="Instagram source work identity is invalid"):
        pipeline_owner.submit(work, no_post=True, inbox=inbox)
    assert source_work_routes.read(storage, f"{profile.id}:wrong-key") is None
    assert not storage.exists()
