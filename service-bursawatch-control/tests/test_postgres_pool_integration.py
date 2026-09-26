"""Real connection reuse check against CI's ephemeral Postgres service."""

from __future__ import annotations

import os

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
    app = create_app(
        store=PostgresStore(dsn, pool=pool),
        auth=StaticTokenAuth(machine_token="integration-machine", admin_token="integration-admin"),
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

        previous_checkouts = pool.get_stats()["requests_num"]
        assert client.get("/v1/source-work?status=pending", headers=machine_headers).status_code == 200
        assert pool.get_stats()["requests_num"] > previous_checkouts

        with pool.connection() as connection:
            final_pid = connection.execute("select pg_backend_pid() as pid").fetchone()["pid"]
        assert final_pid == first_pid
        assert pool.get_stats()["connections_num"] == 1
