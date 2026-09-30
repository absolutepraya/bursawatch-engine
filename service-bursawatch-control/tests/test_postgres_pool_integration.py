"""Real connection reuse check against CI's ephemeral Postgres service."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.postgres_pool import create_postgres_pool
from control_plane.store import PostgresStore


def test_api_reuses_one_physical_postgres_connection():
    dsn = os.environ.get("BURSAWATCH_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("requires an isolated test Postgres database")

    pool = create_postgres_pool(dsn)
    store = PostgresStore(dsn, pool=pool)
    app = create_app(
        store=store,
        auth=StaticTokenAuth(
            machine_token="integration-machine",
            admin_token="integration-admin",
            observer_token="integration-observer",
        ),
    )
    with TestClient(app) as client:
        with pool.connection() as connection:
            first_pid = connection.execute("select pg_backend_pid() as pid").fetchone()["pid"]

        machine_headers = {"Authorization": "Bearer integration-machine"}
        admin_headers = {"Authorization": "Bearer integration-admin"}
        for _ in range(12):
            previous_checkouts = pool.get_stats()["requests_num"]
            assert client.get(
                "/v1/watchers/bursawatch-tg-market-news/config",
                headers=machine_headers,
            ).status_code == 200
            assert pool.get_stats()["requests_num"] > previous_checkouts

        previous_checkouts = pool.get_stats()["requests_num"]
        assert client.get("/v1/source-catalog", headers=admin_headers).status_code == 200
        assert pool.get_stats()["requests_num"] > previous_checkouts

        job = next(job for job in store.list_all_jobs() if job.schedule is not None)
        observation_headers = {"Authorization": "Bearer integration-observer"}
        desired = job.schedule.to_dict()
        observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        previous_checkouts = pool.get_stats()["requests_num"]
        accepted = client.post(
            "/v1/internal/observations",
            headers=observation_headers,
            json={
                "api_version": 1,
                "identity_kind": "job",
                "identity_id": job.job_id,
                "observed_at": observed_at,
                "status": "enabled" if desired["enabled"] else "disabled",
                "evidence": {
                    "runtime_job_key": job.runtime_job_key,
                    "enabled": desired["enabled"],
                    "schedule": {"kind": "interval", "minutes": desired["interval_seconds"] // 60},
                    "last_execution": {"at": None, "status": None},
                },
            },
        )
        assert accepted.status_code == 202, accepted.text
        assert pool.get_stats()["requests_num"] > previous_checkouts

        previous_checkouts = pool.get_stats()["requests_num"]
        observations = client.get("/v1/observations", headers=admin_headers)
        assert observations.status_code == 200
        assert any(item["identity_id"] == job.job_id for item in observations.json())
        assert pool.get_stats()["requests_num"] > previous_checkouts

        previous_checkouts = pool.get_stats()["requests_num"]
        assert client.get("/v1/source-work?status=pending", headers=machine_headers).status_code == 200
        assert pool.get_stats()["requests_num"] > previous_checkouts

        with pool.connection() as connection:
            final_pid = connection.execute("select pg_backend_pid() as pid").fetchone()["pid"]
        assert final_pid == first_pid
        assert pool.get_stats()["connections_num"] == 1
