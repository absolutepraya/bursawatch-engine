from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api import create_app, create_app_from_environment
from control_plane.auth import AuthenticationError, Principal, StaticTokenAuth
from control_plane.profile_metadata import AvatarResolution
from control_plane.store import InMemoryStore


WATCHER = "bursawatch-x-account-watch"
TOKEN = "machine-token"
ADMIN = "admin-token"
RECONCILER = "reconciler-token"


class ViewerAuth:
    def authenticate(self, authorization: str | None) -> Principal:
        if authorization == "Bearer viewer-token":
            return Principal(subject="viewer-user", kind="viewer")
        raise AuthenticationError("invalid bearer credential")


class AvatarResolver:
    def resolve(self, profile):
        return AvatarResolution(
            url=f"https://pbs.twimg.com/profile_images/{profile.profile_id}.jpg",
            source="rsshub_icon",
        )


PROFILE_CONFIG = {
    "version": 1,
    "profiles": [
        {
            "id": "kutekians",
            "enabled": True,
            "profile_url": "https://x.com/Kutekians",
            "handle": "Kutekians",
            "display_name": "Kutekians",
        }
    ],
}


def build_client():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, {"version": 1, "profiles": []})
    store.seed_job(
        job_id="bursawatch-x-account-watch-source",
        watcher_id=WATCHER,
        display_name="X Account Watch source poller",
        runtime_job_key="bursawatch-x-account-watch",
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
        auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN, reconciler_token=RECONCILER),
        validators={WATCHER: lambda config: None},
    )
    return TestClient(app), store


def test_health_is_public_and_config_requires_authentication():
    client, _store = build_client()

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get(f"/v1/watchers/{WATCHER}/config").status_code == 401


def test_operator_component_reads_are_human_only_and_source_gate_uses_catalog():
    client, _store = build_client()
    admin_headers = {"Authorization": f"Bearer {ADMIN}"}
    machine_headers = {"Authorization": f"Bearer {TOKEN}"}

    inventory = client.get("/v1/components", headers=admin_headers)
    components = {item["component_id"]: item for item in inventory.json()["components"]}

    assert inventory.status_code == 200
    assert inventory.json()["inventory_version"] == 1
    assert components["bursawatch-tg-source-ingest"]["source_gate"]["catalog_revision"] == 1
    assert client.get("/v1/components/bursawatch-tg-source-ingest", headers=admin_headers).status_code == 200
    assert client.get("/v1/components/unknown", headers=admin_headers).status_code == 404
    assert client.get("/v1/components", headers=machine_headers).status_code == 403


def test_cors_allowlist_supports_the_separate_web_origin():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, {"version": 1, "profiles": []})
    from control_plane.api import create_app

    client = TestClient(
        create_app(
            store=store,
            auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN, reconciler_token=RECONCILER),
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


def test_signed_in_viewer_can_read_chronological_logs_but_not_config():
    client, store = build_client()
    headers = {"Authorization": f"Bearer {ADMIN}"}
    for run_id, event_id, occurred_at in (
        ("older-run", "older-event", "2026-09-19T10:00:00+00:00"),
        ("newer-run", "newer-event", "2026-09-19T11:00:00+00:00"),
    ):
        assert client.post(
            "/v1/runs",
            headers=headers,
            json={"watcher_id": WATCHER, "config_revision": 1, "run_id": run_id},
        ).status_code == 201
        assert client.post(
            f"/v1/runs/{run_id}/events",
            headers=headers,
            json={
                "event_id": event_id,
                "occurred_at": occurred_at,
                "level": "info",
                "phase": "delivery",
                "event_type": "delivery.completed",
                "message": event_id,
            },
        ).status_code == 201

    viewer = TestClient(
        create_app(
            store=store,
            auth=ViewerAuth(),
            validators={WATCHER: lambda config: None},
        )
    )
    headers = {"Authorization": "Bearer viewer-token"}

    assert viewer.get("/v1/watchers", headers=headers).status_code == 200
    assert viewer.get(f"/v1/watchers/{WATCHER}/runs", headers=headers).status_code == 200
    assert viewer.get(f"/v1/watchers/{WATCHER}/jobs", headers=headers).status_code == 200
    assert viewer.get("/v1/jobs/bursawatch-x-account-watch-source/schedule", headers=headers).status_code == 200
    events = viewer.get(f"/v1/watchers/{WATCHER}/events", headers=headers)
    assert events.status_code == 200
    assert [event["event_id"] for event in events.json()] == ["newer-event", "older-event"]
    assert viewer.get("/v1/runs/newer-run/events", headers=headers).status_code == 200
    assert viewer.get(f"/v1/watchers/{WATCHER}/config", headers=headers).status_code == 403


def test_machine_can_read_config_but_cannot_write():
    client, _store = build_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    response = client.get(f"/v1/watchers/{WATCHER}/config", headers=headers)
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert client.get("/v1/watchers", headers=headers).status_code == 403

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
        "last_error": None,
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
        "last_error": None,
        "effective": False,
    }


def test_reconciler_only_endpoints_expose_interval_jobs_and_record_verified_outcomes():
    client, store = build_client()
    store.seed_job(
        job_id="bursawatch-tg-source-ingest",
        watcher_id=None,
        display_name="Telegram Source Intake",
        runtime_job_key="bursawatch-tg-source-ingest",
        schedule_kind="interval",
        min_interval_seconds=60,
        max_interval_seconds=3_600,
        enabled=True,
        interval_seconds=60,
        timezone="Asia/Jakarta",
    )
    headers = {"Authorization": f"Bearer {RECONCILER}"}

    schedules = client.get("/v1/internal/schedules", headers=headers)

    assert schedules.status_code == 200
    rows = {job["job_id"]: job for job in schedules.json()}
    assert set(rows) == {"bursawatch-tg-source-ingest", "bursawatch-x-account-watch-source"}
    shared_job = rows["bursawatch-tg-source-ingest"]
    assert shared_job["watcher_id"] is None
    assert set(shared_job) == {
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
    assert "component_ids" not in shared_job
    assert "can_edit" not in shared_job
    applied = client.post(
        "/v1/internal/jobs/bursawatch-x-account-watch-source/reconciliation",
        headers=headers,
        json={"revision": 1, "status": "applied"},
    )

    assert applied.status_code == 200
    assert applied.json()["reconciliation"] == {
        "status": "applied",
        "applied_revision": 1,
        "last_error": None,
        "effective": True,
    }


def test_reconciler_cannot_mark_a_stale_revision_effective_or_retain_old_error():
    client, _store = build_client()
    reconciler_headers = {"Authorization": f"Bearer {RECONCILER}"}
    admin_headers = {"Authorization": f"Bearer {ADMIN}"}

    failed = client.post(
        "/v1/internal/jobs/bursawatch-x-account-watch-source/reconciliation",
        headers=reconciler_headers,
        json={"revision": 1, "status": "error", "error": "hermes cli rejected edit"},
    )
    rewritten = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers=admin_headers,
        json={"enabled": False, "interval_seconds": 7_200, "timezone": "Asia/Jakarta"},
    )
    stale = client.post(
        "/v1/internal/jobs/bursawatch-x-account-watch-source/reconciliation",
        headers=reconciler_headers,
        json={"revision": 1, "status": "applied"},
    )

    assert failed.status_code == 200
    assert failed.json()["reconciliation"]["last_error"] == "hermes cli rejected edit"
    assert rewritten.status_code == 200
    assert rewritten.json()["reconciliation"]["last_error"] is None
    assert stale.status_code == 409
    assert client.get(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers=admin_headers,
    ).json()["reconciliation"] == {
        "status": "pending",
        "applied_revision": None,
        "last_error": None,
        "effective": False,
    }


def test_only_the_reconciler_credential_can_use_internal_schedule_routes():
    client, store = build_client()

    for token in (TOKEN, ADMIN):
        assert client.get("/v1/internal/schedules", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/v1/internal/schedules", headers={"Authorization": "Bearer unknown-token"}).status_code == 401
    viewer = TestClient(create_app(store=store, auth=ViewerAuth(), validators={WATCHER: lambda config: None}))
    assert viewer.get(
        "/v1/internal/schedules",
        headers={"Authorization": "Bearer viewer-token"},
    ).status_code == 403
    assert client.post(
        "/v1/internal/jobs/bursawatch-x-account-watch-source/reconciliation",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"revision": 1, "status": "applied"},
    ).status_code == 403


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
    assert fixed.status_code == 422


def test_schedule_rejects_values_outside_the_job_policy():
    client, _store = build_client()
    response = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"enabled": True, "interval_seconds": 60, "timezone": "Asia/Jakarta"},
    )

    assert response.status_code == 422
    assert "between 600 and 86400" in response.json()["detail"]


def test_schedule_timezone_cannot_claim_a_hermes_setting_that_does_not_exist():
    client, _store = build_client()

    response = client.put(
        "/v1/jobs/bursawatch-x-account-watch-source/schedule",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"enabled": True, "interval_seconds": 600, "timezone": "UTC"},
    )

    assert response.status_code == 422
    assert "scheduler timezone must remain Asia/Jakarta" in response.json()["detail"]


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


def test_dashboard_profile_route_hydrates_metadata_without_exposing_config():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, PROFILE_CONFIG)
    client = TestClient(
        create_app(
            store=store,
            auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN, reconciler_token=RECONCILER),
            validators={WATCHER: lambda config: None},
        )
    )

    response = client.get(f"/v1/watchers/{WATCHER}/profiles", headers={"Authorization": f"Bearer {ADMIN}"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "watcher_id": WATCHER,
            "profile_id": "kutekians",
            "handle": "Kutekians",
            "display_name": "Kutekians",
            "profile_url": "https://x.com/Kutekians",
            "enabled": True,
            "avatar": {
                "mode": "auto",
                "url": None,
                "source": None,
                "fetched_at": None,
                "last_success_at": None,
                "last_error": None,
                "updated_at": response.json()[0]["avatar"]["updated_at"],
            },
        }
    ]
    assert client.get(f"/v1/watchers/{WATCHER}/config", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_config_write_fetches_new_profile_avatar_in_the_background_and_keeps_it_out_of_config():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, {"version": 1, "profiles": []})
    client = TestClient(
        create_app(
            store=store,
            auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN, reconciler_token=RECONCILER),
            validators={WATCHER: lambda config: None},
            avatar_resolver=AvatarResolver(),
        )
    )

    response = client.put(
        f"/v1/watchers/{WATCHER}/config",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"config_version": 1, "config": PROFILE_CONFIG},
    )

    assert response.status_code == 200
    assert "avatar_url" not in response.json()["config"]["profiles"][0]
    profile_response = client.get(
        f"/v1/watchers/{WATCHER}/profiles",
        headers={"Authorization": f"Bearer {ADMIN}"},
    )
    assert profile_response.json()[0]["avatar"] == {
        "mode": "auto",
        "url": "https://pbs.twimg.com/profile_images/kutekians.jpg",
        "source": "rsshub_icon",
        "fetched_at": profile_response.json()[0]["avatar"]["fetched_at"],
        "last_success_at": profile_response.json()[0]["avatar"]["last_success_at"],
        "last_error": None,
        "updated_at": profile_response.json()[0]["avatar"]["updated_at"],
    }


def test_admin_can_use_manual_avatar_override_and_return_to_automatic_refresh():
    store = InMemoryStore()
    store.seed_config(WATCHER, 1, PROFILE_CONFIG)
    client = TestClient(
        create_app(
            store=store,
            auth=StaticTokenAuth(machine_token=TOKEN, admin_token=ADMIN, reconciler_token=RECONCILER),
            validators={WATCHER: lambda config: None},
            avatar_resolver=AvatarResolver(),
        )
    )
    headers = {"Authorization": f"Bearer {ADMIN}"}

    manual = client.put(
        f"/v1/watchers/{WATCHER}/profiles/kutekians/avatar",
        headers=headers,
        json={"mode": "manual", "url": "https://cdn.example.test/kutekians.png"},
    )
    assert manual.status_code == 200
    assert manual.json()["avatar"]["mode"] == "manual"
    assert manual.json()["avatar"]["source"] == "manual"
    assert manual.json()["avatar"]["url"] == "https://cdn.example.test/kutekians.png"

    automatic = client.put(
        f"/v1/watchers/{WATCHER}/profiles/kutekians/avatar",
        headers=headers,
        json={"mode": "auto"},
    )
    assert automatic.status_code == 200
    refreshed = client.get(
        f"/v1/watchers/{WATCHER}/profiles",
        headers=headers,
    ).json()[0]["avatar"]
    assert refreshed["mode"] == "auto"
    assert refreshed["source"] == "rsshub_icon"
    assert refreshed["url"] == "https://pbs.twimg.com/profile_images/kutekians.jpg"
