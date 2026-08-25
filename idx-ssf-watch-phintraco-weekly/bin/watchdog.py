#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

import scan

WIB = ZoneInfo("Asia/Jakarta")
MAX_GAP_MINUTES = 65
WATCHER_HEARTBEAT_NAME = "idx-ssf"
WATCHDOG_METADATA_VERSION = 1
WATCHDOG_METADATA_FILENAME = "watchdog-notices.json"


def watchdog_metadata_path() -> Path:
    return scan._state_path().parent / WATCHDOG_METADATA_FILENAME


def empty_watchdog_metadata() -> dict[str, Any]:
    return {"version": WATCHDOG_METADATA_VERSION, "last_error_notice": None}


def load_scanner_state_read_only() -> dict[str, Any]:
    path = scan._state_path()
    if not path.exists():
        return scan.empty_state()
    try:
        return scan._validate_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception as error:
        raise scan.StateBlockedError("unable to read state") from error


def load_watchdog_metadata() -> dict[str, Any]:
    path = watchdog_metadata_path()
    try:
        if not path.exists():
            return empty_watchdog_metadata()
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("version") != WATCHDOG_METADATA_VERSION
            or "last_error_notice" not in metadata
        ):
            raise ValueError("unsupported watchdog metadata")
        return metadata
    except Exception:
        return empty_watchdog_metadata()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_watchdog_metadata(metadata: dict[str, Any]) -> None:
    path = watchdog_metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(metadata, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def is_stale(
    state: dict[str, Any], now: datetime, max_gap_minutes: int = MAX_GAP_MINUTES
) -> bool:
    raw = state.get("last_poll_success")
    if not isinstance(raw, str):
        return True
    try:
        last_poll = datetime.fromisoformat(raw)
        if last_poll.tzinfo is None or last_poll.utcoffset() is None:
            return True
        elapsed = now.astimezone(WIB) - last_poll.astimezone(WIB)
    except (TypeError, ValueError):
        return True
    return elapsed > timedelta(minutes=max_gap_minutes)


def report_watchdog_fatal(now: datetime, reason: str, dry_run: bool) -> bool:
    metadata = load_watchdog_metadata()
    fingerprint = scan.error_fingerprint(reason)
    hour = now.astimezone(WIB).strftime("%Y-%m-%dT%H:%z")
    previous = metadata.get("last_error_notice")
    fingerprints: list[str] = []
    if isinstance(previous, dict) and previous.get("hour") == hour:
        raw_fingerprints = previous.get("fingerprints")
        if isinstance(raw_fingerprints, list):
            fingerprints = [item for item in raw_fingerprints if isinstance(item, str)]
    if fingerprint in fingerprints:
        return False
    message_id = scan.post_operational_text(
        scan.format_fatal(now, reason), f"watchdog-fatal-{fingerprint}-{hour}", dry_run
    )
    if message_id is None:
        return False
    metadata["last_error_notice"] = {
        "hour": hour,
        "fingerprints": (fingerprints + [fingerprint])[
            -scan.MAX_FATAL_FINGERPRINTS_PER_HOUR:
        ],
    }
    save_watchdog_metadata(metadata)
    return True


def run(now: datetime | None = None, dry_run: bool = False) -> int:
    now = now or datetime.now(WIB)
    try:
        state = load_scanner_state_read_only()
    except Exception:
        report_watchdog_fatal(now, "watchdog cannot read scanner state", dry_run)
        return 1
    if not is_stale(state, now):
        return 0
    report_watchdog_fatal(
        now, f"no successful Telegram poll within {MAX_GAP_MINUTES} minutes", dry_run
    )
    return 1


def main() -> int:
    dry_run = os.environ.get("IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST") == "1"
    return run(dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
