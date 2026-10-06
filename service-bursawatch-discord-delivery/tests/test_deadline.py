"""Deadline behavior with private temporary state and fake Discord transport."""
from dataclasses import replace
from datetime import timedelta, timezone

import pytest
import requests

from discord_delivery.discord_gateway import DiscordGateway
from discord_delivery.worker import DeliveryWorker
from test_discord_gateway import Response, Session

from discord_delivery.models import Attachment, OperationIntent, ValidationError
from discord_delivery.store import DeliveryStore, OperationKeyConflict
from test_api import operation as api_operation, setup_client, submit
from test_worker import NOW, operation


def test_optional_deadline_preserves_legacy_digest_and_requires_aware_datetime():
    original = operation()
    assert original.digest == '699f27f31b326cc1d31512f50736b3fa810114290622073976eeb4368c75add1'
    assert replace(original, attempt_deadline=None).digest == original.digest
    for invalid in (NOW.replace(tzinfo=None), '2026-09-24T00:00:00Z', 12):
        with pytest.raises(ValidationError, match='attempt deadline'):
            replace(original, attempt_deadline=invalid)
    aware = replace(original, attempt_deadline=NOW)
    offset = replace(original, attempt_deadline=NOW.astimezone(timezone(timedelta(hours=7))))
    assert aware.digest == offset.digest
    assert aware.digest != original.digest
    assert replace(original, attempt_deadline=NOW + timedelta(microseconds=1)).digest != aware.digest


def test_api_deadline_persists_bytes_digest_and_conflict_across_restart(tmp_path):
    client, store = setup_client(tmp_path)
    value = api_operation(attempt_deadline='2026-09-24T07:00:00+07:00')
    first = submit(client, value, attachments=[('chart.png', b'frozen image', 'image/png')])
    assert first.status_code == 202
    assert set(first.json()) == {'id', 'key', 'digest', 'status', 'receipt'}
    store.db.close()
    for _ in range(2):
        reopened = DeliveryStore(tmp_path / 'delivery.sqlite3', tmp_path / 'media')
        intent = reopened.load_intent(value['key'])
        assert intent.attempt_deadline == NOW
        assert intent.attachments[0].data == b'frozen image'
        assert intent.digest == first.json()['digest']
        assert reopened.accept(intent).id == first.json()['id']
        with pytest.raises(OperationKeyConflict):
            reopened.accept(replace(intent, attempt_deadline=NOW + timedelta(seconds=1)))
        reopened.db.close()


@pytest.mark.parametrize('value', ['2026-09-24T00:00:00', 'bad', 5])
def test_api_rejects_naive_or_invalid_deadline(tmp_path, value):
    client, store = setup_client(tmp_path)
    assert submit(client, api_operation(attempt_deadline=value)).status_code == 422
    assert store.counts()['pending'] == 0


def test_old_schema_migration_preserves_legacy_keys_receipts_bytes_and_repeats(tmp_path):
    store = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
    old = replace(operation(), attachments=(Attachment('chart.png', 'image/png', b'frozen'),))
    record = store.adopt_completed(old, {'message_id': '456'})
    # Recreate a pre-deadline database without assuming its new column names.
    original_columns = {'id', 'operation_key', 'payload_digest', 'kind', 'ordering_key',
        'target_json', 'payload_json', 'attachments_json', 'status', 'attempt_count',
        'next_attempt_at', 'error_category', 'receipt_json', 'create_recovery_json',
        'created_at', 'updated_at'}
    for row in list(store.db.execute('PRAGMA table_info(discord_operations)')):
        if row['name'] not in original_columns:
            store.db.execute('ALTER TABLE discord_operations DROP COLUMN ' + row['name'])
    store.db.close()
    for _ in range(2):
        reopened = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
        restored = reopened.load_intent(old.key)
        assert restored.digest == old.digest
        assert restored.attempt_deadline is None
        assert restored.attachments[0].data == b'frozen'
        assert reopened.get_by_key(old.key).id == record.id
        assert reopened.get_by_key(old.key).receipt == {'message_id': '456'}
        reopened.db.close()



class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def deadline_worker(tmp_path, responses=(), *, session=None, clock=None):
    store = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
    transport = session if session is not None else Session(responses)
    current = clock if clock is not None else Clock()
    delivery = DeliveryWorker(store, DiscordGateway('fake-token', session=transport),
                              alert=lambda *_: None, clock=current)
    return store, transport, delivery, current


@pytest.mark.parametrize('kind', ['create', 'edit'])
def test_queued_expiry_rejects_without_gateway_io_and_unblocks_order(tmp_path, kind):
    store, session, delivery, clock = deadline_worker(tmp_path)
    original = operation() if kind == 'create' else OperationIntent(
        'one', 'channel_message_edit', 'channel:123',
        {'channel_id': '123', 'message_id': '456'}, {'content': 'edit'})
    store.accept(replace(original, attempt_deadline=NOW))
    store.accept(operation('two'))
    assert delivery.run_once(NOW).status == 'rejected'
    record = store.get_by_key('one')
    assert record.error_category == 'attempt_deadline_expired'
    assert record.receipt is None
    assert session.calls == []
    assert store.claim_next().key == 'two'


def test_retry_after_definite_rate_limit_expires_without_second_post(tmp_path):
    store, session, delivery, clock = deadline_worker(tmp_path, [Response(body=[]), Response(429, {'retry_after': 8})])
    store.accept(replace(operation(), attempt_deadline=NOW + timedelta(seconds=2)))
    assert delivery.run_once(NOW).status == 'retrying'
    clock.now += timedelta(seconds=10)
    assert delivery.run_once(clock.now).status == 'rejected'
    assert store.get_by_key('one').error_category == 'attempt_deadline_expired'
    assert [item[0] for item in session.calls] == ['GET', 'POST']


def test_clock_crossing_during_snapshot_prevents_first_post(tmp_path):
    clock = Clock()
    class SlowRead(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            assert method == 'GET'
            clock.now += timedelta(seconds=3)
            return Response(body=[])
    store, session, delivery, clock = deadline_worker(tmp_path, session=SlowRead([]), clock=clock)
    store.accept(replace(operation(), attempt_deadline=NOW + timedelta(seconds=1)))
    assert delivery.run_once(NOW).status == 'rejected'
    assert store.get_by_key('one').error_category == 'attempt_deadline_expired'
    assert [item[0] for item in session.calls] == ['GET']


def test_send_started_before_expiry_retains_success_after_expiry(tmp_path):
    clock = Clock()
    class SlowSend(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == 'POST':
                clock.now += timedelta(seconds=3)
                return Response(body={'id': '456'})
            return Response(body=[])
    store, session, delivery, clock = deadline_worker(tmp_path, session=SlowSend([]), clock=clock)
    store.accept(replace(operation(), attempt_deadline=NOW + timedelta(seconds=1)))
    assert delivery.run_once(NOW).status == 'delivered'
    assert store.get_by_key('one').receipt == {'message_id': '456'}
    assert [item[0] for item in session.calls] == ['GET', 'POST']


@pytest.mark.parametrize('outcome,expected', [('match', 'delivered'), ('absence', 'rejected'), ('inconclusive', 'ambiguous'), ('read_error', 'pending_reconciliation')])
def test_accepted_response_loss_after_expiry_keeps_reconciliation_semantics(tmp_path, outcome, expected):
    clock = Clock()
    class LostResponse(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == 'POST':
                clock.now += timedelta(seconds=3)
                raise requests.Timeout('fake response lost')
            if len(self.calls) == 1 or outcome == 'absence':
                return Response(body=[])
            if outcome == 'read_error':
                return Response(429, {'retry_after': 2})
            if outcome == 'match':
                return Response(body=[{'id': '456', 'content': 'exact content', 'nonce': DiscordGateway.nonce('one')}])
            return Response(body=[{'id': '456', 'content': 'exact content', 'nonce': None}])
    store, session, delivery, clock = deadline_worker(tmp_path, session=LostResponse([]), clock=clock)
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(intent)
    assert delivery.run_once(NOW).status == expected
    assert [item[0] for item in session.calls] == ['GET', 'POST', 'GET']
    reopened = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
    record = reopened.get_by_key('one')
    assert record.digest == intent.digest
    assert record.receipt == ({'message_id': '456'} if outcome == 'match' else None)
    if outcome == 'absence':
        assert record.error_category == 'attempt_deadline_expired'
    if outcome == 'read_error':
        restarted = DeliveryWorker(reopened, delivery.gateway, alert=lambda *_: None, clock=clock)
        clock.now += timedelta(seconds=3)
        assert restarted.run_once(clock.now).status == 'pending_reconciliation'
        assert [item[0] for item in session.calls].count('POST') == 1


def test_clock_crossing_during_second_absence_reconciliation_prevents_resend(tmp_path):
    clock = Clock()
    class LateAbsence(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if len(self.calls) == 1:
                return Response(body=[])
            clock.now += timedelta(seconds=20)
            return Response(body=[])
    store, session, delivery, clock = deadline_worker(tmp_path, session=LateAbsence([]), clock=clock)
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=10))
    store.accept(intent)
    claimed = store.claim_next()
    delivery._snapshot(claimed, intent)
    snapshot = store.create_snapshot('one')
    snapshot['absence_backoff_done'] = True
    store.save_create_snapshot('one', snapshot)
    store.finish('one', 'pending_reconciliation')
    assert delivery.run_once(NOW).status == 'rejected'
    assert [item[0] for item in session.calls] == ['GET', 'GET']
    assert store.get_by_key('one').error_category == 'attempt_deadline_expired'


@pytest.mark.parametrize('kind', ['create', 'edit'])
def test_interrupted_attempt_after_expiry_never_becomes_safe_rejection(tmp_path, kind):
    store, session, delivery, clock = deadline_worker(tmp_path, [Response(body=[])])
    original = operation() if kind == 'create' else OperationIntent(
        'one', 'channel_message_edit', 'channel:123',
        {'channel_id': '123', 'message_id': '456'}, {'content': 'edit'})
    intent = replace(original, attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(intent)
    store.claim_next()  # Simulates a crash before a durable result; outcome unknown.
    store.db.close()
    reopened = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
    clock.now += timedelta(seconds=2)
    restarted = DeliveryWorker(reopened, delivery.gateway, alert=lambda *_: None, clock=clock)
    assert restarted.run_once(clock.now).status == 'ambiguous'
    assert reopened.get_by_key('one').receipt is None
    assert reopened.get_by_key('one').error_category != 'attempt_deadline_expired'
    assert all(item[0] == 'GET' for item in session.calls)


def test_uncertain_noncreate_retry_expiry_retains_unknown_outcome(tmp_path):
    class LostPatch(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            assert method == 'PATCH'
            raise requests.Timeout('fake accepted patch response lost')
    store, session, delivery, clock = deadline_worker(tmp_path, session=LostPatch([]))
    edit = OperationIntent('one', 'channel_message_edit', 'channel:123',
                           {'channel_id': '123', 'message_id': '456'}, {'content': 'edit'},
                           attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(edit)
    assert delivery.run_once(NOW).status == 'retrying'
    clock.now += timedelta(seconds=3)
    assert delivery.run_once(clock.now).status == 'ambiguous'
    assert store.get_by_key('one').receipt is None
    assert [item[0] for item in session.calls] == ['PATCH']


@pytest.mark.parametrize('corruption', ['missing', 'changed'])
def test_corrupt_staged_bytes_block_before_any_send(tmp_path, corruption):
    store, session, delivery, clock = deadline_worker(tmp_path)
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=10),
                     attachments=(Attachment('chart.png', 'image/png', b'frozen'),))
    store.accept(intent)
    path = store.media_root / store.stored_attachments('one')[0]['relative_path']
    if corruption == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'corrupt')
    assert delivery.run_once(NOW).status == 'blocked'
    assert store.get_by_key('one').error_category == 'local_state_invalid'
    assert session.calls == []


def test_clock_crossing_during_gateway_keep_attachment_read_prevents_patch(tmp_path):
    clock = Clock()
    class SlowKeepRead(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == 'GET':
                clock.now += timedelta(seconds=3)
                return Response(body={'id': '456', 'attachments': []})
            return Response(body={'id': '456'})
    store, session, delivery, clock = deadline_worker(tmp_path, session=SlowKeepRead([]), clock=clock)
    edit = OperationIntent('one', 'thread_message_edit', 'thread:123',
                           {'thread_id': '123', 'message_id': '456'},
                           {'content': 'edit', 'attachments_mode': 'keep'},
                           attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(edit)
    assert delivery.run_once(NOW).status == 'rejected'
    assert store.get_by_key('one').error_category == 'attempt_deadline_expired'
    assert [item[0] for item in session.calls] == ['GET']


def test_final_transport_gate_runs_after_attachment_bytes_are_prepared(tmp_path, monkeypatch):
    from pathlib import Path
    clock = Clock()
    store, session, delivery, clock = deadline_worker(
        tmp_path, [Response(body=[]), Response(body={'id': '456'})], clock=clock)
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=1),
                     attachments=(Attachment('chart.png', 'image/png', b'frozen'),))
    store.accept(intent)
    staged = store.media_root / store.stored_attachments('one')[0]['relative_path']
    original_read = Path.read_bytes
    reads = 0
    def slow_second_read(path):
        nonlocal reads
        data = original_read(path)
        if path == staged:
            reads += 1
            if reads == 2:  # Gateway loads immutable bytes after store validation.
                clock.now += timedelta(seconds=3)
        return data
    monkeypatch.setattr(Path, 'read_bytes', slow_second_read)
    assert delivery.run_once(NOW).status == 'rejected'
    assert reads == 2
    assert store.get_by_key('one').error_category == 'attempt_deadline_expired'
    assert [item[0] for item in session.calls] == ['GET']


def test_crash_before_receipt_persistence_reconciles_after_expiry_without_resend(tmp_path, monkeypatch):
    store, session, delivery, clock = deadline_worker(tmp_path, [
        Response(body=[]), Response(body={'id': '456'}), Response(body=[
            {'id': '456', 'content': 'exact content', 'nonce': DiscordGateway.nonce('one')}])])
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(intent)
    def crash_on_receipt(key, status, **kwargs):
        assert status == 'delivered'
        raise KeyboardInterrupt('simulated process death before receipt persistence')
    monkeypatch.setattr(store, 'finish', crash_on_receipt)
    with pytest.raises(KeyboardInterrupt):
        delivery.run_once(NOW)
    assert store.get_by_key('one').status == 'delivering'
    reopened = DeliveryStore(tmp_path / 'state.sqlite3', tmp_path / 'media')
    clock.now += timedelta(seconds=3)
    restarted = DeliveryWorker(reopened, delivery.gateway, alert=lambda *_: None, clock=clock)
    assert restarted.run_once(clock.now).status == 'delivered'
    assert reopened.get_by_key('one').receipt == {'message_id': '456'}
    assert [item[0] for item in session.calls] == ['GET', 'POST', 'GET']


def test_local_receipt_persistence_failure_preserves_uncertainty_on_admin_retry(tmp_path, monkeypatch):
    store, session, delivery, clock = deadline_worker(tmp_path, [
        Response(body=[]), Response(body={'id': '456'}), Response(body=[
            {'id': '456', 'content': 'exact content', 'nonce': DiscordGateway.nonce('one')}])])
    intent = replace(operation(), attempt_deadline=NOW + timedelta(seconds=1))
    store.accept(intent)
    original_finish = store.finish
    def fail_receipt_once(key, status, **kwargs):
        if status == 'delivered':
            monkeypatch.setattr(store, 'finish', original_finish)
            raise OSError('simulated local receipt write failure')
        return original_finish(key, status, **kwargs)
    monkeypatch.setattr(store, 'finish', fail_receipt_once)
    assert delivery.run_once(NOW).status == 'blocked'
    assert store.retry_blocked('one', intent.digest).status == 'pending_reconciliation'
    clock.now += timedelta(seconds=3)
    assert delivery.run_once(clock.now).status == 'delivered'
    assert store.get_by_key('one').receipt == {'message_id': '456'}
    assert [item[0] for item in session.calls] == ['GET', 'POST', 'GET']
