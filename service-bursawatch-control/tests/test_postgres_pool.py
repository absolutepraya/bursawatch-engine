from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.contract import config_checksum
from control_plane.postgres_pool import create_postgres_pool
from control_plane.source_catalog import MemoryCatalogStore, PostgresCatalogStore, initial_config
from control_plane.source_inbox import PostgresInboxStore
from control_plane.store import PostgresStore
import control_plane.source_inbox as source_inbox


class FakeConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def execute(self, query, _parameters=None):
        self.queries.append(query)
        return self

    def fetchone(self):
        query = self.queries[-1]
        if "bursawatch_config_revisions" in query:
            return {
                "watcher_id": "bursawatch-tg-market-news",
                "revision": 1,
                "config_version": 1,
                "config": {},
                "config_sha256": config_checksum({}),
                "created_at": datetime(2026, 9, 26, tzinfo=timezone.utc),
            }
        if "bursawatch_source_catalog_revisions" in query:
            return {
                "revision": 1,
                "config": initial_config(),
                "config_sha256": "0" * 64,
                "actor_id": "test",
                "created_at": datetime(2026, 9, 26, tzinfo=timezone.utc),
            }
        if "select envelope from bursawatch_source_event_versions" in query:
            return None
        raise AssertionError(f"unexpected query: {query}")

    def fetchall(self):
        return []


class FakePool:
    def __init__(self) -> None:
        self.connection_instance = FakeConnection()
        self.open_count = 0
        self.close_count = 0
        self.checkout_count = 0
        self.return_count = 0
        self.checked_out = False

    def open(self, *, wait: bool, timeout: float) -> None:
        assert wait is True and timeout == 10.0
        self.open_count += 1

    def close(self) -> None:
        self.close_count += 1

    @contextmanager
    def connection(self):
        assert self.open_count == 1 and self.close_count == 0
        assert not self.checked_out, "nested pool checkout"
        self.checked_out = True
        self.checkout_count += 1
        try:
            yield self.connection_instance
        finally:
            self.checked_out = False
            self.return_count += 1


def test_pool_is_bounded_and_disables_prepared_statements():
    with patch("psycopg_pool.ConnectionPool") as constructor:
        create_postgres_pool("postgresql://example.invalid/test")
    assert constructor.call_args.kwargs["min_size"] == 1
    assert constructor.call_args.kwargs["max_size"] == 4
    assert constructor.call_args.kwargs["open"] is False
    assert constructor.call_args.kwargs["kwargs"]["prepare_threshold"] is None


def test_api_lifespan_opens_and_closes_one_shared_pool():
    pool = FakePool()
    store = PostgresStore("postgresql://example.invalid/test", pool=pool)
    app = create_app(store=store, auth=StaticTokenAuth(machine_token="machine", admin_token="admin"))
    with patch("psycopg.connect", side_effect=AssertionError("unexpected new connection")):
        with TestClient(app) as client:
            assert client.get("/healthz").json() == {"status": "ok"}
            assert client.get(
                "/v1/watchers/bursawatch-tg-market-news/config",
                headers={"Authorization": "Bearer machine"},
            ).status_code == 200
            assert client.get(
                "/v1/source-catalog",
                headers={"Authorization": "Bearer admin"},
            ).status_code == 200
            assert client.get(
                "/v1/source-work?status=pending",
                headers={"Authorization": "Bearer machine"},
            ).json() == []
            assert pool.open_count == 1
            assert pool.close_count == 0
    assert pool.close_count == 1
    assert pool.checkout_count == pool.return_count == 4


def test_api_lifespan_closes_pool_when_startup_connection_fails():
    pool = FakePool()
    app = create_app(store=PostgresStore("postgresql://example.invalid/test", pool=pool))
    def fail_open(*, wait: bool, timeout: float):
        raise RuntimeError("database unavailable")
    pool.open = fail_open
    try:
        with TestClient(app):
            raise AssertionError("startup should fail")
    except RuntimeError as exc:
        assert str(exc) == "database unavailable"
    assert pool.close_count == 1


def test_all_postgres_stores_borrow_and_return_the_same_connection():
    pool = FakePool()
    watcher = PostgresStore("postgresql://example.invalid/test", pool=pool)
    catalog = PostgresCatalogStore(watcher.dsn, pool=pool)
    inbox = PostgresInboxStore(watcher.dsn, catalog, pool=pool)
    pool.open(wait=True, timeout=10.0)
    try:
        assert watcher.get_config("bursawatch-tg-market-news").revision == 1
        assert catalog.get()["revision"] == 1
        assert inbox.list_work("pending") == []
    finally:
        pool.close()
    assert pool.checkout_count == pool.return_count == 3
    assert pool.connection_instance.queries and pool.close_count == 1


def test_source_accept_reads_catalog_in_its_existing_transaction(monkeypatch):
    pool = FakePool()
    catalog = PostgresCatalogStore("postgresql://example.invalid/test", pool=pool)
    inbox = PostgresInboxStore(catalog.dsn, catalog, pool=pool)
    envelope = {
        "endpoint_id": "test:endpoint",
        "publisher_id": "test-publisher",
        "platform": "telegram",
        "provider_event_id": "1",
        "content_hash": "0" * 64,
    }
    monkeypatch.setattr(source_inbox, "validate_envelope", lambda _raw: envelope)
    monkeypatch.setattr(source_inbox, "event_key", lambda _envelope: "test-event")
    monkeypatch.setattr(source_inbox, "_subscriptions", lambda _catalog, _registry, _envelope: [])
    pool.open(wait=True, timeout=10.0)
    try:
        assert inbox.accept({}) == {"event_key": "test-event", "version": 1, "duplicate": False, "work_keys": []}
    finally:
        pool.close()
    assert pool.checkout_count == pool.return_count == 1


def test_source_accept_supports_injected_memory_catalog(monkeypatch):
    pool = FakePool()
    inbox = PostgresInboxStore("postgresql://example.invalid/test", MemoryCatalogStore(), pool=pool)
    envelope = {
        "endpoint_id": "test:endpoint",
        "publisher_id": "test-publisher",
        "platform": "telegram",
        "provider_event_id": "1",
        "content_hash": "0" * 64,
    }
    monkeypatch.setattr(source_inbox, "validate_envelope", lambda _raw: envelope)
    monkeypatch.setattr(source_inbox, "event_key", lambda _envelope: "test-event")
    monkeypatch.setattr(source_inbox, "_subscriptions", lambda _catalog, _registry, _envelope: [])
    pool.open(wait=True, timeout=10.0)
    try:
        assert inbox.accept({})["duplicate"] is False
    finally:
        pool.close()
    assert pool.checkout_count == pool.return_count == 1
