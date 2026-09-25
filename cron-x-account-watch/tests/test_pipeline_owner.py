from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import config
import pipeline_owner
import scan
import state
import vision_media
import supersession
import rsshub
import render
from models import PostKind, SourcePost


NOW = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)


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
    assert events[0]["ready_after"] == (NOW + timedelta(minutes=1)).isoformat()
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


def test_multiple_images_remain_unclaimed_until_board_supports_their_paths(tmp_path):
    profile = _profile("kutekians")
    refs = [{"ref": f"20000000-0000-4000-8000-{number:012d}"} for number in (1, 2)]
    post = _post(profile, 101, "A market thesis")
    with pytest.raises(ValueError, match="Board path contract"):
        pipeline_owner.accept_source_work(_work(profile, [post], refs=refs), profiles=(profile,), storage=tmp_path / "x.json", no_post=True)
    assert not (tmp_path / "x.json").exists()


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
