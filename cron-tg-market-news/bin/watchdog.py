#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

import scan
import state as durable_state

WIB = ZoneInfo("Asia/Jakarta")
MAX_GAP_MINUTES = 10
_METADATA_VERSION = 1
_METADATA_FILENAME = "watchdog-notices.json"


def _state_path() -> Path:
    configured = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "state.json"


def watchdog_metadata_path() -> Path:
    return _state_path().with_name(_METADATA_FILENAME)


def empty_watchdog_metadata() -> dict[str, object]:
    return {"version": _METADATA_VERSION, "last_error_notice": None}


def load_scanner_state_read_only() -> dict[str, object]:
    """Read and validate scanner state without invoking migration or any write path."""
    path = _state_path()
    if not path.exists():
        return durable_state.empty_state()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return durable_state.empty_state()
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise durable_state.StateBlockedError("malformed state: JSON cannot be decoded") from error
    durable_state._validate_state(loaded)
    return loaded


def load_watchdog_metadata() -> dict[str, object]:
    path = watchdog_metadata_path()
    if not path.exists():
        return empty_watchdog_metadata()
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or set(metadata) != {"version", "last_error_notice"}:
            raise ValueError("invalid watchdog metadata")
        if metadata["version"] != _METADATA_VERSION:
            raise ValueError("unsupported watchdog metadata version")
        notice = metadata["last_error_notice"]
        if notice is not None and (
            not isinstance(notice, dict)
            or not isinstance(notice.get("hour"), str)
            or not isinstance(notice.get("fingerprints"), list)
            or any(not isinstance(value, str) for value in notice["fingerprints"])
        ):
            raise ValueError("invalid watchdog notice metadata")
        return metadata
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_watchdog_metadata()


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_watchdog_metadata(metadata: Mapping[str, object]) -> None:
    path = watchdog_metadata_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(dict(metadata), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def is_stale(state: Mapping[str, object], now: datetime, max_gap_minutes: int = MAX_GAP_MINUTES) -> bool:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    raw = state.get("last_poll_success")
    if not isinstance(raw, str):
        return True
    try:
        last_success = datetime.fromisoformat(raw)
        if last_success.tzinfo is None or last_success.utcoffset() is None:
            return True
    except ValueError:
        return True
    return now.astimezone(WIB) - last_success.astimezone(WIB) > timedelta(minutes=max_gap_minutes)


def report_watchdog_fatal(
    now: datetime,
    reason: str,
    dry_run: bool,
    *,
    delivery_client: object | None = None,
) -> bool:
    metadata = load_watchdog_metadata()
    fingerprint = scan.error_fingerprint(reason)
    hour = scan._hour_key(now)
    previous = metadata.get("last_error_notice")
    fingerprints: list[str] = []
    if isinstance(previous, dict) and previous.get("hour") == hour:
        raw = previous.get("fingerprints")
        if isinstance(raw, list):
            fingerprints = [value for value in raw if isinstance(value, str)]
    if fingerprint in fingerprints:
        return False
    if delivery_client is None and not dry_run:
        delivery_client = scan.delivery_client_from_environment()
    if scan.post_hermes_text(
        scan.format_fatal(now, reason),
        f"watchdog-fatal-{fingerprint}-{hour}",
        dry_run,
        delivery_client=delivery_client,
    ) is None:
        return False
    fingerprints.append(fingerprint)
    metadata["last_error_notice"] = {"hour": hour, "fingerprints": fingerprints[-64:]}
    save_watchdog_metadata(metadata)
    return True


def _report_best_effort(now: datetime, reason: str, dry_run: bool) -> None:
    try:
        report_watchdog_fatal(now, reason, dry_run)
    except Exception:
        pass


def main() -> int:
    now = datetime.now(WIB)
    dry_run = os.environ.get("IDX_MARKET_NEWS_NO_POST") == "1"
    try:
        scanner_state = load_scanner_state_read_only()
    except Exception as error:
        _report_best_effort(now, f"watchdog cannot read state: {error}", dry_run)
        return 1
    if not is_stale(scanner_state, now):
        return 0
    _report_best_effort(now, f"no successful Telegram poll within {MAX_GAP_MINUTES} minutes", dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
