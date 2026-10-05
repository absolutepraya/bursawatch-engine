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
from adapter import _item, endpoints, plan_legacy_cursor_seed, run_once
import runner
from runner import format_fatal, format_heartbeat, process_pending

sys.path.insert(0, str(ROOT / "cron-x-account-watch" / "bin"))
from config import REVIEWED_PUBLISHERS, load_watch_config
from models import PostKind, SourceMedia, SourcePost
import pipeline_owner
import state
from compatible_catalog_transition import _require_x_transition_chain
import compatible_catalog_transition as x_transition
from source_ingest import IntakeBlocked

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_x_revision_eight_requires_both_completed_journal_edges(tmp_path):
    root = tmp_path / "source"
    directory = root / "catalog-transitions"
    directory.mkdir(parents=True, mode=0o700)
    projection_hash = "877e8fce0e374dc2c94e876455d10087298ff837071d82c19d059e0450bef3d3"
    for start, end in ((5, 7), (7, 8)):
        metadata = {"reason": "Reviewed unchanged X reader projection."}
        if start == 7:
            metadata = {"transition_type": "x-compatible-catalog-transition", "projection_sha256": projection_hash,
                        "prior_catalog_sha256": "a" * 64, "target_catalog_sha256": "b" * 64, "watch_config_revision": 9,
                        "reason": "The complete effective X subscription projection is unchanged across catalog revisions 7 and 8."}
        plan = {"version": 1, "status": "preview", "apply": False, "state_root": str(root),
                "transition_path": str(directory / f"{start}-to-{end}.json"), "from_revision": start,
                "to_revision": end, "state_files": {}, "seeds": [], "revision_only": True, "metadata": metadata}
        path = directory / f"{start}-to-{end}.json"
        path.write_text(json.dumps({"version": 1, "status": "complete", "plan": plan, "seeded_endpoints": []}))
        path.chmod(0o600)
    _require_x_transition_chain(root, 8)
    path = directory / "7-to-8.json"
    journal = json.loads(path.read_text())
    journal["status"] = "applying"
    path.write_text(json.dumps(journal))
    with pytest.raises(IntakeBlocked):
        _require_x_transition_chain(root, 8)
    _require_x_transition_chain(root, 7, allow_in_progress_edge=True)


def test_x_catalog_transition_preview_and_apply_preserve_cursor_bytes(tmp_path, monkeypatch):
    root = tmp_path / "source"
    directory = root / "catalog-transitions"
    directory.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (root / "catalog-revision.json").write_text('{"revision":7}')
    marker = root / "catalog-revision.json"
    marker.chmod(0o600)
    prior_path = directory / "5-to-7.json"
    legacy_plan = {
        "version": 1, "status": "preview", "apply": False, "state_root": str(root),
        "transition_path": str(prior_path), "from_revision": 5, "to_revision": 7,
        "state_files": {}, "seeds": [], "metadata": {"reason": "Reviewed unchanged X projection across catalog revisions."},
        "revision_only": True,
    }
    prior_path.write_text(json.dumps({"version": 1, "status": "complete", "plan": legacy_plan, "seeded_endpoints": []}))
    prior_path.chmod(0o600)
    profile_config = load_watch_config(ROOT / "cron-x-account-watch/config/watches.json")
    enabled_ids = {"kutekians", "rickyho1989", "writingtorch", "arvinhonami", "doktermarket", "txthariansaham", "aldotjahjadi8", "kobeissiletter"}
    profiles = tuple(replace(profile, enabled=profile.id in enabled_ids) for profile in profile_config.profiles)
    monkeypatch.setattr(x_transition, "load_watch_config_for_run", lambda: SimpleNamespace(revision=9, config=SimpleNamespace(profiles=profiles)))
    rows = [{
        "platform": "x", "endpoint_id": f"x:{profile.handle.casefold()}",
        "publisher_id": REVIEWED_PUBLISHERS[profile.id], "address": profile.handle, "provider_id": None,
        "capability_id": capability, "verification_status": "verified",
        "enabled": profile.id in enabled_ids and capability in {"company_news", "macro_news"},
    } for profile in profiles for capability in ("company_news", "macro_news", "swing_chart_context")]
    rows.sort(key=lambda row: (row["endpoint_id"], row["capability_id"]))
    projection_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    monkeypatch.setattr(x_transition, "REVIEWED_PROJECTION_SHA256", projection_hash)
    prior = {"revision": 7, "subscriptions": rows}
    target = {"revision": 8, "subscriptions": rows}
    cursor = root / "x-writingtorch" / "cursor.json"
    cursor.parent.mkdir(mode=0o700)
    cursor_bytes = b'{"initialized":true,"anchor":"2105222314002677829","position":null}'
    cursor.write_bytes(cursor_bytes)
    cursor.chmod(0o600)

    plan = x_transition.preview(prior, target, root)
    assert plan["projection_sha256"] == projection_hash
    assert cursor.read_bytes() == cursor_bytes
    monkeypatch.setenv(x_transition.APPLY_ENV, "1")
    assert x_transition.apply(plan, prior, target, root)["status"] == "applied"
    assert json.loads(marker.read_text()) == {"revision": 8}
    assert cursor.read_bytes() == cursor_bytes
    x_transition.require_catalog_revision(root, 8, lambda *_args: None)


def test_x_source_heartbeat_reports_empty_runs_and_warns_on_pending_work():
    clean = format_heartbeat(NOW, {"source": [{"endpoint_id": "x:kutekians", "status": "empty", "accepted": 0}], "work": []})
    assert clean == "🫀 bursawatch-x-source-ingest · 07:00 WIB · endpoints=1 accepted=0 work=0 pending=0"

    degraded = format_heartbeat(NOW, {
        "source": [{"endpoint_id": "x:kutekians", "status": "blocked", "accepted": 0}],
        "work": [{"status": "retry"}],
    })
    assert degraded == "🫀 bursawatch-x-source-ingest · 07:00 WIB · endpoints=1 accepted=0 work=1 pending=1 ⚠️"
    assert format_fatal(NOW) == "❌ bursawatch-x-source-ingest · 07:00 WIB · failed: source processing failed"


def test_group_capabilities_select_one_reviewed_x_endpoint():
    profile = replace(next(item for item in load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles if item.id == "wavetiga"), enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    publisher_id = REVIEWED_PUBLISHERS[profile.id]
    snapshot = {"revision": 17, "subscriptions": [
        {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": publisher_id,
         "address": profile.handle, "provider_id": None, "capability_id": capability,
         "verification_status": "verified", "enabled": True}
        for capability in ("company_news", "macro_news", "swing_chart_context")
    ]}
    selected, by_endpoint = endpoints(snapshot, (profile,))
    assert set(selected) == {endpoint_id}
    assert selected[endpoint_id]["capabilities"] == {"company_news", "macro_news", "swing_chart_context"}
    assert selected[endpoint_id]["publisher_id"] == publisher_id
    assert by_endpoint[endpoint_id].id == profile.id


def test_group_and_legacy_work_are_claimed_by_one_x_owner_handler():
    class WorkInbox:
        def claim(self, pipelines, limit):
            assert set(pipelines) == {"x_post_route", "company_news", "macro_news"}
            return [{"work_key": name, "lease_token": name, "pipeline_id": name} for name in pipelines]
        def begin(self, key, token):
            return True
        def settle(self, key, token, success, error_code=None):
            assert success and error_code is None
            return {"status": "done"}

    seen = []
    results = process_pending(WorkInbox(), handler=lambda item: seen.append(item["pipeline_id"]))
    assert set(seen) == {"x_post_route", "company_news", "macro_news"}
    assert all(item["status"] == "done" for item in results)


def test_owner_handler_acknowledges_previously_suppressed_group_work(monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(kwargs["input"])
        return SimpleNamespace(returncode=0, stdout='{"outcome":"suppressed_ineligible"}')
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._owner_handler({"pipeline_id": "x_post_route"})
    assert len(calls) == 1


def test_route_group_handoff_is_acknowledged_once_with_fake_owner(monkeypatch):
    class WorkInbox:
        def __init__(self):
            self.begins = []
            self.settles = []

        def claim(self, pipelines, limit):
            assert set(pipelines) == {"x_post_route", "company_news", "macro_news"}
            assert limit == 20
            return [{
                "work_key": "stable-work-key",
                "effect_key": "stable-work-key",
                "lease_token": "fake-lease",
                "pipeline_id": "x_post_route",
                "dispatch_context": {
                    "dispatch_group": "x_post_route",
                    "subscriptions": [
                        {"capability_id": "company_news"},
                        {"capability_id": "macro_news"},
                        {"capability_id": "swing_chart_context"},
                    ],
                },
            }]

        def begin(self, key, token):
            self.begins.append((key, token))
            return True

        def settle(self, key, token, success, error_code=None):
            self.settles.append((key, token, success, error_code))
            return {"status": "done"}

    owner_inputs = []

    def fake_run(argv, **kwargs):
        owner_inputs.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout='{"outcome":"accepted"}')

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    inbox = WorkInbox()
    results = process_pending(inbox, handler=runner._owner_handler)

    assert results == [{"work_key": "stable-work-key", "status": "done"}]
    assert inbox.begins == [("stable-work-key", "fake-lease")]
    assert inbox.settles == [("stable-work-key", "fake-lease", True, None)]
    assert len(owner_inputs) == 1
    assert owner_inputs[0]["pipeline_id"] == "x_post_route"


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


def test_direct_x_bootstrap_records_profile_head_without_fetching_visible_posts(tmp_path):
    profile = replace(
        load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0],
        enabled=True,
        source="direct_x",
    )
    endpoint_id = f"x:{profile.handle.casefold()}"
    row = {
        "platform": "x",
        "endpoint_id": endpoint_id,
        "publisher_id": REVIEWED_PUBLISHERS[profile.id],
        "address": profile.handle,
        "provider_id": None,
        "capability_id": "company_news",
        "verification_status": "verified",
        "enabled": True,
    }
    snapshot = {"revision": 3, "subscriptions": [row]}
    fetched_after = []
    head_reads = []
    post = lambda identity: SourcePost(
        profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}",
        NOW, "Market", PostKind.NORMAL, None, None, (), (),
    )

    def fetch_profile(_profile, *, after_id):
        fetched_after.append(after_id)
        return [post("100"), post("101")] if after_id == "99" else [post("101")]

    def fetch_head(_profile):
        head_reads.append(_profile.id)
        return "100"

    inbox = Inbox()
    first = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=fetch_profile, fetch_direct_x_head=fetch_head)
    cursor = json.loads((tmp_path / endpoint_id.replace(":", "-") / "cursor.json").read_text())
    assert first == [{"endpoint_id": endpoint_id, "status": "bootstrapped", "accepted": 0}]
    assert cursor["anchor"] == "100"
    assert fetched_after == []

    second = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=fetch_profile, fetch_direct_x_head=fetch_head)
    assert second[0]["accepted"] == 1
    assert head_reads == [profile.id]
    assert fetched_after == ["100"]
    assert [event["provider_event_id"] for event in inbox.events] == ["101"]


def test_hybrid_source_passes_prior_anchor_to_shared_fetcher(tmp_path):
    profile = replace(
        load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0],
        enabled=True, source="hybrid",
    )
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{
        "platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians",
        "address": profile.handle, "provider_id": None, "capability_id": "company_news",
        "verification_status": "verified", "enabled": True,
    }]}
    calls = []
    post = lambda identity: SourcePost(
        profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}",
        NOW, "Market", PostKind.NORMAL, None, None, (), (),
    )
    def fetch(_profile, *, after_id):
        calls.append(after_id)
        return [post("10")] if after_id is None else [post("10"), post("11")]

    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=fetch)
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=fetch)

    assert calls == [None, "10"]
    assert [event["provider_event_id"] for event in inbox.events] == ["11"]


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


@pytest.mark.parametrize("profile_id", ["rickyho1989", "insidertracker"])
def test_x_legacy_seed_uses_stable_profile_id_when_handle_differs(tmp_path, profile_id):
    profile = replace(
        next(item for item in load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles if item.id == profile_id),
        enabled=True,
    )
    endpoint_id = f"x:{profile.handle.casefold()}"
    publisher_id = REVIEWED_PUBLISHERS[profile.id]
    endpoint = {
        "platform": "x",
        "endpoint_id": endpoint_id,
        "publisher_id": publisher_id,
        "address": profile.handle,
        "provider_id": None,
        "catalog_revision": 3,
    }
    row = {
        **{key: value for key, value in endpoint.items() if key != "catalog_revision"},
        "capability_id": "company_news",
        "verification_status": "verified",
        "enabled": True,
    }
    selected, _ = endpoints({"revision": 3, "subscriptions": [row]}, (profile,))
    assert endpoint_id in selected

    legacy_path = tmp_path / profile.id / "legacy.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"profiles": {profile.id: {"cursor": "10"}}, "outbox": [], "deliveries": []}))
    preview = plan_legacy_cursor_seed(legacy_path, tmp_path / profile.id / "new", endpoint, profile, 3)
    assert preview["status"] == "preview"


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


def test_two_x_images_are_accepted_in_source_order(tmp_path):
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    post = lambda identity, media=(): SourcePost(profile.id, identity, f"https://x.com/{profile.handle}/status/{identity}", NOW, "Two charts", PostKind.NORMAL, None, None, tuple(media), ())
    posts = [post("100")]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(post("101", (SourceMedia("https://pbs.twimg.com/media/a.jpg", 0), SourceMedia("https://pbs.twimg.com/media/b.jpg", 1))))
    class OrderedMediaStore(MediaStore):
        def upload(self, key, data, *, kind, content_type, filename):
            result = super().upload(key, data, kind=kind, content_type=content_type, filename=filename)
            result["ref"] = f"20000000-0000-4000-8000-{len(self.uploads):012d}"
            return result

    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts,
                      media_store=OrderedMediaStore(), media_preparer=fake_image_prepare)
    assert result[0]["status"] == "accepted"
    assert [item["media_ref_id"] for item in inbox.events[0]["payload"]["thread_posts"][-1]["media"]] == [item["ref"] for item in inbox.events[0]["media_refs"]]
    assert len(inbox.events[0]["media_refs"]) == 2
    assert json.loads((tmp_path / endpoint_id.replace(":", "-") / "cursor.json").read_text())["anchor"] == "101"


def test_self_chain_images_keep_post_and_authored_quoted_order():
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    url = lambda identity: f"https://x.com/{profile.handle}/status/{identity}"
    root = SourcePost(profile.id, "100", url("100"), NOW, "Root", PostKind.NORMAL, None, None,
                      (SourceMedia("https://pbs.twimg.com/media/root.jpg", 0),), ())
    child = SourcePost(profile.id, "101", url("101"), NOW, "Child", PostKind.REPLY, None, None,
                       (SourceMedia("https://pbs.twimg.com/media/child.jpg", 0),),
                       (SourceMedia("https://pbs.twimg.com/media/quoted.jpg", 0),), root.url)

    class OrderedMediaStore(MediaStore):
        def upload(self, key, data, *, kind, content_type, filename):
            result = super().upload(key, data, kind=kind, content_type=content_type, filename=filename)
            result["ref"] = f"20000000-0000-4000-8000-{len(self.uploads):012d}"
            return result

    item = _item(child, f"x:{profile.handle.casefold()}", OrderedMediaStore(), upload_media=True,
                 media_preparer=fake_image_prepare, thread_posts=(root, child))
    refs = [metadata["ref"] for metadata in item["media_refs"]]
    assert len(refs) == 3
    assert item["payload"]["thread_posts"][0]["media"][0]["media_ref_id"] == refs[0]
    assert item["payload"]["thread_posts"][1]["media"][0]["media_ref_id"] == refs[1]
    assert item["payload"]["thread_posts"][1]["quoted_media"][0]["media_ref_id"] == refs[2]


def test_repeated_source_image_url_uses_one_ref_and_one_thread_entry():
    profile = replace(load_watch_config(ROOT / "cron-x-account-watch" / "config" / "watches.json").profiles[0], enabled=True)
    media = SourceMedia("https://pbs.twimg.com/media/chart.jpg", 0)
    post = SourcePost(profile.id, "101", f"https://x.com/{profile.handle}/status/101", NOW,
                      "One chart", PostKind.NORMAL, None, None, (media,), (media,))
    item = _item(post, f"x:{profile.handle.casefold()}", MediaStore(), upload_media=True,
                 media_preparer=fake_image_prepare)
    assert len(item["media_refs"]) == 1
    assert len(item["payload"]["thread_posts"][0]["media"]) == 1
    assert item["payload"]["thread_posts"][0]["quoted_media"] == []


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
    assert result[0]["correction_error_code"] == "source_work_not_pending"
    assert inbox.revisions == []


def test_correction_media_failure_identifies_stage_without_advancing_or_revising(tmp_path):
    from vision_media import VisionBundle

    profile = replace(load_watch_config(ROOT / "cron-x-account-watch/config/watches.json").profiles[0], enabled=True)
    endpoint_id = f"x:{profile.handle.casefold()}"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-kutekians", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    url = lambda identity: f"https://x.com/{profile.handle}/status/{identity}"
    posts = [SourcePost(profile.id, "100", url("100"), NOW, "Boundary", PostKind.NORMAL, None, None, (), ())]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(SourcePost(profile.id, "101", url("101"), NOW, "Original", PostKind.NORMAL, None, None, (SourceMedia("https://pbs.twimg.com/media/image.jpg", 0),), ()))
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts,
             media_store=MediaStore(), media_preparer=fake_image_prepare)
    cursor_path = tmp_path / endpoint_id.replace(":", "-") / "cursor.json"
    before = cursor_path.read_bytes()

    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts,
                      media_store=MediaStore(), media_preparer=lambda _post, root: VisionBundle(root, (), 1))

    assert result[0]["reason"] == "correction_handoff_failed"
    assert result[0]["correction_error_code"] == "correction_media_unavailable"
    assert cursor_path.read_bytes() == before
    assert inbox.revisions == []
    assert len(inbox.events) == 1


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


@pytest.mark.parametrize("parent_visible", [False, True])
def test_self_quote_keeps_inline_context_when_original_is_outside_thread_window(tmp_path, parent_visible):
    from datetime import timedelta

    profile = replace(next(item for item in load_watch_config(ROOT / "cron-x-account-watch/config/watches.json").profiles if item.id == "writingtorch"), enabled=True)
    endpoint_id = "x:writingtorch"
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": endpoint_id, "publisher_id": "x-writingtorch", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    url = lambda identity: f"https://x.com/{profile.handle}/status/{identity}"
    boundary = SourcePost(profile.id, "100", url("100"), NOW, "Boundary", PostKind.NORMAL, None, None, (), ())
    original = SourcePost(profile.id, "90", url("90"), NOW - timedelta(days=30), "Original rights issue", PostKind.NORMAL, None, None, (), ())
    quote = SourcePost(profile.id, "101", url("101"), NOW, "Updated rights issue date", PostKind.QUOTE, original.url, "Original rights issue", (), (), original.url)
    posts = [boundary]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts = ([original] if parent_visible else []) + [boundary, quote]

    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)

    assert result[0]["status"] == "accepted"
    assert result[0]["accepted"] == 1
    event = inbox.events[0]
    assert [post["post_id"] for post in event["payload"]["thread_posts"]] == ["101"]
    assert event["payload"]["post"]["quoted_content_html"] == "Original rights issue"
    assert event["payload"]["post"]["quoted_url"] == url("90")
    # The real owner must accept the same frozen single-post quote context.
    posts, refs = pipeline_owner._posts(profile, event)
    assert posts[0].quoted_content_html == "Original rights issue"
    assert refs == {}
    assert json.loads((tmp_path / "x-writingtorch/cursor.json").read_text())["anchor"] == "101"


@pytest.mark.parametrize("kind,quoted_text", [
    (PostKind.REPLY, None),
    (PostKind.QUOTE, None),
    (PostKind.QUOTE, " \n\t"),
    (PostKind.QUOTE, "<br> \n"),
    (PostKind.QUOTE, "&nbsp;<p> </p>"),
])
def test_self_continuation_without_parent_or_inline_context_holds_cursor(tmp_path, kind, quoted_text):
    profile = replace(next(item for item in load_watch_config(ROOT / "cron-x-account-watch/config/watches.json").profiles if item.id == "writingtorch"), enabled=True)
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": "x:writingtorch", "publisher_id": "x-writingtorch", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    url = lambda identity: f"https://x.com/{profile.handle}/status/{identity}"
    posts = [SourcePost(profile.id, "100", url("100"), NOW, "Boundary", PostKind.NORMAL, None, None, (), ())]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(SourcePost(profile.id, "101", url("101"), NOW, "Continuation", kind, url("90") if kind is PostKind.QUOTE else None, quoted_text, (), (), url("90")))

    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)

    assert result[0]["status"] == "blocked"
    assert inbox.events == []
    assert json.loads((tmp_path / "x-writingtorch/cursor.json").read_text())["anchor"] == "100"


def test_self_quote_keeps_durable_quoted_image_when_parent_is_absent(tmp_path):
    profile = replace(next(item for item in load_watch_config(ROOT / "cron-x-account-watch/config/watches.json").profiles if item.id == "writingtorch"), enabled=True)
    snapshot = {"revision": 3, "subscriptions": [{"platform": "x", "endpoint_id": "x:writingtorch", "publisher_id": "x-writingtorch", "address": profile.handle, "provider_id": None, "capability_id": "company_news", "verification_status": "verified", "enabled": True}]}
    url = lambda identity: f"https://x.com/{profile.handle}/status/{identity}"
    posts = [SourcePost(profile.id, "100", url("100"), NOW, "Boundary", PostKind.NORMAL, None, None, (), ())]
    inbox = Inbox()
    run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts)
    posts.append(SourcePost(profile.id, "101", url("101"), NOW, "New date", PostKind.QUOTE, url("90"), "Original rights issue", (), (SourceMedia("https://pbs.twimg.com/media/original.jpg", 0),), url("90")))

    result = run_once(snapshot, (profile,), tmp_path, inbox, NOW, fetch_profile=lambda *_args, **_kwargs: posts,
                      media_store=MediaStore(), media_preparer=fake_image_prepare)

    assert result[0]["status"] == "accepted"
    event = inbox.events[0]
    assert event["media_required"] is True
    assert len(event["media_refs"]) == 1
    converted, refs = pipeline_owner._posts(profile, event)
    assert len(converted[0].quoted_media) == 1
    assert converted[0].quoted_content_html == "Original rights issue"
    assert len(refs) == 1


def test_x_subscriptions_settle_independently_through_pipeline_runtime():
    class WorkInbox:
        def __init__(self):
            self.work = [{"work_key": "company", "lease_token": "a", "pipeline_id": "company_news"},
                         {"work_key": "macro", "lease_token": "b", "pipeline_id": "macro_news"}]
            self.settled = {}
        def claim(self, pipelines, limit):
            assert set(pipelines) == {"x_post_route", "company_news", "macro_news"}
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
