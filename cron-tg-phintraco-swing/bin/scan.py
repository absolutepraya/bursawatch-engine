#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import importlib.util
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
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from zoneinfo import ZoneInfo

_CONFIG_MODULE_NAME = "bursawatch_tg_phintraco_swing_config"
config = sys.modules.get(_CONFIG_MODULE_NAME)
if config is None:
    _CONFIG_SPEC = importlib.util.spec_from_file_location(
        _CONFIG_MODULE_NAME,
        Path(__file__).with_name("config.py"),
    )
    if _CONFIG_SPEC is None or _CONFIG_SPEC.loader is None:
        raise RuntimeError("Phintraco config module is unavailable")
    config = importlib.util.module_from_spec(_CONFIG_SPEC)
    sys.modules[_CONFIG_MODULE_NAME] = config
    _CONFIG_SPEC.loader.exec_module(config)

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

_DISCORD_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DISCORD_DELIVERY_BIN.exists():
    _DISCORD_DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DISCORD_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DISCORD_DELIVERY_BIN))

from swing_format import (
    SwingMessage,
    fields as shared_fields,
    render_message,
    render_message_unbounded,
    replace_board_topic_link,
)
from bursawatch_discord_delivery import Attachment, DeliveryClient, DiscordQuery, OperationIntent, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError

from telegram_resilience import (
    PolyCopResilience,
    StateBlockedError as ResilienceStateBlockedError,
    acquire_probe_after_active_lease,
    is_transport_error,
)

try:
    from control_plane_runtime import ControlPlaneRun
except ModuleNotFoundError:
    class ControlPlaneRun:
        @classmethod
        def begin(cls, *_args, **_kwargs):
            return cls()

        def event(self, *_args, **_kwargs):
            pass

        def finish(self, *_args, **_kwargs):
            pass

WIB = ZoneInfo("Asia/Jakarta")
_DEFAULT_WATCH_CONFIG = config.default_watch_config()
# Compatibility defaults for isolated parser and watchdog tests. Runtime calls
# resolve destinations and source identity from one activated config snapshot.
SOURCE_CHANNEL_ID = _DEFAULT_WATCH_CONFIG.telegram_channel_id
ALERT_CHANNEL_ID = _DEFAULT_WATCH_CONFIG.alert_discord_channel_id
HEARTBEAT_CHANNEL_ID = _DEFAULT_WATCH_CONFIG.heartbeat_discord_channel_id
PROVIDER = "Phintraco"
PHINTRACO_EMOJI = "<:phintraco:1531272488645038091>"
UP_EMOJI = "<:up:1531285100346740766>"
DOWN_EMOJI = "<:down:1531285063986053200>"
ALLOWED_SUBTYPES = (
    "Trading Buy",
    "Hold/Trading Buy",
    "Buy on Support",
    "Speculative Buy",
)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

STATE_VERSION = 4
PHASE_PENDING_MEDIA_CAPTURE = "pending_media_capture"
PHASE_PENDING_SOURCE_MEDIA = "pending_source_media"
PHASE_PENDING_TEXT = "pending_text"
PHASE_PENDING_CHART = "pending_chart"
PHASE_PENDING_BOARD = "pending_board"
PHASE_DELIVERED = "delivered"
MAX_WEEKLY_PDF_BYTES = 8 * 1024 * 1024
WEEKLY_PDF_PREFIX = "PHINTAS Weekly Swing Trading Ideas_"
WEEKLY_PDF_FILENAME_RE = re.compile(
    r"^PHINTAS Weekly Swing Trading Ideas_\d{8}\.pdf$"
)
WEEKLY_TEXT_COMPANION_RE = re.compile(
    r"\bweekly\s+swing(?:\s+trading)?\s+ideas?\b",
    re.IGNORECASE,
)
PDF_EVENT_KEY_RE = re.compile(r"^pdf:(\d+):([A-Z]{4})$")
BOARD_PDF_EVENT_KEY_RE = re.compile(r"^phintraco:(\d+):weekly:(\d+):([A-Z]{4})$")
MAX_FATAL_FINGERPRINTS_PER_HOUR = 64
MAX_RETRY_SECONDS = 15 * 60
WATCHER_NAME = "bursawatch-tg-phintraco-swing"
WATCHER_HEARTBEAT_NAME = "bursawatch-tg-phintraco-swing"
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"

_REQUIRED_STATE_FIELDS = (
    "version",
    "blocked",
    "block_reason",
    "observed_message_id",
    "outbox",
    "pdf_batches",
    "source_plans",
    "quarantined_documents",
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
    "delivery_order",
    "pdf_batch_id",
    "source_page",
    "source_section",
    "pdf_sha256",
    "pdf_path",
    "chart_path",
    "call",
    "phase",
    "chart_status",
    "media_path",
    "text_discord_id",
    "attempts",
    "next_attempt_at",
    "last_error",
    "board_submitted",
    "matched_setup_event_key",
    "board_kind_override",
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
    "source_text",
)
_CALL_STRING_FIELDS = (
    "provider",
    "ticker",
    "call_subtype",
    "entry",
    "stop_loss",
    "rationale",
    "event_kind",
    "source_text",
)
_EVENT_PHASES = {
    PHASE_PENDING_MEDIA_CAPTURE,
    PHASE_PENDING_SOURCE_MEDIA,
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
        "pdf_batches": {},
        "source_plans": {},
        "quarantined_documents": {},
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
    if type(key) is not str:
        raise ValueError("outbox keys must be strings")
    is_legacy = key.isascii() and key.isdigit()
    pdf_key = PDF_EVENT_KEY_RE.fullmatch(key)
    if not is_legacy and pdf_key is None:
        raise ValueError("outbox keys must be decimal IDs or PDF ticker event keys")
    event = _require_fields(payload, _REQUIRED_EVENT_FIELDS, f"outbox event {key}")
    _validate_call_payload(event["call"], event["source_message_id"] if type(event["source_message_id"]) is int else -1)
    if type(event["event_key"]) is not str or event["event_key"] != key:
        raise ValueError(f"outbox event {key} event_key must match its key")
    if type(event["source_message_id"]) is not int or event["source_message_id"] <= 0:
        raise ValueError(f"outbox event {key} source_message_id must be a positive integer")
    if is_legacy and str(event["source_message_id"]) != key:
        raise ValueError(f"outbox event {key} source_message_id must match its key")
    if type(event["delivery_order"]) is not int or event["delivery_order"] < 0:
        raise ValueError(f"outbox event {key} delivery_order must be a non-negative integer")
    if event["pdf_batch_id"] is not None and type(event["pdf_batch_id"]) is not str:
        raise ValueError(f"outbox event {key} pdf_batch_id must be a string or null")
    for field in ("source_page", "source_section"):
        if event[field] is not None and (type(event[field]) is not int or event[field] <= 0):
            raise ValueError(f"outbox event {key} {field} must be a positive integer or null")
    for field in ("pdf_sha256", "pdf_path", "chart_path"):
        if event[field] is not None and type(event[field]) is not str:
            raise ValueError(f"outbox event {key} {field} must be a string or null")
    if is_legacy:
        if any(event[field] is not None for field in ("pdf_batch_id", "source_page", "source_section", "pdf_sha256", "pdf_path", "chart_path")):
            raise ValueError(f"outbox event {key} has unexpected PDF metadata")
        if event["delivery_order"] != 0:
            raise ValueError(f"outbox event {key} legacy delivery_order must be zero")
    else:
        pdf_message_id, ticker = pdf_key.groups()
        if (
            event["source_message_id"] != int(pdf_message_id)
            or event["pdf_batch_id"] != pdf_message_id
            or event["source_page"] is None
            or event["source_section"] is None
            or not isinstance(event["pdf_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", event["pdf_sha256"]) is None
            or not event["pdf_path"]
            or not event["chart_path"]
            or type(event["delivery_order"]) is not int
            or event["delivery_order"] <= 0
        ):
            raise ValueError(f"outbox event {key} has incomplete PDF metadata")
        if event["call"].get("ticker") != ticker:
            raise ValueError(f"outbox event {key} ticker must match its call")
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
    if event["matched_setup_event_key"] is not None and (
        type(event["matched_setup_event_key"]) is not str
        or BOARD_PDF_EVENT_KEY_RE.fullmatch(event["matched_setup_event_key"]) is None
    ):
        raise ValueError(f"outbox event {key} matched_setup_event_key is invalid")
    if event["board_kind_override"] not in {None, "context"}:
        raise ValueError(f"outbox event {key} board_kind_override is invalid")
    if event["board_kind_override"] == "context" and event["call"]["event_kind"] not in {"STATUS", "REMINDER"}:
        raise ValueError(f"outbox event {key} context override requires an update event")
    if event["matched_setup_event_key"] is not None and event["board_kind_override"] is not None:
        raise ValueError(f"outbox event {key} cannot be both matched and source context")
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


def _validate_target_list(payload: object, label: str) -> None:
    if type(payload) is not list:
        raise ValueError(f"{label} must be a list")
    for target in payload:
        target = _require_fields(target, ("number", "value"), label + " target")
        if target["number"] is not None and (type(target["number"]) is not int or not 1 <= target["number"] <= 6):
            raise ValueError(f"{label} target number must be between 1 and 6 or null")
        if type(target["value"]) is not str or not target["value"]:
            raise ValueError(f"{label} target value must be a non-empty string")


def _validate_source_media_record(payload: object, kind: str, label: str) -> None:
    if payload is None:
        return
    record = _require_fields(
        payload,
        ("ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"),
        f"{label} source media",
    )
    if type(record["ref"]) is not str or re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        record["ref"],
    ) is None:
        raise ValueError(f"{label} source media reference is invalid")
    if type(record["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None:
        raise ValueError(f"{label} source media digest is invalid")
    if record["kind"] != kind:
        raise ValueError(f"{label} source media kind is invalid")
    expected_content_type = "application/pdf" if kind == "document" else "image/jpeg"
    if record["content_type"] != expected_content_type:
        raise ValueError(f"{label} source media content type is invalid")
    if type(record["size_bytes"]) is not int or not 1 <= record["size_bytes"] <= MAX_WEEKLY_PDF_BYTES:
        raise ValueError(f"{label} source media size is invalid")
    if type(record["filename"]) is not str or not record["filename"] or len(record["filename"]) > 240:
        raise ValueError(f"{label} source media filename is invalid")
    if record["durable"] is not True:
        raise ValueError(f"{label} source media reference is not durable")


def _validate_pdf_indexes(state: dict) -> None:
    batches = state["pdf_batches"]
    plans = state["source_plans"]
    quarantined = state["quarantined_documents"]
    for label, collection in (
        ("pdf_batches", batches),
        ("source_plans", plans),
        ("quarantined_documents", quarantined),
    ):
        if type(collection) is not dict:
            raise ValueError(f"state {label} must be an object")

    batch_fields = (
        "source_message_id",
        "filename",
        "mime_type",
        "published_at",
        "report_date",
        "pdf_sha256",
        "pdf_path",
        "event_keys",
        "quarantined_pages",
        "source_media",
        "status",
    )
    for key, raw in batches.items():
        if type(key) is not str or not key.isascii() or not key.isdigit():
            raise ValueError("PDF batch keys must be decimal source message IDs")
        batch = _require_fields(raw, batch_fields, f"PDF batch {key}")
        if type(batch["source_message_id"]) is not int or str(batch["source_message_id"]) != key:
            raise ValueError(f"PDF batch {key} source ID must match its key")
        if any(type(batch[field]) is not str or not batch[field] for field in ("filename", "mime_type", "pdf_path")):
            raise ValueError(f"PDF batch {key} filename, MIME type, and path must be non-empty strings")
        _parse_aware_datetime(batch["published_at"], f"PDF batch {key} published_at")
        try:
            dt.date.fromisoformat(batch["report_date"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"PDF batch {key} report_date is invalid") from exc
        if type(batch["pdf_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", batch["pdf_sha256"]) is None:
            raise ValueError(f"PDF batch {key} digest is invalid")
        event_keys = batch["event_keys"]
        if type(event_keys) is not list or len(set(event_keys)) != len(event_keys):
            raise ValueError(f"PDF batch {key} event_keys must be a unique list")
        for event_key in event_keys:
            match = PDF_EVENT_KEY_RE.fullmatch(event_key) if type(event_key) is str else None
            if match is None or match.group(1) != key:
                raise ValueError(f"PDF batch {key} has an invalid child event key")
        pages = batch["quarantined_pages"]
        if type(pages) is not list:
            raise ValueError(f"PDF batch {key} quarantined_pages must be a list")
        for page in pages:
            page = _require_fields(page, ("page_number", "reason"), f"PDF batch {key} quarantined page")
            if type(page["page_number"]) is not int or page["page_number"] <= 0:
                raise ValueError(f"PDF batch {key} quarantine page number is invalid")
            if type(page["reason"]) is not str or not page["reason"] or len(page["reason"]) > 200:
                raise ValueError(f"PDF batch {key} quarantine reason is invalid")
        if batch["status"] not in {"ready", "degraded"}:
            raise ValueError(f"PDF batch {key} status is invalid")
        if bool(pages) != (batch["status"] == "degraded"):
            raise ValueError(f"PDF batch {key} status does not match its page quarantine list")
        _validate_source_media_record(batch["source_media"], "document", f"PDF batch {key}")

    plan_fields = (
        "event_key", "ticker", "descriptor", "trend", "ma_indicator",
        "potential_upside", "potential_downside", "entry", "stop_loss", "targets",
        "signal_datetime", "document_message_id", "page_number", "section_number",
        "pdf_sha256", "pdf_path", "chart_path", "chart_sha256", "report_date", "source_media",
    )
    for key, raw in plans.items():
        match = PDF_EVENT_KEY_RE.fullmatch(key) if type(key) is str else None
        if match is None:
            raise ValueError("source plan keys must be PDF ticker event keys")
        plan = _require_fields(raw, plan_fields, f"source plan {key}")
        if (
            plan["event_key"] != key
            or type(plan["ticker"]) is not str
            or plan["ticker"] != match.group(2)
        ):
            raise ValueError(f"source plan {key} identity fields do not match its key")
        for field in ("descriptor", "trend", "ma_indicator", "potential_upside", "potential_downside", "entry", "stop_loss", "pdf_path", "chart_path"):
            if type(plan[field]) is not str:
                raise ValueError(f"source plan {key} {field} must be a string")
        _validate_target_list(plan["targets"], f"source plan {key} targets")
        _parse_aware_datetime(plan["signal_datetime"], f"source plan {key} signal_datetime")
        if type(plan["document_message_id"]) is not int or plan["document_message_id"] != int(match.group(1)):
            raise ValueError(f"source plan {key} document ID does not match its key")
        for field in ("page_number", "section_number"):
            if type(plan[field]) is not int or plan[field] <= 0:
                raise ValueError(f"source plan {key} {field} must be positive")
        if type(plan["pdf_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", plan["pdf_sha256"]) is None:
            raise ValueError(f"source plan {key} PDF digest is invalid")
        if plan["chart_sha256"] is not None and (
            type(plan["chart_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", plan["chart_sha256"]) is None
        ):
            raise ValueError(f"source plan {key} chart digest is invalid")
        try:
            dt.date.fromisoformat(plan["report_date"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"source plan {key} report_date is invalid") from exc
        _validate_source_media_record(plan["source_media"], "image", f"source plan {key}")

    quarantine_fields = ("source_message_id", "filename", "mime_type", "reason", "observed_at", "pdf_sha256", "pdf_path")
    for key, raw in quarantined.items():
        if type(key) is not str or not key.isascii() or not key.isdigit():
            raise ValueError("quarantined document keys must be decimal source message IDs")
        item = _require_fields(raw, quarantine_fields, f"quarantined document {key}")
        if type(item["source_message_id"]) is not int or str(item["source_message_id"]) != key:
            raise ValueError(f"quarantined document {key} source ID must match its key")
        for field in ("filename", "mime_type", "reason"):
            if type(item[field]) is not str or len(item[field]) > 240:
                raise ValueError(f"quarantined document {key} {field} is invalid")
        if not item["reason"]:
            raise ValueError(f"quarantined document {key} reason must not be empty")
        _parse_aware_datetime(item["observed_at"], f"quarantined document {key} observed_at")
        if item["pdf_sha256"] is not None and (
            type(item["pdf_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", item["pdf_sha256"]) is None
        ):
            raise ValueError(f"quarantined document {key} digest is invalid")
        if item["pdf_path"] is not None and type(item["pdf_path"]) is not str:
            raise ValueError(f"quarantined document {key} path must be a string or null")

    if set(batches).intersection(quarantined):
        raise ValueError("a source message cannot be both a PDF batch and quarantined document")
    event_to_batch: dict[str, str] = {}
    for batch_id, batch in batches.items():
        for event_key in batch["event_keys"]:
            if event_key in event_to_batch:
                raise ValueError(f"PDF event {event_key} belongs to multiple batches")
            event_to_batch[event_key] = batch_id
            plan = plans.get(event_key)
            if plan is None:
                raise ValueError(f"PDF batch {batch_id} is missing source plan {event_key}")
            if (
                plan["document_message_id"] != batch["source_message_id"]
                or plan["pdf_sha256"] != batch["pdf_sha256"]
                or plan["pdf_path"] != batch["pdf_path"]
                or plan["report_date"] != batch["report_date"]
            ):
                raise ValueError(f"PDF source plan {event_key} does not match its batch")
    if set(plans) != set(event_to_batch):
        raise ValueError("source plans and PDF batch child keys do not match")
    for event_key, batch_id in event_to_batch.items():
        event = state["outbox"].get(event_key)
        if event is not None and (
            event["pdf_batch_id"] != batch_id
            or event["pdf_sha256"] != batches[batch_id]["pdf_sha256"]
            or event["pdf_path"] != batches[batch_id]["pdf_path"]
            or event["chart_path"] != plans[event_key]["chart_path"]
        ):
            raise ValueError(f"PDF outbox event {event_key} does not match its source plan")
    for event_key in state["outbox"]:
        if PDF_EVENT_KEY_RE.fullmatch(event_key) and event_key not in event_to_batch:
            raise ValueError(f"PDF outbox event {event_key} has no source plan")
    for event_key, event in state["outbox"].items():
        matched = event["matched_setup_event_key"]
        if matched is None:
            continue
        parsed = BOARD_PDF_EVENT_KEY_RE.fullmatch(matched)
        if parsed is None:
            raise ValueError(f"outbox event {event_key} has an invalid linked Board setup")
        _channel_id, document_id, ticker = parsed.groups()
        source_plan = plans.get(f"pdf:{document_id}:{ticker}")
        if source_plan is None or source_plan["document_message_id"] != int(document_id):
            raise ValueError(f"outbox event {event_key} links to a missing PDF source plan")


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
    _validate_pdf_indexes(state)
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
    if version not in {1, 2, 3}:
        raise ValueError(f"unsupported state version: {version}")

    outbox = payload.get("outbox")
    if type(outbox) is not dict:
        raise ValueError("state outbox must be an object")
    if version == 1:
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
        payload["version"] = 2

    for field in ("pdf_batches", "source_plans", "quarantined_documents"):
        payload.setdefault(field, {})
    for event in outbox.values():
        if type(event) is not dict:
            raise ValueError("outbox event must be an object")
        event.setdefault("delivery_order", 0)
        event.setdefault("pdf_batch_id", None)
        event.setdefault("source_page", None)
        event.setdefault("source_section", None)
        event.setdefault("pdf_sha256", None)
        event.setdefault("pdf_path", None)
        event.setdefault("chart_path", None)
        event.setdefault("matched_setup_event_key", None)
        event.setdefault("board_kind_override", None)
        call = event.get("call")
        if type(call) is not dict:
            raise ValueError("outbox call must be an object")
        call.setdefault("source_text", "")
    for batch in payload["pdf_batches"].values():
        if type(batch) is not dict:
            raise ValueError("PDF batch must be an object")
        batch.setdefault("source_media", None)
    for plan in payload["source_plans"].values():
        if type(plan) is not dict:
            raise ValueError("source plan must be an object")
        plan.setdefault("chart_sha256", None)
        plan.setdefault("source_media", None)
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


def enqueue_call(
    state: dict,
    call: SwingCall,
    now: dt.datetime,
    *,
    event_key: str | None = None,
    delivery_order: int = 0,
    pdf_batch_id: str | None = None,
) -> dict:
    key = event_key or str(call.source_message_id)
    existing = state.setdefault("outbox", {}).get(key)
    if existing is not None:
        return existing
    has_chart = call.has_source_chart
    event = {
        "event_key": key,
        "source_message_id": call.source_message_id,
        "delivery_order": delivery_order,
        "pdf_batch_id": pdf_batch_id,
        "source_page": None,
        "source_section": None,
        "pdf_sha256": None,
        "pdf_path": None,
        "chart_path": None,
        "call": serialize_call(call),
        "phase": PHASE_PENDING_MEDIA_CAPTURE if has_chart else PHASE_PENDING_TEXT,
        "chart_status": "expected" if has_chart else "absent",
        "media_path": None,
        "text_discord_id": None,
        "attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
        "board_submitted": False,
        "matched_setup_event_key": None,
        "board_kind_override": None,
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
    key = min(
        outbox,
        key=lambda value: (
            outbox[value]["source_message_id"],
            outbox[value]["delivery_order"],
            outbox[value]["event_key"],
        ),
    )
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
    r"(?P<subtype>Trading Buy|Hold/Trading Buy|Buy on Support|Speculative Buy)\s*:\s*"
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
    r"\b(?:(?P<ordinal>first|second|third|fourth|fifth|sixth|\d+(?:st|nd|rd|th))\s+)?"
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
    source_text: str = ""


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
        source_text=normalized,
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
        source_text=normalize_text(text),
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
        source_text=normalize_text(text),
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
        source_text=str(payload.get("source_text", "")),
    )


def format_signal_datetime(value: dt.datetime) -> str:
    local = value.astimezone(WIB)
    return f"{local.day} {local:%b %Y %H:%M} WIB"


def escape_discord_markdown(value: str) -> str:
    return re.sub(r"([\\*_~`|\[])", r"\\\1", value)


def source_message_url(source_message_id: int) -> str:
    return f"https://t.me/{config.active_watch_config().telegram_username}/{source_message_id}"


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


def format_source_context(call: SwingCall) -> str:
    source_text = call.source_text or format_swing_alert(call, include_board=False)
    return render_message_unbounded(
        SwingMessage(
            source_emoji=PHINTRACO_EMOJI,
            title=f"{call.ticker}: Source context",
            analyst_name=call.advisor_name,
            institution="Phintraco Sekuritas",
            fields=shared_fields(("Published", format_signal_datetime(call.signal_datetime))),
            body=("", f"**Source text:** {escape_discord_markdown(source_text)}"),
            source_status="Source context",
            updated_at=call.signal_datetime,
            source_url=source_message_url(call.source_message_id),
            footer_label="View in Telegram",
        ),
        include_board=False,
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


def source_media_client():
    base_url = _env("BURSAWATCH_SOURCE_MEDIA_URL")
    token_file = _env("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    if not base_url or not token_file:
        raise RuntimeError("Source Media Owner upload configuration is unavailable")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
    if not local.exists():
        local = Path.home() / ".agents" / "skills" / "lib-bursawatch-source-media" / "bin"
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))
    from bursawatch_source_media import SourceMediaClient

    return SourceMediaClient(base_url, Path(token_file))


def _source_media_metadata(payload: dict, kind: str, label: str) -> dict:
    _validate_source_media_record(payload, kind, label)
    return {
        "ref": payload["ref"],
        "sha256": payload["sha256"],
        "kind": payload["kind"],
        "content_type": payload["content_type"],
        "size_bytes": payload["size_bytes"],
        "filename": payload["filename"],
        "durable": payload["durable"],
    }


def _upload_pdf_source_media(state: dict, event: dict) -> None:
    batch = state["pdf_batches"].get(event["pdf_batch_id"])
    plan = state["source_plans"].get(event["event_key"])
    if batch is None or plan is None:
        raise RuntimeError("weekly PDF source media index is incomplete")

    client = source_media_client()
    channel_id = config.active_watch_config().telegram_channel_id
    message_id = batch["source_message_id"]

    if batch["source_media"] is None:
        try:
            pdf_bytes = Path(batch["pdf_path"]).read_bytes()
        except OSError:
            raise RuntimeError("cached weekly PDF is unavailable") from None
        if (
            not pdf_bytes
            or len(pdf_bytes) > MAX_WEEKLY_PDF_BYTES
            or hashlib.sha256(pdf_bytes).hexdigest() != batch["pdf_sha256"]
        ):
            raise RuntimeError("cached weekly PDF failed its digest check")
        result = client.upload(
            f"telegram:channel:{channel_id}:message:{message_id}:weekly-pdf",
            pdf_bytes,
            kind="document",
            content_type="application/pdf",
            filename=Path(batch["pdf_path"]).name,
        )
        metadata = _source_media_metadata(result, "document", "weekly PDF")
        if metadata["sha256"] != batch["pdf_sha256"]:
            raise RuntimeError("Source Media Owner returned an unexpected weekly PDF digest")
        batch["source_media"] = metadata
        save_state(state)

    if plan["source_media"] is None:
        try:
            chart_bytes = Path(plan["chart_path"]).read_bytes()
        except OSError:
            raise RuntimeError("cached weekly chart is unavailable") from None
        chart_digest = hashlib.sha256(chart_bytes).hexdigest() if chart_bytes else None
        if (
            not chart_bytes
            or len(chart_bytes) > MAX_WEEKLY_PDF_BYTES
            or (plan["chart_sha256"] is not None and chart_digest != plan["chart_sha256"])
        ):
            raise RuntimeError("cached weekly chart failed its size or digest check")
        if plan["chart_sha256"] is None:
            plan["chart_sha256"] = chart_digest
            save_state(state)
        result = client.upload(
            f"telegram:channel:{channel_id}:message:{message_id}:weekly-chart:{plan['ticker']}",
            chart_bytes,
            kind="image",
            content_type="image/jpeg",
            filename=Path(plan["chart_path"]).name,
        )
        metadata = _source_media_metadata(result, "image", "weekly chart")
        if metadata["sha256"] != plan["chart_sha256"]:
            raise RuntimeError("Source Media Owner returned an unexpected weekly chart digest")
        plan["source_media"] = metadata
        save_state(state)

    if event["phase"] == PHASE_PENDING_SOURCE_MEDIA:
        event["phase"] = PHASE_PENDING_TEXT
        clear_retry(event)
        save_state(state)


def _canonical_price_number(value: str) -> int | None:
    match = re.fullmatch(r"\s*([0-9][0-9.,]*)\s*", value)
    if match is None:
        return None
    digits = re.sub(r"[.,]", "", match.group(1))
    return int(digits) if digits else None


def _source_price_matches(source_value: str, reported_value: str) -> bool:
    normalized = normalize_price(source_value).casefold().replace("–", " to ").replace("—", " to ")
    reported_normalized = normalize_price(reported_value).casefold()
    compact_source = re.sub(r"\s+", "", normalized)
    compact_reported = re.sub(r"\s+", "", reported_normalized)
    if compact_source == compact_reported:
        return True
    reported = _canonical_price_number(reported_value)
    if reported is None:
        return False
    numbers = re.findall(r"[0-9][0-9.,]*", normalized)
    values = [_canonical_price_number(value) for value in numbers]
    if any(value is None for value in values):
        return False
    if re.search(r"\bto\b", normalized) and len(values) == 2:
        low, high = sorted(values)
        return low <= reported <= high
    return len(values) == 1 and values[0] == reported


def _target_ordinal(value: str | None) -> int | None:
    if value is None:
        return None
    named = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
    }
    folded = value.casefold()
    if folded in named:
        return named[folded]
    match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)", folded)
    return int(match.group(1)) if match and 1 <= int(match.group(1)) <= 6 else None


def _update_matches_plan(call: SwingCall, plan: dict, *, direct_pdf_reply: bool) -> bool:
    plan_time = _parse_aware_datetime(plan["signal_datetime"], "source plan signal_datetime")
    if call.signal_datetime <= plan_time:
        return False
    if call.entry and not _source_price_matches(plan["entry"], call.entry):
        return False
    if call.stop_loss and not _source_price_matches(plan["stop_loss"], call.stop_loss):
        return False

    targets = plan["targets"]
    numbered_targets = {
        target["number"]: target
        for target in targets
        if target["number"] is not None
    }
    highest_number = max(numbered_targets, default=0)
    has_anchor = False
    for reported in call.targets:
        if reported.number is None:
            matches = [target for target in targets if _source_price_matches(target["value"], reported.value)]
            if len(matches) != 1:
                return False
            has_anchor = True
            continue
        source_target = numbered_targets.get(reported.number)
        if source_target is not None:
            if not _source_price_matches(source_target["value"], reported.value):
                return False
            has_anchor = True
            continue
        if reported.number == highest_number + 1 and 1 <= reported.number <= 6:
            # A contiguous next target may be an explicit amendment. It is not
            # evidence of plan identity by itself.
            continue
        return False

    for outcome in call.outcomes:
        achieved = TARGET_ACHIEVED_RE.search(outcome)
        if achieved is None:
            continue
        ordinal = _target_ordinal(achieved.group("ordinal"))
        reported_value = achieved.group("value")
        if ordinal is not None:
            source_target = numbered_targets.get(ordinal)
            if source_target is None or not _source_price_matches(source_target["value"], reported_value):
                return False
            has_anchor = True
        else:
            matches = [target for target in targets if _source_price_matches(target["value"], reported_value)]
            if len(matches) != 1:
                return False
            has_anchor = True

    return direct_pdf_reply or has_anchor


def match_source_plan(
    call: SwingCall, state: dict, reply_parent_id: int | None
) -> str | None:
    if call.event_kind not in {"STATUS", "REMINDER"}:
        return None
    plans = state.get("source_plans")
    if type(plans) is not dict:
        return None
    pdf_parent = reply_parent_id is not None and any(
        plan.get("document_message_id") == reply_parent_id
        for plan in plans.values()
        if type(plan) is dict
    )
    candidates = []
    for key, plan in plans.items():
        if type(plan) is not dict or plan.get("ticker") != call.ticker:
            continue
        if pdf_parent and plan.get("document_message_id") != reply_parent_id:
            continue
        if _update_matches_plan(call, plan, direct_pdf_reply=pdf_parent):
            candidates.append(key)
    if len(candidates) != 1:
        return None
    plan = plans[candidates[0]]
    channel_id = config.active_watch_config().telegram_channel_id
    return f"phintraco:{channel_id}:weekly:{plan['document_message_id']}:{plan['ticker']}"


def _update_references_pdf_plan(
    call: SwingCall, state: dict, reply_parent_id: int | None
) -> bool:
    if call.event_kind not in {"STATUS", "REMINDER"}:
        return False
    if reply_parent_id is not None and str(reply_parent_id) in state.get("pdf_batches", {}):
        return True
    return any(
        type(plan) is dict and plan.get("ticker") == call.ticker
        for plan in state.get("source_plans", {}).values()
    )


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
            config.active_watch_config().heartbeat_discord_channel_id,
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
            config.active_watch_config().heartbeat_discord_channel_id,
            dry_run,
            f"telegram-resilience-state-blocked-{now.astimezone(WIB):%Y%m%d%H}",
        )
    except Exception:
        pass


async def resolve_source(client):
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if getattr(dialog.entity, "id", None) == config.active_watch_config().telegram_channel_id:
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


def parse_weekly_pdf(filename: str, pdf_bytes: bytes):
    """Load the optional PDF parser only when a weekly attachment is received."""
    try:
        from weekly_pdf import parse_weekly_pdf as parse
    except ImportError as exc:
        raise RuntimeError("PyMuPDF weekly PDF parser dependency is unavailable") from exc
    return parse(filename, pdf_bytes)


def _weekly_document_filename(message) -> str | None:
    file_info = getattr(message, "file", None)
    filename = getattr(file_info, "name", None)
    if isinstance(filename, str) and filename:
        return filename
    document = getattr(message, "document", None)
    for attribute in getattr(document, "attributes", ()) or ():
        filename = getattr(attribute, "file_name", None)
        if isinstance(filename, str) and filename:
            return filename
    return None


def _is_weekly_text_companion(message) -> bool:
    text = normalize_text(getattr(message, "message", "") or "")
    heading_lines = [line for line in text.splitlines() if line][:2]
    return any(WEEKLY_TEXT_COMPANION_RE.search(line) for line in heading_lines)


def _record_quarantined_document(
    state: dict,
    source_message_id: int,
    filename: str,
    mime_type: str,
    reason: str,
    observed_at: dt.datetime,
    *,
    pdf_sha256: str | None = None,
    pdf_path: str | None = None,
) -> bool:
    key = str(source_message_id)
    if key in state["quarantined_documents"] or key in state["pdf_batches"]:
        return False
    state["quarantined_documents"][key] = {
        "source_message_id": source_message_id,
        "filename": filename[:240],
        "mime_type": mime_type[:240],
        "reason": re.sub(r"\s+", " ", reason).strip()[:240],
        "observed_at": observed_at.isoformat(),
        "pdf_sha256": pdf_sha256,
        "pdf_path": pdf_path,
    }
    return True


def _weekly_setup_call(
    setup, message_id: int, published_at: dt.datetime, report_date: dt.date
) -> SwingCall:
    context = [
        "Weekly Swing Trading Ideas",
        f"Report date: {report_date.day} {report_date:%b %Y}",
        setup.descriptor,
    ]
    if setup.trend:
        context.append(f"Trend: {setup.trend}")
    if setup.ma_indicator:
        context.append(f"MA indicator: {setup.ma_indicator}")
    if setup.potential_upside:
        context.append(f"Potential upside: {setup.potential_upside}")
    if setup.potential_downside:
        context.append(f"Potential downside: {setup.potential_downside}")
    return SwingCall(
        source_message_id=message_id,
        provider=PROVIDER,
        ticker=setup.ticker,
        call_subtype="Trading Buy",
        entry=setup.entry,
        stop_loss=setup.stop_loss,
        targets=tuple(PriceTarget(target.number, target.value) for target in setup.targets),
        signal_datetime=published_at,
        rationale=". ".join(context),
        advisor_name="Investment Advisory Team",
        advisor_role="Investment Advisory Team",
        has_source_chart=True,
        source_text=". ".join(context),
    )


async def _ingest_weekly_pdf_document(
    client, message, state: dict, now: dt.datetime
) -> tuple[bool, int, int]:
    document = getattr(message, "document", None)
    if document is None:
        return False, 0, 0
    filename = _weekly_document_filename(message) or ""
    if not filename.startswith(WEEKLY_PDF_PREFIX):
        return False, 0, 0

    source_message_id = int(message.id)
    batch_id = str(source_message_id)
    if batch_id in state["pdf_batches"] or batch_id in state["quarantined_documents"]:
        return True, 0, 0
    mime_type = getattr(document, "mime_type", None)
    mime_type = mime_type if isinstance(mime_type, str) else ""
    if not WEEKLY_PDF_FILENAME_RE.fullmatch(filename):
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF filename is outside the supported format", now,
        )
        return True, 0, int(created)
    if mime_type.casefold() != "application/pdf":
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly attachment is not an application/pdf document", now,
        )
        return True, 0, int(created)

    content = await client.download_media(message, bytes)
    if not isinstance(content, bytes) or not content:
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF download returned no bytes", now,
        )
        return True, 0, int(created)
    pdf_digest = hashlib.sha256(content).hexdigest()
    if len(content) > MAX_WEEKLY_PDF_BYTES:
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF exceeds the 8 MiB size limit", now, pdf_sha256=pdf_digest,
        )
        return True, 0, int(created)

    directory = media_dir()
    _ensure_durable_directory(directory)
    pdf_path = directory / f"phintraco-weekly-{source_message_id}.pdf"
    _write_durable_media(pdf_path, content)
    raw_published_at = getattr(message, "date", None)
    if (
        not isinstance(raw_published_at, dt.datetime)
        or raw_published_at.tzinfo is None
        or raw_published_at.utcoffset() is None
    ):
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF has no timezone-aware Telegram publication time", now,
            pdf_sha256=pdf_digest, pdf_path=str(pdf_path),
        )
        return True, 0, int(created)
    published_at = raw_published_at.astimezone(WIB)

    try:
        parsed = parse_weekly_pdf(filename, content)
    except ValueError as exc:
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            str(exc) or "weekly PDF could not be parsed", now,
            pdf_sha256=pdf_digest, pdf_path=str(pdf_path),
        )
        return True, 0, int(created)

    setups = tuple(parsed.setups)
    quarantined_pages = [
        {"page_number": page.page_number, "reason": page.reason}
        for page in parsed.quarantined_pages
    ]
    if len(setups) > 24 or len({setup.ticker for setup in setups}) != len(setups):
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF parser returned duplicate or excessive ticker plans", now,
            pdf_sha256=pdf_digest, pdf_path=str(pdf_path),
        )
        return True, 0, int(created)
    if not setups and not quarantined_pages:
        created = _record_quarantined_document(
            state, source_message_id, filename, mime_type,
            "weekly PDF contains no validated ticker plans", now,
            pdf_sha256=pdf_digest, pdf_path=str(pdf_path),
        )
        return True, 0, int(created)

    event_keys: list[str] = []
    new_calls = 0
    for delivery_order, setup in enumerate(setups, start=1):
        event_key = f"pdf:{source_message_id}:{setup.ticker}"
        chart_path = directory / f"phintraco-weekly-{source_message_id}-{setup.ticker}.jpg"
        _write_durable_media(chart_path, setup.chart_bytes)
        call = _weekly_setup_call(setup, source_message_id, published_at, parsed.report_date)
        event = enqueue_call(
            state,
            call,
            now,
            event_key=event_key,
            delivery_order=delivery_order,
            pdf_batch_id=batch_id,
        )
        event.update(
            source_page=setup.page_number,
            source_section=setup.section_number,
            pdf_sha256=pdf_digest,
            pdf_path=str(pdf_path),
            chart_path=str(chart_path),
            media_path=str(chart_path),
            chart_status="captured",
            phase=PHASE_PENDING_SOURCE_MEDIA,
        )
        targets = [{"number": target.number, "value": target.value} for target in setup.targets]
        state["source_plans"][event_key] = {
            "event_key": event_key,
            "ticker": setup.ticker,
            "descriptor": setup.descriptor,
            "trend": setup.trend,
            "ma_indicator": setup.ma_indicator,
            "potential_upside": setup.potential_upside,
            "potential_downside": setup.potential_downside,
            "entry": setup.entry,
            "stop_loss": setup.stop_loss,
            "targets": targets,
            "signal_datetime": published_at.isoformat(),
            "document_message_id": source_message_id,
            "page_number": setup.page_number,
            "section_number": setup.section_number,
            "pdf_sha256": pdf_digest,
            "pdf_path": str(pdf_path),
            "chart_path": str(chart_path),
            "chart_sha256": hashlib.sha256(setup.chart_bytes).hexdigest(),
            "report_date": parsed.report_date.isoformat(),
            "source_media": None,
        }
        event_keys.append(event_key)
        new_calls += 1

    state["pdf_batches"][batch_id] = {
        "source_message_id": source_message_id,
        "filename": filename,
        "mime_type": mime_type,
        "published_at": published_at.isoformat(),
        "report_date": parsed.report_date.isoformat(),
        "pdf_sha256": pdf_digest,
        "pdf_path": str(pdf_path),
        "event_keys": event_keys,
        "quarantined_pages": quarantined_pages,
        "source_media": None,
        "status": "degraded" if quarantined_pages else "ready",
    }
    return True, new_calls, int(bool(quarantined_pages))


async def parse_reply_status_event(client, entity, message, state: dict | None = None) -> SwingCall | None:
    reply_to_message_id = getattr(message, "reply_to_msg_id", None)
    if not isinstance(reply_to_message_id, int) or reply_to_message_id <= 0:
        return None
    try:
        parent_message = await client.get_messages(entity, ids=reply_to_message_id)
    except Exception:
        return None
    if parent_message is None:
        return None
    parent_call = parse_source_event(parent_message)
    if parent_call is None and state is not None:
        reply = REPLY_STATUS_RE.match(normalize_text(message.message or ""))
        if reply is not None:
            matching_plans = [
                plan
                for plan in state.get("source_plans", {}).values()
                if type(plan) is dict
                and plan.get("document_message_id") == reply_to_message_id
                and plan.get("ticker") == reply.group("ticker").upper()
            ]
            if len(matching_plans) == 1:
                plan = matching_plans[0]
                parent_call = SwingCall(
                    source_message_id=reply_to_message_id,
                    provider=PROVIDER,
                    ticker=plan["ticker"],
                    call_subtype="Trading Buy",
                    entry=plan["entry"],
                    stop_loss=plan["stop_loss"],
                    targets=tuple(
                        PriceTarget(item["number"], item["value"])
                        for item in plan["targets"]
                    ),
                    signal_datetime=dt.datetime.fromisoformat(plan["signal_datetime"]),
                    rationale=plan["descriptor"],
                    advisor_name="Investment Advisory Team",
                    advisor_role="Investment Advisory Team",
                    has_source_chart=True,
                    source_text="",
                )
    return parse_reply_status(
        int(message.id),
        message.message or "",
        has_photo=bool(message.photo),
        source_posted_at=getattr(message, "date", None),
        parent=parent_call,
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
        handled_pdf, pdf_calls, pdf_malformed = await _ingest_weekly_pdf_document(
            client, message, state, now
        )
        if handled_pdf:
            message_calls = pdf_calls
            message_malformed = pdf_malformed
        elif _is_weekly_text_companion(message):
            message_calls = 0
            message_malformed = 0
        else:
            call = parse_source_event(message)
            if call is None:
                call = await parse_reply_status_event(client, entity, message, state)
            if call is not None:
                event = enqueue_call(state, call, now)
                reply_parent_id = getattr(message, "reply_to_msg_id", None)
                matched_setup_event_key = match_source_plan(
                    call,
                    state,
                    reply_parent_id if type(reply_parent_id) is int else None,
                )
                if matched_setup_event_key is not None:
                    event["matched_setup_event_key"] = matched_setup_event_key
                elif _update_references_pdf_plan(
                    call,
                    state,
                    reply_parent_id if type(reply_parent_id) is int else None,
                ):
                    event["board_kind_override"] = "context"
                message_calls = 1
                message_malformed = 0
            else:
                message_calls = 0
                message_malformed = int(looks_like_swing_call(source_text))
        call_count += message_calls
        malformed_count += message_malformed
        state["stats"]["calls"] = int(state["stats"].get("calls", 0)) + message_calls
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


def discord_nonce(event_key: str, leg: str) -> str:
    identity = f"{WATCHER_NAME}:{event_key}:{leg}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


_DELIVERY_OWNER_PREFIX = "bursawatch-tg-phintraco-swing"
_DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
_DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
_NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


def delivery_client_from_environment(*, include_admin: bool = False) -> DeliveryClient:
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", _DELIVERY_OWNER_URL)
    token_path = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / _DELIVERY_CLIENT_TOKEN_FILE),
        )
    ).expanduser()
    admin_path = None
    if include_admin:
        configured = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured:
            raise DeliveryClientError("admin_credentials_required")
        admin_path = Path(configured).expanduser()
    return DeliveryClient(base_url, token_path, admin_token_file=admin_path)


def _operation_key(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("delivery identity requires a nonempty source event and leg")
    normalized = re.sub(
        r"[^A-Za-z0-9:_./-]",
        lambda match: f"_u{ord(match.group()):04x}_",
        f"{event_key}:{leg}",
    )
    key = f"{_DELIVERY_OWNER_PREFIX}:{normalized}"
    if len(key) > 200:
        raise ValueError("delivery operation identity is too long")
    return key


def _channel_message_operation(
    content: str,
    channel_id: str,
    event_key: str,
    *,
    leg: str,
    attachments: tuple[Attachment, ...] = (),
) -> OperationIntent:
    if len(content) > 2000:
        raise ValueError("Swing Alert exceeds Discord message limit")
    return OperationIntent(
        key=_operation_key(event_key, leg),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=attachments,
    )


def _submit_or_lookup(
    operation: OperationIntent,
    client: object,
    *,
    legacy_import_nonce: str | None = None,
) -> OperationReceipt:
    receipt = client.status(operation.key)  # type: ignore[attr-defined]
    from_existing_status = receipt is not None
    if not from_existing_status:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    expected_digest = operation.digest
    if isinstance(receipt, OperationReceipt) and receipt.key == operation.key and receipt.digest != operation.digest:
        if not from_existing_status or legacy_import_nonce is None:
            raise DeliveryClientError("invalid_response")
        imported = replace(
            operation,
            reconcile_before_first_create=True,
            legacy_nonce=legacy_import_nonce,
        )
        if receipt.digest != imported.digest:
            raise DeliveryClientError("invalid_response")
        expected_digest = imported.digest
    if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
        raise DeliveryClientError("invalid_response")
    if receipt.status in _NON_TERMINAL_DELIVERY_STATUSES:
        receipt = client.wait(operation.key, 0)  # type: ignore[attr-defined]
        if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
            raise DeliveryClientError("invalid_response")
    return receipt


def _delivered_message_id(receipt: OperationReceipt, operation: OperationIntent) -> str | None:
    if receipt.status != "delivered" or not isinstance(receipt.receipt, dict):
        return None
    if receipt.receipt.get("channel_id") not in (None, operation.target["channel_id"]):
        raise DeliveryClientError("invalid_response")
    message_id = receipt.receipt.get("message_id")
    return message_id if isinstance(message_id, str) and message_id.isdigit() else None


def post_discord_text(
    content: str,
    channel_id: str,
    dry_run: bool,
    event_key: str,
    *,
    client: object | None = None,
) -> str | None:
    if len(content) > 2000:
        raise ValueError("Swing Alert exceeds Discord message limit")
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(f"[dry-run] Discord text {channel_id} event {event_key}:\n{content}")
        return f"dry-text-{event_key}"
    operation = _channel_message_operation(content, channel_id, event_key, leg="text")
    owner = client if client is not None else delivery_client_from_environment()
    try:
        receipt = _submit_or_lookup(
            operation,
            owner,
            legacy_import_nonce=discord_nonce(event_key, "text"),
        )
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRetryAfter(60.0) from None
        raise
    return _delivered_message_id(receipt, operation)


def _read_channel_message_content(client: object, channel_id: str, message_id: str) -> str | None:
    try:
        target_id = int(message_id)
    except (TypeError, ValueError):
        return None
    cursor = str(target_id + 1)
    while True:
        result = client.query(  # type: ignore[attr-defined]
            DiscordQuery(kind="channel_messages", channel_id=channel_id, before=cursor, limit=100)
        )
        messages = result.get("messages") if isinstance(result, dict) else result
        if not isinstance(messages, list):
            return None
        if not messages:
            return None
        ids: list[int] = []
        for item in messages:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isdigit():
                return None
            ids.append(int(item["id"]))
            if item["id"] == message_id:
                content = item.get("content")
                return content if isinstance(content, str) else None
        oldest = min(ids)
        if oldest <= target_id:
            return None
        next_cursor = str(oldest)
        if next_cursor == cursor:
            return None
        cursor = next_cursor


def edit_discord_board_link(
    message_id: str | None,
    board_url: str | None,
    dry_run: bool,
    event_key: str,
    *,
    client: object | None = None,
) -> bool:
    """Replace the generic forum-channel marker in one delivered All message."""
    if not message_id or not board_url:
        return True
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(
            f"[dry-run] Discord board link {config.active_watch_config().alert_discord_channel_id}/{message_id} "
            f"-> {board_url} event {event_key}"
        )
        return True
    channel_id = config.active_watch_config().alert_discord_channel_id
    owner = client if client is not None else delivery_client_from_environment()
    current = _read_channel_message_content(owner, channel_id, message_id)
    if current is None:
        return False
    updated = replace_board_topic_link(current, board_url)
    if updated == current:
        return True
    operation = OperationIntent(
        key=_operation_key(event_key, "board-link"),
        kind="channel_message_edit",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id, "message_id": message_id},
        payload={"content": updated, "allowed_mentions": {"parse": []}},
    )
    try:
        receipt = _submit_or_lookup(operation, owner)
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRetryAfter(60.0) from None
        raise
    return receipt.status == "delivered"


def post_discord_file(
    path: str,
    channel_id: str,
    dry_run: bool,
    event_key: str,
    *,
    client: object | None = None,
) -> str | None:
    file_path = Path(path)
    try:
        if not file_path.is_file() or file_path.stat().st_size == 0:
            return None
        content = file_path.read_bytes()
    except OSError:
        return None
    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
        print(f"[dry-run] Discord chart {channel_id} event {event_key}: {file_path}")
        return f"dry-chart-{event_key}"
    operation = _channel_message_operation(
        "",
        channel_id,
        event_key,
        leg="chart",
        attachments=(Attachment(file_path.name, "image/jpeg", content),),
    )
    owner = client if client is not None else delivery_client_from_environment()
    try:
        receipt = _submit_or_lookup(
            operation,
            owner,
            legacy_import_nonce=discord_nonce(event_key, "chart"),
        )
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRetryAfter(60.0) from None
        raise
    return _delivered_message_id(receipt, operation)


def board_event_payload(event: dict, call: SwingCall) -> tuple[dict, Path | None]:
    is_context = event.get("board_kind_override") == "context"
    if is_context:
        kind = "context"
        source_status = None
        source_title = f"{call.ticker}: Source context"
        plan = None
    elif call.event_kind == "BUY":
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
    channel_id = config.active_watch_config().telegram_channel_id
    if event.get("pdf_batch_id") is not None:
        board_event_key = f"phintraco:{channel_id}:weekly:{call.source_message_id}:{call.ticker}"
    else:
        board_event_key = f"phintraco:{channel_id}:{call.source_message_id}"
    payload = {
        "event_key": board_event_key,
        "source": "phintraco",
        "kind": kind,
        "ticker": call.ticker,
        "published_at": call.signal_datetime.isoformat(),
        "source_url": source_message_url(call.source_message_id),
        "all_content": format_source_context(call) if is_context else format_swing_alert(call, include_board=False),
        "source_title": source_title,
        "source_status": source_status,
        "plan": plan,
        "media_path": str(chart) if chart is not None else None,
        "media_urls": [],
    }
    if event.get("matched_setup_event_key") is not None:
        payload["matched_setup_event_key"] = event["matched_setup_event_key"]
    return payload, chart


def _board_wrapper() -> str:
    return os.environ.get(
        "IDX_SWING_PLAN_BOARD_WRAPPER",
        str(Path.home() / ".hermes/scripts/bursawatch-dc-swing-board.sh"),
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
        if (type(acknowledgement) is not dict
                or set(acknowledgement) not in ({"accepted"}, {"accepted", "board_url"}, {"accepted", "board_url", "board_pending"})
                or type(acknowledgement.get("accepted")) is not bool
                or acknowledgement["accepted"] is not True):
            return False
        board_url = acknowledgement.get("board_url")
        if board_url is not None and (type(board_url) is not str or not board_url):
            return False
        board_pending = acknowledgement.get("board_pending", False)
        if type(board_pending) is not bool:
            return False
        # Keep the public helper's boolean contract for existing adapters and
        # tests, while handing the deep link to the caller without adding it
        # to the event sent to the owner.
        payload["_board_url"] = board_url
        payload["_board_pending"] = board_pending
        return True
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
        if event.get("pdf_batch_id") is not None:
            batch = state["pdf_batches"].get(event["pdf_batch_id"])
            plan = state["source_plans"].get(event["event_key"])
            if batch is None or plan is None:
                schedule_retry(event, current_time(), "weekly PDF source media index is incomplete")
                save_state(state)
                return delivered
            if batch.get("source_media") is None or plan.get("source_media") is None:
                if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
                    print(f"[dry-run] source media upload {event['event_key']}")
                    return delivered
                try:
                    _upload_pdf_source_media(state, event)
                except Exception as exc:
                    schedule_retry(event, current_time(), str(exc))
                    save_state(state)
                    return delivered
                phase = event["phase"]
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
                    format_swing_alert(call, include_board=True),
                    config.active_watch_config().alert_discord_channel_id,
                    dry_run,
                    event["event_key"],
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
                    str(media_path),
                    config.active_watch_config().alert_discord_channel_id,
                    dry_run,
                    event["event_key"],
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
    ordered_keys = sorted(
        list(state["outbox"]),
        key=lambda key: (
            state["outbox"][key]["source_message_id"],
            state["outbox"][key]["delivery_order"],
            state["outbox"][key]["event_key"],
        ),
    )
    for key in ordered_keys:
        event = state["outbox"][key]
        # Preserve source handoff order, without blocking the All queue.
        if event["phase"] not in {PHASE_PENDING_BOARD, PHASE_DELIVERED}:
            break
        if event["phase"] == PHASE_PENDING_BOARD:
            if not board_retry_due(event, now):
                break
            call = deserialize_call(event["call"])
            if event.get("pdf_batch_id") is not None:
                batch = state["pdf_batches"].get(event["pdf_batch_id"])
                plan = state["source_plans"].get(event["event_key"])
                if batch is None or plan is None:
                    schedule_board_retry(event, current_time(), "weekly PDF source media index is incomplete")
                    save_state(state)
                    return delivered
                if batch.get("source_media") is None or plan.get("source_media") is None:
                    if dry_run or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1":
                        print(f"[dry-run] source media upload {event['event_key']}")
                        break
                    try:
                        _upload_pdf_source_media(state, event)
                    except Exception as exc:
                        schedule_board_retry(event, current_time(), str(exc))
                        save_state(state)
                        return delivered
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
            if payload.get("_board_pending"):
                schedule_board_retry(event, current_time(), "board topic is not materialized yet")
                save_state(state)
                return delivered
            if not edit_discord_board_link(
                event.get("text_discord_id"), payload.get("_board_url"), dry_run, event["event_key"]
            ):
                schedule_board_retry(event, current_time(), "All Swing board link update failed")
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
        format_heartbeat(now, stats),
        config.active_watch_config().heartbeat_discord_channel_id,
        dry_run,
        f"heartbeat-{hour}",
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
        config.active_watch_config().heartbeat_discord_channel_id,
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
    """Run once against one frozen operator configuration snapshot."""
    now = now or dt.datetime.now(WIB)
    loaded_config = config.load_watch_config_for_run()
    with config.activate_watch_config(loaded_config.config):
        return await _run_loaded_config(now, dry_run, loaded_config)


async def _run_loaded_config(
    now: dt.datetime,
    dry_run: bool,
    loaded_config: config.LoadedWatchConfig,
) -> dict:
    with run_lock() as acquired:
        if not acquired:
            return {"wakeAgent": False}
        control_run = ControlPlaneRun.begin(
            "IDX_SWING_WATCH_PHINTRACO_DAILY",
            loaded_config.revision,
            scheduler_job_id="bursawatch-tg-phintraco-swing",
        )
        control_run.event(
            "run-started",
            level="info",
            phase="lifecycle",
            event_type="run.started",
            message="Phintraco Swing watcher run started",
            attributes={"config_revision": loaded_config.revision, "no_post": dry_run},
        )
        messages = calls = malformed = delivered = pending = 0
        degraded = False
        outcome = "failed"
        failure: str | None = None
        try:
            control = resilience()
            decision = await acquire_probe_after_active_lease(control, WATCHER_NAME, now)
            if decision.kind == "state_blocked":
                _report_resilience_state_blocked(now, dry_run)
                outcome = "blocked"
                return {"wakeAgent": False}
            if decision.kind != "probe":
                deliver_resilience_notification(control, now, dry_run)
                outcome = "blocked"
                return {"wakeAgent": False}
            client = make_client()
            try:
                await client.connect()
                if not await _is_client_authorized(client):
                    control.record_auth_required(decision.lease_id, WATCHER_NAME, now)
                    deliver_resilience_notification(control, now, dry_run)
                    await _disconnect_quietly(client)
                    outcome = "blocked"
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
                    outcome = "blocked"
                    return {"wakeAgent": False}
                await _disconnect_quietly(client)
                raise

            try:
                state = load_state()
                state["stats"]["runs"] = int(state["stats"].get("runs", 0)) + 1
                entity = await resolve_source(client)
                if await bootstrap_source(client, entity, state, now):
                    degraded = not drain_board(dry_run)
                    pending = len(state.get("outbox") or {})
                    outcome = "degraded" if degraded else "ok"
                    return {"wakeAgent": False}

                messages, calls, malformed = await ingest_unseen_messages(client, entity, state, now)
                degraded = degraded or malformed > 0
                control_run.event(
                    "source-poll-completed",
                    level="warning" if malformed else "info",
                    phase="source",
                    event_type="source.poll.completed",
                    message="Phintraco source poll completed",
                    attributes={"messages": messages, "calls": calls, "malformed": malformed},
                )
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
                await _disconnect_quietly(client)

            # Service retained board handoffs even when no All work was due.
            delivered += drain_outbox(state, now, dry_run=dry_run)
            board_healthy = drain_board(dry_run)
            degraded = degraded or not board_healthy
            pending = len(state.get("outbox") or {})
            degraded = degraded or pending > 0
            stats = RunStats(messages, calls, delivered, pending, degraded)
            post_heartbeat_if_due(state, now, stats, dry_run)
            control_run.event(
                "delivery-drain-completed",
                level="warning" if degraded else "info",
                phase="delivery",
                event_type="delivery.drain.completed",
                message="Phintraco delivery and board drain completed",
                attributes={
                    "delivered": delivered,
                    "pending": pending,
                    "board_healthy": board_healthy,
                },
            )
            outcome = "degraded" if degraded else "ok"
            return {"wakeAgent": False}
        except Exception as exc:
            failure = re.sub(r"\s+", " ", str(exc)).strip()[:500]
            control_run.event(
                "run-failed",
                level="fatal",
                phase="lifecycle",
                event_type="run.failed",
                message="Phintraco Swing watcher run failed",
                attributes={"error": failure},
            )
            raise
        finally:
            control_run.event(
                "run-completed",
                level="warning" if outcome in {"blocked", "degraded"} else "info",
                phase="lifecycle",
                event_type="run.completed",
                message=f"Phintraco Swing watcher run {outcome}",
                attributes={
                    "messages": messages,
                    "calls": calls,
                    "malformed": malformed,
                    "delivered": delivered,
                    "pending": pending,
                    "config_revision": loaded_config.revision,
                },
            )
            control_run.finish(outcome, failure)


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
