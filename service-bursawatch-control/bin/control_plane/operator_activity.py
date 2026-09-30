"""Bounded intake and pipeline activity, separate from delivery evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


ACTIVITY_AGE = timedelta(hours=24)
WORK_STATUSES = {"pending", "leased", "executing", "done", "dead_letter", "suppressed", "superseded"}


class InboxActivityStore(Protocol):
    def latest_endpoint_accepted_at(self, endpoint_id: str) -> str | None: ...

    def latest_pipeline_work(self, pipeline_id: str) -> tuple[str, str] | None: ...


def _status(timestamp: str | None, now: datetime) -> str:
    if timestamp is None:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("activity store returned an invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("activity store returned a timestamp without timezone")
    return "stale" if now - parsed > ACTIVITY_AGE else "observed"


@dataclass(frozen=True)
class EndpointActivity:
    endpoint_id: str
    accepted_at: str | None
    status: str
    delivery_status: str = "not instrumented"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "endpoint_id": self.endpoint_id,
            "accepted_at": self.accepted_at,
            "status": self.status,
            "meaning": "last accepted into Source Inbox",
        }


@dataclass(frozen=True)
class PipelineActivity:
    pipeline_id: str
    work_created_at: str | None
    work_status: str | None
    status: str
    delivery_status: str = "not instrumented"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "pipeline_id": self.pipeline_id,
            "work_created_at": self.work_created_at,
            "work_status": self.work_status,
            "status": self.status,
            "meaning": "last pipeline work",
        }


def get_endpoint_activity(
    inbox_store: InboxActivityStore, endpoint_id: str, *, now: datetime | None = None,
) -> EndpointActivity:
    accepted_at = inbox_store.latest_endpoint_accepted_at(endpoint_id)
    return EndpointActivity(endpoint_id, accepted_at, _status(accepted_at, now or datetime.now(timezone.utc)))


def get_pipeline_activity(
    inbox_store: InboxActivityStore, pipeline_id: str, *, now: datetime | None = None,
) -> PipelineActivity:
    latest = inbox_store.latest_pipeline_work(pipeline_id)
    if latest is None:
        return PipelineActivity(pipeline_id, None, None, "unknown")
    created_at, work_status = latest
    if work_status not in WORK_STATUSES:
        raise ValueError("activity store returned an invalid work status")
    return PipelineActivity(pipeline_id, created_at, work_status, _status(created_at, now or datetime.now(timezone.utc)))
