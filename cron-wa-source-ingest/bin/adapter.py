"""Read only the existing durable WhatsApp bridge queue for source handoff."""
from __future__ import annotations

import sys
from itertools import islice
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-wa-channel-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-wa-channel-watch" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, bind_catalog_revision, ingest_all, select_endpoints

ALLOWED = {"company_news", "macro_news", "swing_chart_context"}
PUBLISHERS = {"whatsapp:0029VbAjdnb60eBhwVdJxj1c": "bri-danareksa"}
MAX_QUEUE_FILES = 500


def bounded_queue(queue_dir: Path) -> list[dict[str, Any]]:
    if not queue_dir.exists():
        return []
    if len(list(islice(queue_dir.glob("*.json"), MAX_QUEUE_FILES + 1))) > MAX_QUEUE_FILES:
        raise IntakeBlocked("WhatsApp bridge queue exceeds the safe read bound")
    from event_queue import list_events
    return list_events(queue_dir)


def endpoints(snapshot: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bindings = {}
    by_endpoint = {}
    for profile in profiles:
        if not profile.enabled or profile.is_observing:
            continue
        endpoint_id = f"whatsapp:{profile.channel_url.rstrip('/').rsplit('/', 1)[-1]}"
        if endpoint_id in bindings:
            raise IntakeBlocked("duplicate WhatsApp endpoint")
        publisher_id = PUBLISHERS.get(endpoint_id)
        if publisher_id is None:
            raise IntakeBlocked("WhatsApp forward endpoint has no reviewed publisher binding")
        bindings[endpoint_id] = {"platform": "whatsapp", "publisher_id": publisher_id, "address": profile.channel_url, "provider_id": profile.channel_jid}
        by_endpoint[endpoint_id] = profile
    selected = select_endpoints(snapshot, "whatsapp", bindings, ALLOWED)
    for endpoint_id in bindings:
        if endpoint_id not in selected:
            raise IntakeBlocked("enabled WhatsApp forward profile has no verified subscription")
    return selected, by_endpoint


def _item(event: Any, profile: Any) -> dict[str, Any]:
    return {"provider_event_id": event.message_id, "published_at": event.published_at.isoformat(), "source_url": profile.channel_url, "payload": {"channel_jid": event.channel_jid, "text": event.text, "links": list(event.links)}, "media_required": bool(event.media)}


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], queue_dir: Path, state_root: Path, inbox: Any, observed_at: datetime, *, list_queue: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if list_queue is None:
        list_queue = bounded_queue
    from normalize import deserialize_queue_event
    # The bridge and existing archive retain their own queue and state. This
    # reader never deletes a queue file or marks the old archive delivered.
    queued = list_queue(queue_dir)
    fetchers = {}
    for endpoint_id, endpoint in selected.items():
        profile = by_endpoint[endpoint_id]
        def fetch(_after_id: str | None, profile: Any = profile) -> list[dict[str, Any]]:
            return [_item(deserialize_queue_event(row), profile) for row in queued if row.get("channel_jid") == profile.channel_jid]
        fetchers[endpoint_id] = fetch
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "whatsapp-bridge-queue-1")
