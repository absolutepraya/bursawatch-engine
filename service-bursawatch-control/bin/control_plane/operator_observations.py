"""Validated, monotonic projections of trusted Hermes observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Protocol

from .store import SchedulerJobRecord


class ObservationError(ValueError):
    pass


@dataclass(frozen=True)
class Observation:
    identity_kind: str
    identity_id: str
    observer_id: str
    observed_at: datetime
    status: str
    evidence: dict[str, Any]
    received_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": 1,
            "identity_kind": self.identity_kind,
            "identity_id": self.identity_id,
            "observer_id": self.observer_id,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "received_at": self.received_at.isoformat().replace("+00:00", "Z"),
            "status": self.status,
            "evidence": self.evidence,
        }


class ObservationStore(Protocol):
    def accept(self, observation: Observation) -> Observation: ...
    def list_latest(self) -> list[Observation]: ...


def _timestamp(value: object, field: str, *, now: datetime) -> datetime:
    if type(value) is not str or len(value) > 40 or not value.endswith("Z"):
        raise ObservationError(f"{field} must be an ISO UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ObservationError(f"{field} is invalid") from exc
    if parsed > now + timedelta(seconds=30):
        raise ObservationError(f"{field} cannot be in the future")
    return parsed


def validate_observation(
    payload: object,
    observer_id: str,
    jobs: list[SchedulerJobRecord] | tuple[SchedulerJobRecord, ...],
    *,
    now: datetime | None = None,
) -> Observation:
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict) or set(payload) != {"api_version", "identity_kind", "identity_id", "observed_at", "status", "evidence"}:
        raise ObservationError("observation has unsupported fields or is missing required fields")
    if type(payload["api_version"]) is not int or payload["api_version"] != 1:
        raise ObservationError("api_version must be 1")
    if payload["identity_kind"] != "job":
        raise ObservationError("identity_kind must be job")
    identity_id = payload["identity_id"]
    if type(identity_id) is not str or len(identity_id) > 128:
        raise ObservationError("identity_id is invalid")
    job = next((item for item in jobs if item.job_id == identity_id), None)
    if job is None:
        raise ObservationError("identity_id is not a declared job")
    observed_at = _timestamp(payload["observed_at"], "observed_at", now=now)
    status = payload["status"]
    if type(status) is not str or status not in {"enabled", "disabled"}:
        raise ObservationError("status must be enabled or disabled")
    evidence = payload["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"runtime_job_key", "enabled", "schedule", "last_execution"}:
        raise ObservationError("evidence has unsupported fields or is missing required fields")
    runtime_key = evidence["runtime_job_key"]
    if type(runtime_key) is not str or runtime_key != job.runtime_job_key:
        raise ObservationError("runtime_job_key does not match the declared job")
    enabled = evidence["enabled"]
    if type(enabled) is not bool or status != ("enabled" if enabled else "disabled"):
        raise ObservationError("status must match evidence.enabled")
    schedule = evidence["schedule"]
    if not isinstance(schedule, dict) or len(schedule) > 2:
        raise ObservationError("schedule is invalid")
    if schedule.get("kind") == "interval" and set(schedule) == {"kind", "minutes"}:
        minutes = schedule["minutes"]
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ObservationError("schedule.minutes is out of bounds")
        if job.schedule_kind != "interval":
            raise ObservationError("observed schedule kind does not match declared job")
    elif schedule.get("kind") == "cron" and set(schedule) == {"kind", "expr"}:
        expr = schedule["expr"]
        if type(expr) is not str or len(expr) > 100 or not re.fullmatch(r"[0-9*/?,\- ]+", expr):
            raise ObservationError("schedule.expr is invalid")
        if job.schedule_kind == "interval":
            raise ObservationError("observed schedule kind does not match declared job")
    else:
        raise ObservationError("schedule is invalid")
    last = evidence["last_execution"]
    if not isinstance(last, dict) or set(last) != {"at", "status"}:
        raise ObservationError("last_execution is invalid")
    if last["at"] is None:
        if last["status"] is not None:
            raise ObservationError("last_execution.status requires a timestamp")
    else:
        _timestamp(last["at"], "last_execution.at", now=now)
        if type(last["status"]) is not str or last["status"] not in {"success", "failed", "running", "skipped"}:
            raise ObservationError("last_execution.status is invalid")
    if len(json.dumps(evidence, separators=(",", ":"))) > 512:
        raise ObservationError("evidence is too large")
    return Observation("job", identity_id, observer_id, observed_at, status, evidence, now)


class MemoryObservationStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Observation] = {}

    def accept(self, observation: Observation) -> Observation:
        key = (observation.identity_kind, observation.identity_id)
        current = self._rows.get(key)
        if current is None or observation.observed_at > current.observed_at:
            self._rows[key] = observation
        return self._rows[key]

    def list_latest(self) -> list[Observation]:
        return sorted(self._rows.values(), key=lambda row: (row.identity_kind, row.identity_id))


class PostgresObservationStore:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def accept(self, observation: Observation) -> Observation:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """insert into bursawatch_operator_observations
                   (identity_kind, identity_id, observer_id, observed_at, received_at, status, evidence)
                   values (%s, %s, %s, %s, %s, %s, %s::jsonb)
                   on conflict (identity_kind, identity_id) do update set
                     observer_id = excluded.observer_id, observed_at = excluded.observed_at,
                     received_at = excluded.received_at, status = excluded.status, evidence = excluded.evidence
                   where bursawatch_operator_observations.observed_at < excluded.observed_at
                   returning identity_kind, identity_id, observer_id, observed_at, received_at, status, evidence""",
                (observation.identity_kind, observation.identity_id, observation.observer_id,
                 observation.observed_at, observation.received_at, observation.status,
                 json.dumps(observation.evidence)),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """select identity_kind, identity_id, observer_id, observed_at, received_at, status, evidence
                       from bursawatch_operator_observations where identity_kind = %s and identity_id = %s""",
                    (observation.identity_kind, observation.identity_id),
                )
                row = cursor.fetchone()
            return _from_row(row)

    def list_latest(self) -> list[Observation]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("""select identity_kind, identity_id, observer_id, observed_at, received_at, status, evidence
                              from bursawatch_operator_observations order by identity_kind, identity_id""")
            return [_from_row(row) for row in cursor.fetchall()]


def _from_row(row: Any) -> Observation:
    if isinstance(row, dict):
        identity_kind = row["identity_kind"]
        identity_id = row["identity_id"]
        observer_id = row["observer_id"]
        observed_at = row["observed_at"]
        received_at = row["received_at"]
        status = row["status"]
        evidence = row["evidence"]
    else:
        identity_kind, identity_id, observer_id, observed_at, received_at, status, evidence = row
    if isinstance(evidence, str):
        evidence = json.loads(evidence)
    return Observation(identity_kind, identity_id, observer_id, observed_at, status, evidence, received_at)


def observation_view(observation: Observation, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stale = now - observation.observed_at > timedelta(minutes=5)
    result = observation.to_dict()
    result["freshness"] = "stale" if stale else "fresh"
    if stale:
        result["status"] = "stale"
    return result
