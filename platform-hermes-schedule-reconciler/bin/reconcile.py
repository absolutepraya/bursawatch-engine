#!/usr/bin/env python3
"""Guarded bridge from desired Bursawatch schedules to Hermes CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


API_VERSION = 1
MAX_RESPONSE_BYTES = 1_000_000
MAX_ERROR_LENGTH = 500
LEGACY_INTERVAL_CRON_EXPRESSIONS = {
    1: "* * * * *",
    10: "*/10 * * * *",
    60: "0 * * * *",
}
JOB_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
SECRET_RE = re.compile(
    r"(?i)\b(authorization|bearer|token|secret|password|cookie|session)(?:\s*[:=]\s*|\s+)([^\s,;]+)"
)
URL_RE = re.compile(r"https?://[^\s'\"<>]+")
PATH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:~|/)[^\s'\"<>]+")


class ReconcilerError(RuntimeError):
    """A safe local, API, or Hermes scheduler reconciliation failure."""


class ContractError(ReconcilerError):
    """The control-plane response is not the expected stable contract."""


class StaleRevisionError(ReconcilerError):
    """The desired schedule changed before this worker reported its outcome."""


@dataclass(frozen=True)
class Settings:
    control_plane_url: str
    token: str
    jobs_path: Path
    hermes_cli: str
    timeout_seconds: float
    dry_run: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        prefix = "BURSAWATCH_SCHEDULE_RECONCILER"
        control_plane_url = os.environ.get(f"{prefix}_CONTROL_PLANE_URL", "").strip()
        token = os.environ.get(f"{prefix}_TOKEN", "").strip()
        if not control_plane_url:
            raise ReconcilerError(f"{prefix}_CONTROL_PLANE_URL is required")
        parsed = urlparse(control_plane_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ReconcilerError("control-plane URL must be an origin without credentials, query, or fragment")
        if not token:
            raise ReconcilerError(f"{prefix}_TOKEN is required")
        try:
            timeout_seconds = float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "15"))
        except ValueError as exc:
            raise ReconcilerError("reconciler timeout must be a number") from exc
        if not 1 <= timeout_seconds <= 60:
            raise ReconcilerError("reconciler timeout must be between 1 and 60 seconds")
        dry_run_value = os.environ.get(f"{prefix}_DRY_RUN", "0").strip()
        if dry_run_value not in {"0", "1"}:
            raise ReconcilerError("reconciler dry-run must be 0 or 1")
        jobs_path = Path(
            os.environ.get(f"{prefix}_JOBS_PATH", str(Path.home() / ".hermes/cron/jobs.json"))
        ).expanduser()
        hermes_cli = str(
            Path(os.environ.get(f"{prefix}_HERMES_CLI", str(Path.home() / ".local/bin/hermes"))).expanduser()
        )
        return cls(
            control_plane_url=control_plane_url.rstrip("/"),
            token=token,
            jobs_path=jobs_path,
            hermes_cli=hermes_cli,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run_value == "1",
        )


@dataclass(frozen=True)
class DesiredSchedule:
    job_id: str
    runtime_job_key: str
    revision: int
    enabled: bool
    interval_seconds: int
    timezone: str

    @property
    def interval_minutes(self) -> int:
        return self.interval_seconds // 60

    @property
    def hermes_schedule(self) -> str:
        return f"every {self.interval_minutes}m"


@dataclass(frozen=True)
class HermesJob:
    job_id: str
    runtime_job_key: str
    enabled: bool
    schedule: dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    job_id: str
    revision: int
    status: str
    actions: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "job_id": self.job_id,
            "revision": self.revision,
            "status": self.status,
            "actions": self.actions,
        }
        if self.error is not None:
            result["error"] = self.error
        return result


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("control-plane response has non-JSON data") from exc


def schedule_checksum(enabled: bool, interval_seconds: int, timezone: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                "timezone": timezone,
            }
        )
    ).hexdigest()


def _validate_job_id(value: object, label: str) -> str:
    if type(value) is not str or not JOB_ID_RE.fullmatch(value):
        raise ContractError(f"{label} is invalid")
    return value


def _validate_timestamp(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ContractError("schedule updated_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("schedule updated_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ContractError("schedule updated_at has no timezone")
    return value


def parse_desired_schedule(payload: object) -> DesiredSchedule:
    if type(payload) is not dict:
        raise ContractError("scheduler job is not an object")
    expected_job_fields = {
        "job_id",
        "watcher_id",
        "display_name",
        "runtime_job_key",
        "schedule_kind",
        "min_interval_seconds",
        "max_interval_seconds",
        "schedule",
        "reconciliation",
    }
    if set(payload) != expected_job_fields:
        raise ContractError("scheduler job has unexpected fields")
    if payload["schedule_kind"] != "interval":
        raise ContractError("reconciler received a non-interval job")
    job_id = _validate_job_id(payload["job_id"], "job_id")
    runtime_job_key = _validate_job_id(payload["runtime_job_key"], "runtime_job_key")
    snapshot = payload["schedule"]
    if type(snapshot) is not dict:
        raise ContractError("interval scheduler job has no schedule")
    expected_snapshot_fields = {
        "api_version",
        "job_id",
        "revision",
        "enabled",
        "interval_seconds",
        "timezone",
        "schedule_sha256",
        "updated_at",
    }
    if set(snapshot) != expected_snapshot_fields:
        raise ContractError("schedule snapshot has unexpected fields")
    if snapshot["api_version"] != API_VERSION:
        raise ContractError("schedule snapshot API version is unsupported")
    if _validate_job_id(snapshot["job_id"], "schedule job_id") != job_id:
        raise ContractError("schedule snapshot job_id does not match scheduler job")
    revision = snapshot["revision"]
    enabled = snapshot["enabled"]
    interval_seconds = snapshot["interval_seconds"]
    timezone = snapshot["timezone"]
    checksum = snapshot["schedule_sha256"]
    if type(revision) is not int or revision < 1:
        raise ContractError("schedule revision is invalid")
    if type(enabled) is not bool:
        raise ContractError("schedule enabled is invalid")
    if type(interval_seconds) is not int or not 60 <= interval_seconds <= 86_400 or interval_seconds % 60:
        raise ContractError("schedule interval_seconds is invalid")
    if type(timezone) is not str or not timezone.strip():
        raise ContractError("schedule timezone is invalid")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ContractError("schedule timezone is invalid") from exc
    if timezone != "Asia/Jakarta":
        raise ContractError("schedule timezone must remain Asia/Jakarta")
    if type(checksum) is not str or checksum != schedule_checksum(enabled, interval_seconds, timezone):
        raise ContractError("schedule checksum does not match schedule")
    _validate_timestamp(snapshot["updated_at"])
    return DesiredSchedule(
        job_id=job_id,
        runtime_job_key=runtime_job_key,
        revision=revision,
        enabled=enabled,
        interval_seconds=interval_seconds,
        timezone=timezone,
    )


def sanitize_error(value: object) -> str:
    text = " ".join(str(value).split()) or "reconciliation failed without an error message"
    text = SECRET_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = URL_RE.sub("<url>", text)
    text = PATH_RE.sub("<path>", text)
    return text[:MAX_ERROR_LENGTH]


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.opener = opener

    def _request_json(self, endpoint: str, method: str, payload: dict[str, Any] | None = None) -> Any:
        encoded = None
        if payload is not None:
            encoded = canonical_json_bytes(payload)
        request = Request(
            f"{self.base_url}{endpoint}",
            data=encoded,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 409:
                raise StaleRevisionError("desired schedule revision changed before reconciliation report") from exc
            raise ReconcilerError(f"control plane returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ReconcilerError("control-plane request failed") from exc
        if not 200 <= status < 300:
            raise ReconcilerError(f"control plane returned HTTP {status}")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ContractError("control-plane response is too large")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("control-plane response is not valid JSON") from exc

    def desired_schedules(self) -> list[DesiredSchedule]:
        payload = self._request_json("/v1/internal/schedules", "GET")
        if type(payload) is not list:
            raise ContractError("control-plane schedules response is not an array")
        schedules = [parse_desired_schedule(item) for item in payload]
        job_ids = [schedule.job_id for schedule in schedules]
        runtime_keys = [schedule.runtime_job_key for schedule in schedules]
        if len(job_ids) != len(set(job_ids)) or len(runtime_keys) != len(set(runtime_keys)):
            raise ContractError("control-plane schedules contain duplicate identities")
        return schedules

    def report(self, schedule: DesiredSchedule, status: str, error: str | None = None) -> None:
        payload: dict[str, Any] = {"revision": schedule.revision, "status": status}
        if error is not None:
            payload["error"] = sanitize_error(error)
        self._request_json(
            f"/v1/internal/jobs/{quote(schedule.job_id, safe='')}/reconciliation",
            "POST",
            payload,
        )


def load_hermes_job(jobs_path: Path, runtime_job_key: str) -> HermesJob:
    try:
        raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcilerError("Hermes scheduler registry could not be read") from exc
    if type(raw) is not dict or type(raw.get("jobs")) is not list:
        raise ReconcilerError("Hermes scheduler registry has an invalid shape")
    matches = [job for job in raw["jobs"] if type(job) is dict and job.get("name") == runtime_job_key]
    if len(matches) != 1:
        raise ReconcilerError("Hermes scheduler job name was missing or ambiguous")
    job = matches[0]
    job_id = job.get("id")
    enabled = job.get("enabled")
    schedule = job.get("schedule")
    if type(job_id) is not str or not job_id.strip() or len(job_id) > 128:
        raise ReconcilerError("Hermes scheduler job has an invalid ID")
    if type(enabled) is not bool or type(schedule) is not dict:
        raise ReconcilerError("Hermes scheduler job has an invalid schedule state")
    return HermesJob(
        job_id=job_id,
        runtime_job_key=runtime_job_key,
        enabled=enabled,
        schedule=schedule,
    )


def schedule_matches(job: HermesJob, desired: DesiredSchedule) -> bool:
    interval_matches = (
        job.schedule.get("kind") == "interval"
        and type(job.schedule.get("minutes")) is int
        and job.schedule["minutes"] == desired.interval_minutes
    )
    legacy_cron_matches = (
        job.schedule.get("kind") == "cron"
        and job.schedule.get("expr")
        == LEGACY_INTERVAL_CRON_EXPRESSIONS.get(desired.interval_minutes)
    )
    return interval_matches or legacy_cron_matches


def planned_actions(job: HermesJob, desired: DesiredSchedule) -> list[str]:
    actions: list[str] = []
    if not schedule_matches(job, desired):
        actions.append(f"edit schedule to {desired.hermes_schedule}")
    if job.enabled != desired.enabled:
        actions.append("resume job" if desired.enabled else "pause job")
    return actions


def run_hermes_cli(
    command: list[str],
    timeout_seconds: float,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    try:
        runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReconcilerError("Hermes CLI timed out") from exc
    except subprocess.CalledProcessError as exc:
        output = exc.stderr or exc.stdout or ""
        raise ReconcilerError(
            f"Hermes CLI failed with exit code {exc.returncode}: {sanitize_error(output)}"
        ) from exc
    except OSError as exc:
        raise ReconcilerError("Hermes CLI could not be started") from exc


def apply_schedule(
    settings: Settings,
    desired: DesiredSchedule,
    *,
    registry_loader: Callable[[Path, str], HermesJob] = load_hermes_job,
    command_runner: Callable[..., None] = run_hermes_cli,
) -> list[str]:
    current = registry_loader(settings.jobs_path, desired.runtime_job_key)
    actions = planned_actions(current, desired)
    if settings.dry_run:
        return actions
    if not schedule_matches(current, desired):
        try:
            command_runner(
                [settings.hermes_cli, "cron", "edit", current.job_id, "--schedule", desired.hermes_schedule],
                settings.timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise ReconcilerError(sanitize_error(exc)) from exc
        current = registry_loader(settings.jobs_path, desired.runtime_job_key)
        if not schedule_matches(current, desired):
            raise ReconcilerError("Hermes scheduler did not retain the requested interval")
    if current.enabled != desired.enabled:
        try:
            command_runner(
                [settings.hermes_cli, "cron", "resume" if desired.enabled else "pause", current.job_id],
                settings.timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise ReconcilerError(sanitize_error(exc)) from exc
        current = registry_loader(settings.jobs_path, desired.runtime_job_key)
        if current.enabled != desired.enabled:
            raise ReconcilerError("Hermes scheduler did not retain the requested enabled state")
    return actions


def reconcile_all(
    settings: Settings,
    client: ControlPlaneClient,
    *,
    registry_loader: Callable[[Path, str], HermesJob] = load_hermes_job,
    command_runner: Callable[..., None] = run_hermes_cli,
) -> list[Outcome]:
    schedules = client.desired_schedules()
    outcomes: list[Outcome] = []
    for desired in schedules:
        try:
            actions = apply_schedule(
                settings,
                desired,
                registry_loader=registry_loader,
                command_runner=command_runner,
            )
        except ReconcilerError as exc:
            error = sanitize_error(exc)
            if settings.dry_run:
                outcomes.append(Outcome(desired.job_id, desired.revision, "error", [], error))
                continue
            try:
                client.report(desired, "error", error)
            except StaleRevisionError:
                outcomes.append(Outcome(desired.job_id, desired.revision, "stale", [], None))
            except ReconcilerError as report_exc:
                outcomes.append(
                    Outcome(desired.job_id, desired.revision, "report_error", [], sanitize_error(report_exc))
                )
            else:
                outcomes.append(Outcome(desired.job_id, desired.revision, "error", [], error))
            continue
        if settings.dry_run:
            outcomes.append(Outcome(desired.job_id, desired.revision, "planned", actions, None))
            continue
        try:
            client.report(desired, "applied")
        except StaleRevisionError:
            outcomes.append(Outcome(desired.job_id, desired.revision, "stale", actions, None))
        except ReconcilerError as exc:
            outcomes.append(Outcome(desired.job_id, desired.revision, "report_error", actions, sanitize_error(exc)))
        else:
            outcomes.append(Outcome(desired.job_id, desired.revision, "applied", actions, None))
    return outcomes


def main() -> int:
    try:
        settings = Settings.from_environment()
        client = ControlPlaneClient(settings.control_plane_url, settings.token, settings.timeout_seconds)
        outcomes = reconcile_all(settings, client)
    except ReconcilerError as exc:
        print(json.dumps({"status": "fatal", "error": sanitize_error(exc)}, sort_keys=True))
        return 1
    for outcome in outcomes:
        print(json.dumps(outcome.to_dict(), sort_keys=True))
    return 1 if any(outcome.status in {"error", "report_error"} for outcome in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
