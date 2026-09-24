"""Bounded X source adapter; existing X owner retains analysis and delivery."""
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


def _item(post: Any) -> dict[str, Any]:
    from state import serialize_post
    from scan import source_visible_text
    return {"provider_event_id": post.post_id, "published_at": post.published_at.isoformat(), "source_url": post.url, "payload": {"post": serialize_post(post)}, "blocked_payload": {"profile_id": post.profile_id, "kind": post.kind.value, "source_text": source_visible_text(post.content_html), "quoted_text": source_visible_text(post.quoted_content_html or "")}, "media_required": bool(post.media or post.quoted_media)}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], state_root: Path, inbox: Any, observed_at: datetime, *, fetch_profile: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if fetch_profile is None:
        from rsshub import fetch_profile_items
        fetch_profile = fetch_profile_items
    fetchers = {endpoint_id: (lambda after_id, profile=by_endpoint[endpoint_id]: [_item(post) for post in fetch_profile(profile, after_id=after_id)]) for endpoint_id in selected}
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "x-watch-parser-1")
