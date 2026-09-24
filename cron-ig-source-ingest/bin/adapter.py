"""Bounded Instagram source adapter; media stays pending at its cursor."""
from __future__ import annotations

import sys
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-ig-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-ig-account-watch" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, bind_catalog_revision, ingest_all, select_endpoints

ALLOWED = {"company_news", "macro_news"}
PUBLISHERS = {
    "instagram:beyondthefundamental": "instagram-beyondthefundamental",
    "instagram:investart_id": "instagram-investart_id",
    "instagram:avenirresearch.id": "instagram-avenirresearch_id",
    "instagram:acresresearch": "instagram-acresresearch",
    "instagram:sectorsapp": "instagram-sectorsapp",
    "instagram:cukhurukuque": "instagram-cukhurukuque",
    "instagram:notintofinance": "instagram-notintofinance",
}


def endpoints(snapshot: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bindings = {}
    by_endpoint = {}
    for profile in profiles:
        if not profile.enabled:
            continue
        endpoint_id = f"instagram:{profile.handle.casefold()}"
        if endpoint_id in bindings:
            raise IntakeBlocked("duplicate Instagram endpoint")
        publisher_id = PUBLISHERS.get(endpoint_id)
        if publisher_id is None:
            raise IntakeBlocked("Instagram endpoint has no reviewed publisher binding")
        bindings[endpoint_id] = {"platform": "instagram", "publisher_id": publisher_id, "address": profile.handle, "provider_id": None}
        by_endpoint[endpoint_id] = profile
    selected = select_endpoints(snapshot, "instagram", bindings, ALLOWED)
    for endpoint_id in bindings:
        if endpoint_id not in selected:
            raise IntakeBlocked("enabled Instagram profile has no verified subscription")
    return selected, by_endpoint


def _upload_post_media(post: Any, endpoint_id: str, media_store: Any, media_downloader: Any = None) -> list[dict[str, Any]]:
    if not post.media or media_store is None or len(post.media) > 16:
        return []
    indexes = [source.index for source in post.media]
    if any(type(index) is not int or index < 0 for index in indexes) or len(set(indexes)) != len(indexes):
        return []
    temporary_root = Path(tempfile.mkdtemp(prefix="bursawatch-ig-source-media-"))
    temporary_root.chmod(0o700)
    refs: list[dict[str, Any]] = []
    try:
        if media_downloader is None:
            import requests
            from media import DownloadLimits, download_publication
            session = requests.Session()
            try:
                downloaded = download_publication(
                    post,
                    temporary_root,
                    session,
                    DownloadLimits(max_asset_bytes=8 * 1024 * 1024, max_publication_bytes=25 * 1024 * 1024, timeout_seconds=30),
                    allow_partial=False,
                )
            finally:
                session.close()
        else:
            downloaded = media_downloader(post, temporary_root)
        assets = sorted(downloaded.assets, key=lambda asset: asset.source.index)
        if downloaded.failed_assets or len(assets) != len(post.media) or sum(asset.size_bytes for asset in assets) > 25 * 1024 * 1024:
            return []
        suffix_types = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
            "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
        }
        for asset in assets:
            data = asset.path.read_bytes()
            content_type = asset.content_type
            suffix = suffix_types.get(content_type)
            if suffix is None or not 1 <= len(data) <= 8 * 1024 * 1024 or len(data) != asset.size_bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
                return []
            media_kind = asset.source.kind.value
            expected_kind = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else None
            if media_kind != expected_kind:
                return []
            publication_hash = hashlib.sha256(post.publication_id.encode("utf-8")).hexdigest()[:16]
            filename = f"ig-{publication_hash}-{asset.source.index}{suffix}"
            refs.append(media_store.upload(
                f"instagram:{endpoint_id}:{post.publication_id}:attachment:{asset.source.index}",
                data,
                kind=media_kind,
                content_type=content_type,
                filename=filename,
            ))
        return refs
    except Exception:
        # Missing bytes, an unsafe upstream URL, or a failed durable upload
        # leaves the event pending at its existing cursor.
        return []
    finally:
        try:
            from media import cleanup_event_media
            cleanup_event_media(temporary_root, post.publication_id)
        except Exception:
            pass
        import shutil
        shutil.rmtree(temporary_root, ignore_errors=True)


def _item(post: Any, endpoint_id: str, media_store: Any, *, upload_media: bool, media_downloader: Any = None) -> dict[str, Any]:
    has_media = bool(post.media)
    refs = _upload_post_media(post, endpoint_id, media_store, media_downloader) if has_media and upload_media else []
    payload = {"caption_html": post.caption_html, "kind": post.kind.value}
    if has_media and refs:
        payload["media_ref_ids"] = [ref["ref"] for ref in refs]
    return {"provider_event_id": post.publication_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": payload, "media_refs": refs, "blocked_payload": {"caption_html": post.caption_html, "kind": post.kind.value}, "media_required": has_media}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None, media_store: Any = None, media_downloader: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    def fetch(cursor: dict[str, Any] | None, profile: Any, endpoint_id: str) -> dict[str, Any]:
        # RSSHub presents newest first. Keep provider page order and do not
        # decide freshness from the publication timestamp.
        posts = fetch_profile(profile, after_id=None)
        ordered = list(reversed(posts))
        truncated = len(posts) >= profile.max_items_per_poll
        identities = [post.publication_id for post in ordered]
        anchor = cursor.get("anchor") if cursor else None
        if cursor is None or truncated and anchor not in identities:
            upload_ids: set[str] = set()
        else:
            start = identities.index(anchor) + 1 if anchor in identities else 0
            upload_ids = set(identities[start:start + 20])
        items = [_item(post, endpoint_id, media_store, upload_media=post.publication_id in upload_ids, media_downloader=media_downloader) for post in ordered]
        return {"items": items, "truncated": truncated, "contiguous": False}
    fetchers = {endpoint_id: (lambda cursor, profile=by_endpoint[endpoint_id], endpoint_id=endpoint_id: fetch(cursor, profile, endpoint_id)) for endpoint_id in selected}
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "instagram-watch-parser-1")
