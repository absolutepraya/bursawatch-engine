"""Bounded X source adapter; existing X owner retains analysis and delivery."""
from __future__ import annotations

import sys
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-x-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, bind_catalog_revision, ingest_all, select_endpoints

ALLOWED = {"company_news", "macro_news"}
PUBLISHERS = {
    "x:kutekians": "x-kutekians",
    "x:rickyho_1989": "x-rickyho1989",
    "x:writingtorch": "x-writingtorch",
    "x:arvinhonami": "x-arvinhonami",
    "x:insidertrackx": "x-insidertracker",
    "x:doktermarket": "x-doktermarket",
    "x:txthariansaham": "x-txthariansaham",
    "x:wavetiga": "x-wavetiga",
    "x:aldotjahjadi8": "x-aldotjahjadi8",
    "x:kobeissiletter": "x-kobeissiletter",
}


def endpoints(snapshot: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bindings = {}
    by_endpoint = {}
    for profile in profiles:
        if not profile.enabled:
            continue
        endpoint_id = f"x:{profile.handle.casefold()}"
        if endpoint_id in bindings:
            raise IntakeBlocked("duplicate X endpoint")
        publisher_id = PUBLISHERS.get(endpoint_id)
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


def _item(post: Any, endpoint_id: str, media_store: Any, *, upload_media: bool, media_preparer: Any = None) -> dict[str, Any]:
    from state import serialize_post
    from scan import source_visible_text
    has_media = bool(post.media or post.quoted_media)
    refs, url_to_ref = _upload_post_media(post, endpoint_id, media_store, media_preparer) if has_media and upload_media else ([], {})
    payload_post = serialize_post(post)
    if has_media and refs:
        media_urls = {item.url for item in (*post.media, *post.quoted_media)}
        payload_post["content_html"] = _safe_html(payload_post.get("content_html"), media_urls)
        payload_post["quoted_content_html"] = _safe_html(payload_post.get("quoted_content_html"), media_urls)
        payload_post["media"] = [{"index": item.index, "media_ref_id": url_to_ref[item.url]} for item in post.media]
        payload_post["quoted_media"] = [{"index": item.index, "media_ref_id": url_to_ref[item.url]} for item in post.quoted_media]
    payload = {"post": payload_post}
    if has_media and refs:
        payload["media_ref_ids"] = [ref["ref"] for ref in refs]
    return {"provider_event_id": post.post_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": payload, "media_refs": refs, "blocked_payload": {"profile_id": post.profile_id, "kind": post.kind.value, "source_text": source_visible_text(post.content_html), "quoted_text": source_visible_text(post.quoted_content_html or "")}, "media_required": has_media}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None, media_store: Any = None, media_preparer: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    def fetch(cursor: dict[str, Any] | None, profile: Any, endpoint_id: str) -> dict[str, Any]:
        # RSSHub returns a whole visible page. Direct X takes an after-id and
        # expands threads; a full result without the old anchor remains
        # ambiguous and must block rather than skip unseen posts.
        after_id = cursor["anchor"] if cursor and profile.source == "direct_x" else None
        posts = fetch_profile(profile, after_id=after_id)
        ordered = sorted(posts, key=lambda post: int(post.post_id))
        truncated = len(posts) >= profile.max_items_per_poll
        identities = [post.post_id for post in ordered]
        anchor = cursor.get("anchor") if cursor else None
        if cursor is None or truncated and anchor not in identities:
            upload_ids: set[str] = set()
        else:
            start = identities.index(anchor) + 1 if anchor in identities else 0
            upload_ids = set(identities[start:start + 20])
        items = [_item(post, endpoint_id, media_store, upload_media=post.post_id in upload_ids, media_preparer=media_preparer) for post in ordered]
        return {"items": items, "truncated": truncated, "contiguous": False}
    fetchers = {endpoint_id: (lambda cursor, profile=by_endpoint[endpoint_id], endpoint_id=endpoint_id: fetch(cursor, profile, endpoint_id)) for endpoint_id in selected}
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "x-watch-parser-1")
