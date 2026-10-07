import pytest
import json
import os

from discord_delivery.models import Attachment, OperationIntent, ValidationError, validate_query
from discord_delivery.store import DeliveryStore, OperationKeyConflict, OperationStateConflict


def make_operation(key, content="Example"):
    return OperationIntent(
        key=key,
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=(),
        reconcile_before_first_create=False,
    )


def test_accept_persists_and_deduplicates_identical_operation(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    intent = make_operation("news:event-1:text")

    first = store.accept(intent)
    reopened = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    second = reopened.accept(intent)

    assert second.id == first.id
    assert reopened.get_by_key(intent.key).status == "pending"


def test_accept_rejects_changed_payload_for_existing_operation_key(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    original = make_operation(key="swing:event-7:text", content="Original")
    changed = make_operation(key="swing:event-7:text", content="Corrected")
    store.accept(original)

    with pytest.raises(OperationKeyConflict):
        store.accept(changed)


def test_attachments_are_private_and_durable(tmp_path):
    store = DeliveryStore(tmp_path / "state" / "delivery.sqlite3", tmp_path / "media")
    intent = OperationIntent("news:image", "channel_message_create", "channel:123",
                             {"channel_id": "123"}, {"content": "Image", "allowed_mentions": {"parse": []}},
                             (Attachment("chart.png", "image/png", b"image-data"),))
    stored = store.accept(intent)
    row = store.db.execute("SELECT attachments_json FROM discord_operations WHERE id=?", (stored.id,)).fetchone()
    metadata = json.loads(row[0])[0]
    media = tmp_path / "media" / metadata["relative_path"]
    assert media.read_bytes() == b"image-data"
    assert metadata["sha256"] == __import__("hashlib").sha256(b"image-data").hexdigest()
    assert os.stat(media).st_mode & 0o777 == 0o600
    assert os.stat(tmp_path / "media").st_mode & 0o777 == 0o700
    assert os.stat(tmp_path / "state" / "delivery.sqlite3").st_mode & 0o777 == 0o600


def test_adopt_pending_requires_reconciliation_and_retry_requires_exact_blocked_digest(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    with pytest.raises(ValueError):
        store.adopt_pending(make_operation("legacy:one"))
    intent = OperationIntent("legacy:one", "channel_message_create", "channel:123",
                             {"channel_id": "123"}, {"content": "Old"}, (), True)
    record = store.adopt_pending(intent)
    assert record.status == "pending_reconciliation"
    with pytest.raises(OperationStateConflict):
        store.retry_blocked(intent.key, intent.digest)
    store.db.execute("UPDATE discord_operations SET status='blocked' WHERE operation_key=?", (intent.key,))
    with pytest.raises(OperationStateConflict):
        store.retry_blocked(intent.key, "0" * 64)
    retried = store.retry_blocked(intent.key, intent.digest)
    assert retried.status == "retrying"
    assert retried.target == {"channel_id": "123"}


def test_completed_import_is_idempotent_and_retains_receipt(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    intent = make_operation("legacy:completed")
    first = store.adopt_completed(intent, {"message_id": "456"})
    second = store.adopt_completed(intent, {"message_id": "456"})
    assert first.id == second.id
    assert second.status == "delivered"
    assert second.receipt == {"message_id": "456"}


@pytest.mark.parametrize("kind,target,payload", [
    ("channel_message_create", {"channel_id": "123"}, {"content": "hello"}),
    ("channel_message_edit", {"channel_id": "123", "message_id": "456"}, {"content": "edit"}),
    ("channel_message_delete", {"channel_id": "123", "message_id": "456"}, {}),
    ("forum_thread_create", {"forum_id": "123"}, {"name": "topic", "content": "starter"}),
    ("forum_thread_update", {"thread_id": "123"}, {"name": "renamed"}),
    ("forum_thread_archive", {"thread_id": "123"}, {}),
    ("thread_message_create", {"thread_id": "123"}, {"content": "hello"}),
    ("thread_message_edit", {"thread_id": "123", "message_id": "456"},
     {"content": "edit", "attachments_mode": "keep"}),
    ("thread_message_delete", {"thread_id": "123", "message_id": "456"}, {}),
    ("forum_channel_create", {"guild_id": "123"}, {"name": "board"}),
    ("forum_channel_edit", {"channel_id": "123"}, {"name": "board"}),
    ("forum_channel_delete", {"channel_id": "123"}, {}),
])
def test_required_mutation_kinds_have_valid_typed_shapes(kind, target, payload):
    intent = OperationIntent("typed:one", kind, "channel:123", target, payload)
    assert intent.kind == kind


@pytest.mark.parametrize("kind,target,payload", [
    ("channel_message_edit", {"channel_id": "123"}, {"content": "edit"}),
    ("channel_message_delete", {"channel_id": "123", "message_id": "456"}, {"content": "oops"}),
    ("forum_thread_create", {"forum_id": "123"}, {"content": "starter"}),
    ("forum_thread_update", {"thread_id": "123"}, {}),
    ("forum_thread_archive", {"thread_id": "123", "message_id": "456"}, {}),
    ("thread_message_create", {"channel_id": "123"}, {"content": "wrong target"}),
    ("thread_message_edit", {"thread_id": "123", "message_id": "456"}, {}),
    ("forum_channel_create", {"channel_id": "123"}, {"name": "wrong target"}),
    ("forum_channel_delete", {"channel_id": "123"}, {"name": "oops"}),
    ("reaction_add", {"channel_id": "123", "message_id": "456"}, {"emoji": "x"}),
])
def test_invalid_or_unplanned_mutation_shapes_are_rejected(kind, target, payload):
    with pytest.raises(ValidationError):
        OperationIntent("typed:bad", kind, "channel:123", target, payload)


@pytest.mark.parametrize("query", [
    {"kind": "forum_thread_read", "thread_id": "123"},
    {"kind": "thread_message_read", "thread_id": "123", "message_id": "456"},
    {"kind": "forum_channel_read", "channel_id": "123"},
    {"kind": "channel_messages", "channel_id": "123", "limit": 10},
    {"kind": "thread_messages", "thread_id": "123", "before": "456", "limit": 10},
])
def test_required_reads_are_typed_and_bounded(query):
    assert validate_query(query) == query


@pytest.mark.parametrize("query", [
    {"kind": "forum_thread_read", "channel_id": "123"},
    {"kind": "thread_message_read", "thread_id": "123"},
    {"kind": "forum_channel_read", "channel_id": "123", "before": "456"},
    {"kind": "channel_messages", "channel_id": "123", "limit": 101},
    {"kind": "channel_messages", "thread_id": "123"},
    {"kind": "reaction_add", "channel_id": "123"},
])
def test_invalid_read_shapes_are_rejected(query):
    with pytest.raises(ValidationError):
        validate_query(query)


def test_recover_interrupted_claims_reconciles_creates_and_retries_mutations(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    store = DeliveryStore(path, tmp_path / "media")
    create = make_operation("crashed:create")
    edit = OperationIntent("crashed:edit", "channel_message_edit", "channel:456",
                           {"channel_id": "456", "message_id": "789"}, {"content": "Edited"})
    store.accept(create)
    store.accept(edit)
    assert store.claim_next().key in {create.key, edit.key}
    assert store.claim_next().key in {create.key, edit.key}
    store.save_create_snapshot(create.key, {"request": {"method": "POST"}})
    reopened = DeliveryStore(path, tmp_path / "media")
    recovered = reopened.recover_interrupted()
    assert recovered == {"pending_reconciliation": 1, "pending": 1}
    assert reopened.get_by_key(create.key).status == "pending_reconciliation"
    assert reopened.get_by_key(edit.key).status == "pending"
    assert reopened.claim_next().key == edit.key
    assert reopened.recover_interrupted() == {"pending_reconciliation": 0, "pending": 1}


@pytest.mark.parametrize('ambiguous', [False, True])
def test_native_create_interrupted_before_request_snapshot_does_not_block_chain(tmp_path, ambiguous):
    store = DeliveryStore(tmp_path / 'delivery.sqlite3', tmp_path / 'media')
    first = make_operation('first')
    second = make_operation('second')
    store.accept(first)
    store.accept(second)
    assert store.claim_next().key == first.key
    if ambiguous:
        store.save_create_snapshot(first.key, {
            'reconcile_before_first_create': False, 'legacy_nonce': None,
            'reconciliation_required': True,
        })
        store.finish(first.key, 'ambiguous', error_category='reconciliation_inconclusive')
    assert store.claim_next() is None
    assert store.recover_interrupted() == {'pending_reconciliation': 0, 'pending': 1}
    assert 'reconciliation_required' not in store.create_snapshot(first.key)
    assert store.claim_next().key == first.key
    store.finish(first.key, 'delivered', receipt={'message_id': '456'})
    assert store.claim_next().key == second.key


def test_adopted_create_without_request_snapshot_remains_uncertain(tmp_path):
    store = DeliveryStore(tmp_path / 'delivery.sqlite3', tmp_path / 'media')
    intent = OperationIntent('adopted', 'channel_message_create', 'channel:123',
                             {'channel_id': '123'}, {'content': 'Old'}, (), True)
    store.adopt_pending(intent)
    assert store.claim_reconciliation().key == intent.key
    assert store.recover_interrupted() == {'pending_reconciliation': 1, 'pending': 0}
    assert store.get_by_key(intent.key).status == 'pending_reconciliation'


@pytest.mark.parametrize("kind,target,payload,valid_receipt,invalid_receipt", [
    ("channel_message_create", {"channel_id": "123"}, {"content": "text"},
     {"message_id": "456"}, {"channel_id": "123"}),
    ("forum_thread_create", {"forum_id": "123"}, {"name": "topic", "content": "starter"},
     {"thread_id": "456", "message_id": "789"}, {"message_id": "789"}),
    ("forum_channel_create", {"guild_id": "123"}, {"name": "board"},
     {"channel_id": "456"}, {"thread_id": "456"}),
])
def test_completed_import_requires_kind_specific_receipt(tmp_path, kind, target, payload,
                                                         valid_receipt, invalid_receipt):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    intent = OperationIntent("receipt:import", kind, "channel:123", target, payload)
    with pytest.raises(ValidationError):
        store.adopt_completed(intent, invalid_receipt)
    assert store.get_by_key(intent.key) is None
    assert store.adopt_completed(intent, valid_receipt).receipt == valid_receipt


@pytest.mark.parametrize("kind,target,payload,valid_receipt,invalid_receipt", [
    ("channel_message_create", {"channel_id": "123"}, {"content": "text"},
     {"message_id": "456"}, {"channel_id": "123"}),
    ("forum_thread_create", {"forum_id": "123"}, {"name": "topic", "content": "starter"},
     {"thread_id": "456"}, {"channel_id": "123"}),
    ("forum_channel_create", {"guild_id": "123"}, {"name": "board"},
     {"channel_id": "456"}, {"message_id": "456"}),
])
def test_finish_delivered_requires_kind_specific_receipt(tmp_path, kind, target, payload,
                                                          valid_receipt, invalid_receipt):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    intent = OperationIntent("receipt:finish", kind, "channel:123", target, payload)
    store.accept(intent)
    assert store.claim_next().key == intent.key
    with pytest.raises(ValidationError):
        store.finish(intent.key, "delivered", receipt=invalid_receipt)
    assert store.get_by_key(intent.key).status == "delivering"
    assert store.finish(intent.key, "delivered", receipt=valid_receipt).receipt == valid_receipt
