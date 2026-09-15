from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from models import SourceMessage
from parsing import extract_plan, parse_gtw_header


QUIET_WINDOW = timedelta(minutes=20)
AGENT_LEASE = timedelta(minutes=15)
DELIVERY_PHASE = "delivering"
BOARD_PENDING = "pending"
BOARD_UNAVAILABLE = "unavailable"
STATE_VERSION = 2


class CorruptStateError(RuntimeError):
    """Persisted state was quarantined and must not be reset automatically."""


class RunLockBusyError(RuntimeError):
    """The watcher lock is already owned by an active process."""


def new_state() -> dict[str, object]:
    return {"version": STATE_VERSION, "cursor": None, "pending": [], "outbox": [], "stats": {"observed": 0}}


def load_state(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except FileNotFoundError:
        return new_state()
    except (OSError, TypeError, json.JSONDecodeError) as error:
        _quarantine(path, error)
    value = _migrate_state(value)
    if not _is_state(value, _configured_media_root(path)):
        _quarantine(path, ValueError("invalid state shape"))
    return value


def save_state(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            json.dump(value, destination, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def observe_messages(value: dict[str, object], messages: list[SourceMessage], now: datetime) -> None:
    del now
    ordered = sorted(messages, key=lambda message: message.message_id)
    if value["cursor"] is None:
        if ordered:
            value["cursor"] = ordered[-1].message_id
            _stats(value)["observed"] += len(ordered)
        return

    cursor = int(value["cursor"])
    for message in ordered:
        if message.message_id <= cursor:
            continue
        _append_message(value, message)
        cursor = message.message_id
        value["cursor"] = cursor
        _stats(value)["observed"] += 1


def ready_events(value: dict[str, object], now: datetime) -> list[dict[str, object]]:
    pending = _pending(value)
    if pending and now - _time(pending[0]["last_message_at"]) > QUIET_WINDOW:
        _close_pending(value)
    return list(_outbox(value))


def claim_oldest_agent(value: dict[str, object], now: datetime) -> dict[str, object] | None:
    for event in _outbox(value):
        lease = event["agent_lease_until"]
        can_claim = event["agent_phase"] == "ready" or (
            event["agent_phase"] == "claimed" and lease is not None and _time(lease) <= now
        )
        if can_claim:
            event["agent_phase"] = "claimed"
            event["agent_lease_until"] = (now + AGENT_LEASE).isoformat()
            return event
    return None


def restore_expired_claim(event: dict[str, object], now: datetime) -> bool:
    """Make an expired agent lease claimable again without accepting a late submission."""
    if event.get("agent_phase") != "claimed":
        return False
    lease = event.get("agent_lease_until")
    if not isinstance(lease, str) or _time(lease) > now:
        return False
    event["agent_phase"] = "ready"
    event["agent_lease_until"] = None
    return True


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunLockBusyError(f"watcher is already running: {path}") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_message(value: dict[str, object], message: SourceMessage) -> None:
    # Replies are never part of the chronological channel stream.  Do this
    # before recognizing headers, since a quoted header in a reply must not
    # close the current bundle or open another one.
    if message.reply_to_message_id is not None:
        return

    header = parse_gtw_header(message.text)
    if header is not None:
        if _pending(value):
            _close_pending(value)
        _pending(value).append(
            {
                "header_message_id": message.message_id,
                "ticker": header.ticker,
                "source_message_ids": [message.message_id],
                "source_text": message.text,
                "media": _media(message),
                "source_published_at": message.posted_at.isoformat(),
                "last_message_at": message.posted_at.isoformat(),
                "closed_by_header": False,
            }
        )
        return

    if not _pending(value):
        return
    candidate = _pending(value)[0]
    if message.posted_at - _time(candidate["last_message_at"]) > QUIET_WINDOW:
        _close_pending(value)
        return
    if not _is_bundle_continuation(message, str(candidate["ticker"])):
        return
    candidate["source_message_ids"].append(message.message_id)
    if message.text.strip():
        candidate["source_text"] = f"{candidate['source_text']}\n{message.text}".strip()
    candidate["last_message_at"] = message.posted_at.isoformat()


def _close_pending(value: dict[str, object]) -> None:
    candidate = _pending(value).pop(0)
    candidate["closed_by_header"] = True
    event_key = f"{candidate['header_message_id']}:{candidate['ticker']}"
    if any(event["event_key"] == event_key for event in _outbox(value)):
        return
    plan = extract_plan(candidate["source_text"])
    _outbox(value).append(
        {
            "event_key": event_key,
            "ticker": candidate["ticker"],
            "header_message_id": candidate["header_message_id"],
            "source_message_ids": list(candidate["source_message_ids"]),
            "source_text": candidate["source_text"],
            "source_published_at": candidate["source_published_at"],
            "plan": {"buy_area": plan.buy_area, "targets": plan.targets, "stoploss": plan.stoploss},
            "media": list(candidate["media"]),
            "title": None,
            "summary": None,
            "agent_phase": "ready",
            "agent_lease_until": None,
            "text_index": 0,
            "next_media_index": 0,
            "attempts": 0,
            "next_attempt_at": None,
            "last_error": None,
            "board_phase": BOARD_PENDING if candidate["source_published_at"] is not None else BOARD_UNAVAILABLE,
            "board_attempts": 0,
            "board_next_attempt_at": None,
            "board_last_error": None,
        }
    )


def _pending(value: dict[str, object]) -> list[dict[str, object]]:
    return value["pending"]  # type: ignore[return-value]


def _outbox(value: dict[str, object]) -> list[dict[str, object]]:
    return value["outbox"]  # type: ignore[return-value]


def _stats(value: dict[str, object]) -> dict[str, int]:
    return value["stats"]  # type: ignore[return-value]


def _media(message: SourceMessage) -> list[dict[str, int]]:
    return [{"message_id": item.message_id, "ordinal": item.ordinal} for item in message.media]


def _time(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _quarantine(path: Path, error: BaseException) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    sequence = 0
    while True:
        suffix = f"-{sequence}" if sequence else ""
        quarantine = path.with_name(f"{path.stem}.corrupt-{timestamp}-{os.getpid()}{suffix}{path.suffix}")
        try:
            # link(2) atomically reserves the quarantine name without replacing
            # an existing forensic copy. The source and destination are siblings,
            # so the subsequent unlink is a same-filesystem move.
            os.link(path, quarantine)
        except FileExistsError:
            sequence += 1
            continue
        except OSError as move_error:
            raise CorruptStateError(f"state is corrupt and could not be quarantined: {move_error}") from error
        try:
            os.unlink(path)
            _fsync_directory(path.parent)
            break
        except OSError as move_error:
            raise CorruptStateError(f"state is corrupt and could not be quarantined: {move_error}") from error
    raise CorruptStateError(f"state is corrupt; moved aside to {quarantine.name}") from error


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_state(value: object, media_root: Path | None = None) -> bool:
    if not isinstance(value, dict) or set(value) != {"version", "cursor", "pending", "outbox", "stats"}:
        return False
    if value["version"] != STATE_VERSION or not _optional_id(value["cursor"]):
        return False
    stats = value["stats"]
    if not isinstance(stats, dict) or set(stats) != {"observed"} or not _nonnegative_int(stats["observed"]):
        return False
    pending = value["pending"]
    outbox = value["outbox"]
    return (
        isinstance(pending, list)
        and len(pending) <= 1
        and all(_is_pending(item, media_root) for item in pending)
        and isinstance(outbox, list)
        and all(_is_outbox(item, media_root) for item in outbox)
        and len({item["event_key"] for item in outbox}) == len(outbox)
    )


def _is_pending(value: object, media_root: Path | None = None) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "header_message_id", "ticker", "source_message_ids", "source_text", "media", "source_published_at", "last_message_at", "closed_by_header"
    }:
        return False
    return (
        _positive_int(value["header_message_id"])
        and _ticker(value["ticker"])
        and _message_ids(value["source_message_ids"], value["header_message_id"])
        and isinstance(value["source_text"], str)
        and _media_items(value["media"], value["source_message_ids"], media_root)
        and _optional_timestamp(value["source_published_at"])
        and _timestamp(value["last_message_at"])
        and value["closed_by_header"] is False
    )


def _is_outbox(value: object, media_root: Path | None = None) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "event_key", "ticker", "header_message_id", "source_message_ids", "source_text", "source_published_at", "plan", "media", "title", "summary",
        "agent_phase", "agent_lease_until", "text_index", "next_media_index", "attempts", "next_attempt_at", "last_error",
        "board_phase", "board_attempts", "board_next_attempt_at", "board_last_error"
    }:
        return False
    plan = value["plan"]
    return (
        value["event_key"] == f"{value['header_message_id']}:{value['ticker']}"
        and _ticker(value["ticker"])
        and _positive_int(value["header_message_id"])
        and _message_ids(value["source_message_ids"], value["header_message_id"])
        and isinstance(value["source_text"], str)
        and _optional_timestamp(value["source_published_at"])
        and isinstance(plan, dict)
        and set(plan) == {"buy_area", "targets", "stoploss"}
        and all(isinstance(item, str) for item in plan.values())
        and _media_items(value["media"], value["source_message_ids"], media_root)
        and _optional_string(value["title"])
        and _optional_string(value["summary"])
        and _valid_agent_lease(value["agent_phase"], value["agent_lease_until"])
        and _nonnegative_int(value["text_index"])
        and _nonnegative_int(value["next_media_index"])
        and value["next_media_index"] <= len(value["media"])
        and _nonnegative_int(value["attempts"])
        and _optional_timestamp(value["next_attempt_at"])
        and _optional_string(value["last_error"])
        and _valid_board_context(value)
    )


def _migrate_state(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("version") != 1:
        return value  # type: ignore[return-value]
    pending = value.get("pending")
    outbox = value.get("outbox")
    if not isinstance(pending, list) or not isinstance(outbox, list):
        return value
    for candidate in pending:
        if isinstance(candidate, dict):
            candidate.setdefault("source_published_at", None)
    for event in outbox:
        if not isinstance(event, dict):
            continue
        # Version one did not retain closed bundles' source-post timestamp.
        # Preserve the cursor and All delivery but do not invent a source fact
        # for board submission.
        event.setdefault("source_published_at", None)
        event.setdefault("board_phase", BOARD_UNAVAILABLE)
        event.setdefault("board_attempts", 0)
        event.setdefault("board_next_attempt_at", None)
        event.setdefault("board_last_error", None)
    value["version"] = STATE_VERSION
    return value


def _valid_board_context(value: dict[object, object]) -> bool:
    phase = value["board_phase"]
    timestamp = value["source_published_at"]
    if timestamp is None:
        return (
            phase == BOARD_UNAVAILABLE
            and _nonnegative_int(value["board_attempts"])
            and value["board_attempts"] == 0
            and value["board_next_attempt_at"] is None
            and value["board_last_error"] is None
        )
    return (
        phase == BOARD_PENDING
        and _nonnegative_int(value["board_attempts"])
        and _optional_timestamp(value["board_next_attempt_at"])
        and _optional_string(value["board_last_error"])
    )


def _is_bundle_continuation(message: SourceMessage, ticker: str) -> bool:
    text = message.text.strip()
    if not text:
        return bool(message.media)
    normalized = " ".join(text.casefold().split())
    if _URL.search(text) or _EXCLUDED_CONTINUATION.search(normalized):
        return False
    # A bare, unrelated channel announcement must not extend an open bundle.
    # Free-form analysis remains valid when it names the ticker or uses a
    # recognisable trading-analysis label/term.
    return ticker.casefold() in normalized or bool(_ANALYSIS_CONTINUATION.search(normalized)) or bool(message.media)


_URL = re.compile(r"(?:https?://|www\.|t\.me/)", re.IGNORECASE)
_EXCLUDED_CONTINUATION = re.compile(
    r"\b(?:disclaimer|disclamer|dyor|promo(?:si)?|premium|member(?:ship)?|subscribe|berlangganan|"
    r"gabung(?:lah)?|join(?:lah)?|webinar|kelas|diskon|baca\s+selengkapnya|read\s+more)\b",
    re.IGNORECASE,
)
_ANALYSIS_CONTINUATION = re.compile(
    r"\b(?:buy\s*area|tp\s*\d*|target\s*\d*|stop[-\s]?loss|support|resistan(?:ce|)\b|"
    r"akumulasi|breakout|breakdown|entry|cut\s*loss|take\s*profit|risk|trend|volume|chart|candle)\b",
    re.IGNORECASE,
)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_id(value: object) -> bool:
    return value is None or _positive_int(value)


def _ticker(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Z]{2,5}", value))


def _message_ids(value: object, header_id: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_positive_int(item) for item in value)
        and value[0] == header_id
        and value == sorted(set(value))
    )


def _media_items(value: object, source_message_ids: object, media_root: Path | None = None) -> bool:
    if not isinstance(value, list) or not isinstance(source_message_ids, list):
        return False
    media_keys: set[tuple[int, int]] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) not in ({"message_id", "ordinal"}, {"message_id", "ordinal", "path"})
            or not _positive_int(item["message_id"])
            or not _nonnegative_int(item["ordinal"])
            or item["message_id"] not in source_message_ids
        ):
            return False
        if "path" in item:
            if not isinstance(item["path"], str) or not item["path"] or media_root is None:
                return False
            try:
                path = Path(item["path"]).resolve()
                path.relative_to(media_root.resolve())
            except (OSError, ValueError):
                return False
            if not path.is_file() or path.stat().st_size <= 0 or not _is_image(path):
                return False
        key = (item["message_id"], item["ordinal"])
        if key in media_keys:
            return False
        media_keys.add(key)
    return True


def _configured_media_root(state_path: Path) -> Path:
    configured = os.environ.get("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT")
    return Path(configured) if configured else state_path.parent / "media"


def _is_image(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            header = source.read(16)
    except OSError:
        return False
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or header.startswith((b"GIF87a", b"GIF89a"))
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def _valid_agent_lease(phase: object, lease: object) -> bool:
    if phase in ("ready", DELIVERY_PHASE):
        return lease is None
    if phase == "claimed":
        return _timestamp(lease)
    return False


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _optional_timestamp(value: object) -> bool:
    return value is None or _timestamp(value)


def _optional_string(value: object) -> bool:
    return value is None or isinstance(value, str)
