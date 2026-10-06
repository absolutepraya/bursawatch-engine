"""Bounded X source adapter; existing X owner retains analysis and delivery."""
from __future__ import annotations

import sys
import re
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
for package, installed in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / installed / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-x-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin"
sys.path.insert(0, str(owner))

from legacy_cursor_seed import LegacySeedBlocked, plan_seed, read_legacy_snapshot
from source_ingest import IntakeBlocked, _write, bind_catalog_revision, envelope, ingest_all, select_endpoints
from source_event_client import SourceEventHandoff, _event_key
from config import REVIEWED_PUBLISHERS

ALLOWED = {"company_news", "macro_news", "swing_chart_context"}


def plan_legacy_cursor_seed(legacy_state_path: Path, state_root: Path, endpoint: dict[str, Any], profile: Any, catalog_revision: int, *, apply: bool = False, expected_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map one legacy X profile ID cursor to its canonical source endpoint."""
    endpoint_id = f"x:{profile.handle.casefold()}"
    publisher_id = REVIEWED_PUBLISHERS.get(profile.id)
    expected = ("x", endpoint_id, publisher_id, profile.handle, None)
    observed = tuple(endpoint.get(key) for key in ("platform", "endpoint_id", "publisher_id", "address", "provider_id"))
    if observed != expected or endpoint.get("catalog_revision") != catalog_revision:
        raise LegacySeedBlocked("X endpoint does not match the selected legacy profile")
    raw, legacy = read_legacy_snapshot(legacy_state_path)
    profiles = legacy.get("profiles") if type(legacy) is dict else None
    record = profiles.get(profile.id) if type(profiles) is dict else None
    boundary = record.get("cursor") if type(record) is dict else None
    if type(boundary) not in {str, int} or not str(boundary).isdigit():
        raise LegacySeedBlocked("X legacy profile cursor is absent or invalid")
    if legacy.get("outbox") or legacy.get("cleanup"):
        raise LegacySeedBlocked("X legacy outbox or cleanup work must be reconciled before cursor seeding")
    return plan_seed(legacy_state_path=legacy_state_path, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=catalog_revision, anchor=str(boundary), cursor_shape="generic", apply=apply, expected_plan=expected_plan)


class _TrackedInbox:
    """Keep a private, acknowledged index for later same-ID source corrections."""

    def __init__(self, inbox: Any, state_root: Path):
        self.inbox = inbox
        self.state_root = state_root

    def _path(self, endpoint_id: str) -> Path:
        return self.state_root / endpoint_id.replace(":", "-") / "accepted-events.json"

    def records(self, endpoint_id: str) -> dict[str, Any]:
        path = self._path(endpoint_id)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise IntakeBlocked("X accepted-event index is invalid") from error
        if type(value) is not dict or any(type(key) is not str or type(item) is not dict for key, item in value.items()):
            raise IntakeBlocked("X accepted-event index is invalid")
        return value

    def _record(self, event: dict[str, Any], version: int) -> None:
        endpoint_id = event["endpoint_id"]
        records = self.records(endpoint_id)
        post_id = event["provider_event_id"]
        current = records.get(post_id)
        if current is not None and current.get("version", 0) > version:
            return
        records[post_id] = {"version": version, "content_hash": event["content_hash"]}
        payload = event["payload"]
        if payload.get("source_media_policy") == "optional_news":
            records[post_id]["source_observation_hash"] = payload["source_observation_hash"]
        _write(self._path(endpoint_id), records)

    def accept(self, event: dict[str, Any]) -> dict[str, Any]:
        receipt = self.inbox.accept(event)
        self._record(event, receipt["version"])
        return receipt

    def revise(self, event_key: str, event: dict[str, Any], kind: str, revision_id: str, reason: str, **kwargs: Any) -> dict[str, Any]:
        receipt = self.inbox.revise(event_key, event, kind, revision_id, reason, **kwargs)
        self._record(event, receipt["version"])
        return receipt


def endpoints(snapshot: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bindings = {}
    by_endpoint = {}
    for profile in profiles:
        if not profile.enabled:
            continue
        endpoint_id = f"x:{profile.handle.casefold()}"
        if endpoint_id in bindings:
            raise IntakeBlocked("duplicate X endpoint")
        publisher_id = REVIEWED_PUBLISHERS.get(profile.id)
        if publisher_id is None:
            raise IntakeBlocked("X endpoint has no reviewed publisher binding")
        bindings[endpoint_id] = {"platform": "x", "publisher_id": publisher_id, "address": profile.handle, "provider_id": None}
        by_endpoint[endpoint_id] = profile
    selected = select_endpoints(snapshot, "x", bindings, ALLOWED)
    for endpoint_id in bindings:
        if endpoint_id not in selected:
            raise IntakeBlocked("enabled X profile has no verified subscription")
    return selected, by_endpoint


def _bounded_x_image_url(value: Any) -> bool:
    if type(value) is not str or len(value) > 4096:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname is not None and parsed.hostname.lower().rstrip(".") == "pbs.twimg.com" and port in {None, 443} and not parsed.username and not parsed.password and bool(parsed.path)


def _upload_post_media(post: Any, endpoint_id: str, media_store: Any, media_preparer: Any = None, *, optional_media: bool = False) -> tuple[list[dict[str, Any]], dict[str, str]]:
    media = [("media", item) for item in post.media] + [("quoted_media", item) for item in post.quoted_media]
    if not media or media_store is None:
        return [], {}
    unique: list[tuple[str, Any]] = []
    seen_urls: set[str] = set()
    for role, source in media:
        if not optional_media and (type(source.index) is not int or source.index < 0 or not _bounded_x_image_url(source.url)):
            return [], {}
        if source.url not in seen_urls:
            seen_urls.add(source.url)
            unique.append((role, source))
    # The existing bounded X fetcher is image-only and caps each post at 8.
    if not unique or (not optional_media and len(unique) > 8):
        return [], {}
    candidates = [(index, role, source) for index, (role, source) in enumerate(unique)
                  if type(source.index) is int and source.index >= 0 and _bounded_x_image_url(source.url)][:8]
    prepared_post = post
    if optional_media:
        allowed_urls = {source.url for _, _, source in candidates}
        prepared_post = replace(post, media=tuple(item for item in post.media if item.url in allowed_urls),
                                quoted_media=tuple(item for item in post.quoted_media if item.url in allowed_urls))
    if media_preparer is None:
        from vision_media import cleanup_event, prepare
        media_preparer = prepare
    else:
        from vision_media import cleanup_event

    temporary_root = Path(tempfile.mkdtemp(prefix="bursawatch-x-source-media-"))
    temporary_root.chmod(0o700)
    refs: list[dict[str, Any]] = []
    url_to_ref: dict[str, str] = {}
    try:
        bundle = media_preparer(prepared_post, temporary_root)
        if not optional_media and (bundle.unavailable_count or len(bundle.assets) != len(unique)):
            return [], {}
        # Partial bundles retain source labels, so a missing earlier image
        # cannot shift a later asset onto the wrong source URL or upload key.
        assets = {(asset.role, asset.post_id, asset.index): asset for asset in bundle.assets}
        total_bytes = 0
        suffix_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        for index, role, source in candidates:
            try:
                asset = assets[("tweet" if role == "media" else "quoted_tweet", post.post_id, source.index)]
                data = asset.path.read_bytes()
                content_type = suffix_types.get(asset.path.suffix.lower())
                if content_type is None or not 1 <= len(data) <= 8 * 1024 * 1024 or total_bytes + len(data) > 25 * 1024 * 1024:
                    if optional_media:
                        continue
                    return [], {}
                filename = f"x-{post.post_id}-{index}{asset.path.suffix.lower()}"
                ref = media_store.upload(
                    f"x:{endpoint_id}:{post.post_id}:attachment:{index}",
                    data,
                    kind="image",
                    content_type=content_type,
                    filename=filename,
                )
            except Exception:
                if optional_media:
                    continue
                return [], {}
            refs.append(ref)
            url_to_ref[source.url] = ref["ref"]
            total_bytes += len(data)
        return refs, url_to_ref
    except Exception:
        # The caller applies the news fallback or required Swing policy.
        # Stable upload keys keep partial durable uploads safe to retry.
        return (refs, url_to_ref) if optional_media else ([], {})
    finally:
        try:
            cleanup_event(temporary_root, post.profile_id, post.post_id)
        except Exception:
            pass
        shutil.rmtree(temporary_root, ignore_errors=True)


def _safe_html(value: str | None, media_urls: set[str]) -> str | None:
    if value is None:
        return None
    # Remove media elements and every exact source locator the parser found.
    value = re.sub(r"</?(?:img|video|source)\b[^>]*>", "", value, flags=re.IGNORECASE)
    for url in media_urls:
        value = value.replace(url, "")
    return value


def _source_observation_hash(posts: tuple[Any, ...]) -> str:
    from state import serialize_post
    raw = json.dumps([serialize_post(post) for post in posts], sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _item(post: Any, endpoint_id: str, media_store: Any, *, upload_media: bool, media_preparer: Any = None, thread_posts: tuple[Any, ...] | None = None, optional_media: bool = False) -> dict[str, Any]:
    from state import serialize_post
    from scan import source_visible_text
    ordered = thread_posts or (post,)
    has_media = any(item.media or item.quoted_media for item in ordered)
    refs: list[dict[str, Any]] = []
    serialized: list[dict[str, Any]] = []
    complete = upload_media or not has_media
    for source_post in ordered:
        source_media = bool(source_post.media or source_post.quoted_media)
        current_refs, url_to_ref = _upload_post_media(source_post, endpoint_id, media_store, media_preparer, optional_media=optional_media) if source_media and upload_media else ([], {})
        if any(item.url not in url_to_ref for item in (*source_post.media, *source_post.quoted_media)):
            complete = False
        refs.extend(current_refs)
        payload_post = serialize_post(source_post)
        if source_media and (current_refs or optional_media):
            media_urls = {item.url for item in (*source_post.media, *source_post.quoted_media)}
            payload_post["content_html"] = _safe_html(payload_post.get("content_html"), media_urls)
            payload_post["quoted_content_html"] = _safe_html(payload_post.get("quoted_content_html"), media_urls)
            seen_refs: set[str] = set()
            for field, items in (("media", source_post.media), ("quoted_media", source_post.quoted_media)):
                serialized_media = []
                for item in items:
                    if item.url not in url_to_ref:
                        continue
                    ref = url_to_ref[item.url]
                    if ref in seen_refs:
                        continue
                    seen_refs.add(ref)
                    serialized_media.append({"index": item.index, "media_ref_id": ref})
                payload_post[field] = serialized_media
        serialized.append(payload_post)
    exceeds_bounds = len(refs) > 16 or sum(ref["size_bytes"] for ref in refs) > 25 * 1024 * 1024
    if (not complete and not optional_media) or exceeds_bounds:
        refs = []
        if optional_media:
            for item in serialized:
                item["media"] = []
                item["quoted_media"] = []
    payload = {"post": serialized[-1], "thread_posts": serialized}
    if optional_media:
        payload.update(source_media_policy="optional_news", source_observation_hash=_source_observation_hash(ordered), media_degraded=not complete or exceeds_bounds)
    if has_media and refs:
        payload["media_ref_ids"] = [ref["ref"] for ref in refs]
    return {"provider_event_id": post.post_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": payload, "media_refs": refs, "blocked_payload": {"profile_id": post.profile_id, "kind": post.kind.value, "source_text": source_visible_text(post.content_html), "quoted_text": source_visible_text(post.quoted_content_html or "")}, "media_required": False if optional_media else has_media}



def _current_source(inspected: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    versions = inspected.get("event", {}).get("versions")
    work = inspected.get("work")
    if type(versions) is not list or not versions or type(work) is not list:
        raise IntakeBlocked("X accepted version inspection is invalid")
    current = max(versions, key=lambda value: value["version"])
    if type(current.get("version")) is not int or type(current.get("envelope")) is not dict:
        raise IntakeBlocked("X accepted version is invalid")
    rows = [row for row in work if row.get("version") == current["version"]]
    if not rows:
        raise IntakeBlocked("X accepted version has no work")
    return current, rows


def _pending(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(row.get("status") == "pending" for row in rows)


def _frozen_capabilities(rows: list[dict[str, Any]]) -> set[str]:
    capabilities = set()
    for row in rows:
        context = row.get("dispatch_context") or {}
        subscriptions = context.get("subscriptions")
        if subscriptions is not None:
            if context.get("dispatch_group") != "x_post_route" or type(subscriptions) is not list or not subscriptions:
                raise IntakeBlocked("X frozen dispatch is invalid")
            capabilities.update(subscription["capability_id"] for subscription in subscriptions)
        else:
            capabilities.add(row["capability_id"])
    if not capabilities or not capabilities <= ALLOWED:
        raise IntakeBlocked("X frozen capabilities are invalid")
    return capabilities


def _text_context(payload: dict[str, Any]) -> list[dict[str, Any]]:
    posts = payload.get("thread_posts") or [payload["post"]]
    return [{key:value for key,value in post.items() if key not in {"media", "quoted_media"}} for post in posts]


def _flush_correction(request: Any, handoff: SourceEventHandoff, inbox: Any) -> dict[str, str]:
    payload = request.payload
    key = request.endpoint.removeprefix("/v1/source-events/").removesuffix("/versions")
    required = {"envelope", "kind", "revision_id", "reason"}
    if (request.method != "POST" or type(payload) is not dict
            or set(payload) not in (required, required | {"expected_pending_version"})
            or request.endpoint != f"/v1/source-events/{key}/versions"
            or not re.fullmatch(r"[0-9a-f]{64}", key)
            or _event_key(payload["envelope"]) != key or payload["kind"] != "correction"
            or type(payload["revision_id"]) is not str or not 1 <= len(payload["revision_id"]) <= 128
            or type(payload["reason"]) is not str or not 1 <= len(payload["reason"].strip()) <= 500):
        raise IntakeBlocked("X saved correction is invalid")
    expected = payload.get("expected_pending_version")
    if expected is not None and (type(expected) is not int or expected < 1):
        raise IntakeBlocked("X saved correction guard is invalid")
    inspected = inbox.inspect(key)
    accepted, rows = _current_source(inspected)
    versions = inspected["event"]["versions"]
    already_accepted = any(version.get("revision_id") == payload.get("revision_id") for version in versions)
    if not already_accepted and (not _pending(rows) or expected is not None and accepted["version"] != expected):
        handoff.spool.acknowledge(request.path)
        return {"provider_event_id":payload["envelope"]["provider_event_id"],"status":"deferred_frozen"}
    # Submit this exact request, not the queue's first item. Older saved requests
    # retain their bytes and identity while receiving the same atomic guard.
    handoff.client.revise(key, payload["envelope"], payload["kind"], payload["revision_id"], payload["reason"],
                          expected_pending_version=expected if expected is not None else accepted["version"])
    handoff.spool.acknowledge(request.path)
    return {"provider_event_id":payload["envelope"]["provider_event_id"],"status":"revised"}


def _flush_corrections(handoff: SourceEventHandoff, inbox: Any, outcomes: list[dict[str, str]], *, attempted: set[Path] | None = None) -> set[str]:
    """Retry independent saved corrections without losing failed requests.

    A raced claim retires the unsent correction, not the accepted source event.
    A lost acknowledgement still reconciles the same accepted revision identity.
    """
    attempted = attempted if attempted is not None else set()
    failed_keys: set[str] = set()
    for request in handoff.spool.pending(50):
        if request.path in attempted:
            continue
        attempted.add(request.path)
        try:
            outcomes.append(_flush_correction(request, handoff, inbox))
        except Exception:
            outcome = {"status":"retry", "error_code":"revision_flush_failed"}
            try:
                event = request.payload["envelope"]
                failed_keys.add(_event_key(event))
                identity = event["provider_event_id"]
                if type(identity) is str and identity.isascii() and identity.isdigit() and len(identity) <= 128:
                    outcome["provider_event_id"] = identity
            except Exception:
                pass
            outcomes.append(outcome)
    return failed_keys


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None, fetch_direct_x_head: Any = None, media_store: Any = None, media_preparer: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    from compatible_catalog_transition import require_catalog_revision
    require_catalog_revision(state_root, snapshot["revision"], bind_catalog_revision)
    tracked = _TrackedInbox(inbox, state_root)
    observed: dict[str, tuple[Any, ...]] = {}
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    if fetch_direct_x_head is None:
        from direct_x import fetch_profile_head_id
        fetch_direct_x_head = fetch_profile_head_id
    def fetch(cursor: dict[str, Any] | None, profile: Any, endpoint_id: str) -> dict[str, Any]:
        from state import _self_chain, _within_thread_age
        from rsshub import is_self_thread_post
        from models import PostKind
        from scan import source_visible_text
        from agent_protocol import optional_news_media
        # RSSHub returns a whole visible page. Direct X takes an after-id and
        # expands threads; a full result without the old anchor remains
        # ambiguous and must block rather than skip unseen posts.
        if cursor is None and profile.source == "direct_x":
            # Establish a future-only boundary without downloading every
            # visible status. Direct-X detail requests are slow and can be
            # rate limited during this one-time initialization.
            head_id = str(fetch_direct_x_head(profile))
            if not head_id.isdigit():
                raise IntakeBlocked("direct X profile head ID is invalid")
            return {
                "items": [{"provider_event_id": head_id}],
                "truncated": False,
                "contiguous": False,
                "id_order": "numeric_provider_event_id",
            }
        after_id = cursor["anchor"] if cursor and profile.source in {"direct_x", "hybrid"} else None
        posts = fetch_profile(profile, after_id=after_id)
        ordered = sorted(posts, key=lambda post: int(post.post_id))
        observed[endpoint_id] = tuple(ordered)
        by_id = {post.post_id: post for post in ordered}
        truncated = len(posts) >= profile.max_items_per_poll
        identities = [post.post_id for post in ordered]
        anchor = cursor.get("anchor") if cursor else None
        if cursor is None or truncated and anchor not in identities:
            upload_ids: set[str] = set()
        else:
            start = identities.index(anchor) + 1 if anchor in identities else 0
            upload_ids = set(identities[start:start + 20])
        items = []
        for post in ordered:
            chain = _within_thread_age(profile, _self_chain(profile, post, by_id, lambda item: is_self_thread_post(profile, item)))
            inline_quote = post.kind is PostKind.QUOTE and bool(source_visible_text(post.quoted_content_html or "").strip())
            if post.post_id in upload_ids and is_self_thread_post(profile, post) and len(chain) == 1 and post.related_url and not inline_quote:
                raise IntakeBlocked("self-chain parent is unavailable")
            items.append(_item(post, endpoint_id, media_store, upload_media=post.post_id in upload_ids, media_preparer=media_preparer, thread_posts=chain, optional_media=optional_news_media(profile, post, chain, selected[endpoint_id]["capabilities"])))
        return {"items": items, "truncated": truncated, "contiguous": False, "id_order": "numeric_provider_event_id"}
    fetchers = {endpoint_id: (lambda cursor, profile=by_endpoint[endpoint_id], endpoint_id=endpoint_id: fetch(cursor, profile, endpoint_id)) for endpoint_id in selected}
    outcomes = ingest_all(selected, fetchers, state_root, tracked, observed_at, "x-watch-parser-1")
    for result in outcomes:
        endpoint_id = result["endpoint_id"]
        if result["status"] == "blocked" or endpoint_id not in observed:
            continue
        root = state_root / endpoint_id.replace(":", "-")
        handoff = SourceEventHandoff(root / "revisions", tracked)
        correction_outcomes = []
        result["corrections"] = correction_outcomes
        attempted_corrections: set[Path] = set()
        try:
            failed_corrections = _flush_corrections(handoff, inbox, correction_outcomes, attempted=attempted_corrections)
            if any(row["status"] == "retry" for row in correction_outcomes):
                result.update(status="blocked", reason="correction_handoff_failed", correction_error_code="revision_flush_failed")
            records = tracked.records(endpoint_id)
        except Exception:
            result.update(status="blocked", reason="correction_handoff_failed", correction_error_code="revision_flush_failed")
            continue
        profile = by_endpoint[endpoint_id]
        by_id = {post.post_id: post for post in observed[endpoint_id]}
        from state import _self_chain, _within_thread_age
        from rsshub import is_self_thread_post
        for post in observed[endpoint_id]:
            prior = records.get(post.post_id)
            if prior is None:
                continue
            event_key = hashlib.sha256(json.dumps(["x", endpoint_id, post.post_id], separators=(",", ":")).encode()).hexdigest()
            if event_key in failed_corrections:
                # Keep this event's saved retry instead of staging another edit.
                continue
            correction_error_code = "correction_context_failed"
            try:
                chain = _within_thread_age(profile, _self_chain(profile, post, by_id, lambda item: is_self_thread_post(profile, item)))
                if "source_observation_hash" in prior and _source_observation_hash(chain) == prior["source_observation_hash"]:
                    continue
                correction_error_code = "source_work_inspection_failed"
                inspected = inbox.inspect(event_key)
                accepted, rows = _current_source(inspected)
                if accepted["version"] != prior["version"] or not _pending(rows):
                    correction_outcomes.append({"provider_event_id":post.post_id,"status":"deferred_frozen"})
                    continue
                from models import PostKind
                from scan import source_visible_text
                inline_quote = post.kind is PostKind.QUOTE and bool(source_visible_text(post.quoted_content_html or "").strip())
                if is_self_thread_post(profile, post) and len(chain) == 1 and post.related_url and not inline_quote:
                    raise IntakeBlocked("X correction self-chain parent is unavailable")
                from agent_protocol import optional_news_media
                # The immutable source work, rather than today's catalog, owns
                # the capabilities available to this correction.
                capabilities = _frozen_capabilities(rows)
                optional_media = optional_news_media(profile, post, chain, capabilities)
                if "swing_chart_context" in capabilities and not any(channel.key == "id_stocks_swing" for channel in profile.discord_channels):
                    # A changed catalog cannot remove the accepted Swing boundary.
                    optional_media = False
                if "source_observation_hash" not in prior:
                    comparison = _item(post, endpoint_id, None, upload_media=False, thread_posts=chain, optional_media=True)
                    if _text_context(comparison["payload"]) == _text_context(accepted["envelope"]["payload"]):
                        # Legacy refs cannot establish an image-observation hash.
                        # Keep accepted media unchanged without inventing a baseline.
                        correction_outcomes.append({"provider_event_id":post.post_id,"status":"text_unchanged_media_unverified"})
                        continue
                item = _item(post, endpoint_id, media_store, upload_media=True, media_preparer=media_preparer, thread_posts=chain, optional_media=optional_media)
                if item["media_required"] and not item["media_refs"]:
                    correction_error_code = "correction_media_unavailable"
                    raise IntakeBlocked("X source correction media is unavailable")
                correction_error_code = "correction_envelope_invalid"
                current = envelope(selected[endpoint_id], item, observed_at, "x-watch-parser-1")
                if current["content_hash"] == prior["content_hash"]:
                    continue
                revision_id = f"x-source-content-{current['content_hash']}"
                correction_error_code = "revision_stage_failed"
                handoff.stage_revision(event_key, current, "correction", revision_id, "Observed source post content changed", expected_pending_version=accepted["version"])
                correction_error_code = "revision_flush_failed"
                outcome_start = len(correction_outcomes)
                failed_corrections.update(_flush_corrections(handoff, inbox, correction_outcomes, attempted=attempted_corrections))
                if any(row["status"] == "retry" for row in correction_outcomes[outcome_start:]):
                    result.update(status="blocked", reason="correction_handoff_failed", correction_error_code="revision_flush_failed")
                records = tracked.records(endpoint_id)
            except Exception:
                result.update(status="blocked", reason="correction_handoff_failed", correction_error_code=correction_error_code)
                correction_outcomes.append({"provider_event_id":post.post_id,"status":"retry","error_code":correction_error_code})
                # A failed correction must not stop other publications' checks.
    return outcomes
