from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import tempfile
from typing import Iterable

from models import ChannelEvent


ARCHIVE_SCHEMA_VERSION = 1
MAX_ARCHIVE_MEDIA_BYTES = 25 * 1024 * 1024
MINIMUM_RETENTION_DAYS = 365
QUARANTINE_ACTIVE_PHASES = {"pending", "awaiting_agent", "ready"}
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_RECORD_KEYS = {
    "schema_version",
    "event_key",
    "profile_id",
    "channel_jid",
    "message_id",
    "published_at",
    "received_at",
    "text",
    "links",
    "media",
    "config_revision",
    "checksum",
}
_MEDIA_KEYS = {"kind", "index", "mime", "capture_status", "archive_path", "sha256", "bytes"}
_MEDIA_CAPTURE_STATUSES = {"not_captured", "captured", "unavailable"}


@dataclass(frozen=True)
class ArchiveResult:
    created: bool
    record_path: Path


@dataclass(frozen=True)
class ArchiveRecord:
    record_path: Path
    data: dict[str, object]

    @property
    def event_key(self) -> str:
        return str(self.data["event_key"])

    @property
    def profile_id(self) -> str:
        return str(self.data["profile_id"])

    @property
    def published_at(self) -> datetime:
        return _parse_timestamp(self.data["published_at"], "published_at")


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _utc_timestamp(value: datetime, label: str) -> str:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _checksum(record: dict[str, object]) -> str:
    body = {key: value for key, value in record.items() if key != "checksum"}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def event_filename(event_key: str) -> str:
    return f"{hashlib.sha256(event_key.encode('utf-8')).hexdigest()}.json"


def _validate_profile_id(profile_id: str) -> None:
    if not _PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError("profile ID is invalid")


def _uncaptured_media_item(media) -> dict[str, object]:
    return {
        "kind": media.kind,
        "index": media.index,
        "mime": media.mime,
        "capture_status": "not_captured",
        "archive_path": None,
        "sha256": None,
        "bytes": None,
    }


def _write_media(root: Path, digest: str, content: bytes) -> Path:
    media_dir = root / "media"
    _private_directory(media_dir)
    target = media_dir / digest
    if target.exists():
        if not target.is_symlink() and target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            return target
        raise ValueError("archive media collision")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".media-", suffix=".tmp", dir=media_dir)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_name, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("archive media collision")
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target


def _captured_media_item(root: Path, media, staging_root: Path | None) -> dict[str, object]:
    item = _uncaptured_media_item(media)
    if not media.path:
        return item
    if staging_root is None:
        return item
    if not staging_root.is_absolute():
        item["capture_status"] = "unavailable"
        return item
    try:
        source = Path(media.path)
        if not source.is_absolute() or source.is_symlink() or not source.is_file():
            raise ValueError("source media is not a safe regular file")
        staging = staging_root.resolve(strict=True)
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(staging):
            raise ValueError("source media is outside staging")
        content = resolved.read_bytes()
        if len(content) > MAX_ARCHIVE_MEDIA_BYTES:
            raise ValueError("source media exceeds archive size limit")
        digest = hashlib.sha256(content).hexdigest()
        _write_media(root, digest, content)
    except (OSError, ValueError):
        item["capture_status"] = "unavailable"
        return item
    item.update(
        {
            "capture_status": "captured",
            "archive_path": f"media/{digest}",
            "sha256": digest,
            "bytes": len(content),
        }
    )
    return item


def _media_record(
    root: Path,
    event: ChannelEvent,
    *,
    staging_root: Path | None = None,
) -> list[dict[str, object]]:
    return [_captured_media_item(root, media, staging_root) for media in event.media]


def build_record(
    profile_id: str,
    event: ChannelEvent,
    config_revision: int | None,
    *,
    media: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a source-only record without retaining untrusted media paths."""
    _validate_profile_id(profile_id)
    if config_revision is not None and (type(config_revision) is not int or config_revision < 0):
        raise ValueError("config revision must be a non-negative integer or null")
    record: dict[str, object] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "event_key": event.event_key,
        "profile_id": profile_id,
        "channel_jid": event.channel_jid,
        "message_id": event.message_id,
        "published_at": _utc_timestamp(event.published_at, "published_at"),
        "received_at": _utc_timestamp(event.received_at, "received_at"),
        "text": event.text,
        "links": list(event.links),
        "media": media if media is not None else [_uncaptured_media_item(item) for item in event.media],
        "config_revision": config_revision,
    }
    record["checksum"] = _checksum(record)
    return record


def record_path(root: Path, record: dict[str, object]) -> Path:
    profile_id = record.get("profile_id")
    if not isinstance(profile_id, str):
        raise ValueError("record profile ID is invalid")
    _validate_profile_id(profile_id)
    published_at = _parse_timestamp(record.get("published_at"), "published_at")
    event_key = record.get("event_key")
    if not isinstance(event_key, str) or not event_key:
        raise ValueError("record event key is invalid")
    return root / profile_id / published_at.strftime("%Y") / published_at.strftime("%m") / published_at.strftime("%d") / event_filename(event_key)


def _same_source(existing: dict[str, object], candidate: dict[str, object]) -> bool:
    if any(existing.get(key) != candidate.get(key) for key in ("event_key", "profile_id", "channel_jid", "message_id", "text", "links")):
        return False
    try:
        if _parse_timestamp(existing["published_at"], "published_at") != _parse_timestamp(candidate["published_at"], "published_at"):
            return False
    except ValueError:
        return False
    existing_media = existing.get("media")
    candidate_media = candidate.get("media")
    if type(existing_media) is not list or type(candidate_media) is not list or len(existing_media) != len(candidate_media):
        return False
    return all(
        type(left) is dict
        and type(right) is dict
        and all(left.get(key) == right.get(key) for key in ("kind", "index", "mime"))
        for left, right in zip(existing_media, candidate_media)
    )


def _existing_matches(target: Path, candidate: dict[str, object], archive_root: Path) -> bool:
    try:
        existing = _load_record(target, archive_root=archive_root).data
    except ValueError:
        return False
    return _same_source(existing, candidate)


def _capture_upgrade(existing: dict[str, object], candidate: dict[str, object]) -> dict[str, object] | None:
    if not _same_source(existing, candidate):
        return None
    current_media = existing.get("media")
    candidate_media = candidate.get("media")
    if type(current_media) is not list or type(candidate_media) is not list:
        return None
    replacement = json.loads(json.dumps(existing))
    changed = False
    for index, proposed in enumerate(candidate_media):
        current = current_media[index]
        if (
            type(current) is dict
            and type(proposed) is dict
            and current.get("capture_status") != "captured"
            and proposed.get("capture_status") == "captured"
        ):
            replacement["media"][index] = proposed
            changed = True
    if not changed:
        return None
    replacement["checksum"] = _checksum(replacement)
    return replacement


def _replace_record(target: Path, record: dict[str, object]) -> None:
    payload = _canonical_json(record)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".record-", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _write_atomic_or_compare(target: Path, record: dict[str, object], archive_root: Path) -> bool:
    payload = _canonical_json(record)
    _private_directory(target.parent)
    if target.exists():
        if target.read_bytes() == payload:
            return False
        try:
            existing = _load_record(target, archive_root=archive_root).data
        except ValueError:
            existing = None
        if existing is not None and _same_source(existing, record):
            upgrade = _capture_upgrade(existing, record)
            if upgrade is not None:
                _replace_record(target, upgrade)
            return False
        raise ValueError("archive event-key collision")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".record-", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_name, target)
        except FileExistsError:
            if target.read_bytes() == payload:
                return False
            try:
                existing = _load_record(target, archive_root=archive_root).data
            except ValueError:
                existing = None
            if existing is not None and _same_source(existing, record):
                upgrade = _capture_upgrade(existing, record)
                if upgrade is not None:
                    _replace_record(target, upgrade)
                return False
            raise ValueError("archive event-key collision")
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        os.chmod(target, 0o600)
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True


def ensure(
    root: Path,
    profile_id: str,
    event: ChannelEvent,
    config_revision: int | None,
    *,
    staging_root: Path | None = None,
) -> ArchiveResult:
    """Persist one immutable raw-source record, or verify its exact prior copy."""
    root = Path(root)
    _private_directory(root)
    record = build_record(
        profile_id,
        event,
        config_revision,
        media=_media_record(root, event, staging_root=staging_root),
    )
    target = record_path(root, record)
    return ArchiveResult(created=_write_atomic_or_compare(target, record, root), record_path=target)


def _validate_media(value: object) -> None:
    if type(value) is not list:
        raise ValueError("record media is invalid")
    seen_indexes: set[int] = set()
    for item in value:
        if type(item) is not dict or set(item) != _MEDIA_KEYS:
            raise ValueError("record media item is invalid")
        if item["kind"] not in {"image", "video"} or type(item["index"]) is not int or item["index"] < 0:
            raise ValueError("record media item is invalid")
        if item["index"] in seen_indexes:
            raise ValueError("record media indexes must be unique")
        seen_indexes.add(item["index"])
        if item["mime"] is not None and type(item["mime"]) is not str:
            raise ValueError("record media MIME is invalid")
        status = item["capture_status"]
        if status not in _MEDIA_CAPTURE_STATUSES:
            raise ValueError("record media capture status is invalid")
        archive_path, digest, size = item["archive_path"], item["sha256"], item["bytes"]
        if status == "captured":
            if not isinstance(archive_path, str) or not _CHECKSUM_RE.fullmatch(str(digest)) or type(size) is not int or size < 0:
                raise ValueError("captured media record is incomplete")
        elif archive_path is not None or digest is not None or size is not None:
            raise ValueError("uncaptured media record must not contain media references")


def _verify_captured_media(root: Path, media: object) -> None:
    if type(media) is not list:
        raise ValueError("record media is invalid")
    for item in media:
        if type(item) is not dict or item.get("capture_status") != "captured":
            continue
        archive_path = item["archive_path"]
        digest = item["sha256"]
        size = item["bytes"]
        relative = PurePosixPath(str(archive_path))
        if relative.is_absolute() or relative.parts != ("media", str(digest)):
            raise ValueError("captured media archive path is invalid")
        media_path = root.joinpath(*relative.parts)
        try:
            stat_result = media_path.lstat()
        except OSError as exc:
            raise ValueError("captured media is unavailable") from exc
        if not media_path.is_file() or media_path.is_symlink() or stat_result.st_size != size:
            raise ValueError("captured media is invalid")
        digest_value = hashlib.sha256(media_path.read_bytes()).hexdigest()
        if digest_value != digest:
            raise ValueError("captured media checksum mismatch")


def validate_record(
    value: object,
    *,
    path: Path | None = None,
    archive_root: Path | None = None,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != _RECORD_KEYS:
        raise ValueError("archive record has unexpected or missing fields")
    if value["schema_version"] != ARCHIVE_SCHEMA_VERSION:
        raise ValueError("archive record schema version is invalid")
    profile_id = value["profile_id"]
    if not isinstance(profile_id, str):
        raise ValueError("record profile ID is invalid")
    _validate_profile_id(profile_id)
    event_key = value["event_key"]
    channel_jid, message_id = value["channel_jid"], value["message_id"]
    if not all(isinstance(item, str) and item for item in (event_key, channel_jid, message_id)):
        raise ValueError("record Channel identity is invalid")
    if event_key != f"{channel_jid}:{message_id}":
        raise ValueError("record event key does not match Channel identity")
    published_at = _parse_timestamp(value["published_at"], "published_at")
    _parse_timestamp(value["received_at"], "received_at")
    if type(value["text"]) is not str or type(value["links"]) is not list or not all(isinstance(link, str) for link in value["links"]):
        raise ValueError("record source content is invalid")
    _validate_media(value["media"])
    revision = value["config_revision"]
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError("record config revision is invalid")
    checksum = value["checksum"]
    if not isinstance(checksum, str) or not _CHECKSUM_RE.fullmatch(checksum) or checksum != _checksum(value):
        raise ValueError("archive record checksum mismatch")
    if path is not None:
        if path.name != event_filename(event_key):
            raise ValueError("archive record filename does not match event key")
        if path.parts[-5:-1] != (profile_id, published_at.strftime("%Y"), published_at.strftime("%m"), published_at.strftime("%d")):
            raise ValueError("archive record path does not match source date")
    if archive_root is not None:
        _verify_captured_media(archive_root, value["media"])
    return value


def _load_record(path: Path, *, archive_root: Path | None = None) -> ArchiveRecord:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read archive record: {path.name}") from exc
    return ArchiveRecord(record_path=path, data=validate_record(raw, path=path, archive_root=archive_root))


def _iter_paths(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    records: list[Path] = []
    for profile_dir in root.iterdir():
        if profile_dir.name in {"cutovers", "media"}:
            continue
        if not profile_dir.is_dir() or not _PROFILE_ID_RE.fullmatch(profile_dir.name):
            continue
        records.extend(path for path in profile_dir.rglob("*.json") if path.is_file())
    return sorted(records)


def verify(root: Path) -> dict[str, int]:
    result = {"checked": 0, "valid": 0, "invalid": 0}
    for path in _iter_paths(Path(root)):
        result["checked"] += 1
        try:
            _load_record(path, archive_root=Path(root))
        except ValueError:
            result["invalid"] += 1
        else:
            result["valid"] += 1
    return result


def _date_bound(value: date | datetime | None, label: str) -> date | None:
    if value is None:
        return None
    if type(value) is datetime:
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if type(value) is date:
        return value
    raise ValueError(f"{label} must be a date or datetime")


def layout_signature_for_text(text: str) -> str:
    """Return a stable structural signature for archive review filters.

    The signature deliberately describes the message layout, rather than its
    market-specific words or numbers, so it can group recurring Channel
    templates without exposing another copy of raw source text.
    """
    if not isinstance(text, str):
        raise ValueError("source text must be a string")
    shapes: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value:
            shapes.append("blank")
        elif re.match(r"^(?:[-*•]|\d+[.)])\s+", value):
            shapes.append("bullet")
        elif value.startswith("#"):
            shapes.append("tag")
        elif re.fullmatch(r"[*_`]+.+[*_`]+", value):
            shapes.append("emphasized")
        elif re.fullmatch(r"https?://\S+", value, re.IGNORECASE):
            shapes.append("link")
        else:
            shapes.append("paragraph")
    return hashlib.sha256("\n".join(shapes).encode("utf-8")).hexdigest()


def query(
    root: Path,
    *,
    profile_id: str | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    event_key: str | None = None,
    layout_signature: str | None = None,
    limit: int = 500,
) -> list[ArchiveRecord]:
    if profile_id is not None:
        _validate_profile_id(profile_id)
    start_date, end_date = _date_bound(start, "start"), _date_bound(end, "end")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start must not be after end")
    if layout_signature is not None and not _CHECKSUM_RE.fullmatch(layout_signature):
        raise ValueError("layout signature is invalid")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("query limit must be between 1 and 500")
    records: list[ArchiveRecord] = []
    for path in _iter_paths(Path(root)):
        record = _load_record(path, archive_root=Path(root))
        if profile_id is not None and record.profile_id != profile_id:
            continue
        if event_key is not None and record.event_key != event_key:
            continue
        if layout_signature is not None and layout_signature_for_text(str(record.data["text"])) != layout_signature:
            continue
        record_date = record.published_at.date()
        if start_date is not None and record_date < start_date:
            continue
        if end_date is not None and record_date > end_date:
            continue
        records.append(record)
    return sorted(records, key=lambda item: (item.published_at, item.event_key))[:limit]


def _private_export(output: Path, payload: bytes) -> None:
    if output.exists():
        raise ValueError("archive export output already exists")
    if not output.parent.exists() or not output.parent.is_dir():
        raise ValueError("archive export parent directory does not exist")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise
    os.chmod(output, 0o600)


def _markdown(records: list[ArchiveRecord]) -> bytes:
    sections = [
        "\n".join(
            (
                f"## {record.event_key}",
                f"- Profile: {record.profile_id}",
                f"- Published: {record.data['published_at']}",
                "",
                str(record.data["text"]),
            )
        )
        for record in records
    ]
    return ("\n\n".join(sections) + ("\n" if sections else "")).encode("utf-8")


def export(
    root: Path,
    *,
    profile_id: str | None,
    output: Path,
    format: str,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    event_key: str | None = None,
    layout_signature: str | None = None,
    limit: int = 500,
) -> dict[str, int]:
    if format not in {"jsonl", "markdown"}:
        raise ValueError("archive export format must be jsonl or markdown")
    records = query(
        root,
        profile_id=profile_id,
        start=start,
        end=end,
        event_key=event_key,
        layout_signature=layout_signature,
        limit=limit,
    )
    if format == "jsonl":
        payload = b"".join(_canonical_json(record.data) for record in records)
    else:
        payload = _markdown(records)
    _private_export(Path(output), payload)
    return {"exported": len(records)}


def _referenced_media_paths(root: Path, *, excluded_records: set[Path] | None = None) -> set[str]:
    references: set[str] = set()
    excluded = excluded_records or set()
    for path in _iter_paths(root):
        record = _load_record(path, archive_root=root)
        if record.record_path in excluded:
            continue
        media = record.data["media"]
        if not isinstance(media, list):  # validate_record already guarantees this.
            continue
        for item in media:
            if type(item) is dict and item.get("capture_status") == "captured":
                archive_path = item.get("archive_path")
                if isinstance(archive_path, str):
                    references.add(archive_path)
    return references


def _orphaned_media_paths(root: Path, *, excluded_records: set[Path] | None = None) -> list[Path]:
    media_root = root / "media"
    if not media_root.exists():
        return []
    if not media_root.is_dir() or media_root.is_symlink():
        raise ValueError("archive media root is invalid")
    references = _referenced_media_paths(root, excluded_records=excluded_records)
    return [
        item
        for item in media_root.iterdir()
        if not item.is_symlink()
        and item.is_file()
        and _CHECKSUM_RE.fullmatch(item.name)
        and f"media/{item.name}" not in references
    ]


def prune(
    root: Path,
    *,
    before: date,
    apply: bool = False,
    today: date | None = None,
) -> dict[str, int]:
    if type(before) is not date or type(before) is datetime:
        raise ValueError("prune before must be a date")
    current_day = today or date.today()
    if type(current_day) is not date or type(current_day) is datetime:
        raise ValueError("prune today must be a date")
    if before > current_day - timedelta(days=MINIMUM_RETENTION_DAYS):
        raise ValueError(f"archive retention requires at least {MINIMUM_RETENTION_DAYS} days")
    root = Path(root)
    candidates = [record for record in query(root) if record.published_at.date() < before]
    candidate_paths = {record.record_path for record in candidates}
    orphaned_media = _orphaned_media_paths(root, excluded_records=candidate_paths)
    if not apply:
        return {"candidates": len(candidates), "deleted": 0, "media_candidates": len(orphaned_media), "media_deleted": 0}
    if not root.is_absolute():
        raise ValueError("archive root must be absolute for prune --apply")
    for record in candidates:
        record.record_path.unlink()
    orphaned_media = _orphaned_media_paths(root)
    for media_path in orphaned_media:
        media_path.unlink()
    return {
        "candidates": len(candidates),
        "deleted": len(candidates),
        "media_candidates": len(orphaned_media),
        "media_deleted": len(orphaned_media),
    }


def _cutover_events(queue_dir: Path, channel_jid: str) -> list[ChannelEvent]:
    from event_queue import list_events
    from normalize import deserialize_queue_event

    events: list[ChannelEvent] = []
    for item in list_events(queue_dir):
        if item.get("channel_jid") == channel_jid:
            events.append(deserialize_queue_event(item))
    return sorted(events, key=lambda event: (_utc_timestamp(event.published_at, "published_at"), event.event_key))


def _cursor_for(event: ChannelEvent) -> dict[str, str]:
    return {"published_at": _utc_timestamp(event.published_at, "published_at"), "event_key": event.event_key}


def cutover_plan(
    queue_dir: Path,
    state_path: Path,
    *,
    profile_id: str,
    channel_jid: str,
) -> dict[str, object]:
    """Inventory an existing queue without changing the archive, queue, or state."""
    from state import load as load_state

    _validate_profile_id(profile_id)
    events = _cutover_events(Path(queue_dir), channel_jid)
    current_state = load_state(Path(state_path))
    existing_outbox_count = sum(
        1
        for record in current_state["outbox"]
        if isinstance(record, dict) and record.get("profile_id") == profile_id
    )
    return {
        "profile_id": profile_id,
        "channel_jid": channel_jid,
        "event_count": len(events),
        "earliest": _cursor_for(events[0]) if events else None,
        "latest": _cursor_for(events[-1]) if events else None,
        "existing_outbox_count": existing_outbox_count,
        "proposed_cursor": _cursor_for(events[-1]) if events else None,
    }


def _write_private_new(path: Path, payload: bytes) -> None:
    _private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError as exc:
            raise ValueError(f"cutover artifact already exists: {path.name}") from exc
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    os.chmod(path, 0o600)


def cutover_apply(
    root: Path,
    queue_dir: Path,
    state_path: Path,
    *,
    profile_id: str,
    channel_jid: str,
    config_revision: int | None = None,
) -> dict[str, object]:
    """Archive a reviewed baseline and set only the future-only cursor."""
    from state import load as load_state
    from state import save as save_state

    root = Path(root)
    if not root.is_absolute():
        raise ValueError("archive root must be absolute for cutover apply")
    if os.environ.get("WHATSAPP_CHANNEL_WATCH_ALLOW_CUTOVER_APPLY") != "1":
        raise PermissionError("cutover apply requires WHATSAPP_CHANNEL_WATCH_ALLOW_CUTOVER_APPLY=1")
    plan = cutover_plan(queue_dir, state_path, profile_id=profile_id, channel_jid=channel_jid)
    events = _cutover_events(Path(queue_dir), channel_jid)
    _private_directory(root)
    cutover_dir = root / "cutovers" / profile_id
    original_state = Path(state_path).read_bytes() if Path(state_path).exists() else _canonical_json(load_state(Path(state_path)))
    _write_private_new(cutover_dir / "state-before.json", original_state)
    archived = 0
    for event in events:
        ensure(root, profile_id, event, config_revision)
        archived += 1
    current_state = load_state(Path(state_path))
    if plan["proposed_cursor"] is not None:
        profile_state = current_state["profiles"].setdefault(profile_id, {})  # type: ignore[union-attr]
        if type(profile_state) is not dict:
            raise ValueError("profile state is invalid")
        profile_state["cursor"] = plan["proposed_cursor"]
        profile_state["initialized"] = True
        profile_state["cutover_complete"] = True
    save_state(Path(state_path), current_state)
    manifest = {
        "schema_version": 1,
        "profile_id": profile_id,
        "channel_jid": channel_jid,
        "event_count": plan["event_count"],
        "existing_outbox_count": plan["existing_outbox_count"],
        "proposed_cursor": plan["proposed_cursor"],
        "queue_preserved": True,
        "state_backup": "state-before.json",
    }
    _write_private_new(cutover_dir / "manifest.json", _canonical_json(manifest))
    return {
        "archived": archived,
        "proposed_cursor": plan["proposed_cursor"],
        "existing_outbox_count": plan["existing_outbox_count"],
    }


def _quarantine_candidates(
    current_state: dict[str, object],
    *,
    profile_id: str,
    channel_jid: str,
    cutoff: dict[str, object],
) -> list[dict[str, object]]:
    from state import cursor_key

    cutoff_key = cursor_key(cutoff)
    candidates: list[dict[str, object]] = []
    for record in current_state["outbox"]:  # type: ignore[union-attr]
        if type(record) is not dict:
            continue
        if record.get("profile_id") != profile_id or record.get("routable") is not True:
            continue
        if record.get("agent_phase") not in QUARANTINE_ACTIVE_PHASES:
            continue
        event = record.get("event")
        if type(event) is not dict or event.get("channel_jid") != channel_jid:
            continue
        try:
            event_key = cursor_key(event)
        except (KeyError, TypeError, ValueError):
            continue
        if event_key <= cutoff_key:
            candidates.append(record)
    return candidates


def quarantine_outbox(
    root: Path,
    state_path: Path,
    *,
    profile_id: str,
    channel_jid: str,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    """Preserve, then disable stale pre-cutover forwarding work.

    The operation never deletes outbox records or source archives. It only
    changes selected active records' routability after a private state backup.
    """
    from state import cursor_key, load as load_state, save as save_state

    _validate_profile_id(profile_id)
    root = Path(root)
    state_path = Path(state_path)
    current_state = load_state(state_path)
    profile_state = current_state["profiles"].get(profile_id)  # type: ignore[union-attr]
    if type(profile_state) is not dict or profile_state.get("cutover_complete") is not True:
        raise ValueError("outbox quarantine requires a completed profile cutover")
    cutoff = profile_state.get("cursor")
    if type(cutoff) is not dict or not {"published_at", "event_key"}.issubset(cutoff):
        raise ValueError("outbox quarantine requires a valid cutover cursor")
    cursor_key(cutoff)
    candidates = _quarantine_candidates(
        current_state,
        profile_id=profile_id,
        channel_jid=channel_jid,
        cutoff=cutoff,
    )
    event_keys = [str(record["event_key"]) for record in candidates]
    result: dict[str, object] = {
        "profile_id": profile_id,
        "channel_jid": channel_jid,
        "cutover_cursor": cutoff,
        "candidate_count": len(candidates),
        "event_keys": event_keys,
        "applied": False,
    }
    if not apply:
        return result
    if not root.is_absolute() or not state_path.is_absolute():
        raise ValueError("outbox quarantine requires absolute archive and state paths")
    if os.environ.get("WHATSAPP_CHANNEL_WATCH_ALLOW_OUTBOX_QUARANTINE") != "1":
        raise PermissionError("outbox quarantine requires WHATSAPP_CHANNEL_WATCH_ALLOW_OUTBOX_QUARANTINE=1")
    if not candidates:
        result["applied"] = True
        result["quarantined"] = 0
        return result

    applied_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = applied_at.strftime("%Y%m%dT%H%M%SZ")
    quarantine_dir = root / "quarantines" / profile_id / stamp
    _private_directory(root)
    if quarantine_dir.exists():
        raise ValueError(f"outbox quarantine artifact already exists: {quarantine_dir}")
    _private_directory(quarantine_dir)
    original_state = copy.deepcopy(current_state)
    _write_private_new(quarantine_dir / "state-before.json", _canonical_json(original_state))
    updated_state = copy.deepcopy(current_state)
    updated_candidates = _quarantine_candidates(
        updated_state,
        profile_id=profile_id,
        channel_jid=channel_jid,
        cutoff=cutoff,
    )
    for record in updated_candidates:
        record["routable"] = False
        record["quarantine"] = {
            "reason": "pre-cutover-outbox",
            "cutover_cursor": cutoff,
            "quarantined_at": applied_at.isoformat().replace("+00:00", "Z"),
        }
    try:
        save_state(state_path, updated_state)
        manifest = {
            "schema_version": 1,
            "operation": "outbox-quarantine",
            "profile_id": profile_id,
            "channel_jid": channel_jid,
            "cutover_cursor": cutoff,
            "quarantined_count": len(updated_candidates),
            "event_keys": [str(record["event_key"]) for record in updated_candidates],
            "state_backup": "state-before.json",
            "archive_preserved": True,
            "queue_preserved": True,
            "applied_at": applied_at.isoformat().replace("+00:00", "Z"),
        }
        _write_private_new(quarantine_dir / "manifest.json", _canonical_json(manifest))
    except Exception:
        save_state(state_path, original_state)
        raise
    result.update(
        {
            "applied": True,
            "quarantined": len(updated_candidates),
            "backup_dir": str(quarantine_dir),
        }
    )
    return result


def _default_root() -> Path:
    configured = os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT")
    if configured:
        return Path(configured)
    return Path.home() / ".hermes/state/whatsapp-channel-watch/archive"


def _parse_cli_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _cutover_channel_jid(config_path: Path, profile_id: str) -> str:
    from config import load as load_config

    for profile in load_config(config_path).profiles:
        if profile.id == profile_id:
            return profile.channel_jid
    raise ValueError("cutover profile is not configured")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect immutable WhatsApp Channel source archives")
    parser.add_argument("--root", type=Path, default=_default_root(), help="archive root")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify")
    query_parser = commands.add_parser("query")
    query_parser.add_argument("--profile")
    query_parser.add_argument("--start", type=_parse_cli_date)
    query_parser.add_argument("--end", type=_parse_cli_date)
    query_parser.add_argument("--event-key")
    query_parser.add_argument("--layout-signature")
    query_parser.add_argument("--limit", type=int, default=500)
    export_parser = commands.add_parser("export")
    export_parser.add_argument("--profile")
    export_parser.add_argument("--start", type=_parse_cli_date)
    export_parser.add_argument("--end", type=_parse_cli_date)
    export_parser.add_argument("--event-key")
    export_parser.add_argument("--layout-signature")
    export_parser.add_argument("--limit", type=int, default=500)
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.add_argument("--format", choices=("jsonl", "markdown"), default="jsonl")
    prune_parser = commands.add_parser("prune")
    prune_parser.add_argument("--before", required=True, type=_parse_cli_date)
    prune_parser.add_argument("--apply", action="store_true")
    cutover_default_config = Path(
        os.environ.get(
            "WHATSAPP_CHANNEL_WATCH_CONFIG_PATH",
            str(Path(__file__).parents[1] / "config" / "watches.json"),
        )
    )
    for command_name in ("cutover-plan", "cutover-apply", "quarantine-plan", "quarantine-apply"):
        cutover_parser = commands.add_parser(command_name)
        cutover_parser.add_argument("--state", required=True, type=Path)
        cutover_parser.add_argument("--profile", required=True)
        cutover_parser.add_argument("--config", type=Path, default=cutover_default_config)
        if command_name in {"cutover-plan", "cutover-apply"}:
            cutover_parser.add_argument("--queue-dir", required=True, type=Path)
        if command_name in {"cutover-apply", "quarantine-apply"}:
            cutover_parser.add_argument("--apply", action="store_true")
        if command_name in {"quarantine-plan", "quarantine-apply"}:
            cutover_parser.add_argument("--root", type=Path, default=_default_root())
    arguments = parser.parse_args(argv)
    if arguments.command == "verify":
        result: object = verify(arguments.root)
    elif arguments.command == "query":
        records = query(
            arguments.root,
            profile_id=arguments.profile,
            start=arguments.start,
            end=arguments.end,
            event_key=arguments.event_key,
            layout_signature=arguments.layout_signature,
            limit=arguments.limit,
        )
        result = {
            "count": len(records),
            "events": [
                {
                    "event_key": record.event_key,
                    "profile_id": record.profile_id,
                    "published_at": record.data["published_at"],
                    "media_count": len(record.data["media"]),
                    "layout_signature": layout_signature_for_text(str(record.data["text"])),
                }
                for record in records
            ],
        }
    elif arguments.command == "export":
        result = export(
            arguments.root,
            profile_id=arguments.profile,
            output=arguments.output,
            format=arguments.format,
            start=arguments.start,
            end=arguments.end,
            event_key=arguments.event_key,
            layout_signature=arguments.layout_signature,
            limit=arguments.limit,
        )
    elif arguments.command == "cutover-plan":
        result = cutover_plan(
            arguments.queue_dir,
            arguments.state,
            profile_id=arguments.profile,
            channel_jid=_cutover_channel_jid(arguments.config, arguments.profile),
        )
    elif arguments.command == "cutover-apply":
        if not arguments.apply:
            parser.error("cutover-apply requires --apply")
        result = cutover_apply(
            arguments.root,
            arguments.queue_dir,
            arguments.state,
            profile_id=arguments.profile,
            channel_jid=_cutover_channel_jid(arguments.config, arguments.profile),
        )
    elif arguments.command in {"quarantine-plan", "quarantine-apply"}:
        if arguments.command == "quarantine-apply" and not arguments.apply:
            parser.error("quarantine-apply requires --apply")
        result = quarantine_outbox(
            arguments.root,
            arguments.state,
            profile_id=arguments.profile,
            channel_jid=_cutover_channel_jid(arguments.config, arguments.profile),
            apply=arguments.command == "quarantine-apply",
        )
    else:
        result = prune(arguments.root, before=arguments.before, apply=arguments.apply)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
