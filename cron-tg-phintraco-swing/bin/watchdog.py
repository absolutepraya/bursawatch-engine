#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan

WIB = ZoneInfo("Asia/Jakarta")
MAX_GAP_MINUTES = 10
WATCHDOG_METADATA_VERSION = 1
WATCHDOG_METADATA_FILENAME = "watchdog-notices.json"


def watchdog_metadata_path() -> Path:
    return scan.state_path().parent / WATCHDOG_METADATA_FILENAME


def empty_watchdog_metadata() -> dict:
    return {"version": WATCHDOG_METADATA_VERSION, "last_error_notice": None}


def load_scanner_state_read_only() -> dict:
    path = scan.state_path()
    if not path.exists():
        return scan.empty_state()
    state = scan._validate_state(json.loads(path.read_text()))
    if state.get("blocked"):
        raise scan.StateBlockedError(
            str(state.get("block_reason") or "state is blocked"), state
        )
    return state


def load_watchdog_metadata() -> dict:
    path = watchdog_metadata_path()
    if not path.exists():
        return empty_watchdog_metadata()
    try:
        metadata = json.loads(path.read_text())
        if type(metadata) is not dict:
            raise ValueError("watchdog metadata must be an object")
        if metadata.get("version") != WATCHDOG_METADATA_VERSION:
            raise ValueError("unsupported watchdog metadata version")
        scan._validate_last_error_notice(metadata.get("last_error_notice"))
        return metadata
    except Exception:
        return empty_watchdog_metadata()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_watchdog_metadata(metadata: dict) -> None:
    path = watchdog_metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with handle:
            handle.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temp.unlink(missing_ok=True)
        raise


def report_watchdog_fatal(now: dt.datetime, reason: str, dry_run: bool) -> bool:
    metadata = load_watchdog_metadata()
    fingerprint = scan.error_fingerprint(reason)
    hour = scan.heartbeat_hour_key(now)
    previous = metadata.get("last_error_notice")
    fingerprints = []
    if type(previous) is dict and previous.get("hour") == hour:
        fingerprints = list(previous.get("fingerprints") or [])
    if fingerprint in fingerprints:
        return False
    message_id = scan.post_discord_text(
        scan.format_fatal(now, reason),
        scan.HEARTBEAT_CHANNEL_ID,
        dry_run,
        f"watchdog-fatal-{fingerprint}-{hour}",
    )
    if message_id is None:
        return False
    fingerprints.append(fingerprint)
    metadata["last_error_notice"] = {
        "hour": hour,
        "fingerprints": fingerprints[-scan.MAX_FATAL_FINGERPRINTS_PER_HOUR:],
    }
    save_watchdog_metadata(metadata)
    return True


def _report_watchdog_fatal_best_effort(
    now: dt.datetime, reason: str, dry_run: bool
) -> bool:
    try:
        return report_watchdog_fatal(now, reason, dry_run)
    except Exception:
        return False


def is_stale(state: dict, now: dt.datetime, max_gap_minutes: int = MAX_GAP_MINUTES) -> bool:
    raw = state.get("last_poll_success")
    if not raw:
        return True
    try:
        last = dt.datetime.fromisoformat(raw).astimezone(WIB)
    except Exception:
        return True
    return now.astimezone(WIB) - last > dt.timedelta(minutes=max_gap_minutes)


def main() -> int:
    now = dt.datetime.now(WIB)
    dry_run = os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1"
    try:
        state = load_scanner_state_read_only()
    except scan.StateBlockedError as exc:
        _report_watchdog_fatal_best_effort(
            now, f"watchdog state blocked: {exc}", dry_run
        )
        return 1
    except Exception as exc:
        _report_watchdog_fatal_best_effort(
            now, f"watchdog cannot read state: {exc}", dry_run
        )
        return 1
    if not is_stale(state, now):
        return 0
    _report_watchdog_fatal_best_effort(
        now,
        f"no successful Telegram poll within {MAX_GAP_MINUTES} minutes",
        dry_run,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
