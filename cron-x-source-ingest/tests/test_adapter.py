from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-x-source-ingest" / "bin"))
from adapter import endpoints, plan_legacy_cursor_seed, run_once
from runner import process_pending

sys.path.insert(0, str(ROOT / "cron-x-account-watch" / "bin"))
from config import load_watch_config
from models import PostKind, SourceMedia, SourcePost
import pipeline_owner
import state

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []
        self.revisions = []
    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}
    def revise(self, event_key, event, kind, revision_id, reason):
        self.revisions.append((event_key, event, kind, revision_id, reason))
        return {"event_key": event_key, "version": 2, "duplicate": False, "work_keys": []}
    def inspect(self, event_key):
        return {"event": {"event_key": event_key}, "work": [{"status": "pending"}]}


class MediaStore:
    def __init__(self):
        self.uploads = []
    def upload(self, key, data, *, kind, content_type, filename):
        self.uploads.append((key, data, kind, content_type, filename))
        return {"ref": "20000000-0000-4000-8000-000000000001", "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True}
    def download(self, ref):
        assert ref == "20000000-0000-4000-8000-000000000001"
        data = self.uploads[-1][1]
        return SimpleNamespace(data=data, content_type="image/jpeg", kind="image", sha256=hashlib.sha256(data).hexdigest())


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


def test_x_legacy_seed_proves_numeric_boundary_even_when_anchor_left_page(tmp_path, monkeypatch):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    endpoint = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "catalog_revision": 3}
    legacy_path = tmp_path / "synthetic-snapshot" / "x.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"profiles": {profile.id: {"cursor": "10"}}, "outbox": [], "deliveries": []}))
    state_root = tmp_path / "synthetic-snapshot" / "new"
    with pytest.raises(Exception, match="selected legacy profile"):
        plan_legacy_cursor_seed(legacy_path, state_root, {**endpoint, "address": "wrong"}, profile, 3)
    preview = plan_legacy_cursor_seed(legacy_path, state_root, endpoint, profile, 3)
    assert preview["status"] == "preview"
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    plan = plan_legacy_cursor_seed(legacy_path, state_root, endpoint, profile, 3, apply=True, expected_plan=preview)
    row = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 3, "subscriptions": [row]}
    post = lambda identity: SourcePost(profile.id, str(identity), f"https://x.com/{profile.handle}/status/{identity}", NOW, "text", PostKind.NORMAL, None, None, (), ())
    inbox = Inbox()
    result = run_once(snapshot, (profile,), state_root, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: [post(9), post(11)])[0]
    assert result["accepted"] == 1
    assert [event["provider_event_id"] for event in inbox.events] == ["11"]
    cursor = json.loads((state_root / endpoint_id.replace(":", "-") / "cursor.json").read_text())
    assert cursor["legacy_seed"]["legacy_state_sha256"] == plan["legacy_state_sha256"]


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


def test_two_x_images_hold_cursor_before_unrepresentable_board_work(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    post = lambda identity, media=(): SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, "Two charts", PostKind.NORMAL, None, None, tuple(media), ())
    posts = [post("100")]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(post("101", (SourceMedia("https://pbs.twimg.com/media/a.jpg", 0), SourceMedia("https://pbs.twimg.com/media/b.jpg", 1))))
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts,
                      media_store=MediaStore(), media_preparer=fake_image_prepare)
    assert result[0]["status"] == "blocked"
    assert result[0]["reason"] == "media_blocked"
    assert inbox.events == []
    assert json.loads((tmp_path / endpoint_id.replace(":", "-") / "cursor.json").read_text())["anchor"] == "100"


def test_same_provider_post_edit_becomes_durable_source_revision(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    posts = [SourcePost(profile.id, "100", f"https://x.com/{profile.handle}/status/100", NOW, "Bootstrap", PostKind.NORMAL, None, None, (), ())]
    inbox = Inbox()
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["status"] == "bootstrapped"
    posts.append(SourcePost(profile.id, "101", f"https://x.com/{profile.handle}/status/101", NOW, "First text", PostKind.NORMAL, None, None, (), ()))
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["accepted"] == 1
    posts[-1] = replace(posts[-1], content_html="Corrected text")
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["status"] != "blocked"
    assert len(inbox.revisions) == 1
    assert inbox.revisions[0][2] == "correction"
    assert inbox.revisions[0][1]["provider_event_id"] == "101"
    assert inbox.revisions[0][1]["payload"]["post"]["content_html"] == "Corrected text"
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    assert len(inbox.revisions) == 1


def test_x_correction_after_original_work_claim_stays_at_source_boundary(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    posts = [SourcePost(profile.id, "100", f"https://x.com/{profile.handle}/status/100", NOW, "Bootstrap", PostKind.NORMAL, None, None, (), ())]

    class CompletedInbox(Inbox):
        def inspect(self, event_key):
            return {"event": {"event_key": event_key}, "work": [{"status": "done"}]}

    inbox = CompletedInbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(SourcePost(profile.id, "101", f"https://x.com/{profile.handle}/status/101", NOW, "Original", PostKind.NORMAL, None, None, (), ()))
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts[-1] = replace(posts[-1], content_html="Edited")
    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    assert result[0]["status"] == "blocked"
    assert result[0]["reason"] == "correction_handoff_failed"
    assert inbox.revisions == []


def test_self_chain_source_event_carries_ordered_post_context(tmp_path):
    profile = replace(next(item for item in load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles if item.id == "writingtorch"), enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-writingtorch", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    root = SourcePost(profile.id, "100", f"https://x.com/{profile.handle}/status/100", NOW, "Root", PostKind.NORMAL, None, None, (), ())
    posts = [root]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    child = SourcePost(profile.id, "101", f"https://x.com/{profile.handle}/status/101", NOW, "Child", PostKind.REPLY, None, None, (), (), root.url)
    posts.append(child)
    assert run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)[0]["accepted"] == 1
    assert [item["post_id"] for item in inbox.events[0]["payload"]["thread_posts"]] == ["100", "101"]
    assert inbox.events[0]["provider_event_id"] == "101"


def test_x_subscriptions_settle_independently_through_pipeline_runtime():
    class WorkInbox:
        def __init__(self):
            self.work = [{"work_key": "company", "lease_token": "a", "pipeline_id": "company_news"},
                         {"work_key": "macro", "lease_token": "b", "pipeline_id": "macro_news"}]
            self.settled = {}
        def claim(self, pipelines, limit):
            assert set(pipelines) == {"company_news", "macro_news"}
            return self.work[:limit]
        def begin(self, key, token):
            return True
        def settle(self, key, token, success, error_code=None):
            self.settled[key] = (success, error_code)
            return {"status": "done" if success else "pending"}

    inbox = WorkInbox()
    def handler(item):
        if item["pipeline_id"] == "company_news":
            raise RuntimeError("fake owner rejection")
    results = process_pending(inbox, handler=handler)
    assert results == [{"work_key": "company", "status": "retry"}, {"work_key": "macro", "status": "done"}]
    assert inbox.settled == {"company": (False, "handler_failed"), "macro": (True, None)}


def test_adapter_to_existing_owner_queue_uses_same_event_and_opaque_image(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    image_url = "https://pbs.twimg.com/media/chart.jpg"
    post = lambda identity, media=(): SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, "KPIG: Chart setup", PostKind.NORMAL, None, None, tuple(media), ())
    posts = [post("100")]
    inbox = Inbox()
    media = MediaStore()
    run_once(snapshot, (profile,), tmp_path / "source", inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(post("101", (SourceMedia(image_url, 0),)))
    assert run_once(snapshot, (profile,), tmp_path / "source", inbox, NOW,
                    fetch_profile=lambda *_args, **_kwargs: posts, media_store=media,
                    media_preparer=fake_image_prepare)[0]["accepted"] == 1
    event = inbox.events[0]
    source_key = hashlib.sha256(json.dumps(["x", endpoint_id, "101"], separators=(",", ":")).encode()).hexdigest()
    work_key = hashlib.sha256(f"{source_key}:1:company_news".encode()).hexdigest()
    work = {"event_key": source_key, "work_key": work_key, "effect_key": work_key,
            "pipeline_id": "company_news", "capability_id": "company_news", "version": 1,
            "event_kind": "original", "envelope": event}
    owner_path = tmp_path / "owner.json"
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=owner_path,
                                             media_client=media, no_post=True) == {"outcome": "accepted"}
    queued = state.load_state(owner_path)["outbox"]
    assert len(queued) == 1
    assert queued[0]["source_event_key"] == source_key
    assert queued[0]["post"]["media"][0]["url"] == "source-media-ref:20000000-0000-4000-8000-000000000001"
    assert image_url not in json.dumps(queued)
