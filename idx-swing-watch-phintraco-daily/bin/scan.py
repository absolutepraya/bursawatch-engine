#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import shutil
import datetime as dt
import html
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from swing_format import SwingMessage, fields as shared_fields, render_message

from telegram_resilience import (
    PolyCopResilience,
    StateBlockedError as ResilienceStateBlockedError,
    acquire_probe_after_active_lease,
    is_transport_error,
)

SOURCE_CHANNEL_ID = 1444713822
ALERT_CHANNEL_ID = "1525102458253217803"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
DISCORD_API = "https://discord.com/api/v10"
WIB = ZoneInfo("Asia/Jakarta")
PROVIDER = "Phintraco"
PHINTRACO_EMOJI = "<:phintraco:1531272488645038091>"
UP_EMOJI = "<:up:1531285100346740766>"
DOWN_EMOJI = "<:down:1531285063986053200>"
ALLOWED_SUBTYPES = ("Trading Buy", "Buy on Support", "Speculative Buy")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

TELEGRAM_MESSAGE_BASE_URL = "https://t.me/phintraprofits"

STATE_VERSION = 2
PHASE_PENDING_MEDIA_CAPTURE = "pending_media_capture"
PHASE_PENDING_TEXT = "pending_text"
PHASE_PENDING_CHART = "pending_chart"
PHASE_PENDING_BOARD = "pending_board"
PHASE_DELIVERED = "delivered"
MAX_FATAL_FINGERPRINTS_PER_HOUR = 64
MAX_RETRY_SECONDS = 15 * 60
WATCHER_NAME = "idx-swing-watch-phintraco-daily"
WATCHER_HEARTBEAT_NAME = "idx-swing-phintraco-daily"
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"

_REQUIRED_STATE_FIELDS = (
    "version",
    "blocked",
    "block_reason",
    "observed_message_id",
    "outbox",
    "last_poll_success",
    "last_delivery_success",
    "last_heartbeat_hour",
    "last_error_notice",
    "stats",
)
_NULLABLE_STATE_STRING_FIELDS = (
    "block_reason",
    "last_poll_success",
    "last_delivery_success",
    "last_heartbeat_hour",
)
_REQUIRED_STATS_FIELDS = ("runs", "messages", "calls", "delivered")
_REQUIRED_EVENT_FIELDS = (
    "event_key",
    "source_message_id",
    "call",
    "phase",
    "chart_status",
    "media_path",
    "text_discord_id",
    "attempts",
    "next_attempt_at",
    "last_error",
    "board_submitted",
    "board_attempts",
    "board_next_attempt_at",
    "board_last_error",
    "created_at",
)
_REQUIRED_CALL_FIELDS = (
    "source_message_id",
    "provider",
    "ticker",
    "call_subtype",
    "entry",
    "stop_loss",
    "targets",
    "signal_datetime",
    "rationale",
    "advisor_name",
    "advisor_role",
    "has_source_chart",
    "event_kind",
    "status",
    "outcomes",
)
_CALL_STRING_FIELDS = (
    "provider",
    "ticker",
    "call_subtype",
    "entry",
    "stop_loss",
    "rationale",
    "event_kind",
)
_EVENT_PHASES = {
    PHASE_PENDING_MEDIA_CAPTURE,
    PHASE_PENDING_TEXT,
    PHASE_PENDING_CHART,
    PHASE_PENDING_BOARD,
    PHASE_DELIVERED,
}
_CHART_STATUSES = {"absent", "expected", "captured"}


class StateBlockedError(RuntimeError):
    def __init__(self, message: str, state: dict):
        super().__init__(message)
        self.state = state


class DiscordRetryAfter(RuntimeError):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


def state_path() -> Path:
    return Path(
        os.environ.get(
            "IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH",
            str(DEFAULT_STATE_FILE),
        )
    )


def media_dir() -> Path:
    return state_path().parent / "media"


def lock_path() -> Path:
    return state_path().parent / "run.lock"


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "blocked": False,
        "block_reason": None,
        "observed_message_id": 0,
        "outbox": {},
        "last_poll_success": None,
        "last_delivery_success": None,
        "last_heartbeat_hour": None,
        "last_error_notice": None,
        "stats": {"runs": 0, "messages": 0, "calls": 0, "delivered": 0},
    }


def _require_fields(value: object, required: tuple[str, ...], label: str) -> dict:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    missing = [field for field in required if field not in value]
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")
    return value


def _require_aware_datetime(value: dt.datetime, label: str) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _parse_aware_datetime(value: object, label: str) -> dt.datetime:
    if type(value) is not str:
        raise ValueError(f"{label} must be an ISO datetime string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid ISO datetime string") from exc
    return _require_aware_datetime(parsed, label)


def _validate_last_error_notice(payload: object) -> None:
    if payload is None:
        return
    notice = _require_fields(
        payload, ("hour", "fingerprints"), "state last_error_notice"
    )
    if type(notice["hour"]) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}[+-]\d{2}:\d{2}", notice["hour"]
    ):
        raise ValueError("state last_error_notice hour has an invalid format")
    fingerprints = notice["fingerprints"]
    if type(fingerprints) is not list:
        raise ValueError("state last_error_notice fingerprints must be a list")
    if not fingerprints:
        raise ValueError("state last_error_notice fingerprints must not be empty")
    if len(fingerprints) > MAX_FATAL_FINGERPRINTS_PER_HOUR:
        raise ValueError("state last_error_notice has too many fingerprints")
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("state last_error_notice fingerprints must be unique")
    for fingerprint in fingerprints:
        if type(fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{16}", fingerprint
        ):
            raise ValueError(
                "state last_error_notice fingerprints must be 16 lowercase hex characters"
            )


def _validate_call_payload(payload: object, source_message_id: int) -> None:
    call = _require_fields(payload, _REQUIRED_CALL_FIELDS, "outbox call")
    if type(call["source_message_id"]) is not int or call["source_message_id"] != source_message_id:
        raise ValueError("outbox call source_message_id must match its event")
    for field in _CALL_STRING_FIELDS:
        if type(call[field]) is not str:
            raise ValueError(f"outbox call {field} must be a string")
    targets = call["targets"]
    if type(targets) is not list:
        raise ValueError("outbox call targets must be a list")
    if call["event_kind"] == "BUY" and not targets:
        raise ValueError("outbox BUY call targets must not be empty")
    for target in targets:
        target = _require_fields(target, ("number", "value"), "outbox call target")
        if target["number"] is not None and type(target["number"]) is not int:
            raise ValueError("outbox call target number must be an integer or null")
        if type(target["value"]) is not str:
            raise ValueError("outbox call target value must be a string")
    _parse_aware_datetime(call["signal_datetime"], "outbox call signal_datetime")
    for field in ("advisor_name", "advisor_role"):
        if call[field] is not None and type(call[field]) is not str:
            raise ValueError(f"outbox call {field} must be a string or null")
    if type(call["has_source_chart"]) is not bool:
        raise ValueError("outbox call has_source_chart must be a boolean")
    if call["status"] is not None and type(call["status"]) is not str:
        raise ValueError("outbox call status must be a string or null")
    if type(call["outcomes"]) is not list or not all(type(outcome) is str for outcome in call["outcomes"]):
        raise ValueError("outbox call outcomes must be a list of strings")


def _validate_outbox_event(key: object, payload: object) -> None:
    if type(key) is not str or not key.isascii() or not key.isdigit():
        raise ValueError("outbox keys must be decimal source message IDs")
    event = _require_fields(payload, _REQUIRED_EVENT_FIELDS, f"outbox event {key}")
    if type(event["event_key"]) is not str or event["event_key"] != key:
        raise ValueError(f"outbox event {key} event_key must match its key")
    if type(event["source_message_id"]) is not int or event["source_message_id"] <= 0:
        raise ValueError(f"outbox event {key} source_message_id must be a positive integer")
    if str(event["source_message_id"]) != key:
        raise ValueError(f"outbox event {key} source_message_id must match its key")
    _validate_call_payload(event["call"], event["source_message_id"])
    if type(event["phase"]) is not str or event["phase"] not in _EVENT_PHASES:
        raise ValueError(f"outbox event {key} has an invalid phase")
    if type(event["chart_status"]) is not str or event["chart_status"] not in _CHART_STATUSES:
        raise ValueError(f"outbox event {key} has an invalid chart_status")
    for field in ("media_path", "text_discord_id", "last_error"):
        if event[field] is not None and type(event[field]) is not str:
            raise ValueError(f"outbox event {key} {field} must be a string or null")
    if type(event["attempts"]) is not int or event["attempts"] < 0:
        raise ValueError(f"outbox event {key} attempts must be a non-negative integer")
    if event["next_attempt_at"] is not None:
        _parse_aware_datetime(event["next_attempt_at"], f"outbox event {key} next_attempt_at")
    if type(event["board_submitted"]) is not bool:
        raise ValueError(f"outbox event {key} board_submitted must be a boolean")
    if type(event["board_attempts"]) is not int or event["board_attempts"] < 0:
        raise ValueError(f"outbox event {key} board_attempts must be a non-negative integer")
    if event["board_next_attempt_at"] is not None:
        _parse_aware_datetime(
            event["board_next_attempt_at"],
            f"outbox event {key} board_next_attempt_at",
        )
    if event["board_last_error"] is not None and type(event["board_last_error"]) is not str:
        raise ValueError(f"outbox event {key} board_last_error must be a string or null")
    if type(event["created_at"]) is not str:
        raise ValueError(f"outbox event {key} created_at must be a string")


def _validate_state(payload: object) -> dict:
    state = _require_fields(payload, _REQUIRED_STATE_FIELDS, "state")
    if type(state["version"]) is not int or state["version"] != STATE_VERSION:
        raise ValueError(f"unsupported state version: {state['version']}")
    if type(state["blocked"]) is not bool:
        raise ValueError("state blocked must be a boolean")
    for field in _NULLABLE_STATE_STRING_FIELDS:
        if state[field] is not None and type(state[field]) is not str:
            raise ValueError(f"state {field} must be a string or null")
    _validate_last_error_notice(state["last_error_notice"])
    if type(state["observed_message_id"]) is not int or state["observed_message_id"] < 0:
        raise ValueError("state observed_message_id must be a non-negative integer")
    outbox = state["outbox"]
    if type(outbox) is not dict:
        raise ValueError("state outbox must be an object")
    for key, event in outbox.items():
        _validate_outbox_event(key, event)
    stats = _require_fields(state["stats"], _REQUIRED_STATS_FIELDS, "state stats")
    for field in _REQUIRED_STATS_FIELDS:
        if type(stats[field]) is not int or stats[field] < 0:
            raise ValueError(f"state stats {field} must be a non-negative integer")
    return state


def _migrate_state(payload: object) -> tuple[dict, bool]:
    if type(payload) is not dict:
        raise ValueError("state must be an object")
    version = payload.get("version")
    if type(version) is not int:
        raise ValueError(f"unsupported state version: {version}")
    if version == STATE_VERSION:
        return payload, False
    if version != 1:
        raise ValueError(f"unsupported state version: {version}")

    outbox = payload.get("outbox")
    if type(outbox) is not dict:
        raise ValueError("state outbox must be an object")
    for event in outbox.values():
        if type(event) is not dict:
            raise ValueError("outbox event must be an object")
        # Version 1 considered this phase final. It is now the handoff point,
        # so preserve any retained source media and continue with the owner.
        if event.get("phase") == PHASE_DELIVERED:
            event["phase"] = PHASE_PENDING_BOARD
        event.setdefault("board_submitted", False)
        event.setdefault("board_attempts", 0)
        event.setdefault("board_next_attempt_at", None)
        event.setdefault("board_last_error", None)
    payload["version"] = STATE_VERSION
    return payload, True


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with handle:
            handle.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temp.unlink(missing_ok=True)
        raise


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return empty_state()
    try:
        state, migrated = _migrate_state(json.loads(path.read_text()))
        state = _validate_state(state)
        if migrated:
            save_state(state)
    except Exception as exc:
        stamp = dt.datetime.now(WIB).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"state.corrupt-{stamp}.json")
        shutil.move(path, backup)
        state = empty_state()
        state["blocked"] = True
        state["block_reason"] = f"state corruption: {type(exc).__name__}"
        save_state(state)
        raise StateBlockedError(state["block_reason"], state) from exc
    if state.get("blocked"):
        raise StateBlockedError(str(state.get("block_reason") or "state is blocked"), state)
    return state


def current_time() -> dt.datetime:
    return dt.datetime.now(WIB)


def enqueue_call(state: dict, call: SwingCall, now: dt.datetime) -> dict:
    key = str(call.source_message_id)
    existing = state.setdefault("outbox", {}).get(key)
    if existing is not None:
        return existing
    has_chart = call.has_source_chart
    event = {
        "event_key": key,
        "source_message_id": call.source_message_id,
        "call": serialize_call(call),
        "phase": PHASE_PENDING_MEDIA_CAPTURE if has_chart else PHASE_PENDING_TEXT,
        "chart_status": "expected" if has_chart else "absent",
        "media_path": None,
        "text_discord_id": None,
        "attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
        "board_submitted": False,
        "board_attempts": 0,
        "board_next_attempt_at": None,
        "board_last_error": None,
        "created_at": now.isoformat(),
    }
    state["outbox"][key] = event
    return event


def oldest_outbox_event(state: dict) -> dict | None:
    # The All queue contains only unfinished text/chart legs. Completed All
    # events remain durable in the independent board queue below.
    outbox = {key: event for key, event in (state.get("outbox") or {}).items()
              if event["phase"] not in {PHASE_PENDING_BOARD, PHASE_DELIVERED}}
    if not outbox:
        return None
    key = min(outbox, key=lambda value: int(value))
    return outbox[key]


def retry_due(event: dict, now: dt.datetime) -> bool:
    _require_aware_datetime(now, "retry now")
    raw = event.get("next_attempt_at")
    if raw is None:
        return True
    return now >= _parse_aware_datetime(raw, "next_attempt_at")


def schedule_retry(
    event: dict,
    now: dt.datetime,
    error: str,
    minimum_delay_seconds: float | None = None,
) -> None:
    _require_aware_datetime(now, "retry now")
    event["attempts"] = int(event.get("attempts", 0)) + 1
    if event["attempts"] >= 5:
        delay = float(MAX_RETRY_SECONDS)
    else:
        delay = float(60 * (2 ** (event["attempts"] - 1)))
    if minimum_delay_seconds is not None:
        minimum_delay = float(minimum_delay_seconds)
        if not math.isfinite(minimum_delay) or minimum_delay < 0:
            raise ValueError("minimum retry delay must be a non-negative finite number")
        delay = max(delay, minimum_delay)
    event["next_attempt_at"] = (now + dt.timedelta(seconds=delay)).isoformat()
    event["last_error"] = re.sub(r"\s+", " ", error).strip()[:240]


def clear_retry(event: dict) -> None:
    event["attempts"] = 0
    event["next_attempt_at"] = None
    event["last_error"] = None


def board_retry_due(event: dict, now: dt.datetime) -> bool:
    _require_aware_datetime(now, "board retry now")
    raw = event.get("board_next_attempt_at")
    if raw is None:
        return True
    return now >= _parse_aware_datetime(raw, "board_next_attempt_at")


def schedule_board_retry(event: dict, now: dt.datetime, error: str) -> None:
    _require_aware_datetime(now, "board retry now")
    attempts = int(event.get("board_attempts", 0)) + 1
    event["board_attempts"] = attempts
    delay = float(MAX_RETRY_SECONDS) if attempts >= 5 else float(60 * (2 ** (attempts - 1)))
    event["board_next_attempt_at"] = (now + dt.timedelta(seconds=delay)).isoformat()
    event["board_last_error"] = re.sub(r"\s+", " ", error).strip()[:240]


def clear_board_retry(event: dict) -> None:
    event["board_attempts"] = 0
    event["board_next_attempt_at"] = None
    event["board_last_error"] = None


@contextlib.contextmanager
def run_lock():
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

HEADER_RE = re.compile(
    r"^(?P<ticker>[A-Z][A-Z0-9]{1,9})\s*-\s*"
    r"(?P<subtype>Trading Buy|Buy on Support|Speculative Buy)\s*:\s*"
    r"(?P<rationale>.*)$",
    re.IGNORECASE,
)
ENTRY_RE = re.compile(r"^Entry\s*(?::|-)\s*(.+)$", re.IGNORECASE)
STOP_RE = re.compile(r"^Stop(?:-?loss)\s*(?::|-)\s*(.+)$", re.IGNORECASE)
TARGET_RE = re.compile(r"^Target(?:\s+(\d+))?\s*:\s*(.+)$", re.IGNORECASE)
DATE_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2})[.:](\d{2})\s+WIB$",
    re.IGNORECASE,
)
ADVISOR_RE = re.compile(r"^(.+?)\s*\|\s*(Investment Advisor)\s*$", re.IGNORECASE)
SOURCE_RE = re.compile(r"^By\s+PHINTRACO\s+SEKURITAS$", re.IGNORECASE)
TICKER_LINE_RE = re.compile(r"^(?P<ticker>[A-Z][A-Z0-9]{1,9})\s*-\s*(?P<body>.+)$", re.IGNORECASE)
STATUS_RE = re.compile(
    r"\b(?:on\s+support|on\s+trac(?:k)?|still\s+(?:on\s+plan|on\s+track|in\s*line|inilne|hold)|keep\s+(?:on|in)\s+plan|trading\s+plan\s+sebelumnya\s+masih\s+berlaku)\b",
    re.IGNORECASE,
)
REPLY_STATUS_RE = re.compile(
    r"^(?P<ticker>[A-Z][A-Z0-9]{1,9})\s*(?:-\s*)?(?P<status>on\s+trac(?:k)?)\.?$",
    re.IGNORECASE,
)
TARGET_ACHIEVED_RE = re.compile(
    r"\b(?:(?P<ordinal>first|second|third|fourth|\d+(?:st|nd|rd|th))\s+)?"
    r"tar(?:get|et)\s+(?P<value>[0-9][0-9.,]*)\s+achieved\b",
    re.IGNORECASE,
)
ALL_TARGETS_RE = re.compile(r"\ball\s+targets?\s+achieved\b", re.IGNORECASE)
STOP_LOSS_HIT_RE = re.compile(r"\bstop[- ]?loss\s+hit\b", re.IGNORECASE)


@dataclass(frozen=True)
class PriceTarget:
    number: int | None
    value: str


@dataclass(frozen=True)
class SwingCall:
    source_message_id: int
    provider: str
    ticker: str
    call_subtype: str
    entry: str
    stop_loss: str
    targets: tuple[PriceTarget, ...]
    signal_datetime: dt.datetime
    rationale: str
    advisor_name: str | None
    advisor_role: str | None
    has_source_chart: bool
    event_kind: str = "BUY"
    status: str | None = None
    outcomes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunStats:
    messages: int
    calls: int
    delivered: int
    pending: int
    degraded: bool


def normalize_text(value: str) -> str:
    lines = []
    for raw in html.unescape(value or "").replace("\u00a0", " ").splitlines():
        lines.append(re.sub(r"[ \t]+", " ", raw).strip())
    return "\n".join(lines).strip()


def normalize_source_posted_at(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def normalize_price(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return re.sub(r"(?<=\d)\s*-\s*(?=\d)", " to ", value)


def canonical_subtype(value: str) -> str:
    folded = value.casefold()
    for subtype in ALLOWED_SUBTYPES:
        if subtype.casefold() == folded:
            return subtype
    raise ValueError(f"unsupported call subtype: {value}")


def looks_like_swing_call(text: str) -> bool:
    lines = normalize_text(text).splitlines()
    return bool(
        lines
        and HEADER_RE.match(lines[0])
        and any(SOURCE_RE.match(line) for line in lines)
    )


def parse_swing_call(
    message_id: int,
    text: str,
    has_photo: bool,
    source_posted_at: dt.datetime | None = None,
) -> SwingCall | None:
    normalized = normalize_text(text)
    lines = normalized.splitlines()
    if not lines:
        return None
    header = HEADER_RE.match(lines[0])
    if not header or not any(SOURCE_RE.match(line) for line in lines):
        return None

    entry = None
    stop_loss = None
    targets: list[PriceTarget] = []
    signal_datetime = normalize_source_posted_at(source_posted_at)
    advisor_name = None
    advisor_role = None
    rationale_parts = [header.group("rationale").strip()]
    before_entry = True

    for line in lines[1:]:
        if not line:
            continue
        if HEADER_RE.match(line):
            return None
        entry_match = ENTRY_RE.match(line)
        if entry_match:
            entry = normalize_price(entry_match.group(1))
            before_entry = False
            continue
        if before_entry and not SOURCE_RE.match(line):
            rationale_parts.append(line)
            continue
        stop_match = STOP_RE.match(line)
        if stop_match:
            stop_loss = normalize_price(stop_match.group(1))
            continue
        target_match = TARGET_RE.match(line)
        if target_match:
            number = int(target_match.group(1)) if target_match.group(1) else None
            targets.append(PriceTarget(number, normalize_price(target_match.group(2))))
            continue
        date_match = DATE_RE.match(line)
        if date_match and signal_datetime is None:
            try:
                day, month, year, hour, minute = map(int, date_match.groups())
                signal_datetime = dt.datetime(year, month, day, hour, minute, tzinfo=WIB)
            except ValueError:
                return None
            continue
        advisor_match = ADVISOR_RE.match(line)
        if advisor_match:
            advisor_name = advisor_match.group(1).strip()
            advisor_role = "Investment Advisor"

    if entry is None or stop_loss is None or not targets or signal_datetime is None:
        return None

    targets.sort(key=lambda target: (target.number is None, target.number or 0))
    rationale = " ".join(part for part in rationale_parts if part).strip()
    return SwingCall(
        source_message_id=message_id,
        provider=PROVIDER,
        ticker=header.group("ticker").upper(),
        call_subtype=canonical_subtype(header.group("subtype")),
        entry=entry,
        stop_loss=stop_loss,
        targets=tuple(targets),
        signal_datetime=signal_datetime,
        rationale=rationale,
        advisor_name=advisor_name,
        advisor_role=advisor_role,
        has_source_chart=has_photo,
    )
def parse_swing_reminder(
    message_id: int,
    text: str,
    has_photo: bool,
    source_posted_at: dt.datetime | None = None,
) -> SwingCall | None:
    lines = [line for line in normalize_text(text).splitlines() if line]
    if not lines or not any(SOURCE_RE.match(line) for line in lines):
        return None
    ticker_lines = [
        match
        for index, line in enumerate(lines)
        if (match := TICKER_LINE_RE.match(line))
        and (index == 0 or lines[index - 1].casefold() == "reminder")
    ]
    if len(ticker_lines) != 1:
        return None
    header = ticker_lines[0]
    body = header.group("body").strip()
    signal_datetime = normalize_source_posted_at(source_posted_at)
    advisor_name = None
    targets: list[PriceTarget] = []
    entry = ""
    stop_loss = ""
    for line in lines:
        if match := ENTRY_RE.match(line):
            entry = normalize_price(match.group(1))
        elif match := STOP_RE.match(line):
            stop_loss = normalize_price(match.group(1))
        elif match := TARGET_RE.match(line):
            number = int(match.group(1)) if match.group(1) else None
            targets.append(PriceTarget(number, normalize_price(match.group(2))))
        elif match := DATE_RE.match(line):
            if signal_datetime is None:
                try:
                    day, month, year, hour, minute = map(int, match.groups())
                    signal_datetime = dt.datetime(year, month, day, hour, minute, tzinfo=WIB)
                except ValueError:
                    return None
        elif match := ADVISOR_RE.match(line):
            advisor_name = match.group(1).strip()
    if signal_datetime is None:
        return None
    targets.sort(key=lambda target: (target.number is None, target.number or 0))
    joined = "\n".join(lines)
    outcomes: list[str] = []
    if match := TARGET_ACHIEVED_RE.search(joined):
        ordinal = match.group("ordinal")
        label = f"{ordinal.capitalize()} target" if ordinal else "Target"
        outcomes.append(f"{label} {match.group('value')} achieved")
    if ALL_TARGETS_RE.search(joined):
        outcomes.append("All targets achieved")
    if STOP_LOSS_HIT_RE.search(joined):
        outcomes.append("Stop-loss hit")
    kind = "REMINDER" if outcomes else "STATUS" if STATUS_RE.search(joined) else None
    if kind is None:
        return None
    status = None
    if kind == "STATUS":
        status = re.sub(r"\binilne\b", "inline", body, flags=re.IGNORECASE)
        status = re.sub(r"^on\s+trac(?:k)?\b", "On track", status, flags=re.IGNORECASE)
    return SwingCall(
        source_message_id=message_id,
        provider=PROVIDER,
        ticker=header.group("ticker").upper(),
        call_subtype="",
        entry=entry,
        stop_loss=stop_loss,
        targets=tuple(targets),
        signal_datetime=signal_datetime,
        rationale="",
        advisor_name=advisor_name,
        advisor_role="Investment Advisor" if advisor_name else None,
        has_source_chart=has_photo,
        event_kind=kind,
        status=status,
        outcomes=tuple(outcomes),
    )


def parse_reply_status(
    message_id: int,
    text: str,
    has_photo: bool,
    source_posted_at: dt.datetime | None,
    parent: SwingCall | None,
) -> SwingCall | None:
    source_datetime = normalize_source_posted_at(source_posted_at)
    if parent is None or parent.event_kind not in {"BUY", "STATUS"} or source_datetime is None:
        return None
    reply = REPLY_STATUS_RE.match(normalize_text(text))
    if reply is None or reply.group("ticker").upper() != parent.ticker:
        return None
    status = "On track"
    return SwingCall(
        source_message_id=message_id,
        provider=PROVIDER,
        ticker=parent.ticker,
        call_subtype="",
        entry="",
        stop_loss="",
        targets=(),
        signal_datetime=source_datetime,
        rationale="",
        advisor_name=None,
        advisor_role=None,
        has_source_chart=has_photo,
        event_kind="STATUS",
        status=status,
    )


def serialize_call(call: SwingCall) -> dict:
    payload = asdict(call)
    payload["signal_datetime"] = call.signal_datetime.isoformat()
    return payload


def deserialize_call(payload: dict) -> SwingCall:
    return SwingCall(
        source_message_id=int(payload["source_message_id"]),
        provider=str(payload["provider"]),
        ticker=str(payload["ticker"]),
        call_subtype=str(payload["call_subtype"]),
        entry=str(payload["entry"]),
        stop_loss=str(payload["stop_loss"]),
        targets=tuple(PriceTarget(item["number"], str(item["value"])) for item in payload["targets"]),
        signal_datetime=dt.datetime.fromisoformat(payload["signal_datetime"]),
        rationale=str(payload["rationale"]),
        advisor_name=payload.get("advisor_name"),
        advisor_role=payload.get("advisor_role"),
        has_source_chart=bool(payload["has_source_chart"]),
        event_kind=str(payload.get("event_kind", "BUY")),
        status=payload.get("status"),
        outcomes=tuple(str(outcome) for outcome in payload.get("outcomes", ())),
    )


def format_signal_datetime(value: dt.datetime) -> str:
    local = value.astimezone(WIB)
    return f"{local.day} {local:%b %Y %H:%M} WIB"


def escape_discord_markdown(value: str) -> str:
    return re.sub(r"([\\*_~`|\[])", r"\\\1", value)


def source_message_url(source_message_id: int) -> str:
    return f"{TELEGRAM_MESSAGE_BASE_URL}/{source_message_id}"


def format_analyst_byline(call: SwingCall) -> str:
    if call.advisor_name:
        return f"-# {escape_discord_markdown(call.advisor_name)}, Phintraco Sekuritas"
    return "-# Phintraco Sekuritas"


def format_swing_alert(call: SwingCall, *, include_board: bool = True) -> str:
    """Render a Phintraco source event through the shared cash-Swing shell."""
    body: tuple[str, ...] = ()
    message_fields: list[tuple[str, str]] = []
    status: str
    chart_unavailable = False
    if call.event_kind == "REMINDER":
        for target in call.targets:
            label = "Target" if target.number is None else f"Target {target.number}"
            message_fields.append((label, target.value))
        status = "; ".join(call.outcomes) or "Reminder"
        title = f"{call.ticker}: {status}"
    elif call.event_kind == "STATUS":
        if call.entry:
            message_fields.append(("Entry", call.entry))
        if call.stop_loss:
            message_fields.append(("Stop-loss", call.stop_loss))
        for target in call.targets:
            label = "Target" if target.number is None else f"Target {target.number}"
            message_fields.append((label, target.value))
        status = call.status or "Hold"
        title = f"{call.ticker}: {status}"
    else:
        is_sell = call.event_kind == "SELL"
        action = "Sell" if is_sell else "Buy"
        type_marker = DOWN_EMOJI if is_sell else UP_EMOJI
        message_fields.extend([
            ("Type", f"{call.call_subtype} {type_marker}"),
            ("Entry", call.entry),
            ("Stop-loss", call.stop_loss),
        ])
        for target in call.targets:
            label = "Target" if target.number is None else f"Target {target.number}"
            message_fields.append((label, target.value))
        message_fields.append(("Signal date", format_signal_datetime(call.signal_datetime)))
        body = ("", f"**Reasons:** {escape_discord_markdown(call.rationale)}")
        status = "New setup"
        title = f"{call.ticker}: {action}"
        chart_unavailable = not call.has_source_chart
    return render_message(
        SwingMessage(
            source_emoji=PHINTRACO_EMOJI,
            title=title,
            analyst_name=call.advisor_name,
            institution="Phintraco Sekuritas",
            fields=shared_fields(*message_fields),
            body=body,
            source_status=status,
            updated_at=call.signal_datetime,
            source_url=source_message_url(call.source_message_id),
            footer_label="View in Telegram",
            chart_unavailable=chart_unavailable,
        ),
        include_board=include_board,
    )


def _env(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value
    for env_file in (Path.home() / ".hermes" / ".env", Path.home() / "telegram-mcp" / ".env"):
        if not env_file.is_file():
            continue
        for raw in env_file.read_text().splitlines():
            if raw.startswith(key + "="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def make_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = _env("TELEGRAM_API_ID")
    api_hash = _env("TELEGRAM_API_HASH")
    session = _env("POLYCOP_SESSION_STRING")
    if not api_id or not api_hash or not session:
        raise RuntimeError("Telegram credentials are incomplete")
    return TelegramClient(StringSession(session), int(api_id), api_hash)


def resilience() -> PolyCopResilience:
    return PolyCopResilience.from_defaults()


def _connection_metadata(client: object) -> tuple[int | None, str | None]:
    session = getattr(client, "session", None)
    dc_id = getattr(session, "dc_id", None)
    endpoint = getattr(session, "server_address", None)
    port = getattr(session, "port", None)
    if isinstance(endpoint, str) and isinstance(port, int):
        endpoint = f"{endpoint}:{port}"
    return (dc_id if isinstance(dc_id, int) else None, endpoint if isinstance(endpoint, str) else None)


async def _is_client_authorized(client: object) -> bool:
    checker = getattr(client, "is_user_authorized", None)
    if checker is None:
        return True
    return bool(await checker())


async def _get_client_identity(client: object) -> object | None:
    getter = getattr(client, "get_me", None)
    return await getter() if getter is not None else None


async def _disconnect_quietly(client: object) -> None:
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        await disconnect()
    except Exception:
        pass


def deliver_resilience_notification(
    control: PolyCopResilience, now: dt.datetime, dry_run: bool
) -> None:
    try:
        notification = control.claim_notification(WATCHER_NAME, now)
    except ResilienceStateBlockedError:
        return
    if notification is None:
        return
    try:
        message_id = post_discord_text(
            notification.content,
            HEARTBEAT_CHANNEL_ID,
            dry_run,
            notification.event_key,
        )
    except Exception:
        return
    if message_id is None:
        return
    try:
        control.acknowledge_notification(notification.claim_id, now)
    except (ResilienceStateBlockedError, ValueError):
        return


def _report_resilience_state_blocked(now: dt.datetime, dry_run: bool) -> None:
    try:
        post_discord_text(
            f"❌ telegram-polycop · {now.astimezone(WIB):%H:%M} WIB · control state unavailable",
            HEARTBEAT_CHANNEL_ID,
            dry_run,
            f"telegram-resilience-state-blocked-{now.astimezone(WIB):%Y%m%d%H}",
        )
    except Exception:
        pass


async def resolve_source(client):
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if getattr(dialog.entity, "id", None) == SOURCE_CHANNEL_ID:
            return dialog.entity
    raise RuntimeError("Phintraco source channel is not accessible")


async def latest_source_message_id(client, entity) -> int:
    messages = await client.get_messages(entity, limit=1)
    return int(messages[0].id) if messages else 0


async def fetch_unseen_messages(client, entity, min_id: int) -> list:
    return [
        message
        async for message in client.iter_messages(entity, min_id=min_id, reverse=True)
    ]


def parse_source_event(message) -> SwingCall | None:
    source_id = int(message.id)
    source_text = message.message or ""
    source_posted_at = getattr(message, "date", None)
    event = parse_swing_call(
        source_id,
        source_text,
        has_photo=bool(message.photo),
        source_posted_at=source_posted_at,
    )
    if event is None:
        event = parse_swing_reminder(
            source_id,
            source_text,
            has_photo=bool(message.photo),
            source_posted_at=source_posted_at,
        )
    return event


async def parse_reply_status_event(client, entity, message) -> SwingCall | None:
    reply_to_message_id = getattr(message, "reply_to_msg_id", None)
    if not isinstance(reply_to_message_id, int) or reply_to_message_id <= 0:
        return None
    try:
        parent_message = await client.get_messages(entity, ids=reply_to_message_id)
    except Exception:
        return None
    if parent_message is None:
        return None
    return parse_reply_status(
        int(message.id),
        message.message or "",
        has_photo=bool(message.photo),
        source_posted_at=getattr(message, "date", None),
        parent=parse_source_event(parent_message),
    )


async def bootstrap_source(client, entity, state: dict, now: dt.datetime) -> bool:
    if int(state.get("observed_message_id", 0)) != 0:
        return False
    state["observed_message_id"] = await latest_source_message_id(client, entity)
    state["last_poll_success"] = current_time().isoformat()
    save_state(state)
    return True


async def ingest_unseen_messages(client, entity, state: dict, now: dt.datetime) -> tuple[int, int, int]:
    messages = await fetch_unseen_messages(client, entity, int(state.get("observed_message_id", 0)))
    call_count = 0
    malformed_count = 0
    for message in messages:
        source_id = int(message.id)
        source_text = message.message or ""
        call = parse_source_event(message)
        if call is None:
            call = await parse_reply_status_event(client, entity, message)
        if call is not None:
            enqueue_call(state, call, now)
            call_count += 1
            state["stats"]["calls"] = int(state["stats"].get("calls", 0)) + 1
        elif looks_like_swing_call(source_text):
            malformed_count += 1
        state["observed_message_id"] = source_id
        state["stats"]["messages"] = int(state["stats"].get("messages", 0)) + 1
        save_state(state)
    state["last_poll_success"] = current_time().isoformat()
    save_state(state)
    return len(messages), call_count, malformed_count


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_durable_directory(path: Path) -> None:
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(path, 0o700)
        _fsync_directory(path.parent)


def _write_durable_media(path: Path, content: bytes) -> None:
    temp = path.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temp.unlink(missing_ok=True)
        raise


def _cached_media_path(event: dict) -> Path | None:
    raw = event.get("media_path")
    if not raw:
        return None
    path = Path(raw)
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


async def capture_oldest_media(client, entity, state: dict, now: dt.datetime) -> bool:
    event = oldest_outbox_event(state)
    if event is None or event["phase"] != PHASE_PENDING_MEDIA_CAPTURE:
        return True
    if not retry_due(event, now):
        return False
    try:
        message = await client.get_messages(entity, ids=int(event["source_message_id"]))
        if message is None or not message.photo:
            raise RuntimeError("expected source chart is unavailable")
        content = await client.download_media(message, bytes)
        if not content:
            raise RuntimeError("source chart download returned no bytes")
        directory = media_dir()
        _ensure_durable_directory(directory)
        final = directory / f"phintraco-{event['source_message_id']}.jpg"
        _write_durable_media(final, content)
        event["media_path"] = str(final)
        event["chart_status"] = "captured"
        event["phase"] = (
            PHASE_PENDING_CHART if event.get("text_discord_id") else PHASE_PENDING_TEXT
        )
        clear_retry(event)
        save_state(state)
        return True
    except Exception as exc:
        schedule_retry(event, current_time(), str(exc))
        save_state(state)
        return False


def _discord_token() -> str | None:
    return _env("DISCORD_BOT_TOKEN")


def discord_nonce(event_key: str, leg: str) -> str:
    identity = f"{WATCHER_NAME}:{event_key}:{leg}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def _discord_request(method: str, url: str, *, headers: dict, max_retries: int = 3, **kwargs):
    import requests

    response = None
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        except Exception as exc:
            print(f"Discord request failed on attempt {attempt + 1}: {exc}", file=os.sys.stderr)
            if attempt + 1 < max_retries:
                time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 429:
            try:
                retry_after = float(response.json().get("retry_after", 1.0))
            except Exception:
                try:
                    retry_after = float(response.headers.get("Retry-After", 1.0))
                except Exception:
                    retry_after = 1.0
            if not math.isfinite(retry_after) or retry_after < 0:
                retry_after = 1.0
            raise DiscordRetryAfter(retry_after)
        return response
    return response


def post_discord_text(content: str, channel_id: str, dry_run: bool, event_key: str) -> str | None:
    if len(content) > 2000:
        raise ValueError("Swing Alert exceeds Discord message limit")
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(f"[dry-run] Discord text {channel_id} event {event_key}:\n{content}")
        return f"dry-text-{event_key}"
    token = _discord_token()
    if not token:
        return None
    response = _discord_request(
        "POST",
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={
            "content": content,
            "nonce": discord_nonce(event_key, "text"),
            "enforce_nonce": True,
        },
    )
    if response is None or response.status_code not in (200, 201):
        return None
    return str(response.json()["id"])


def post_discord_file(path: str, channel_id: str, dry_run: bool, event_key: str) -> str | None:
    file_path = Path(path)
    try:
        valid_file = file_path.is_file() and file_path.stat().st_size > 0
    except OSError:
        valid_file = False
    if not valid_file:
        return None
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(f"[dry-run] Discord chart {channel_id} event {event_key}: {file_path}")
        return f"dry-chart-{event_key}"
    token = _discord_token()
    if not token:
        return None
    payload = {
        "content": "",
        "nonce": discord_nonce(event_key, "chart"),
        "enforce_nonce": True,
    }
    with file_path.open("rb") as handle:
        response = _discord_request(
            "POST",
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            max_retries=1,
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": (file_path.name, handle, "image/jpeg")},
        )
    if response is None or response.status_code not in (200, 201):
        return None
    return str(response.json()["id"])


def board_event_payload(event: dict, call: SwingCall) -> tuple[dict, Path | None]:
    if call.event_kind == "BUY":
        kind = "buy"
        source_title = f"{call.ticker}: {call.call_subtype}"
        source_status = "New setup"
        plan = {
            "entry": call.entry,
            "stop_loss": call.stop_loss,
            "targets": [target.value for target in call.targets],
        }
    elif call.event_kind == "STATUS":
        kind = "status"
        source_status = call.status or "Source status update"
        source_title = f"{call.ticker}: {source_status}"
        plan = None
    elif call.event_kind == "REMINDER":
        kind = "reminder"
        source_status = "; ".join(call.outcomes)
        source_title = f"{call.ticker}: {source_status or 'Reminder'}"
        plan = None
    else:
        raise ValueError(f"unsupported board source event kind: {call.event_kind}")

    chart = _cached_media_path(event) if call.has_source_chart else None
    return (
        {
            "event_key": f"phintraco:{SOURCE_CHANNEL_ID}:{call.source_message_id}",
            "source": "phintraco",
            "kind": kind,
            "ticker": call.ticker,
            "published_at": call.signal_datetime.isoformat(),
            "source_url": source_message_url(call.source_message_id),
            "all_content": format_swing_alert(call, include_board=False),
            "source_title": source_title,
            "source_status": source_status,
            "plan": plan,
            "media_path": str(chart) if chart is not None else None,
            "media_urls": [],
        },
        chart,
    )


def _board_wrapper() -> str:
    return os.environ.get(
        "IDX_SWING_PLAN_BOARD_WRAPPER",
        str(Path.home() / ".hermes/scripts/idx-swing-plan-board.sh"),
    )


def submit_board_event(payload: dict, chart: Path | None, dry_run: bool) -> bool:
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(f"[dry-run] board source event {payload['event_key']}")
        return True
    # ``chart`` is deliberately passed separately from the event builder so
    # callers cannot accidentally hand the owner a stale or inferred path.
    submission = {**payload, "media_path": str(chart) if chart is not None else None}
    try:
        completed = subprocess.run(
            [_board_wrapper(), "submit-source-event", "--stdin"],
            input=json.dumps(submission, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    try:
        acknowledgement = json.loads(completed.stdout.strip())
        return (type(acknowledgement) is dict and set(acknowledgement) == {"accepted"}
                and acknowledgement["accepted"] is True)
    except (TypeError, ValueError):
        return False


def drain_board(dry_run: bool) -> bool:
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print("[dry-run] board drain")
        return True
    try:
        completed = subprocess.run(
            [_board_wrapper(), "drain"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        health = json.loads(completed.stdout.strip())
        return (completed.returncode == 0 and type(health) is dict
                and set(health) == {"drained", "pending", "failed"}
                and all(type(value) is int and value >= 0 for value in health.values())
                and health["pending"] == 0 and health["failed"] == 0)
    except (TypeError, ValueError):
        return False


def drain_outbox(state: dict, now: dt.datetime, dry_run: bool = False) -> int:
    _drain_all_outbox(state, now, dry_run)
    return _drain_board_outbox(state, now, dry_run)


def _drain_all_outbox(state: dict, now: dt.datetime, dry_run: bool) -> int:
    delivered = 0
    while True:
        event = oldest_outbox_event(state)
        if event is None:
            return delivered
        phase = event["phase"]
        if not retry_due(event, now):
            return delivered
        if phase == PHASE_PENDING_MEDIA_CAPTURE:
            return delivered
        call = deserialize_call(event["call"])

        if (
            phase == PHASE_PENDING_TEXT
            and call.has_source_chart
            and _cached_media_path(event) is None
        ):
            event["phase"] = PHASE_PENDING_MEDIA_CAPTURE
            event["chart_status"] = "expected"
            schedule_retry(
                event, current_time(), "cached source chart is missing or empty"
            )
            save_state(state)
            return delivered

        if phase == PHASE_PENDING_TEXT:
            try:
                text_id = post_discord_text(
                    format_swing_alert(call, include_board=True), ALERT_CHANNEL_ID, dry_run, event["event_key"]
                )
            except DiscordRetryAfter as exc:
                schedule_retry(
                    event,
                    current_time(),
                    str(exc),
                    minimum_delay_seconds=exc.retry_after,
                )
                save_state(state)
                return delivered
            except Exception as exc:
                schedule_retry(event, current_time(), str(exc))
                save_state(state)
                return delivered
            if text_id is None:
                schedule_retry(
                    event, current_time(), "Discord text delivery failed"
                )
                save_state(state)
                return delivered
            event["text_discord_id"] = text_id
            clear_retry(event)
            if call.has_source_chart:
                event["phase"] = PHASE_PENDING_CHART
                save_state(state)
                phase = PHASE_PENDING_CHART
            else:
                event["phase"] = PHASE_PENDING_BOARD
                save_state(state)
                phase = PHASE_PENDING_BOARD

        if phase == PHASE_PENDING_CHART:
            media_path = _cached_media_path(event)
            if media_path is None:
                event["phase"] = PHASE_PENDING_MEDIA_CAPTURE
                event["chart_status"] = "expected"
                schedule_retry(
                    event, current_time(), "cached source chart is missing or empty"
                )
                save_state(state)
                return delivered
            try:
                chart_id = post_discord_file(
                    str(media_path), ALERT_CHANNEL_ID, dry_run, event["event_key"]
                )
            except DiscordRetryAfter as exc:
                schedule_retry(
                    event,
                    current_time(),
                    str(exc),
                    minimum_delay_seconds=exc.retry_after,
                )
                save_state(state)
                return delivered
            except Exception as exc:
                schedule_retry(event, current_time(), str(exc))
                save_state(state)
                return delivered
            if chart_id is None:
                schedule_retry(
                    event, current_time(), "Discord chart delivery failed"
                )
                save_state(state)
                return delivered
            clear_retry(event)
            event["phase"] = PHASE_PENDING_BOARD
            save_state(state)
            phase = PHASE_PENDING_BOARD


def _drain_board_outbox(state: dict, now: dt.datetime, dry_run: bool) -> int:
    delivered = 0
    for key in sorted(list(state["outbox"]), key=int):
        event = state["outbox"][key]
        # Preserve source handoff order, without blocking the All queue.
        if event["phase"] not in {PHASE_PENDING_BOARD, PHASE_DELIVERED}:
            break
        if event["phase"] == PHASE_PENDING_BOARD:
            if not board_retry_due(event, now):
                break
            call = deserialize_call(event["call"])
            chart = _cached_media_path(event) if call.has_source_chart else None
            if call.has_source_chart and chart is None:
                schedule_board_retry(event, current_time(), "cached source chart is missing")
                save_state(state)
                return delivered
            try:
                payload, chart = board_event_payload(event, call)
                accepted = submit_board_event(payload, chart, dry_run)
            except Exception as exc:
                schedule_board_retry(event, current_time(), str(exc))
                save_state(state)
                return delivered
            if not accepted:
                schedule_board_retry(event, current_time(), "board source event was not accepted")
                save_state(state)
                return delivered
            event["board_submitted"] = True
            clear_board_retry(event)
            event["phase"] = PHASE_DELIVERED
            save_state(state)
        media_path = event.get("media_path")
        del state["outbox"][key]
        if event.get("board_submitted"):
            state["last_delivery_success"] = now.isoformat()
            state["stats"]["delivered"] = int(state["stats"].get("delivered", 0)) + 1
            delivered += 1
        save_state(state)
        if media_path:
            Path(media_path).unlink(missing_ok=True)
    return delivered


def heartbeat_hour_key(now: dt.datetime) -> str:
    local = now.astimezone(WIB)
    return local.strftime("%Y-%m-%dT%H") + local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:]


def format_heartbeat(now: dt.datetime, stats: RunStats) -> str:
    line = (
        f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · "
        f"{stats.messages} messages · {stats.calls} calls · "
        f"{stats.delivered} delivered · {stats.pending} pending"
    )
    return line + (" ⚠️" if stats.degraded else "")


def format_fatal(now: dt.datetime, reason: str) -> str:
    clean = re.sub(r"\s+", " ", reason).strip()[:180]
    return f"❌ {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {clean}"


def post_heartbeat_if_due(state: dict, now: dt.datetime, stats: RunStats, dry_run: bool) -> bool:
    hour = heartbeat_hour_key(now)
    if not os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT") and state.get("last_heartbeat_hour") == hour:
        return False
    message_id = post_discord_text(
        format_heartbeat(now, stats), HEARTBEAT_CHANNEL_ID, dry_run, f"heartbeat-{hour}"
    )
    if message_id is None:
        return False
    state["last_heartbeat_hour"] = hour
    save_state(state)
    return True


def error_fingerprint(reason: str) -> str:
    clean = re.sub(r"\s+", " ", reason).strip()
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def report_fatal(state: dict, now: dt.datetime, reason: str, dry_run: bool) -> bool:
    fingerprint = error_fingerprint(reason)
    hour = heartbeat_hour_key(now)
    previous = state.get("last_error_notice")
    fingerprints = []
    if type(previous) is dict and previous.get("hour") == hour:
        fingerprints = list(previous.get("fingerprints") or [])
    if fingerprint in fingerprints:
        return False
    message_id = post_discord_text(
        format_fatal(now, reason),
        HEARTBEAT_CHANNEL_ID,
        dry_run,
        f"fatal-{fingerprint}-{hour}",
    )
    if message_id is None:
        return False
    fingerprints.append(fingerprint)
    state["last_error_notice"] = {
        "hour": hour,
        "fingerprints": fingerprints[-MAX_FATAL_FINGERPRINTS_PER_HOUR:],
    }
    save_state(state)
    return True


def _report_fatal_best_effort(
    _state: dict, now: dt.datetime, reason: str, dry_run: bool
) -> bool:
    try:
        with run_lock() as acquired:
            if not acquired:
                return False
            try:
                latest_state = load_state()
            except StateBlockedError as blocked:
                latest_state = blocked.state
            return report_fatal(latest_state, now, reason, dry_run)
    except Exception:
        return False


async def run(now: dt.datetime | None = None, dry_run: bool = False) -> dict:
    now = now or dt.datetime.now(WIB)
    with run_lock() as acquired:
        if not acquired:
            return {"wakeAgent": False}
        control = resilience()
        decision = await acquire_probe_after_active_lease(control, WATCHER_NAME, now)
        if decision.kind == "state_blocked":
            _report_resilience_state_blocked(now, dry_run)
            return {"wakeAgent": False}
        if decision.kind != "probe":
            deliver_resilience_notification(control, now, dry_run)
            return {"wakeAgent": False}

        client = make_client()
        try:
            await client.connect()
            if not await _is_client_authorized(client):
                control.record_auth_required(decision.lease_id, WATCHER_NAME, now)
                deliver_resilience_notification(control, now, dry_run)
                await _disconnect_quietly(client)
                return {"wakeAgent": False}
            await _get_client_identity(client)
            dc_id, endpoint = _connection_metadata(client)
            control.record_authenticated_success(
                decision.lease_id, WATCHER_NAME, now, dc_id, endpoint
            )
            deliver_resilience_notification(control, now, dry_run)
        except Exception as error:
            if is_transport_error(error):
                control.record_transport_failure(
                    decision.lease_id, WATCHER_NAME, error, now
                )
                deliver_resilience_notification(control, now, dry_run)
                await _disconnect_quietly(client)
                return {"wakeAgent": False}
            await _disconnect_quietly(client)
            raise

        state = load_state()
        state["stats"]["runs"] = int(state["stats"].get("runs", 0)) + 1
        messages = calls = malformed = delivered = 0
        degraded = False
        try:
            entity = await resolve_source(client)
            if await bootstrap_source(client, entity, state, now):
                degraded = not drain_board(dry_run)
                stats = RunStats(0, 0, 0, 0, degraded)
                post_heartbeat_if_due(state, now, stats, dry_run)
                return {"wakeAgent": False}

            messages, calls, malformed = await ingest_unseen_messages(client, entity, state, now)
            degraded = degraded or malformed > 0
            while True:
                event = oldest_outbox_event(state)
                if event is None:
                    break
                if event["phase"] == PHASE_PENDING_BOARD:
                    due = board_retry_due(event, now)
                else:
                    due = event["phase"] == PHASE_DELIVERED or retry_due(event, now)
                if not due:
                    break
                if event["phase"] == PHASE_PENDING_MEDIA_CAPTURE:
                    if not await capture_oldest_media(client, entity, state, now):
                        degraded = True
                        break
                before = (event["event_key"], event["phase"])
                delivered += drain_outbox(state, now, dry_run=dry_run)
                current = oldest_outbox_event(state)
                if current is not None and (current["event_key"], current["phase"]) == before:
                    degraded = True
                    break
            state["last_poll_success"] = current_time().isoformat()
            save_state(state)
        finally:
            await client.disconnect()

        # Service retained board handoffs even when no All work was due.
        delivered += drain_outbox(state, now, dry_run=dry_run)
        board_healthy = drain_board(dry_run)
        degraded = degraded or not board_healthy
        pending = len(state.get("outbox") or {})
        degraded = degraded or pending > 0
        stats = RunStats(messages, calls, delivered, pending, degraded)
        post_heartbeat_if_due(state, now, stats, dry_run)
        return {"wakeAgent": False}


def main() -> int:
    dry_run = os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1"
    now = dt.datetime.now(WIB)
    try:
        result = asyncio.run(run(now=now, dry_run=dry_run))
    except StateBlockedError as exc:
        _report_fatal_best_effort(exc.state, now, str(exc), dry_run)
        result = {"wakeAgent": False, "error": str(exc)}
    except Exception as exc:
        _report_fatal_best_effort(empty_state(), now, str(exc), dry_run)
        result = {"wakeAgent": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
