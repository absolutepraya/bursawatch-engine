from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from control_plane.api import create_app
from control_plane.operator_observations import MemoryObservationStore, validate_observation
from control_plane.publication_coverage import coverage_view, validate_checkpoint
from control_plane.publication_model import OWNER_ROUTES
from control_plane.publication_store import MemoryPublicationStore, PublicationConflict
from control_plane.store import InMemoryStore
from test_publication_api import ADMIN_TOKEN, OWNER, OWNER_TOKEN, PublicationAuth


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
BOUNDARY = "2026-09-29T07:01:00+00:00"


def comparison(at: datetime = NOW, *, outstanding: int = 0) -> dict:
    return {
        "compared_at": at.isoformat(),
        "confirmed_through_at": None,
        "accepted_through_at": None,
        "outstanding_count": outstanding,
    }


def test_missing_and_stale_checkpoints_are_unknown_and_all_owners_are_required():
    cutover = {"boundary": BOUNDARY, "owner_ids": tuple(OWNER_ROUTES)}
    one = {OWNER: comparison()}
    view = coverage_view(cutover, one, now=NOW)
    assert view["overall_status"] == "incomplete"
    assert next(row for row in view["owners"] if row["owner_id"] == OWNER)["status"] == "complete"
    assert all(row["status"] == "unknown" for row in view["owners"] if row["owner_id"] != OWNER)
    stale = coverage_view(cutover, {OWNER: comparison(NOW - timedelta(hours=1))}, now=NOW)
    assert next(row for row in stale["owners"] if row["owner_id"] == OWNER)["status"] == "unknown"
    paused = coverage_view(cutover, one, now=NOW, paused_owner_ids={OWNER})
    assert next(row for row in paused["owners"] if row["owner_id"] == OWNER)["status"] == "paused/unverified"


def test_nonzero_outstanding_is_lagging_and_zero_requires_equal_boundaries():
    cutover = {"boundary": BOUNDARY, "owner_ids": (OWNER,)}
    lag = coverage_view(cutover, {OWNER: comparison(outstanding=2)}, now=NOW)
    assert lag["owners"][0]["status"] == "lagging"
    bad = comparison()
    bad["confirmed_through_at"] = "2026-09-30T11:50:00+00:00"
    with pytest.raises(ValueError, match="equal"):
        validate_checkpoint(bad, BOUNDARY, now=NOW)


def test_owner_checkpoint_is_scoped_monotonic_and_immutable_at_same_time():
    store = MemoryPublicationStore()
    store.activate(BOUNDARY, (OWNER,))
    actual_now = datetime.now(timezone.utc)
    first = store.checkpoint(OWNER, comparison(actual_now))
    assert store.checkpoint(OWNER, comparison(actual_now - timedelta(minutes=1))) == first
    with pytest.raises(PublicationConflict, match="conflicts"):
        store.checkpoint(OWNER, comparison(actual_now, outstanding=1))
    with pytest.raises(ValueError, match="outside"):
        store.checkpoint("bursawatch-stockbit-snips", comparison(actual_now))


def test_checkpoint_post_and_coverage_get_keep_machine_and_human_roles_separate():
    store = MemoryPublicationStore()
    store.activate(BOUNDARY, (OWNER,))
    app = TestClient(create_app(
        store=InMemoryStore(), publication_store=store,
        auth=PublicationAuth(
            machine_token="m" * 32, admin_token=ADMIN_TOKEN,
            publication_owner_tokens={OWNER: OWNER_TOKEN},
        ),
    ))
    accepted = app.post(
        "/v1/publications/checkpoints", json=comparison(datetime.now(timezone.utc)),
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )
    assert accepted.status_code == 202, accepted.text
    assert app.post(
        "/v1/publications/checkpoints", json=comparison(),
        headers={"Authorization": "Bearer viewer-token"},
    ).status_code == 403
    assert app.get("/v1/publications/coverage", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}).status_code == 403
    read = app.get("/v1/publications/coverage", headers={"Authorization": "Bearer viewer-token"})
    assert read.status_code == 200
    assert read.json()["overall_status"] == "complete"


def test_stale_last_known_disabled_job_cannot_make_owner_complete():
    store = MemoryPublicationStore()
    store.activate(BOUNDARY, (OWNER,))
    store.checkpoint(OWNER, comparison(datetime.now(timezone.utc)))
    jobs = InMemoryStore()
    jobs.seed_job(
        job_id=OWNER, watcher_id=OWNER, display_name="Synthetic owner job",
        runtime_job_key=OWNER, schedule_kind="fixed",
    )
    observations = MemoryObservationStore()
    six_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=6)
    observed = validate_observation({
        "api_version": 1, "identity_kind": "job", "identity_id": OWNER,
        "observed_at": six_minutes_ago.isoformat().replace("+00:00", "Z"),
        "status": "disabled",
        "evidence": {"runtime_job_key": OWNER, "enabled": False,
                     "schedule": {"kind": "cron", "expr": "* * * * *"},
                     "last_execution": {"at": None, "status": None}},
    }, "synthetic-observer", jobs.list_all_jobs())
    observations.accept(observed)
    app = TestClient(create_app(
        store=jobs, publication_store=store, observation_store=observations,
        auth=PublicationAuth(machine_token="m" * 32, admin_token=ADMIN_TOKEN),
    ))
    response = app.get("/v1/publications/coverage", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    assert response.json()["owners"][0]["status"] == "paused/unverified"
    assert response.json()["overall_status"] == "incomplete"
