from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api import create_app, create_app_from_environment
from control_plane.auth import StaticTokenAuth
from control_plane.store import InMemoryStore


WATCHER = "bursawatch-x-account-watch"
TOKEN = "machine-token"
ADMIN = "admin-token"


def build_client():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, {"version": 1, "profiles": []})
    store.seed_job(
        job_id="bursawatch-x-account-watch-source",
        watcher_id=WATCHER,
        display_name="X Account Watch source poller",
        runtime_job_key="x-post-source",
        schedule_kind="interval",
        min_interval_seconds=600,
        max_interval_seconds=86_400,
        enabled=True,
        interval_seconds=600,
        timezone="Asia/Jakarta",
    )
    store.seed_job(
        job_id="bursawatch-x-account-watch-queue-worker",
        watcher_id=WATCHER,
        display_name="X Account Watch queue worker",
        runtime_job_key="x-post-queue-worker",
        schedule_kind="fixed",
    )
    app = create_app(
        store=store,
        auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN),
        validators={WATCHER: lambda config: None},
    )
    return TestClient(app), store


def test_health_is_public_and_config_requires_authentication():
    client, _store = build_client()

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get(f"/v1/watchers/{WATCHER}/config").status_code == 401


def test_cors_allowlist_supports_the_separate_web_origin():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, {"version": 1, "profiles": []})
    from control_plane.api import create_app

    client = TestClient(
        create_app(
            store=store,
            auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN),
            validators={WATCHER: lambda config: None},
            allowed_origins=["https://watch.example.test"],
        )
    )

    response = client.options(
        f"/v1/watchers/{WATCHER}/config",
        headers={
            "Origin": "https://watch.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://watch.example.test"


def test_web_read_routes_expose_watchers_runs_and_events():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {ADMIN}"}
    run = client.post(
        "/v1/runs",
        headers=headers,
        json={"watcher_id": WATCHER, "config_revision": 1, "run_id": "read-route-run"},
    )
    event = client.post(
        "/v1/runs/read-route-run/events",
        headers=headers,
        json={
            "event_id": "read-route-event",
            "occurred_at": "2026-09-19T10:00:00+00:00",
            "level": "info",
            "phase": "lifecycle",
            "event_type": "run.started",
            "message": "started",
        },
    )

    assert run.status_code == 201
    assert event.status_code == 201
    assert client.get("/v1/watchers", headers=headers).json()[0]["watcher_id"] == WATCHER
    assert client.get(f"/v1/watchers/{WATCHER}/runs", headers=headers).json()[0]["run_id"] == "read-route-run"
    assert client.get("/v1/runs/read-route-run/events", headers=headers).json()[0]["event_id"] == "read-route-event"


def test_machine_can_read_config_but_cannot_write():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    response = client.get(f"/v1/watchers/{WATCHER}/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["revision"] == 1

    response = client.put(
        f"/v1/watchers/{WATCHER}/config",
        headers=headers,
        json={"config_version": 1, "config": {"version": 1}},
    )
    assert response.status_code == 403


def test_admin_write_creates_a_new_revision():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {ADMIN}"}

    response = client.put(
        f"/v1/watchers/{WATCHER}/config",
        headers=headers,
        json={"config_version": 1, "config": {"version": 1, "profiles": [{"id": "next"}]}},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 2


def test_config_write_rejects_payload_larger_than_the_control_plane_contract_limit():
    client, _store = build_client()
    response = client.put(
        f"/v1/watchers/{WATCHER}/config",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"config_version": 1, "config": {"value": "x" * 2_000_001}},
    )

    assert response.status_code == 422
    assert "exceeds" in response.json()["detail"]


def test_environment_factory_registers_config_validator(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    config = json.loads(
        (root / "cron-x-account-watch/config/watches.json").read_text(encoding="utf-8")
    )
    monkeypatch.setenv("CONTROL_PLANE_STORE", "memory")
    monkeypatch.setenv("CONTROL_PLANE_MACHINE_TOKEN", TOKEN)
    monkeypatch.setenv("CONTROL_PLANE_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv(
        "CONTROL_PLANE_X_CONFIG_VALIDATOR_DIR",
        str(root / "cron-x-account-watch/bin"),
    )

    client = TestClient(create_app_from_environment())
    response = client.put(
        f"/v1/watchers/{WATCHER}/config",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"config_version": 1, "config": config},
    )

    assert response.status_code == 200
    assert response.json()["config"] == config


def test_jobs_show_schedule_capabilities_and_current_reconciliation_state():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {ADMIN}"}

    jobs = client.get(f"/v1/watchers/{WATCHER}/jobs", headers=headers)

    assert jobs.status_code == 200
    by_id = {job["job_id"]: job for job in jobs.json()}
    source = by_id["bursawatch-x-account-watch-source"]
    worker = by_id["bursawatch-x-account-watch-queue-worker"]
    assert source["schedule_kind"] == "interval"
    assert source["schedule"]["interval_seconds"] == 600
    assert source["reconciliation"] == {
        "status": "not_connected",
        "applied_revision": None,
        "effective": False,
    }
    assert worker["schedule_kind"] == "fixed"
    assert worker["schedule"] is None


def test_admin_can_store_an_interval_schedule_without_claiming_it_is_live():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {ADMIN}"}

    response = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers=headers,
        json={"enabled": False, "interval_seconds": 7_200, "timezone": "Asia/Jakarta"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schedule"]["revision"] == 2
    assert body["schedule"]["enabled"] is False
    assert body["schedule"]["interval_seconds"] == 7_200
    assert body["reconciliation"] == {
        "status": "pending",
        "applied_revision": None,
        "effective": False,
    }


def test_machine_cannot_change_schedule_and_fixed_jobs_reject_changes():
    client, _store = build_client()
    payload = {"enabled": True, "interval_seconds": 600, "timezone": "Asia/Jakarta"}

    machine = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=payload,
    )
    fixed = client.put(
        "/v1/jobs/bursawatch-x-account-watch-queue-worker/schedule",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json=payload,
    )

    assert machine.status_code == 403
    assert fixed.status_code == 409


def test_schedule_rejects_values_outside_the_job_policy():
    client, _store = build_client()
    response = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"enabled": True, "interval_seconds": 60, "timezone": "Asia/Jakarta"},
    )

    assert response.status_code == 422
    assert "between 600 and 86400" in response.json()["detail"]


def test_run_events_are_idempotent_by_event_id():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    run = client.post(
        "/v1/runs",
        headers=headers,
        json={"watcher_id": WATCHER, "config_revision": 1},
    )
    assert run.status_code == 201
    run_id = run.json()["run_id"]
    event = {
        "event_id": "source-fetch-1",
        "occurred_at": "2026-09-19T10:00:00+00:00",
        "level": "info",
        "phase": "source",
        "event_type": "fetch.completed",
        "message": "source fetch completed",
        "attributes": {"items": 0},
    }

    first = client.post(f"/v1/runs/{run_id}/events", headers=headers, json=event)
    second = client.post(f"/v1/runs/{run_id}/events", headers=headers, json=event)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()


def test_event_id_cannot_be_reused_for_different_event_data():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    run = client.post(
        "/v1/runs",
        headers=headers,
        json={"watcher_id": WATCHER, "config_revision": 1},
    )
    run_id = run.json()["run_id"]
    event = {
        "event_id": "same-id",
        "occurred_at": "2026-09-19T10:00:00+00:00",
        "level": "info",
        "phase": "source",
        "event_type": "fetch.completed",
        "message": "first",
    }

    assert client.post(f"/v1/runs/{run_id}/events", headers=headers, json=event).status_code == 201
    response = client.post(
        f"/v1/runs/{run_id}/events",
        headers=headers,
        json={**event, "message": "different"},
    )

    assert response.status_code == 422


def test_run_finish_is_idempotent():
    client, store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    run = client.post(
        "/v1/runs",
        headers=headers,
        json={"watcher_id": WATCHER, "config_revision": 1},
    )
    run_id = run.json()["run_id"]

    first = client.post(f"/v1/runs/{run_id}/finish", headers=headers, json={"status": "ok"})
    second = client.post(f"/v1/runs/{run_id}/finish", headers=headers, json={"status": "ok"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert store.runs[run_id].status == "ok"


def test_run_start_is_idempotent_by_client_supplied_run_id():
    client, store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {
        "run_id": "run-from-spool-1",
        "watcher_id": WATCHER,
        "config_revision": 1,
        "scheduler_job_id": "x-post-source",
        "trigger": "scheduled",
    }

    first = client.post("/v1/runs", headers=headers, json=payload)
    second = client.post("/v1/runs", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert len(store.runs) == 1


def test_run_start_rejects_reusing_run_id_for_different_run():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {
        "run_id": "run-from-spool-2",
        "watcher_id": WATCHER,
        "config_revision": 1,
    }

    assert client.post("/v1/runs", headers=headers, json=payload).status_code == 201
    response = client.post(
        "/v1/runs",
        headers=headers,
        json={**payload, "trigger": "manual"},
    )

    assert response.status_code == 422
