"""Frozen evidence must not follow revisions, moving windows, or worker state."""
from copy import deepcopy
from datetime import datetime, timezone
import re

import pytest
from fastapi.testclient import TestClient

from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth, Principal, auth_from_environment
from control_plane.source_catalog import MemoryCatalogStore
from control_plane.source_inbox import MemoryInboxStore
from control_plane.store import InMemoryStore
from test_source_inbox import envelope

START = '2026-09-24T00:00:00+00:00'
CUTOFF = '2026-09-24T01:00:00+00:00'
READER = {'Authorization': 'Bearer ' + 'r' * 32}


def fixture(monkeypatch):
    now = [datetime.fromisoformat('2026-09-24T00:30:00+00:00')]
    monkeypatch.setattr('control_plane.source_inbox._now', lambda: now[0])
    inbox = MemoryInboxStore(MemoryCatalogStore())
    item = envelope()
    item.update(published_at='2026-09-24T00:20:00Z', observed_at='2026-09-24T00:21:00Z')
    return inbox, item, now


def test_capture_keeps_explicit_version_after_correction_and_tombstone(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    receipt = inbox.accept(item)
    now[0] = datetime.fromisoformat(CUTOFF)
    assert hasattr(inbox, 'capture_window'), 'missing immutable source capture'
    manifest = inbox.capture_window(START, CUTOFF, history_available_from=START)
    assert manifest['capture_status'] == 'on_time'
    assert manifest['complete'] is True
    assert manifest['items'][0]['version'] == 1
    assert manifest['items'][0]['accepted_at'] == '2026-09-24T00:30:00+00:00'
    frozen = manifest['items'][0]
    now[0] = datetime.fromisoformat('2026-09-24T01:10:00+00:00')
    changed = deepcopy(item)
    changed.update(content_hash='b' * 64, payload={'text': 'changed'})
    inbox.revise(receipt['event_key'], changed, 'correction', 'edit1', 'test', 'edit')
    changed.update(content_hash='c' * 64, payload={})
    inbox.revise(receipt['event_key'], changed, 'tombstone', 'delete1', 'test', 'delete')
    records = inbox.read_versions([frozen['version_ref']])
    assert records[0]['text'] == 'source'
    assert records[0]['evidence_hash'] == frozen['evidence_hash']
    assert records[0]['original_publisher_id'] is None
    assert records[0]['origin_status'] == 'unknown'
    assert inbox.capture_window(START, '2026-09-24T01:20:00Z')['items'] == []


def test_latest_eligible_version_selected_before_publication_window(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    first = inbox.accept(item)
    correction = deepcopy(item)
    correction.update(published_at='2026-09-23T23:00:00Z', content_hash='b' * 64)
    inbox.revise(first['event_key'], correction, 'correction', 'edit1', 'test', 'edit')
    now[0] = datetime.fromisoformat(CUTOFF)
    assert hasattr(inbox, 'capture_window'), 'missing highest eligible version capture'
    assert inbox.capture_window(START, CUTOFF)['items'] == []


def test_boundaries_observation_acceptance_overflow_and_history_are_honest(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    for ident, published, observed, accepted in [
        ('lower', START, '2026-09-24T00:21:00Z', '2026-09-24T00:30:00Z'),
        ('upper', CUTOFF, CUTOFF, CUTOFF),
        ('second', '2026-09-24T00:40:00Z', '2026-09-24T00:41:00Z', '2026-09-24T00:50:00Z'),
        ('unobserved', '2026-09-24T00:50:00Z', '2026-09-24T01:01:00Z', CUTOFF),
        ('late', '2026-09-24T00:50:00Z', CUTOFF, '2026-09-24T01:01:00Z'),
    ]:
        now[0] = datetime.fromisoformat(accepted.replace('Z', '+00:00'))
        candidate = deepcopy(item)
        candidate.update(provider_event_id=ident, published_at=published, observed_at=observed)
        inbox.accept(candidate)
    assert hasattr(inbox, 'capture_window'), 'missing bounded capture'
    manifest = inbox.capture_window(START, CUTOFF, limit=1)
    assert manifest['capture_status'] == 'late'
    assert manifest['capture_gap_seconds'] == 60
    assert manifest['overflow'] is True
    assert manifest['history_status'] == 'unknown'
    assert manifest['complete'] is False
    assert len(manifest['items']) == 1
    full = inbox.capture_window(START, CUTOFF, limit=10, history_available_from=START)
    assert [r['published_at'] for r in full['items']] == ['2026-09-24T00:40:00+00:00', CUTOFF]
    now[0] = datetime.fromisoformat('2026-09-24T00:59:00Z')
    early = inbox.capture_window(START, CUTOFF, history_available_from='2026-09-24T00:10:00Z')
    assert early['capture_status'] == 'early'
    assert early['history_status'] == 'unavailable'
    assert early['complete'] is False


def test_batch_rejects_tampering_missing_duplicate_and_excess_refs(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    inbox.accept(item)
    now[0] = datetime.fromisoformat(CUTOFF)
    assert hasattr(inbox, 'capture_window'), 'missing integrity bound version reads'
    ref = inbox.capture_window(START, CUTOFF)['items'][0]['version_ref']
    with pytest.raises(ValueError):
        inbox.read_versions([ref, ref])
    with pytest.raises(ValueError):
        inbox.read_versions(['bad-ref'])
    with pytest.raises(ValueError):
        inbox.read_versions([ref] * 101)
    inbox.events[next(iter(inbox.events))]['versions'][0]['envelope']['payload']['text'] = 'corrupted'
    with pytest.raises(ValueError, match='integrity'):
        inbox.read_versions([ref])
    inbox.events.clear()
    with pytest.raises(KeyError):
        inbox.read_versions([ref])


def test_sanitized_text_excludes_unrelated_config_and_bounds_content(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    item['payload'] = {'text': 'x' * 13000, 'secret_config': {'token': 'must-not-return'}}
    inbox.accept(item)
    assert hasattr(inbox, 'capture_window'), 'missing safe evidence view'
    manifest = inbox.capture_window(START, CUTOFF)
    record = inbox.read_versions([manifest['items'][0]['version_ref']])[0]
    assert len(record['text']) == 12000
    assert record['text_truncated'] is True
    assert 'must-not-return' not in str(record)
    assert 'payload' not in record


@pytest.mark.parametrize('supabase', [False, True])
def test_environment_factory_recognizes_reader_without_crossing_roles(monkeypatch, supabase):
    monkeypatch.setenv('CONTROL_PLANE_SOURCE_READER_TOKEN', 'r' * 32)
    monkeypatch.delenv('CONTROL_PLANE_ADMIN_TOKEN', raising=False)
    monkeypatch.setenv('CONTROL_PLANE_SUPABASE_URL', 'https://example.supabase.co' if supabase else '')
    # Constructor only; no JWT authentication/network is exercised.
    class RejectJwt:
        def authenticate(self, _authorization):
            from control_plane.auth import AuthenticationError
            raise AuthenticationError('invalid fake JWT')
    monkeypatch.setattr('control_plane.auth.SupabaseJwtAuth', lambda *args: RejectJwt())
    auth = auth_from_environment()
    assert auth.authenticate(READER['Authorization']) == Principal('source-evidence-reader', 'source_reader')


def test_reader_only_surface_denies_every_other_registered_authenticated_route(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    class ReaderAuth:
        def authenticate(self, _authorization):
            return Principal('source-evidence-reader', 'source_reader')
    app = create_app(store=InMemoryStore(), inbox_store=inbox, auth=ReaderAuth())
    client = TestClient(app)
    for route in app.routes:
        if not route.path.startswith('/v1/') or route.path.startswith('/v1/source-evidence/'):
            continue
        path = re.sub(r'\{[^}]+\}', 'test', route.path)
        for method in route.methods:
            response = client.request(method, path, headers=READER, json={})
            assert response.status_code == 403, (method, path, response.status_code)


def test_read_routes_allow_reader_but_deny_general_machine(monkeypatch):
    inbox, item, now = fixture(monkeypatch)
    inbox.accept(item)
    assert 'source_reader_token' in __import__('inspect').signature(StaticTokenAuth).parameters, 'missing dedicated reader token'
    api = TestClient(create_app(store=InMemoryStore(), inbox_store=inbox,
        auth=StaticTokenAuth('machine', 'admin', source_reader_token='r' * 32)))
    request = {'previous_cutoff': START, 'cutoff': CUTOFF, 'limit': 10}
    capture = api.post('/v1/source-evidence/capture', headers=READER, json=request)
    assert capture.status_code == 200, capture.text
    ref = capture.json()['items'][0]['version_ref']
    response = api.post('/v1/source-evidence/versions', headers=READER, json={'version_refs': [ref]})
    assert response.status_code == 200
    assert response.json()['items'][0]['text'] == 'source'
    assert api.post('/v1/source-evidence/capture', headers={'Authorization': 'Bearer machine'}, json=request).status_code == 403
    assert api.post('/v1/source-evidence/versions', headers=READER, json={'version_refs': ['bad']}).status_code == 422
    before = deepcopy(inbox.work)
    api.post('/v1/source-evidence/capture', headers=READER, json=request)
    assert inbox.work == before


@pytest.mark.parametrize('token', [' ' * 32, 'r' * 31 + ' '])
def test_reader_credentials_cannot_be_unusable_after_bearer_normalization(token):
    with pytest.raises(ValueError, match='source reader'):
        StaticTokenAuth('machine', 'admin', source_reader_token=token)
