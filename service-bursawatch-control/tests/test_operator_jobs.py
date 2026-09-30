from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import Principal, StaticTokenAuth
from control_plane.operator_inventory import list_components
from control_plane.store import InMemoryStore


ADMIN = "admin-token"
VIEWER = "viewer-token"
MACHINE = "machine-token"


class JobAuth(StaticTokenAuth):
    def authenticate(self, authorization: str | None) -> Principal:
        if authorization == f"Bearer {VIEWER}":
            return Principal(subject="viewer", kind="viewer")
        return super().authenticate(authorization)


def _seed_jobs() -> InMemoryStore:
    store = InMemoryStore()
    job_ids = {job_id for component in list_components() for job_id in component.job_ids}
    job_ids.update({"bursawatch-tg-market-news-watchdog"})
    interval_specs = {
        "bursawatch-tg-source-ingest": (None, "Telegram Source Intake", 60, 3600, True, 60),
        "bursawatch-x-account-watch-source": ("bursawatch-x-account-watch", "X Account Watch source poller", 600, 86400, True, 600),
        "bursawatch-wa-channel-watch": ("bursawatch-wa-channel-watch", "WhatsApp Channel Watch", 60, 21600, False, 60),
        "bursawatch-stockbit-snips": ("bursawatch-stockbit-snips", "Stockbit Snips", 300, 3600, True, 900),
        "bursawatch-tg-market-news": ("bursawatch-tg-market-news", "Telegram Market News", 60, 3600, False, 60),
    }
    fixed_watchers = {
        "bursawatch-x-account-watch-queue-worker": "bursawatch-x-account-watch",
        "bursawatch-dc-swing-board-close": "bursawatch-dc-swing-board",
        "bursawatch-dc-swing-board-retry": "bursawatch-dc-swing-board",
        "bursawatch-dc-swing-board-lifecycle": "bursawatch-dc-swing-board",
        "bursawatch-tg-market-news-watchdog": "bursawatch-tg-market-news",
    }
    for job_id in sorted(job_ids):
        if job_id in interval_specs:
            watcher, name, minimum, maximum, enabled, interval = interval_specs[job_id]
            kwargs = dict(
                job_id=job_id,
                watcher_id=watcher,
                display_name=name,
                runtime_job_key=job_id,
                schedule_kind="interval",
                min_interval_seconds=minimum,
                max_interval_seconds=maximum,
                enabled=enabled,
                interval_seconds=interval,
                timezone="Asia/Jakarta",
            )
        else:
            watcher = fixed_watchers.get(job_id)
            kwargs = dict(
                job_id=job_id,
                watcher_id=watcher,
                display_name=job_id.replace("-", " ").title(),
                runtime_job_key=job_id,
                schedule_kind="fixed",
            )
        if job_id == "bursawatch-x-account-watch-queue-worker":
            kwargs["runtime_job_key"] = "bursawatch-x-account-watch-queue"
        store.seed_job(**kwargs)
    return store


def _client(store: InMemoryStore | None = None) -> TestClient:
    return TestClient(
        create_app(
            store=store or _seed_jobs(),
            auth=JobAuth(machine_token=MACHINE, admin_token=ADMIN, reconciler_token="reconciler-token"),
        )
    )


def test_telegram_job_is_one_global_row():
    client = _client()
    response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {VIEWER}"})

    assert response.status_code == 200
    rows = response.json()
    matches = [job for job in rows if job["job_id"] == "bursawatch-tg-source-ingest"]
    assert len(matches) == 1
    job = matches[0]
    assert job["runtime_job_key"] == "bursawatch-tg-source-ingest"
    assert job["watcher_id"] is None
    assert set(job["component_ids"]) == {
        "bursawatch-tg-source-ingest",
        "bursawatch-tg-market-news",
        "bursawatch-tg-phintraco-swing",
        "bursawatch-tg-kelas-investasi-gtw",
    }


def test_global_inventory_includes_paused_readers_watchdog_and_board_lifecycle_once():
    client = _client()
    rows = client.get("/v1/jobs", headers={"Authorization": f"Bearer {VIEWER}"}).json()
    by_id = {job["job_id"]: job for job in rows}

    assert len(rows) == len(by_id)
    assert set(by_id) == {job_id for item in list_components() for job_id in item.job_ids} | {"bursawatch-tg-market-news-watchdog"}
    assert by_id["bursawatch-tg-market-news"]["schedule"]["enabled"] is False
    assert by_id["bursawatch-tg-market-news-watchdog"]["schedule_kind"] == "fixed"
    assert by_id["bursawatch-dc-swing-board-lifecycle"]["runtime_job_key"] == "bursawatch-dc-swing-board-lifecycle"
    assert by_id["bursawatch-x-account-watch-queue-worker"]["runtime_job_key"] == "bursawatch-x-account-watch-queue"
    assert by_id["bursawatch-tg-source-ingest"]["can_edit"] is False
    assert by_id["bursawatch-dc-swing-board-lifecycle"]["can_edit"] is False


def test_job_inventory_exposes_server_derived_safe_edit_entitlement():
    client = _client()
    admin = client.get("/v1/jobs", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    viewer = client.get("/v1/jobs", headers={"Authorization": f"Bearer {VIEWER}"}).json()
    admin_by_id = {job["job_id"]: job for job in admin}
    viewer_by_id = {job["job_id"]: job for job in viewer}
    assert admin_by_id["bursawatch-tg-source-ingest"]["can_edit"] is True
    assert admin_by_id["bursawatch-dc-swing-board-lifecycle"]["can_edit"] is False
    assert viewer_by_id["bursawatch-tg-source-ingest"]["can_edit"] is False


def test_existing_revisions_are_unchanged():
    store = _seed_jobs()
    before = {
        job_id: store.get_job(job_id).schedule
        for job_id in (
            "bursawatch-x-account-watch-source",
            "bursawatch-wa-channel-watch",
            "bursawatch-stockbit-snips",
        )
    }
    client = _client(store)
    after = {
        job_id: next(job for job in client.get("/v1/jobs", headers={"Authorization": f"Bearer {VIEWER}"}).json() if job["job_id"] == job_id)["schedule"]
        for job_id in before
    }
    assert after == {job_id: snapshot.to_dict() for job_id, snapshot in before.items()}


def test_fixed_board_job_has_no_schedule_write():
    client = _client()
    response = client.put(
        "/v1/jobs/bursawatch-dc-swing-board-lifecycle/schedule",
        headers={"Authorization": f"Bearer {ADMIN}"},
        json={"enabled": False, "interval_seconds": 60, "timezone": "Asia/Jakarta"},
    )
    assert response.status_code == 422


def test_global_job_reads_are_human_only_and_unknown_job_is_not_found():
    client = _client()
    assert client.get("/v1/jobs", headers={"Authorization": f"Bearer {MACHINE}"}).status_code == 403
    assert client.get("/v1/jobs/bursawatch-tg-source-ingest", headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 200
    assert client.get("/v1/jobs/missing", headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 404


def test_migration_registers_global_jobs_without_rewriting_existing_schedule_revisions():
    migration = (Path(__file__).resolve().parents[1] / "migrations/019_operator_inventory.sql").read_text()
    assert migration.startswith("-- bursawatch-release: manual\n")
    assert "bursawatch-tg-source-ingest" in migration
    assert "bursawatch-tg-market-news-watchdog" in migration
    assert "bursawatch-dc-swing-board-lifecycle" in migration
    assert "bursawatch-x-account-watch-queue" in migration
    assert "on conflict (job_id, revision) do nothing" in migration
    assert "current_schedule_revision is null" in migration
    assert "update bursawatch_schedule_revisions" not in migration.lower()
