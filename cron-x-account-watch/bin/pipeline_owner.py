"""Accept X Source Inbox work into the existing watcher queue and receipts."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import rsshub
import state
from source_media import cache_reference, client_from_environment, reference_url


CAPABILITIES = frozenset({"company_news", "macro_news"})
GROUP_PIPELINE = "x_post_route"
GROUP_CAPABILITY = "x_post_route_group"
GROUP_CAPABILITIES = frozenset({"company_news", "macro_news", "swing_chart_context"})
SOURCE_PUBLISHERS = config.REVIEWED_PUBLISHERS


def _state_path() -> Path:
    return state.state_path()


def _check_no_post(path: Path, no_post: bool) -> None:
    if no_post and path.expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
        raise ValueError("no-post X source work requires isolated state")


def _frozen_capabilities(work: dict[str, Any]) -> tuple[str, ...] | None:
    pipeline = work.get("pipeline_id")
    if pipeline in CAPABILITIES:
        if work.get("capability_id") != pipeline or work.get("dispatch_context", {}) != {}:
            raise ValueError("X legacy work context is invalid")
        return None
    if pipeline != GROUP_PIPELINE or work.get("capability_id") != GROUP_CAPABILITY:
        raise ValueError("X work pipeline is invalid")
    if (type(work.get("catalog_revision")) is not int or work["catalog_revision"] < 1
            or type(work.get("capability_version")) is not int or work["capability_version"] != 1
            or work.get("settings") != {}):
        raise ValueError("X group catalog snapshot is invalid")
    context = work.get("dispatch_context")
    if type(context) is not dict or set(context) != {"dispatch_group", "subscriptions"} or context["dispatch_group"] != GROUP_PIPELINE:
        raise ValueError("X group dispatch context is invalid")
    subscriptions = context["subscriptions"]
    if type(subscriptions) is not list or not subscriptions:
        raise ValueError("X group subscriptions are invalid")
    capabilities = []
    for item in subscriptions:
        if (type(item) is not dict or set(item) != {"capability_id", "capability_version", "settings", "config_source"}
                or item["capability_id"] not in GROUP_CAPABILITIES or type(item["capability_version"]) is not int
                or item["capability_version"] != 1 or item["settings"] != {}
                or item["config_source"] not in {"publisher_default", "endpoint_override"}):
            raise ValueError("X group subscription is invalid")
        capabilities.append(item["capability_id"])
    if capabilities != sorted(set(capabilities)):
        raise ValueError("X group capabilities are not unique and ordered")
    expected_source = "endpoint_override" if any(item["config_source"] == "endpoint_override" for item in subscriptions) else "publisher_default"
    if work.get("config_source") != expected_source:
        raise ValueError("X group catalog snapshot is invalid")
    return tuple(capabilities)


def _identity(work: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[Any, dict[str, Any], tuple[str, ...] | None]:
    capability = work.get("capability_id")
    frozen_capabilities = _frozen_capabilities(work)
    envelope = work.get("envelope")
    if type(envelope) is not dict or work.get("settings") not in ({}, None):
        raise ValueError("X work pipeline is invalid")
    endpoint = envelope.get("endpoint_id")
    identity = envelope.get("provider_event_id")
    if (envelope.get("platform") != "x" or type(endpoint) is not str or type(identity) is not str
            or not re.fullmatch(r"[1-9][0-9]*", identity)):
        raise ValueError("X provider identity is invalid")
    expected_key = hashlib.sha256(json.dumps(["x", endpoint, identity], separators=(",", ":")).encode()).hexdigest()
    version = work.get("version")
    if type(version) is not int or version < 1 or work.get("event_key") != expected_key:
        raise ValueError("X source event identity is invalid")
    expected_work = hashlib.sha256(f"{expected_key}:{version}:{capability}".encode()).hexdigest()
    if work.get("work_key") != expected_work or work.get("effect_key") != expected_work:
        raise ValueError("X subscription work identity is invalid")
    profile = next((item for item in profiles if endpoint == f"x:{item.handle.casefold()}"), None)
    if profile is None or SOURCE_PUBLISHERS.get(profile.id) != envelope.get("publisher_id"):
        raise ValueError("X endpoint has no reviewed owner profile")
    if envelope.get("source_url") != f"https://x.com/{profile.handle}/status/{identity}":
        raise ValueError("X source URL is invalid")
    payload = envelope.get("payload")
    refs = envelope.get("media_refs")
    if type(payload) is not dict or type(refs) is not list:
        raise ValueError("X source payload is invalid")
    hash_input = {"payload": payload, "media_refs": refs} if refs else payload
    digest = hashlib.sha256(json.dumps(hash_input, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if envelope.get("content_hash") != digest:
        raise ValueError("X source content hash is invalid")
    return profile, envelope, frozen_capabilities


def _posts(profile: Any, envelope: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, dict[str, Any]]]:
    payload = envelope.get("payload")
    raw_posts = payload.get("thread_posts") if type(payload) is dict else None
    if type(raw_posts) is not list or not 1 <= len(raw_posts) <= profile.thread_handling.max_posts:
        raise ValueError("X source thread is incomplete")
    refs = envelope.get("media_refs")
    if type(refs) is not list or len(refs) > 1:
        # The Board's current source-event contract has one chart path. More
        # images remain in Source Inbox for a later multi-chart owner contract.
        raise ValueError("X source media exceeds the Board path contract")
    by_ref = {ref["ref"]: ref for ref in refs if type(ref) is dict and type(ref.get("ref")) is str}
    if len(by_ref) != len(refs):
        raise ValueError("X source media references are invalid")
    converted = []
    used_refs: set[str] = set()
    for raw in raw_posts:
        if type(raw) is not dict or raw.get("profile_id") != profile.id:
            raise ValueError("X source post profile is invalid")
        post = dict(raw)
        for field in ("media", "quoted_media"):
            media = post.get(field)
            if not isinstance(media, (list, tuple)):
                raise ValueError("X source media mapping is invalid")
            converted_media = []
            for item in media:
                if type(item) is not dict or set(item) != {"index", "media_ref_id"} or type(item["index"]) is not int:
                    raise ValueError("X source media mapping is invalid")
                ref = item["media_ref_id"]
                if ref not in by_ref:
                    raise ValueError("X source image is not durable")
                used_refs.add(ref)
                converted_media.append({"index": item["index"], "url": reference_url(ref)})
            post[field] = converted_media
        try:
            parsed = state.deserialize_post(post)
        except (KeyError, TypeError, ValueError):
            raise ValueError("X source post is invalid") from None
        if parsed.post_id != str(int(parsed.post_id)) or parsed.url != f"https://x.com/{profile.handle}/status/{parsed.post_id}":
            raise ValueError("X source post identity is invalid")
        converted.append(parsed)
    if used_refs != set(by_ref) or bool(refs) != envelope.get("media_required"):
        raise ValueError("X source media completeness is invalid")
    latest = converted[-1]
    if (latest.post_id != envelope["provider_event_id"] or latest.url != envelope["source_url"]
            or latest.published_at.astimezone(timezone.utc) != datetime.fromisoformat(envelope["published_at"]).astimezone(timezone.utc)):
        raise ValueError("X source latest post differs from the event")
    if payload.get("post") != raw_posts[-1] or [int(item.post_id) for item in converted] != sorted({int(item.post_id) for item in converted}):
        raise ValueError("X source thread order is invalid")
    by_id = {post.post_id: post for post in converted}
    expected = state._within_thread_age(profile, state._self_chain(profile, latest, by_id, lambda item: rsshub.is_self_thread_post(profile, item)))
    if [item.post_id for item in expected] != [item.post_id for item in converted]:
        raise ValueError("X source thread relations are invalid")
    return tuple(converted), by_ref


def accept_source_work(work: dict[str, Any], *, now: datetime | None = None, no_post: bool = False, profiles: tuple[Any, ...] | None = None, storage: Path | None = None, media_client: Any = None, verifier: Any = None) -> dict[str, str]:
    storage = storage or _state_path()
    _check_no_post(storage, no_post)
    if profiles is None:
        loaded = config.load_watch_config_for_run()
        if loaded.revision is None:
            raise ValueError("X owner requires a live watcher config revision")
        profiles = loaded.config.profiles
    profile, envelope, frozen_capabilities = _identity(work, profiles)
    posts, refs = _posts(profile, envelope)
    if work.get("event_kind") not in {"original", "correction"} or (work["event_kind"] == "original") != (work["version"] == 1):
        raise ValueError("X source revision kind is invalid")
    now = now or datetime.now(timezone.utc)
    cached_paths = {}
    for ref, metadata in refs.items():
        cached_paths[ref] = str(cache_reference(storage, metadata, media_client or client_from_environment()))
    storage.parent.mkdir(parents=True, exist_ok=True)
    with (storage.parent / "run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = state.load_state(storage)
        ledger = value["source_events"]
        event_key = work["event_key"]
        recorded = ledger.get(event_key)
        version = work["version"]
        if recorded is not None and frozen_capabilities is not None and recorded.get("enabled_capabilities") != list(frozen_capabilities):
            raise ValueError("X source capability set changed after intake")
        if recorded is not None and frozen_capabilities is not None and recorded.get("source_catalog_revision") != work["catalog_revision"]:
            raise ValueError("X source catalog snapshot changed after intake")
        if recorded is not None and frozen_capabilities is None and "enabled_capabilities" in recorded:
            raise ValueError("X source work changed its dispatch type")
        if recorded is not None and recorded["version"] == version:
            if recorded["content_hash"] != envelope["content_hash"]:
                raise ValueError("X source event version changed content")
            if work["work_key"] not in recorded["work_keys"]:
                recorded["work_keys"].append(work["work_key"])
                state.save_state(storage, value)
            return {"outcome": recorded["outcome"]}
        if version > 1 and recorded is not None and recorded["version"] != version - 1:
            raise ValueError("X correction does not follow the accepted version")
        if version == 1 and recorded is not None:
            raise ValueError("X original source event is already recorded")
        latest = posts[-1]
        delivery_id = f"{profile.id}:{latest.post_id}"
        if state.delivery_by_id(value, delivery_id) is not None:
            raise ValueError("X source event has already been delivered")
        existing = next((item for item in value["outbox"] if item.get("profile_id") == profile.id and item.get("thread_root_id") == posts[0].post_id), None)
        would_update = existing is None or int(existing["post_id"]) <= int(latest.post_id)
        if existing and would_update and existing.get("agent_phase") not in {None, "pending"}:
            raise ValueError("X source thread has already been claimed")
        if existing and would_update and (existing.get("text_index", 0) or existing.get("media_index", 0)
                                           or existing.get("text_message_ids") or existing.get("media_message_ids")):
            raise ValueError("X source thread has already begun delivery")
        forwardable = rsshub.is_forwardable(profile, latest) or rsshub.is_self_thread_post(profile, latest)
        outcome = "irrelevant"
        if forwardable:
            updating = would_update
            if updating:
                state._event_for_thread(value, profile, posts, now, profile.thread_handling.settle_minutes if profile.thread_handling.mode == "self_chain" else 0)
                existing = next((item for item in value["outbox"] if item.get("profile_id") == profile.id and item.get("thread_root_id") == posts[0].post_id), None)
            if existing is None:
                raise ValueError("X source thread was not queued")
            if updating:
                existing["source_media_refs"] = refs
                existing["source_media_paths"] = cached_paths
                existing["source_event_key"] = event_key
                if frozen_capabilities is not None:
                    existing["enabled_capabilities"] = list(frozen_capabilities)
                    existing["source_catalog_revision"] = work["catalog_revision"]
            if updating and value["deliveries"]:
                import scan
                import supersession
                if no_post and verifier is None:
                    raise ValueError("no-post edit verification requires an injected verifier")
                scan._annotate_replacements(value, profile, {latest.post_id}, verifier or supersession.EditHistoryVerifier(), now, scan.RunStats())
            outcome = "accepted"
        ledger[event_key] = {"version": version, "content_hash": envelope["content_hash"], "work_keys": [work["work_key"]], "outcome": outcome}
        if frozen_capabilities is not None:
            ledger[event_key]["enabled_capabilities"] = list(frozen_capabilities)
            ledger[event_key]["source_catalog_revision"] = work["catalog_revision"]
        state.save_state(storage, value)
        return {"outcome": outcome}


def main() -> int:
    work = json.load(sys.stdin)
    result = accept_source_work(work, no_post=os.environ.get("BURSAWATCH_X_SOURCE_NO_POST") == "1")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
