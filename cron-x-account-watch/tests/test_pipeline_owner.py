from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import delivery_handoff
import pipeline_owner
import scan
import state
import vision_media
import supersession
import rsshub
import render
from models import PostKind, SourcePost


NOW = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)


def test_all_x_owner_paths_share_the_watcher_state_file(monkeypatch, tmp_path):
    monkeypatch.delenv("X_POST_WATCH_STATE_PATH", raising=False)
    expected = Path(__file__).resolve().parents[1] / "state" / "state.json"

    assert state.state_path() == expected
    assert scan.state_path() == expected
    assert pipeline_owner._state_path() == expected
    assert delivery_handoff._state_path() == expected

    configured = tmp_path / "configured-x-state.json"
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(configured))
    assert state.state_path() == configured
    assert scan.state_path() == configured
    assert pipeline_owner._state_path() == configured
    assert delivery_handoff._state_path() == configured


def test_pipeline_owner_uses_the_same_state_for_source_acceptance(tmp_path, monkeypatch):
    profile = _profile()
    post = _post(profile, 101, "A market thesis")
    storage = tmp_path / "watcher-state.json"
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))

    assert pipeline_owner.accept_source_work(
        _work(profile, [post]), profiles=(profile,), no_post=True, now=NOW,
    ) == {"outcome": "accepted"}
    assert storage.exists()
    assert not (tmp_path / ".hermes" / "state" / "x-post-watch.json").exists()


def _post(profile, number, text, *, kind=PostKind.NORMAL, parent=None, media_ref=None):
    post = SourcePost(profile.id, str(number), f"https://x.com/{profile.handle}/status/{number}",
                      NOW + timedelta(minutes=number - 101), text, kind, None, None, (), (), parent)
    value = state.serialize_post(post)
    if media_ref:
        value["media"] = [{"index": 0, "media_ref_id": media_ref}]
    return value


def _work(profile, posts, *, capability="company_news", version=1, kind="original", refs=None):
    latest = posts[-1]
    endpoint = f"x:{profile.handle.casefold()}"
    event_key = hashlib.sha256(json.dumps(["x", endpoint, latest["post_id"]], separators=(",", ":")).encode()).hexdigest()
    key = hashlib.sha256(f"{event_key}:{version}:{capability}".encode()).hexdigest()
    refs = refs or []
    payload = {"post": latest, "thread_posts": posts}
    encoded = json.dumps({"payload": payload, "media_refs": refs} if refs else payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"event_key": event_key, "work_key": key, "effect_key": key, "pipeline_id": capability,
            "capability_id": capability, "version": version, "event_kind": kind,
            "envelope": {"platform": "x", "endpoint_id": endpoint,
                         "publisher_id": pipeline_owner.SOURCE_PUBLISHERS[profile.id],
                         "provider_event_id": latest["post_id"], "source_url": latest["url"],
                         "published_at": latest["published_at"], "payload": payload, "media_refs": refs,
                         "media_required": bool(refs), "content_hash": hashlib.sha256(encoded).hexdigest()}}


def _group_work(profile, posts, capabilities=("company_news", "macro_news", "swing_chart_context"), **kwargs):
    work = _work(profile, posts, capability="x_post_route_group", **kwargs)
    work["pipeline_id"] = "x_post_route"
    work["capability_version"] = 1
    work["catalog_revision"] = 17
    work["settings"] = {}
    work["config_source"] = "publisher_default"
    work["dispatch_context"] = {
        "dispatch_group": "x_post_route",
        "subscriptions": [
            {"capability_id": capability, "capability_version": 1, "settings": {}, "config_source": "publisher_default"}
            for capability in sorted(capabilities)
        ],
    }
    return work


def test_group_work_creates_one_event_and_one_classifier_input(tmp_path):
    profile = _profile("wavetiga")
    storage = tmp_path / "x.json"
    work = _group_work(profile, [_post(profile, 101, "IHSG chart and market outlook")])
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, no_post=True, now=NOW) == {"outcome": "accepted"}
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, no_post=True, now=NOW) == {"outcome": "accepted"}
    saved = state.load_state(storage)
    assert len(saved["outbox"]) == 1
    assert saved["outbox"][0]["enabled_capabilities"] == ["company_news", "macro_news", "swing_chart_context"]
    assert saved["outbox"][0]["dispatch_context"] == work["dispatch_context"]
    assert saved["source_events"][work["event_key"]]["dispatch_context"] == work["dispatch_context"]
    assert saved["outbox"][0]["source_catalog_revision"] == 17
    assert state.claim_oldest_agent(saved, {profile.id: profile}, NOW + timedelta(hours=1)) is saved["outbox"][0]
    assert state.claim_oldest_agent(saved, {profile.id: profile}, NOW + timedelta(hours=1)) is None


def test_group_identity_rejects_changed_or_unknown_frozen_context(tmp_path):
    profile = _profile("wavetiga")
    work = _group_work(profile, [_post(profile, 101, "Company update")])
    bad = [
        {**work, "dispatch_context": {**work["dispatch_context"], "dispatch_group": "other"}},
        {**work, "dispatch_context": {**work["dispatch_context"], "subscriptions": [{"capability_id": "unknown", "capability_version": 1, "settings": {}, "config_source": "publisher_default"}]}},
        {**work, "catalog_revision": "17"},
        {**work, "capability_id": "company_news"},
    ]
    for index, item in enumerate(bad):
        with pytest.raises(ValueError):
            pipeline_owner.accept_source_work(item, profiles=(profile,), storage=tmp_path / f"bad-{index}.json", no_post=True)


def test_group_correction_retains_original_capabilities(tmp_path):
    profile = _profile("wavetiga")
    storage = tmp_path / "x.json"
    first = _group_work(profile, [_post(profile, 101, "First")], capabilities=("company_news",))
    correction = _group_work(profile, [_post(profile, 101, "Corrected")], capabilities=("company_news",), version=2, kind="correction")
    for work in (first, correction):
        work["dispatch_context"]["subscriptions"][0]["config_source"] = "endpoint_override"
        work["config_source"] = "endpoint_override"
    pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, no_post=True)
    pipeline_owner.accept_source_work(correction, profiles=(profile,), storage=storage, no_post=True)
    saved = state.load_state(storage)
    assert saved["outbox"][0]["enabled_capabilities"] == ["company_news"]
    assert saved["source_events"][first["event_key"]]["enabled_capabilities"] == ["company_news"]
    assert saved["outbox"][0]["dispatch_context"] == first["dispatch_context"]
    assert saved["source_events"][first["event_key"]]["dispatch_context"] == first["dispatch_context"]
    expanded = _group_work(profile, [_post(profile, 101, "Changed again")], capabilities=("company_news", "swing_chart_context"), version=3, kind="correction")
    with pytest.raises(ValueError, match="dispatch context"):
        pipeline_owner.accept_source_work(expanded, profiles=(profile,), storage=storage, no_post=True)
    stale = _group_work(profile, [_post(profile, 101, "Changed again")], capabilities=("company_news",), version=3, kind="correction")
    stale["dispatch_context"] = deepcopy(first["dispatch_context"])
    stale["config_source"] = "endpoint_override"
    stale["catalog_revision"] = 18
    with pytest.raises(ValueError, match="catalog snapshot"):
        pipeline_owner.accept_source_work(stale, profiles=(profile,), storage=storage, no_post=True)


def test_group_retry_rejects_changed_config_source_with_same_ids_and_revision(tmp_path):
    profile = _profile("wavetiga")
    storage = tmp_path / "x.json"
    first = _group_work(profile, [_post(profile, 101, "First")], capabilities=("company_news", "macro_news"))
    pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, no_post=True)
    changed = deepcopy(first)
    changed["dispatch_context"]["subscriptions"][0]["config_source"] = "endpoint_override"
    changed["config_source"] = "endpoint_override"
    assert changed["catalog_revision"] == first["catalog_revision"]
    assert [row["capability_id"] for row in changed["dispatch_context"]["subscriptions"]] == [row["capability_id"] for row in first["dispatch_context"]["subscriptions"]]
    with pytest.raises(ValueError, match="dispatch context"):
        pipeline_owner.accept_source_work(changed, profiles=(profile,), storage=storage, no_post=True)
    changed_correction = _group_work(profile, [_post(profile, 101, "Corrected")], capabilities=("company_news", "macro_news"), version=2, kind="correction")
    changed_correction["dispatch_context"] = deepcopy(changed["dispatch_context"])
    changed_correction["config_source"] = "endpoint_override"
    with pytest.raises(ValueError, match="dispatch context"):
        pipeline_owner.accept_source_work(changed_correction, profiles=(profile,), storage=storage, no_post=True)
    saved = state.load_state(storage)
    assert saved["source_events"][first["event_key"]]["dispatch_context"] == first["dispatch_context"]
    assert saved["outbox"][0]["dispatch_context"] == first["dispatch_context"]


def test_legacy_work_still_accepts_during_group_drain(tmp_path):
    profile = _profile("writingtorch")
    storage = tmp_path / "x.json"
    post = _post(profile, 101, "Legacy publication")
    assert pipeline_owner.accept_source_work(_work(profile, [post], capability="company_news"), profiles=(profile,), storage=storage, no_post=True)["outcome"] == "accepted"
    assert len(state.load_state(storage)["outbox"]) == 1
    # The sibling legacy claim may arrive after the watcher has completed its
    # single queued delivery. It must settle from the source ledger alone.
    delivered = state.load_state(storage)
    delivered["outbox"].clear()
    state.save_state(storage, delivered)
    assert pipeline_owner.accept_source_work(_work(profile, [post], capability="macro_news"), profiles=(profile,), storage=storage, no_post=True)["outcome"] == "accepted"
    assert state.load_state(storage)["outbox"] == []


def _profile(profile_id="writingtorch"):
    return next(item for item in config.load_watch_config(pipeline_owner.Path(__file__).resolve().parents[1] / "config" / "watches.json").profiles if item.id == profile_id)


def test_ordered_thread_and_same_source_two_subscriptions_share_one_owner_event(tmp_path):
    profile = _profile()
    root = _post(profile, 101, "A market thesis")
    child = _post(profile, 102, "Continuation with evidence", kind=PostKind.REPLY, parent=root["url"])
    storage = tmp_path / "x.json"
    first = _work(profile, [root])
    second = _work(profile, [root, child])

    assert pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, now=NOW, no_post=True) == {"outcome": "accepted"}
    assert pipeline_owner.accept_source_work(second, profiles=(profile,), storage=storage, now=NOW + timedelta(minutes=1), no_post=True) == {"outcome": "accepted"}
    assert pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, now=NOW, no_post=True) == {"outcome": "accepted"}
    sibling = _work(profile, [root, child], capability="macro_news")
    assert pipeline_owner.accept_source_work(sibling, profiles=(profile,), storage=storage, now=NOW, no_post=True) == {"outcome": "accepted"}
    events = state.load_state(storage)["outbox"]
    assert len(events) == 1
    assert [item["post_id"] for item in events[0]["thread_posts"]] == ["101", "102"]
    assert events[0]["ready_after"] == (NOW + timedelta(minutes=15)).isoformat()
    item = scan.agent_item(profile, state.deserialize_post(events[0]["post"]), tuple(state.deserialize_post(item) for item in events[0]["thread_posts"]))
    assert item["thread_post_count"] == "2"
    assert "Thread post 1/2" in item["post_text"] and "Continuation with evidence" in item["post_text"]
    legacy = state.new_state()
    legacy["profiles"][profile.id] = {"cursor": "100"}
    originals = [state.deserialize_post(root), state.deserialize_post(child)]
    state.observe_posts(legacy, profile, originals, lambda post: rsshub.is_forwardable(profile, post),
                        lambda post: rsshub.is_self_thread_post(profile, post), NOW + timedelta(minutes=1))
    old_event = legacy["outbox"][0]
    old_posts = tuple(state.deserialize_post(raw) for raw in old_event["thread_posts"])
    assert item == scan.agent_item(profile, state.deserialize_post(old_event["post"]), old_posts)
    assert render.render_post(profile, state.deserialize_post(events[0]["post"]), None, None,
                              tuple(state.deserialize_post(raw) for raw in events[0]["thread_posts"])) == render.render_post(
                                  profile, state.deserialize_post(old_event["post"]), None, None, old_posts)


def test_late_older_thread_work_cannot_rewind_newer_owner_event(tmp_path):
    profile = _profile()
    root = _post(profile, 101, "Root")
    child = _post(profile, 102, "Continuation", kind=PostKind.REPLY, parent=root["url"])
    storage = tmp_path / "x.json"
    latest = _work(profile, [root, child])
    older = _work(profile, [root])
    pipeline_owner.accept_source_work(latest, profiles=(profile,), storage=storage, no_post=True, now=NOW)
    pipeline_owner.accept_source_work(older, profiles=(profile,), storage=storage, no_post=True, now=NOW)
    event = state.load_state(storage)["outbox"][0]
    assert event["post_id"] == "102"
    assert event["source_event_key"] == latest["event_key"]
    assert [item["post_id"] for item in event["thread_posts"]] == ["101", "102"]


def test_source_correction_updates_unclaimed_post_with_stable_event_identity(tmp_path):
    profile = _profile("kutekians")
    storage = tmp_path / "x.json"
    first = _work(profile, [_post(profile, 101, "First source text")])
    correction = _work(profile, [_post(profile, 101, "Corrected source text")], version=2, kind="correction")
    pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, now=NOW, no_post=True)
    pipeline_owner.accept_source_work(correction, profiles=(profile,), storage=storage, now=NOW, no_post=True)
    event = state.load_state(storage)["outbox"][0]
    assert event["post"]["content_html"] == "Corrected source text"
    assert state.load_state(storage)["source_events"][first["event_key"]]["version"] == 2
    assert pipeline_owner.accept_source_work(correction, profiles=(profile,), storage=storage, now=NOW, no_post=True) == {"outcome": "accepted"}
    assert len(state.load_state(storage)["outbox"]) == 1


def test_correction_can_be_first_claimed_work_when_original_was_superseded(tmp_path):
    profile = _profile("kutekians")
    storage = tmp_path / "x.json"
    correction = _work(profile, [_post(profile, 101, "Corrected before dispatch")], version=2, kind="correction")
    assert pipeline_owner.accept_source_work(correction, profiles=(profile,), storage=storage,
                                             now=NOW, no_post=True) == {"outcome": "accepted"}
    saved = state.load_state(storage)
    assert saved["outbox"][0]["post"]["content_html"] == "Corrected before dispatch"
    assert saved["source_events"][correction["event_key"]]["version"] == 2


def test_source_correction_after_agent_claim_stays_retriable(tmp_path):
    profile = _profile("kutekians")
    storage = tmp_path / "x.json"
    first = _work(profile, [_post(profile, 101, "First source text")])
    correction = _work(profile, [_post(profile, 101, "Changed text")], version=2, kind="correction")
    pipeline_owner.accept_source_work(first, profiles=(profile,), storage=storage, now=NOW, no_post=True)
    value = state.load_state(storage)
    value["outbox"][0]["agent_phase"] = "awaiting_agent"
    state.save_state(storage, value)
    with pytest.raises(ValueError, match="claimed"):
        pipeline_owner.accept_source_work(correction, profiles=(profile,), storage=storage, now=NOW, no_post=True)
    assert state.load_state(storage)["source_events"][first["event_key"]]["version"] == 1


def test_one_durable_image_keeps_opaque_ref_for_vision_and_board(tmp_path):
    profile = _profile("kutekians")
    ref = "20000000-0000-4000-8000-000000000001"
    data = b"\xff\xd8\xffexample-image"
    metadata = {"ref": ref, "sha256": hashlib.sha256(data).hexdigest(), "kind": "image", "content_type": "image/jpeg", "size_bytes": len(data), "filename": "chart.jpg", "durable": True}

    class MediaStore:
        def download(self, requested):
            assert requested == ref
            return SimpleNamespace(data=data, sha256=metadata["sha256"], kind="image", content_type="image/jpeg")

    storage = tmp_path / "x.json"
    post = _post(profile, 101, "KPIG: Chart setup", media_ref=ref)
    work = _work(profile, [post], refs=[metadata])
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, media_client=MediaStore(), no_post=True)["outcome"] == "accepted"
    event = state.load_state(storage)["outbox"][0]
    assert "pbs.twimg.com" not in json.dumps(event)
    assert event["post"]["media"][0]["url"] == f"source-media-ref:{ref}"
    prepared = vision_media.prepare(state.deserialize_post(event["post"]), tmp_path / "vision", reference_meta=event["source_media_refs"], media_client=MediaStore())
    assert prepared.assets[0].path.read_bytes() == data
    event.update(title="KPIG: Chart setup", summary="*(Ringkasan)* Ringkasan yang benar.", route="id_stocks_swing")
    board = scan.board_source_event(event, profile, status_date=NOW)
    assert board is not None
    assert board["media_path"] == event["source_media_paths"][ref]
    assert board["media_urls"] == []


def test_multiple_images_keep_order_for_vision_and_board(tmp_path):
    profile = _profile("kutekians")
    blobs = [b"\xff\xd8\xfffirst", b"\xff\xd8\xffsecond"]
    refs = [{"ref": f"20000000-0000-4000-8000-{number:012d}", "sha256": hashlib.sha256(blob).hexdigest(),
             "kind": "image", "content_type": "image/jpeg", "size_bytes": len(blob),
             "filename": f"chart-{number}.jpg", "durable": True}
            for number, blob in enumerate(blobs, start=1)]
    post = _post(profile, 101, "KPIG: Chart setup")
    post["media"] = [{"index": index, "media_ref_id": metadata["ref"]} for index, metadata in enumerate(refs)]
    by_ref = {metadata["ref"]: blob for metadata, blob in zip(refs, blobs)}

    class MediaStore:
        def download(self, requested):
            data = by_ref[requested]
            return SimpleNamespace(data=data, sha256=hashlib.sha256(data).hexdigest(), kind="image", content_type="image/jpeg")

    storage = tmp_path / "x.json"
    work = _work(profile, [post], refs=refs)
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage,
                                             media_client=MediaStore(), no_post=True)["outcome"] == "accepted"
    event = state.load_state(storage)["outbox"][0]
    assert event["source_media_refs"] == {item["ref"]: item for item in refs}
    parsed = state.deserialize_post(event["post"])
    vision = vision_media.prepare(parsed, tmp_path / "vision", thread_posts=(parsed,),
                                  reference_meta=event["source_media_refs"], media_client=MediaStore())
    assert [asset.path.read_bytes() for asset in vision.assets] == blobs
    event.update(title="KPIG: Chart setup", summary="*(Ringkasan)* Chart context.", route="id_stocks_swing")
    board = scan.board_source_event(event, profile, status_date=NOW)
    expected_paths = [event["source_media_paths"][metadata["ref"]] for metadata in refs]
    assert board["media_paths"] == expected_paths
    assert board["media_path"] == board["media_paths"][0]
    assert board["media_urls"] == []
    repeated = _work(profile, [{**post, "media": [{"index": 0, "media_ref_id": refs[0]["ref"]},
                                               {"index": 1, "media_ref_id": refs[0]["ref"]}]}], refs=refs)
    with pytest.raises(ValueError, match="repeated"):
        pipeline_owner.accept_source_work(repeated, profiles=(profile,), storage=tmp_path / "repeated.json", no_post=True)
    reordered = _work(profile, [post], refs=list(reversed(refs)))
    with pytest.raises(ValueError, match="completeness"):
        pipeline_owner.accept_source_work(reordered, profiles=(profile,), storage=tmp_path / "reordered.json", no_post=True)


@pytest.mark.parametrize("optional", [False, True])
def test_news_download_failure_falls_back_only_for_new_optional_payloads(tmp_path, optional):
    profile = _profile("kutekians")
    blobs = [b"\xff\xd8\xffavailable", b"\xff\xd8\xffunavailable"]
    refs = [{"ref": f"20000000-0000-4000-8000-{number:012d}", "sha256": hashlib.sha256(blob).hexdigest(),
             "kind": "image", "content_type": "image/jpeg", "size_bytes": len(blob),
             "filename": f"image-{number}.jpg", "durable": True}
            for number, blob in enumerate(blobs, start=1)]
    post = _post(profile, 101, "MYOR: earnings increased")
    post["media"] = [{"index": index, "media_ref_id": ref["ref"]} for index, ref in enumerate(refs)]
    work = _work(profile, [post], refs=refs)
    if optional:
        work["envelope"]["payload"].update(source_media_policy="optional_news", source_observation_hash="a" * 64)
        work["envelope"]["media_required"] = False
        body = {"payload": work["envelope"]["payload"], "media_refs": refs}
        work["envelope"]["content_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    class Store:
        recovered = False
        def download(self, ref):
            index = next(i for i, item in enumerate(refs) if item["ref"] == ref)
            if index == 1 and not self.recovered:
                raise RuntimeError("unavailable")
            return SimpleNamespace(data=blobs[index], content_type="image/jpeg", kind="image", sha256=refs[index]["sha256"])

    storage = tmp_path / "watcher.json"
    client = Store()
    if not optional:
        with pytest.raises(RuntimeError, match="unavailable"):
            pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, media_client=client, no_post=True, now=NOW)
        assert not storage.exists()
        return
    assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, media_client=client, no_post=True, now=NOW) == {"outcome": "accepted"}
    event = state.load_state(storage)["outbox"][0]
    assert event["post"]["content_html"] == "MYOR: earnings increased"
    assert list(event["source_media_refs"]) == [refs[0]["ref"]]
    assert len(event["post"]["media"]) == 1
    assert event["source_media_degraded"] is True
    frozen = deepcopy(event)
    client.recovered = True
    pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, media_client=client, no_post=True, now=NOW)
    assert state.load_state(storage)["outbox"][0] == frozen
    # Source Inbox's accepted payload and operation identities are untouched.
    assert len(work["envelope"]["payload"]["post"]["media"]) == 2


@pytest.mark.parametrize("source_text", ["KPIG: support 100, target 120", "BBCA buy area 8000, TP 9000, SL 7800"])
def test_optional_media_policy_cannot_weaken_possible_swing_claim(tmp_path, source_text):
    from dataclasses import replace
    from models import DiscordChannel
    profile = _profile()
    profile = replace(profile, discord_channels=profile.discord_channels + (DiscordChannel("id_stocks_swing", "123", "Swing"),))
    work = _work(profile, [_post(profile, 101, source_text)])
    payload = work["envelope"]["payload"]
    payload.update(source_media_policy="optional_news", source_observation_hash="a" * 64)
    work["envelope"]["content_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError, match="ordinary-news"):
        pipeline_owner.accept_source_work(work, profiles=(profile,), storage=tmp_path / "swing.json", no_post=True)


@pytest.mark.parametrize("capabilities, accepted", [
    (("company_news", "macro_news"), True),
    (("company_news", "macro_news", "swing_chart_context"), False),
])
def test_owner_checks_optional_policy_against_frozen_swing_capability(tmp_path, capabilities, accepted):
    profile = _profile("doktermarket")
    work = _group_work(profile, [_post(profile, 101, "BBCA buy area 8000, TP 9000, SL 7800")], capabilities)
    payload = work["envelope"]["payload"]
    payload.update(source_media_policy="optional_news", source_observation_hash="a" * 64)
    work["envelope"]["content_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    storage = tmp_path / "swing.json"
    if accepted:
        assert pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, no_post=True) == {"outcome": "accepted"}
        assert state.load_state(storage)["outbox"][0]["enabled_capabilities"] == list(sorted(capabilities))
    else:
        with pytest.raises(ValueError, match="ordinary-news"):
            pipeline_owner.accept_source_work(work, profiles=(profile,), storage=storage, no_post=True)
        assert not storage.exists()


def test_verified_new_x_edit_id_marks_old_delivery_for_owner_cleanup(tmp_path):
    profile = _profile("kutekians")
    storage = tmp_path / "x.json"
    old_post = _post(profile, 101, "KPIG: Profits rose 25 percent")
    value = state.new_state()
    old_event = {"profile_id": profile.id, "post_id": "101", "thread_root_id": "101", "post": old_post,
                 "thread_posts": [old_post], "text_message_ids": ["7001"], "media_message_ids": []}
    state.record_delivery(value, old_event, profile.discord_channels[0].channel_id, NOW, False)
    state.save_state(storage, value)

    class Verified:
        def verify(self, old_url, old_id, new_id):
            assert (old_id, new_id) == ("101", "102")
            return supersession.Verification("confirmed", "verified edit chain")

    new_post = _post(profile, 102, "KPIG: Profits rose 25 percent")
    result = pipeline_owner.accept_source_work(_work(profile, [new_post]), profiles=(profile,), storage=storage,
                                               now=NOW + timedelta(minutes=1), no_post=True, verifier=Verified())
    assert result == {"outcome": "accepted"}
    event = state.load_state(storage)["outbox"][0]
    assert event["replacement_of"] == [f"{profile.id}:101"]
    assert event["updated_tweet"] is True
