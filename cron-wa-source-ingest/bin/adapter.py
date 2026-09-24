"""Read only the existing durable WhatsApp bridge queue for source handoff."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import stat
import uuid
from datetime import datetime, timezone
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
MAX_MEDIA_OBJECT_BYTES = 8 * 1024 * 1024
MAX_EVENT_MEDIA_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_RECORD_BYTES = 1_000_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_REF_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_MEDIA_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEDIA_TYPES = {
    "image": {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"},
    "video": {"video/mp4", "video/quicktime", "video/webm"},
}
_MEDIA_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


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
    item = {"provider_event_id": event.message_id, "published_at": event.published_at.isoformat(), "source_url": profile.channel_url, "payload": {"channel_jid": event.channel_jid, "text": event.text, "links": list(event.links)}, "media_required": bool(event.media), "media_refs": []}
    if event.media:
        # This in-memory handoff contains only queue metadata. The queue's path
        # points at disposable staging and must never be used as a byte source.
        item["_source_media"] = [
            {"index": media.index, "kind": media.kind, "mime": media.mime}
            for media in event.media
        ]
    return item


def _read_regular_file(path: Path, maximum: int) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or not 1 <= details.st_size <= maximum:
            raise ValueError("file is not a bounded regular file")
        chunks = bytearray()
        while len(chunks) <= maximum:
            part = os.read(descriptor, min(64 * 1024, maximum + 1 - len(chunks)))
            if not part:
                break
            chunks.extend(part)
        if len(chunks) != details.st_size or len(chunks) > maximum:
            raise ValueError("file size changed while reading")
        return bytes(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _archive_path(root: Path, relative: str, maximum: int) -> tuple[Path, bytes]:
    """Read one archive file without following symlinks or exceeding its bound."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("archive root is unavailable")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("archive path is invalid")
    candidate = root
    for index, part in enumerate(Path(relative).parts):
        if part in {"", ".", ".."}:
            raise ValueError("archive path is invalid")
        candidate = candidate / part
        details = candidate.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise ValueError("archive path contains a symlink")
        if index < len(Path(relative).parts) - 1 and not stat.S_ISDIR(details.st_mode):
            raise ValueError("archive path parent is not a directory")
    if not candidate.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("archive path escaped its root")
    return candidate, _read_regular_file(candidate, maximum)


def _content_type(kind: str, mime: Any) -> str:
    if type(mime) is not str:
        raise ValueError("media MIME is unavailable")
    normalized = "image/jpeg" if mime.casefold() == "image/jpg" else mime.casefold()
    if normalized not in _MEDIA_TYPES.get(kind, set()):
        raise ValueError("media MIME is unsupported")
    return normalized


def _validate_uploaded_ref(value: Any, *, data: bytes, kind: str, content_type: str, filename: str) -> dict[str, Any]:
    required = {"ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("Source Media Owner metadata is invalid")
    ref = value["ref"]
    try:
        parsed_uuid = uuid.UUID(ref) if type(ref) is str else None
    except (ValueError, AttributeError):
        parsed_uuid = None
    if (
        type(ref) is not str
        or not _MEDIA_REF_RE.fullmatch(ref)
        or parsed_uuid is None
        or str(parsed_uuid) != ref
        or type(value["sha256"]) is not str
        or not _SHA256_RE.fullmatch(value["sha256"])
        or value["sha256"] != hashlib.sha256(data).hexdigest()
        or value["kind"] != kind
        or value["content_type"] != content_type
        or type(value["size_bytes"]) is not int
        or value["size_bytes"] != len(data)
        or type(value["filename"]) is not str
        or not _MEDIA_FILENAME_RE.fullmatch(value["filename"])
        or value["filename"] != filename
        or value["durable"] is not True
    ):
        raise ValueError("Source Media Owner metadata is invalid")
    return value


def _upload_archive_media(item: dict[str, Any], profile: Any, archive_root: Path | None, media_store: Any) -> list[dict[str, Any]] | None:
    """Return complete durable refs, or None so the core holds this event."""
    descriptors = item.get("_source_media")
    if type(descriptors) is not list or not descriptors or len(descriptors) > 16 or archive_root is None or media_store is None:
        return None
    try:
        import archive

        provider_id = item.get("provider_event_id")
        if type(provider_id) is not str or not provider_id:
            raise ValueError("WhatsApp media identity is invalid")
        event_key = f"{profile.channel_jid}:{provider_id}"
        record_path = archive.record_path(
            archive_root,
            {"profile_id": profile.id, "published_at": item["published_at"], "event_key": event_key},
        )
        relative_record = record_path.relative_to(archive_root).as_posix()
        _record_path, record_bytes = _archive_path(archive_root, relative_record, MAX_ARCHIVE_RECORD_BYTES)
        record = archive.validate_record(json.loads(record_bytes.decode("utf-8")), path=record_path)
        expected_payload = item.get("payload")
        queue_published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        archive_published = datetime.fromisoformat(str(record["published_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        if (
            record["profile_id"] != profile.id
            or record["channel_jid"] != profile.channel_jid
            or record["message_id"] != provider_id
            or record["event_key"] != event_key
            or archive_published != queue_published
            or record["text"] != expected_payload.get("text")
            or record["links"] != expected_payload.get("links")
        ):
            raise ValueError("WhatsApp archive identity does not match the queue")
        archived = record["media"]
        if type(archived) is not list or len(archived) != len(descriptors):
            raise ValueError("WhatsApp archive media set is incomplete")
        refs: list[dict[str, Any]] = []
        total = 0
        for descriptor, metadata in zip(descriptors, archived, strict=True):
            if (
                type(descriptor) is not dict
                or type(metadata) is not dict
                or type(descriptor.get("index")) is not int
                or descriptor.get("index") != metadata.get("index")
                or descriptor.get("kind") != metadata.get("kind")
                or descriptor.get("mime") != metadata.get("mime")
                or metadata.get("capture_status") != "captured"
            ):
                raise ValueError("WhatsApp archive media metadata is incomplete")
            kind = descriptor["kind"]
            content_type = _content_type(kind, descriptor.get("mime"))
            digest = metadata.get("sha256")
            size = metadata.get("bytes")
            archive_relative = metadata.get("archive_path")
            if type(digest) is not str or not _SHA256_RE.fullmatch(digest) or type(size) is not int or not 1 <= size <= MAX_MEDIA_OBJECT_BYTES or archive_relative != f"media/{digest}":
                raise ValueError("WhatsApp archive media bounds are invalid")
            total += size
            if total > MAX_EVENT_MEDIA_BYTES:
                raise ValueError("WhatsApp media exceeds the aggregate bound")
            _media_path, data = _archive_path(archive_root, archive_relative, MAX_MEDIA_OBJECT_BYTES)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("WhatsApp archive media checksum is invalid")
            filename = f"whatsapp-media-{descriptor['index']}.{_MEDIA_EXTENSIONS[content_type]}"
            response = media_store.upload(
                f"whatsapp:{profile.channel_url.rstrip('/').rsplit('/', 1)[-1]}:{provider_id}:attachment:{descriptor['index']}",
                data,
                kind=kind,
                content_type=content_type,
                filename=filename,
            )
            refs.append(_validate_uploaded_ref(response, data=data, kind=kind, content_type=content_type, filename=filename))
        return refs
    except Exception:
        # Do not leak provider text, local paths, or owner-service responses.
        # The empty result is handed to source-ingest, which persists a safe
        # blocked-media marker and leaves this queue event unacknowledged.
        return None


def run_once(snapshot: dict[str, Any], profiles: tuple[Any, ...], queue_dir: Path, state_root: Path, inbox: Any, observed_at: datetime, *, scan_queue: Any = None, archive_root: Path | None = None, media_store: Any = None) -> list[dict[str, Any]]:
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
            page = scan_queue(queue_dir, cursor, profile)
            if type(page) is not dict or type(page.get("items")) is not list:
                return page
            prepared_items = []
            for item in page["items"]:
                prepared = dict(item)
                descriptors = prepared.pop("_source_media", None)
                if descriptors is not None:
                    prepared["media_refs"] = _upload_archive_media(prepared | {"_source_media": descriptors}, profile, archive_root, media_store) or []
                    if prepared["media_refs"]:
                        payload = dict(prepared.get("payload", {}))
                        payload["media_ref_ids"] = [reference["ref"] for reference in prepared["media_refs"]]
                        prepared["payload"] = payload
                prepared_items.append(prepared)
            return {**page, "items": prepared_items}
        fetchers[endpoint_id] = fetch
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "whatsapp-bridge-queue-1")
