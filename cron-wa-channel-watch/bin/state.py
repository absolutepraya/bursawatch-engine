from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


STATE_VERSION = 1
LEASE_MINUTES = 15


def empty_state() -> dict[str, object]:
    return {"version": STATE_VERSION, "profiles": {}, "outbox": []}


def load(path: Path) -> dict[str, object]:
    if not path.exists():
        return empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read watcher state: {exc}") from exc
    if type(value) is not dict or value.get("version") != STATE_VERSION or type(value.get("profiles")) is not dict or type(value.get("outbox")) is not list:
        raise ValueError("watcher state has an invalid schema")
    return value


def save(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _cursor_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1_000
        if seconds <= 0:
            raise ValueError("cursor published_at must be a positive timestamp")
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("cursor published_at must be an ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError("cursor published_at must be a timestamp")


def cursor_key(value: dict[str, object]) -> tuple[datetime, str]:
    return (_cursor_timestamp(value["published_at"]), str(value["event_key"]))


def cursor(value: dict[str, object]) -> dict[str, str]:
    return {
        "published_at": _cursor_timestamp(value["published_at"]).isoformat(),
        "event_key": str(value["event_key"]),
    }


def lease_until(now: datetime) -> str:
    return (now + timedelta(minutes=LEASE_MINUTES)).astimezone(timezone.utc).isoformat()


def expire_leases(value: dict[str, object], now: datetime) -> int:
    expired = 0
    for record in value["outbox"]:  # type: ignore[union-attr]
        if not isinstance(record, dict) or record.get("agent_phase") != "awaiting_agent":
            continue
        raw = record.get("agent_lease_until")
        if not isinstance(raw, str):
            record["agent_phase"] = "pending"
            record["agent_lease_until"] = None
            expired += 1
            continue
        try:
            until = datetime.fromisoformat(raw)
        except ValueError:
            until = now
        if until <= now:
            record["agent_phase"] = "pending"
            record["agent_lease_until"] = None
            expired += 1
    return expired
