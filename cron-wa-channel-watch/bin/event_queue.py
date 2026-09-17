from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from models import ChannelEvent


def event_filename(event: ChannelEvent) -> str:
    digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
    return f"{digest}.json"


def serialize_event(event: ChannelEvent) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_key": event.event_key,
        "channel_jid": event.channel_jid,
        "message_id": event.message_id,
        "published_at": event.published_at.isoformat(),
        "text": event.text,
        "links": list(event.links),
        "media": [
            {
                "kind": media.kind,
                "index": media.index,
                "mime": media.mime,
                "path": media.path,
            }
            for media in event.media
        ],
        "received_at": event.received_at.isoformat(),
    }


def enqueue(queue_dir: Path, event: ChannelEvent) -> bool:
    """Persist one event. Return False when the exact event already exists."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(queue_dir, 0o700)
    target = queue_dir / event_filename(event)
    payload = json.dumps(serialize_event(event), ensure_ascii=False, sort_keys=True)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == payload:
            return False
        raise ValueError("event-key collision in Channel queue")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".event-", suffix=".tmp", dir=queue_dir)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True


def list_events(queue_dir: Path) -> list[dict[str, object]]:
    if not queue_dir.exists():
        return []
    events: list[dict[str, object]] = []
    for path in sorted(queue_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if type(payload) is not dict or payload.get("schema_version") != 1:
            raise ValueError(f"invalid queue event: {path.name}")
        payload["_path"] = str(path)
        events.append(payload)
    return sorted(events, key=lambda item: (str(item.get("published_at", "")), str(item.get("event_key", ""))))
