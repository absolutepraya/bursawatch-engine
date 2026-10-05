"""MVCC capture behavior on an explicitly supplied disposable Postgres DB."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
import uuid

import pytest

from control_plane.postgres_pool import create_postgres_pool
from control_plane.source_catalog import MemoryCatalogStore
from control_plane.source_inbox import PostgresInboxStore, event_key
from test_source_inbox import envelope


@pytest.fixture
def postgres():
    dsn = os.environ.get('BURSAWATCH_TEST_POSTGRES_URL')
    if not dsn:
        pytest.skip('requires isolated local test Postgres')
    pool = create_postgres_pool(dsn)
    pool.open(wait=True)
    schema = 'evidence_test_' + uuid.uuid4().hex
    try:
        with pool.connection() as conn:
            conn.execute(f'create schema {schema}')
            conn.execute(f'create table {schema}.bursawatch_source_event_versions (like public.bursawatch_source_event_versions including all)')
        class SchemaPool:
            @contextmanager
            def connection(self):
                with pool.connection() as conn:
                    # Session setting precedes, but must not start the capture transaction.
                    conn.execute(f'set search_path to {schema}')
                    conn.commit()
                    yield conn
        isolated = SchemaPool()
        yield PostgresInboxStore(dsn, MemoryCatalogStore(), pool=isolated), isolated
    finally:
        with pool.connection() as conn:
            conn.execute(f'drop schema if exists {schema} cascade')
        pool.close()


def source(ident, published, observed=None):
    result = envelope(ident)
    result.update(published_at=published.isoformat(), observed_at=(observed or published).isoformat())
    return result


def insert(conn, item, accepted, version=1, kind='original'):
    conn.execute('insert into bursawatch_source_event_versions (event_key,version,kind,envelope,content_hash,created_at,actor_id,reason) values (%s,%s,%s,%s::jsonb,%s,%s,%s,%s)',
        (event_key(item), version, kind, json.dumps(item), item['content_hash'], accepted,
         None if version == 1 else 'test', None if version == 1 else 'revision'))


def test_late_commit_cannot_enter_already_frozen_manifest(postgres):
    store, pool = postgres
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    lower = cutoff - timedelta(days=3)
    existing = source('committed', cutoff - timedelta(minutes=3))
    late = source('uncommitted', cutoff - timedelta(minutes=2))
    with pool.connection() as conn:
        insert(conn, existing, cutoff - timedelta(minutes=1))
    # A transaction timestamp before cutoff is not proof of visibility at capture.
    with pool.connection() as pending:
        insert(pending, late, cutoff - timedelta(seconds=30))
        class CommitAfterSnapshot:
            @contextmanager
            def connection(self):
                with pool.connection() as capture_conn:
                    class Connection:
                        def execute(self, sql, params=None):
                            result = capture_conn.execute(sql, params)
                            if 'pg_current_snapshot()' in sql:
                                pending.commit()
                            return result
                    yield Connection()
        store.pool = CommitAfterSnapshot()
        frozen = store.capture_window(lower.isoformat(), cutoff.isoformat(), history_available_from=lower.isoformat())
    assert [r['event_key'] for r in frozen['items']] == [event_key(existing)]
    assert frozen['capture_status'] == 'late' and frozen['complete'] is False
    store.pool = pool
    recaptured = store.capture_window(lower.isoformat(), cutoff.isoformat())
    assert {r['event_key'] for r in recaptured['items']} == {event_key(existing), event_key(late)}
    assert store.read_versions([r['version_ref'] for r in frozen['items']])[0]['text'] == 'source'
    assert len(frozen['items']) == 1


def test_postgres_highest_eligible_tombstone_boundaries_overflow_and_batch_integrity(postgres):
    store, pool = postgres
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
    lower = cutoff - timedelta(days=4)
    changed = source('correction', cutoff - timedelta(hours=1))
    deleted = source('deleted', cutoff - timedelta(hours=1))
    upper = source('upper', cutoff)
    lower_item = source('lower', lower)
    unobserved = source('unobserved', cutoff, cutoff + timedelta(seconds=1))
    with pool.connection() as conn:
        for item in (changed, deleted, upper, lower_item, unobserved):
            insert(conn, item, cutoff - timedelta(seconds=30))
        correction = deepcopy(changed)
        correction.update(published_at=(lower - timedelta(seconds=1)).isoformat(), content_hash='b' * 64)
        insert(conn, correction, cutoff - timedelta(seconds=20), version=2, kind='correction')
        tombstone = deepcopy(deleted)
        tombstone.update(payload={}, content_hash='c' * 64)
        insert(conn, tombstone, cutoff - timedelta(seconds=10), version=2, kind='tombstone')
    manifest = store.capture_window(lower.isoformat(), cutoff.isoformat(), limit=1)
    assert [r['event_key'] for r in manifest['items']] == [event_key(upper)]
    assert manifest['overflow'] is False
    ref = manifest['items'][0]['version_ref']
    before = store.read_versions([ref])[0]
    with pool.connection() as conn:
        next_item = source('second', cutoff - timedelta(minutes=2))
        insert(conn, next_item, cutoff - timedelta(seconds=40))
        revised = deepcopy(upper)
        revised.update(payload={'text': 'later'}, content_hash='d' * 64)
        insert(conn, revised, cutoff + timedelta(seconds=1), version=2, kind='correction')
    assert store.read_versions([ref])[0] == before
    assert store.capture_window(lower.isoformat(), cutoff.isoformat(), limit=1)['overflow'] is True
    with pool.connection() as conn:
        conn.execute("update bursawatch_source_event_versions set envelope=jsonb_set(envelope,'{payload,text}','\"corrupted\"'::jsonb) where event_key=%s and version=1", (event_key(upper),))
    with pytest.raises(ValueError, match='integrity'):
        store.read_versions([ref])
