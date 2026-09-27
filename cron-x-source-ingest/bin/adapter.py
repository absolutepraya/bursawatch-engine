"""Bounded X source adapter; existing X owner retains analysis and delivery."""
from __future__ import annotations

import sys
import re
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
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
from source_event_client import SourceEventHandoff
from config import REVIEWED_PUBLISHERS

ALLOWED = {"company_news", "macro_news"}


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
        _write(self._path(endpoint_id), records)

    def accept(self, event: dict[str, Any]) -> dict[str, Any]:
        receipt = self.inbox.accept(event)
        self._record(event, receipt["version"])
        return receipt

    def revise(self, event_key: str, event: dict[str, Any], kind: str, revision_id: str, reason: str) -> dict[str, Any]:
        receipt = self.inbox.revise(event_key, event, kind, revision_id, reason)
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


def _upload_post_media(post: Any, endpoint_id: str, media_store: Any, media_preparer: Any = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    media = [("media", item) for item in post.media] + [("quoted_media", item) for item in post.quoted_media]
    if not media or media_store is None:
        return [], {}
    unique: list[tuple[str, Any]] = []
    seen_urls: set[str] = set()
    for role, source in media:
        if type(source.index) is not int or source.index < 0 or not _bounded_x_image_url(source.url):
            return [], {}
        if source.url not in seen_urls:
            seen_urls.add(source.url)
            unique.append((role, source))
    # The existing bounded X fetcher is image-only and caps each post at 8.
    if not 1 <= len(unique) <= 8:
        return [], {}
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
        bundle = media_preparer(post, temporary_root)
        if bundle.unavailable_count or len(bundle.assets) != len(unique):
            return [], {}
        total_bytes = sum(asset.path.stat().st_size for asset in bundle.assets)
        if total_bytes > 25 * 1024 * 1024:
            return [], {}
        suffix_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        for index, ((role, source), asset) in enumerate(zip(unique, bundle.assets, strict=True)):
            data = asset.path.read_bytes()
            content_type = suffix_types.get(asset.path.suffix.lower())
            if content_type is None or not 1 <= len(data) <= 8 * 1024 * 1024:
                return [], {}
            filename = f"x-{post.post_id}-{index}{asset.path.suffix.lower()}"
            ref = media_store.upload(
                f"x:{endpoint_id}:{post.post_id}:attachment:{index}",
                data,
                kind="image",
                content_type=content_type,
                filename=filename,
            )
            refs.append(ref)
            url_to_ref[source.url] = ref["ref"]
        return refs, url_to_ref
    except Exception:
        # A failed fetch or upload keeps the provider cursor blocked. Repeating
        # the stable keys makes partial durable uploads safe to retry.
        return [], {}
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


def _item(post: Any, endpoint_id: str, media_store: Any, *, upload_media: bool, media_preparer: Any = None, thread_posts: tuple[Any, ...] | None = None) -> dict[str, Any]:
    from state import serialize_post
    from scan import source_visible_text
    ordered = thread_posts or (post,)
    has_media = any(item.media or item.quoted_media for item in ordered)
    refs: list[dict[str, Any]] = []
    serialized: list[dict[str, Any]] = []
    complete = upload_media or not has_media
    for source_post in ordered:
        source_media = bool(source_post.media or source_post.quoted_media)
        current_refs, url_to_ref = _upload_post_media(source_post, endpoint_id, media_store, media_preparer) if source_media and upload_media else ([], {})
        if source_media and not current_refs:
            complete = False
        refs.extend(current_refs)
        payload_post = serialize_post(source_post)
        if source_media and current_refs:
            media_urls = {item.url for item in (*source_post.media, *source_post.quoted_media)}
            payload_post["content_html"] = _safe_html(payload_post.get("content_html"), media_urls)
            payload_post["quoted_content_html"] = _safe_html(payload_post.get("quoted_content_html"), media_urls)
            payload_post["media"] = [{"index": item.index, "media_ref_id": url_to_ref[item.url]} for item in source_post.media]
            payload_post["quoted_media"] = [{"index": item.index, "media_ref_id": url_to_ref[item.url]} for item in source_post.quoted_media]
        serialized.append(payload_post)
    # The current X Board handoff has one local chart path. Hold a source
    # event with more than one original before it creates subscription work.
    if not complete or len(refs) > 1 or sum(ref["size_bytes"] for ref in refs) > 25 * 1024 * 1024:
        refs = []
    payload = {"post": serialized[-1], "thread_posts": serialized}
    if has_media and refs:
        payload["media_ref_ids"] = [ref["ref"] for ref in refs]
    return {"provider_event_id": post.post_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": payload, "media_refs": refs, "blocked_payload": {"profile_id": post.profile_id, "kind": post.kind.value, "source_text": source_visible_text(post.content_html), "quoted_text": source_visible_text(post.quoted_content_html or "")}, "media_required": has_media}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None, media_store: Any = None, media_preparer: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    tracked = _TrackedInbox(inbox, state_root)
    observed: dict[str, tuple[Any, ...]] = {}
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    def fetch(cursor: dict[str, Any] | None, profile: Any, endpoint_id: str) -> dict[str, Any]:
        from state import _self_chain, _within_thread_age
        from rsshub import is_self_thread_post
        # RSSHub returns a whole visible page. Direct X takes an after-id and
        # expands threads; a full result without the old anchor remains
        # ambiguous and must block rather than skip unseen posts.
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
            if post.post_id in upload_ids and is_self_thread_post(profile, post) and len(chain) == 1 and post.related_url:
                raise IntakeBlocked("self-chain parent is unavailable")
            items.append(_item(post, endpoint_id, media_store, upload_media=post.post_id in upload_ids, media_preparer=media_preparer, thread_posts=chain))
        return {"items": items, "truncated": truncated, "contiguous": False, "id_order": "numeric_provider_event_id"}
    fetchers = {endpoint_id: (lambda cursor, profile=by_endpoint[endpoint_id], endpoint_id=endpoint_id: fetch(cursor, profile, endpoint_id)) for endpoint_id in selected}
    outcomes = ingest_all(selected, fetchers, state_root, tracked, observed_at, "x-watch-parser-1")
    for result in outcomes:
        endpoint_id = result["endpoint_id"]
        if result["status"] == "blocked" or endpoint_id not in observed:
            continue
        root = state_root / endpoint_id.replace(":", "-")
        handoff = SourceEventHandoff(root / "revisions", tracked)
        try:
            handoff.flush()
            records = tracked.records(endpoint_id)
            profile = by_endpoint[endpoint_id]
            by_id = {post.post_id: post for post in observed[endpoint_id]}
            from state import _self_chain, _within_thread_age
            from rsshub import is_self_thread_post
            for post in observed[endpoint_id]:
                prior = records.get(post.post_id)
                if prior is None:
                    continue
                chain = _within_thread_age(profile, _self_chain(profile, post, by_id, lambda item: is_self_thread_post(profile, item)))
                item = _item(post, endpoint_id, media_store, upload_media=True, media_preparer=media_preparer, thread_posts=chain)
                if item["media_required"] and not item["media_refs"]:
                    raise IntakeBlocked("X source correction media is unavailable")
                current = envelope(selected[endpoint_id], item, observed_at, "x-watch-parser-1")
                if current["content_hash"] == prior["content_hash"]:
                    continue
                event_key = hashlib.sha256(json.dumps(["x", endpoint_id, post.post_id], separators=(",", ":")).encode()).hexdigest()
                inspected = inbox.inspect(event_key)
                rows = inspected.get("work") if type(inspected) is dict else None
                if type(rows) is not list or not rows or any(type(row) is not dict or row.get("status") != "pending" for row in rows):
                    raise IntakeBlocked("X correction requires unclaimed source work")
                revision_id = f"x-source-content-{current['content_hash']}"
                handoff.stage_revision(event_key, current, "correction", revision_id, "Observed source post content changed")
                handoff.flush(limit=1)
                records = tracked.records(endpoint_id)
        except Exception:
            result["status"] = "blocked"
            result["reason"] = "correction_handoff_failed"
    return outcomes
