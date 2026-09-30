#!/usr/bin/env python3
"""Read Hermes job state and report bounded observations to Control Plane."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_REGISTRY_BYTES = 5_000_000
MAX_RESPONSE_BYTES = 32_000
RUNTIME_JOB_IDS = {
    "bursawatch-tg-source-ingest": "bursawatch-tg-source-ingest",
    "bursawatch-tg-market-news-watchdog": "bursawatch-tg-market-news-watchdog",
    "bursawatch-dc-swing-board-lifecycle": "bursawatch-dc-swing-board-lifecycle",
    "bursawatch-x-account-watch": "bursawatch-x-account-watch-source",
    "bursawatch-x-account-watch-queue": "bursawatch-x-account-watch-queue-worker",
    "bursawatch-ig-account-watch": "bursawatch-ig-account-watch-source",
    "bursawatch-tg-phintraco-swing": "bursawatch-tg-phintraco-swing",
    "bursawatch-dc-swing-board-close": "bursawatch-dc-swing-board-close",
    "bursawatch-dc-swing-board-retry": "bursawatch-dc-swing-board-retry",
    "bursawatch-tg-market-news": "bursawatch-tg-market-news",
    "bursawatch-tg-kelas-investasi-gtw": "bursawatch-tg-kelas-investasi-gtw",
    "bursawatch-wa-channel-watch": "bursawatch-wa-channel-watch",
    "cron-stockbit-snips": "bursawatch-stockbit-snips",
}
RUNTIME_JOB_NAMES = frozenset(RUNTIME_JOB_IDS)
JOB_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,99}\Z")
LAST_RUN_STATUS_MAP = {
    "ok": "success",
    "success": "success",
    "succeeded": "success",
    "error": "failed",
    "failed": "failed",
    "failure": "failed",
    "running": "running",
    "skipped": "skipped",
}


class ObserverError(RuntimeError):
    """The registry or observer configuration is unsafe or invalid."""


def _safe_schedule(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ObserverError("Hermes schedule is invalid")
    kind = value.get("kind")
    if kind == "interval":
        minutes = value.get("minutes")
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ObserverError("Hermes interval schedule is invalid")
        return {"kind": "interval", "minutes": minutes}
    if type(kind) is str and kind in {"cron", "fixed"}:
        expression = value.get("expr")
        if type(expression) is not str or not 1 <= len(expression) <= 100:
            raise ObserverError("Hermes fixed schedule is invalid")
        fields = expression.split()
        if (
            any(ord(char) < 32 for char in expression)
            or len(fields) != 5
            or any(not re.fullmatch(r"[0-9*/?,\-]+", field) for field in fields)
        ):
            raise ObserverError("Hermes fixed schedule is invalid")
        return {"kind": "cron", "expr": expression}
    raise ObserverError("Hermes schedule kind is unsupported")


def _safe_last_execution(job: dict[str, Any]) -> dict[str, str | None]:
    at = job.get("last_run_at")
    status = job.get("last_status")
    if at is None and status is None:
        return {"at": None, "status": None}
    if type(at) is not str or not 1 <= len(at) <= 64:
        raise ObserverError("Hermes last execution timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObserverError("Hermes last execution timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ObserverError("Hermes last execution timestamp has no timezone")
    if type(status) is not str or status.lower() not in LAST_RUN_STATUS_MAP:
        raise ObserverError("Hermes last execution status is invalid")
    return {
        "at": parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": LAST_RUN_STATUS_MAP[status.lower()],
    }


def read_observed_jobs(path: Path, allowed_names: set[str]) -> list[dict[str, Any]]:
    """Read each declared Hermes job once and return only safe registry fields."""
    if not allowed_names or any(type(name) is not str or not JOB_NAME_RE.fullmatch(name) for name in allowed_names):
        raise ObserverError("declared Hermes job names are invalid")
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_REGISTRY_BYTES + 1)
    except OSError as exc:
        raise ObserverError("Hermes registry could not be read") from exc
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ObserverError("Hermes registry exceeds the size limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObserverError("Hermes registry JSON is invalid") from exc
    if type(payload) is not dict or type(payload.get("jobs")) is not list:
        raise ObserverError("Hermes registry shape is invalid")
    found: dict[str, dict[str, Any]] = {}
    for item in payload["jobs"]:
        if type(item) is not dict:
            continue
        name = item.get("name")
        if type(name) is not str or name not in allowed_names:
            continue
        if name in found:
            raise ObserverError(f"duplicate Hermes runtime job name: {name}")
        if type(item.get("enabled")) is not bool:
            raise ObserverError(f"Hermes enabled state is invalid for {name}")
        found[name] = {
            "runtime_job_key": name,
            "enabled": item["enabled"],
            "schedule": _safe_schedule(item.get("schedule")),
            "last_execution": _safe_last_execution(item),
        }
    missing = sorted(allowed_names - found.keys())
    if missing:
        raise ObserverError("declared Hermes jobs are missing: " + ", ".join(missing))
    return [found[name] for name in sorted(found)]


def _validate_origin(api_origin: str) -> str:
    parsed = urlparse(api_origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment):
        raise ObserverError("Control Plane API origin is invalid")
    return api_origin.rstrip("/")


def _observation_for(row: dict[str, Any], observed_at: str) -> dict[str, Any]:
    expected = {"runtime_job_key", "enabled", "schedule", "last_execution"}
    if type(row) is not dict or set(row) != expected:
        raise ObserverError("observation row has unexpected fields")
    runtime_name = row["runtime_job_key"]
    if type(runtime_name) is not str or runtime_name not in RUNTIME_JOB_IDS:
        raise ObserverError("observation job identity is not declared")
    if type(row["enabled"]) is not bool:
        raise ObserverError("observation enabled state is invalid")
    schedule = _safe_schedule(row["schedule"])
    last_execution = row["last_execution"]
    if type(last_execution) is not dict or set(last_execution) != {"at", "status"}:
        raise ObserverError("observation last execution is invalid")
    last_execution = _safe_last_execution({"last_run_at": last_execution["at"], "last_status": last_execution["status"]})
    return {
        "api_version": 1,
        "identity_kind": "job",
        "identity_id": RUNTIME_JOB_IDS[runtime_name],
        "observed_at": observed_at,
        "status": "enabled" if row["enabled"] else "disabled",
        "evidence": {
            "runtime_job_key": runtime_name,
            "enabled": row["enabled"],
            "schedule": schedule,
            "last_execution": last_execution,
        },
    }


def report_observations(api_origin: str, token: str, rows: list[dict[str, Any]]) -> None:
    """Submit allowlisted observations; neither response bodies nor tokens escape."""
    origin = _validate_origin(api_origin)
    if (type(token) is not str or not token or len(token) > 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise ObserverError("observer token is missing or invalid")
    if type(rows) is not list or not rows:
        raise ObserverError("there are no observations to report")
    observed_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    for row in rows:
        observation = _observation_for(row, observed_at)
        request = Request(origin + "/v1/internal/observations", data=json.dumps(observation, separators=(",", ":")).encode("utf-8"),
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise ObserverError(f"Control Plane rejected observer report with HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise ObserverError("Control Plane observer report failed") from None


def main() -> int:
    prefix = "BURSAWATCH_OPERATOR_OBSERVER"
    registry_path = Path(os.environ.get(f"{prefix}_JOBS_PATH", "~/.hermes/cron/jobs.json")).expanduser()
    api_origin = os.environ.get(f"{prefix}_CONTROL_PLANE_ORIGIN", "").strip()
    token = os.environ.get(f"{prefix}_TOKEN", "").strip()
    if not api_origin or not token:
        print("observer API origin and token are required", file=sys.stderr)
        return 2
    try:
        rows = read_observed_jobs(registry_path, set(RUNTIME_JOB_NAMES))
        report_observations(api_origin, token, rows)
    except ObserverError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"reported {len(rows)} job observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
