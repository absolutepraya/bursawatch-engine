from __future__ import annotations
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.operator_observations import (
    MemoryObservationStore,
    ObservationError,
    _from_row,
    observation_view,
    validate_observation,
)
from control_plane.store import InMemoryStore


NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
OBSERVER = "observer-token"
VIEWER = "viewer-token"


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.seed_job(
        job_id="bursawatch-x-account-watch-queue-worker",
        watcher_id="bursawatch-x-account-watch",
        display_name="X queue worker",
        runtime_job_key="bursawatch-x-account-watch-queue",
        schedule_kind="fixed",
    )
    store.seed_job(
        job_id="bursawatch-tg-source-ingest",
        watcher_id=None,
        display_name="Telegram Source Intake",
        runtime_job_key="bursawatch-tg-source-ingest",
        schedule_kind="interval",
        min_interval_seconds=60,
        max_interval_seconds=3600,
        enabled=True,
        interval_seconds=60,
        timezone="Asia/Jakarta",
    )
    return store


def _payload(at: str, *, runtime: str = "bursawatch-tg-source-ingest", minutes: int = 1):
    return {
        "api_version": 1,
        "identity_kind": "job",
        "identity_id": "bursawatch-tg-source-ingest",
        "observed_at": at,
        "status": "enabled",
        "evidence": {
            "runtime_job_key": runtime,
            "enabled": True,
            "schedule": {"kind": "interval", "minutes": minutes},
            "last_execution": {"at": None, "status": None},
        },
    }


def test_older_observation_cannot_replace_newer():
    store = MemoryObservationStore()
    jobs = _store().list_all_jobs()
    newer = validate_observation(_payload("2026-09-30T09:59:00Z"), "hermes-observer", jobs, now=NOW)
    older = validate_observation(_payload("2026-09-30T09:58:00Z"), "hermes-observer", jobs, now=NOW)

    store.accept(newer)
    stored = store.accept(older)

    assert stored == newer


def test_stale_observation_is_not_healthy():
    stale = validate_observation(
        _payload("2026-09-30T09:00:00Z"), "hermes-observer", _store().list_all_jobs(), now=NOW
    )
    view = observation_view(stale, now=NOW)
    assert view["status"] == "stale"


def test_unknown_ids_future_times_oversized_fields_secrets_and_schedule_mismatches_rejected():
    jobs = _store().list_all_jobs()
    cases = []
    unknown = _payload("2026-09-30T09:59:00Z")
    unknown["identity_id"] = "not-declared"
    cases.append(unknown)
    cases.append(_payload("2026-09-30T10:01:00Z"))
    large = _payload("2026-09-30T09:59:00Z")
    large["evidence"]["runtime_job_key"] = "x" * 256
    cases.append(large)
    secret = _payload("2026-09-30T09:59:00Z")
    secret["evidence"]["token"] = "secret"
    cases.append(secret)
    wrong_runtime = _payload("2026-09-30T09:59:00Z", runtime="x-post-queue-worker")
    wrong_runtime["identity_id"] = "bursawatch-x-account-watch-queue-worker"
    cases.append(wrong_runtime)
    wrong_schedule = _payload("2026-09-30T09:59:00Z")
    wrong_schedule["evidence"]["schedule"] = {"kind": "cron", "expr": "* * * * *"}
    cases.append(wrong_schedule)

    for payload in cases:
        with pytest.raises(ObservationError):
            validate_observation(payload, "hermes-observer", jobs, now=NOW)


def test_x_queue_logical_id_accepts_only_exact_hermes_runtime_key():
    payload = _payload("2026-09-30T09:59:00Z", runtime="bursawatch-x-account-watch-queue")
    payload["identity_id"] = "bursawatch-x-account-watch-queue-worker"
    payload["evidence"]["schedule"] = {"kind": "cron", "expr": "*/5 * * * *"}
    result = validate_observation(payload, "hermes-observer", _store().list_all_jobs(), now=NOW)
    assert result.identity_id == "bursawatch-x-account-watch-queue-worker"
    assert result.evidence["runtime_job_key"] == "bursawatch-x-account-watch-queue"


def test_postgres_dict_row_projects_observation_fields():
    row = {
        "identity_kind": "job",
        "identity_id": "job-one",
        "observer_id": "hermes-observer",
        "observed_at": NOW,
        "received_at": NOW,
        "status": "enabled",
        "evidence": {"enabled": True},
    }
    assert _from_row(row).identity_id == "job-one"


def test_observer_can_post_and_viewer_cannot_post_observation():
    class ViewerAuth(StaticTokenAuth):
        def authenticate(self, authorization):
            if authorization == f"Bearer {VIEWER}":
                from control_plane.auth import Principal
                return Principal(subject="viewer-user", kind="viewer")
            return super().authenticate(authorization)

    client = TestClient(create_app(
        store=_store(),
        auth=ViewerAuth(machine_token="machine-token", admin_token=None, observer_token=OBSERVER),
    ))
    from datetime import timedelta
    body = _payload(datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    denied = client.post("/v1/internal/observations", headers={"Authorization": f"Bearer {VIEWER}"}, json=body)
    assert denied.status_code == 403
    accepted = client.post("/v1/internal/observations", headers={"Authorization": f"Bearer {OBSERVER}"}, json=body)
    assert accepted.status_code == 202, accepted.text
    read = client.get("/v1/observations", headers={"Authorization": f"Bearer {OBSERVER}"})
    assert read.status_code == 403
    human_read = client.get("/v1/observations", headers={"Authorization": f"Bearer {VIEWER}"})
    assert human_read.status_code == 200
    assert human_read.json()[0]["comparison"] == "match"


def test_fixed_job_observation_has_no_desired_schedule_comparison():
    client = TestClient(create_app(
        store=_store(),
        auth=StaticTokenAuth(machine_token="machine-token", admin_token="admin-token", observer_token=OBSERVER),
    ))
    body = _payload(datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), runtime="bursawatch-x-account-watch-queue")
    body["identity_id"] = "bursawatch-x-account-watch-queue-worker"
    body["evidence"]["schedule"] = {"kind": "cron", "expr": "*/5 * * * *"}
    accepted = client.post("/v1/internal/observations", headers={"Authorization": f"Bearer {OBSERVER}"}, json=body)
    assert accepted.status_code == 202, accepted.text
    read = client.get("/v1/observations", headers={"Authorization": "Bearer admin-token"})
    assert read.status_code == 200
    assert read.json()[0]["comparison"] == "not_comparable"
