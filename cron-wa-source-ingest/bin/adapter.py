"""Read only the existing durable WhatsApp bridge queue for source handoff."""
from __future__ import annotations

import json
import os
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
owner = ROOT / "cron-wa-channel-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-wa-channel-watch" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, bind_catalog_revision, ingest_all, select_endpoints

ALLOWED = {"company_news", "macro_news", "swing_chart_context"}
PUBLISHERS = {"whatsapp:0029VbAjdnb60eBhwVdJxj1c": "bri-danareksa"}
MAX_QUEUE_FILES = 500
MAX_QUEUE_ITEM_BYTES = 1_000_000


def _arrival_position(stamp_ns: int, name: str) -> str:
    return f"{stamp_ns:020d}:{name}"


def bounded_queue(queue_dir: Path, cursor: dict[str, Any] | None, profile: Any) -> dict[str, Any]:
    """Inspect metadata for all files, but parse only a bounded new prefix."""
    if not queue_dir.exists():
        return {"items": [], "truncated": False, "contiguous": True}
    candidates: list[tuple[str, Path, int]] = []
    with os.scandir(queue_dir) as entries:
        for entry in entries:
            if not entry.name.endswith(".json") or not entry.is_file(follow_symlinks=False):
                continue
            details = entry.stat(follow_symlinks=False)
            position = _arrival_position(details.st_mtime_ns, entry.name)
            if cursor is None or cursor["position"] is None or position > cursor["position"]:
                candidates.append((position, Path(entry.path), details.st_size))
    candidates.sort(key=lambda row: row[0])
    if cursor is None:
        # Initial observation records the latest arrival without opening any
        # historical queue payload, even when retention exceeds 500 files.
        return {"items": [], "truncated": False, "contiguous": True, "bootstrap_position": candidates[-1][0] if candidates else None}
    from normalize import deserialize_queue_event
    items: list[dict[str, Any]] = []
    scanned: str | None = None
    for position, path, size in candidates[:MAX_QUEUE_FILES]:
        if size > MAX_QUEUE_ITEM_BYTES:
            raise IntakeBlocked("new WhatsApp queue item exceeds the safe read bound")
        try:
            event = deserialize_queue_event(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise IntakeBlocked("new WhatsApp queue item is invalid") from error
        scanned = position
        if event.channel_jid == profile.channel_jid:
            items.append({**_item(event, profile), "ingest_position": position})
            if len(items) == 20:
                break
    return {"items": items, "truncated": False, "contiguous": True, "scanned_through": scanned}


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


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], queue_dir: Path, state_root: Path, inbox: Any, observed_at: datetime, *, scan_queue: Any = None) -> list[dict[str, Any]]:
    selected, by_endpoint = endpoints(snapshot, profiles)
    bind_catalog_revision(state_root, snapshot["revision"])
    if scan_queue is None:
        scan_queue = bounded_queue
    # The bridge and existing archive retain their own queue and state. This
    # reader never deletes a queue file or marks the old archive delivered.
    fetchers = {}
    for endpoint_id, endpoint in selected.items():
        profile = by_endpoint[endpoint_id]
        def fetch(cursor: dict[str, Any] | None, profile: Any = profile) -> dict[str, Any]:
            return scan_queue(queue_dir, cursor, profile)
        fetchers[endpoint_id] = fetch
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "whatsapp-bridge-queue-1")
