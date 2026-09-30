"""Bounded owner attestations for forward-only publication coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


FRESH_FOR = timedelta(minutes=15)
CHECKPOINT_FIELDS = {"compared_at", "confirmed_through_at", "accepted_through_at", "outstanding_count"}


def _time(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or len(value) > 64:
        raise ValueError(f"{name} must be an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an aware timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be an aware timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def validate_checkpoint(payload: object, boundary: str, *, now: datetime | None = None) -> dict[str, Any]:
    if type(payload) is not dict or set(payload) != CHECKPOINT_FIELDS:
        raise ValueError("publication checkpoint fields are invalid")
    now = now or datetime.now(timezone.utc)
    compared_at = _time(payload["compared_at"], "compared_at")
    confirmed_at = _time(payload["confirmed_through_at"], "confirmed_through_at", optional=True)
    accepted_at = _time(payload["accepted_through_at"], "accepted_through_at", optional=True)
    outstanding = payload["outstanding_count"]
    if type(outstanding) is not int or not 0 <= outstanding <= 1_000_000:
        raise ValueError("outstanding_count is invalid")
    compared = datetime.fromisoformat(compared_at)
    if compared > now + timedelta(seconds=30) or compared < datetime.fromisoformat(boundary):
        raise ValueError("compared_at is outside the publication boundary")
    if confirmed_at is not None and datetime.fromisoformat(confirmed_at) > compared:
        raise ValueError("confirmed_through_at cannot exceed comparison time")
    if accepted_at is not None and datetime.fromisoformat(accepted_at) > compared:
        raise ValueError("accepted_through_at cannot exceed comparison time")
    if confirmed_at is None and accepted_at is not None:
        raise ValueError("accepted boundary needs confirmed boundary")
    if accepted_at is not None and confirmed_at is not None and accepted_at > confirmed_at:
        raise ValueError("accepted boundary cannot exceed confirmed boundary")
    if outstanding == 0 and confirmed_at is not None and accepted_at != confirmed_at:
        raise ValueError("zero outstanding requires equal confirmed and accepted boundaries")
    return {
        "compared_at": compared_at,
        "confirmed_through_at": confirmed_at,
        "accepted_through_at": accepted_at,
        "outstanding_count": outstanding,
    }


def coverage_view(
    cutover: dict[str, Any] | None,
    checkpoints: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    paused_owner_ids: set[str] | None = None,
) -> dict[str, Any]:
    if cutover is None:
        return {"cutover": None, "overall_status": "not_started", "owners": []}
    now = now or datetime.now(timezone.utc)
    paused_owner_ids = paused_owner_ids or set()
    rows = []
    for owner_id in cutover["owner_ids"]:
        checkpoint = checkpoints.get(owner_id)
        status = "unknown"
        if owner_id in paused_owner_ids:
            status = "paused/unverified"
        elif checkpoint is not None:
            compared = datetime.fromisoformat(checkpoint["compared_at"])
            if now - compared <= FRESH_FOR:
                status = "complete" if checkpoint["outstanding_count"] == 0 else "lagging"
        rows.append({"owner_id": owner_id, "status": status, "checkpoint": checkpoint})
    return {
        "cutover": {"boundary": cutover["boundary"], "owner_ids": list(cutover["owner_ids"])},
        "overall_status": "complete" if rows and all(row["status"] == "complete" for row in rows) else "incomplete",
        "owners": rows,
    }
