"""Bounded Instagram source adapter; media stays pending at its cursor."""
from __future__ import annotations

import sys
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


def _item(post: Any) -> dict[str, Any]:
    # Signed CDN URLs and local download paths never enter the inbox payload.
    return {"provider_event_id": post.publication_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": {"caption_html": post.caption_html, "kind": post.kind.value}, "media_required": bool(post.media)}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    fetchers = {endpoint_id: (lambda after_id, profile=by_endpoint[endpoint_id]: [_item(post) for post in fetch_profile(profile, after_id=after_id)]) for endpoint_id in selected}
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "instagram-watch-parser-1")
