from datetime import datetime, timedelta
from dataclasses import replace
import json
import sqlite3
from pathlib import Path
import sys

from conftest import example_buy_event
from discord_forum import DiscordForumClient, operation_key, operation_key_for
from engine import BoardEngine
from store import BoardStore

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.models import OperationIntent, OperationReceipt


class FakeDeliveryOwner:
    """In-memory Delivery Owner fake; it has no Discord REST path."""

    def __init__(self, store):
        self.store = store
        self.receipts = {}
        self.submit_calls = []
        self.status_calls = []
        self.query_calls = []
        self.accept_then_timeout = False
        self.fail_before_accept = False
        self.next_status = "delivered"
        self.sequence = 900

    def status(self, key):
        self.status_calls.append(key)
        return self.receipts.get(key)

    def submit(self, intent):
        assert isinstance(intent, OperationIntent)
        self.submit_calls.append(intent)
        pending = [
            item for item in self.store.operations_for_ticker("SCMA")
            if operation_key(item.dedupe_key) == intent.key
        ]
        assert len(pending) == 1, "Board must persist the operation before service submission"
        assert pending[0].status == "claimed"
        assert pending[0].payload.get("applied_tag_ids") == intent.payload.get("applied_tags")
        if self.fail_before_accept:
            self.fail_before_accept = False
            raise DeliveryClientError("network_error")
        receipt = self._receipt(intent, self.next_status)
        self.receipts[intent.key] = receipt
        if self.accept_then_timeout:
            self.accept_then_timeout = False
            raise DeliveryClientError("timeout")
        return receipt

    def wait(self, key, _timeout_seconds):
        return self.status(key)

    def query(self, query):
        self.query_calls.append(query)
        if query.kind == "forum_channel_read":
            return {
                "guild_id": "940285152335110204",
                "available_tags": [{"name": "Primary plan", "id": "100000000000000001"}],
            }
        raise AssertionError(f"unexpected Delivery Owner query: {query.kind}")

    def deliver(self, key, *, thread_id="900", message_id="901"):
        previous = self.receipts[key]
        self.receipts[key] = OperationReceipt(
            id=previous.id,
            key=previous.key,
            digest=previous.digest,
            status="delivered",
            receipt={"thread_id": thread_id, "message_id": message_id},
        )

    def _receipt(self, intent, status):
        self.sequence += 1
        if intent.kind == "forum_thread_create":
            result = {"thread_id": str(self.sequence), "message_id": str(self.sequence)}
        elif intent.kind == "thread_message_create":
            result = {"message_id": str(self.sequence)}
        else:
            result = {"thread_id": intent.target.get("thread_id", "900")}
        return OperationReceipt(
            id=f"delivery-{self.sequence}",
            key=intent.key,
            digest=intent.digest,
            status=status,
            receipt=result if status == "delivered" else None,
        )


def new_owner(path, delivery):
    return BoardEngine(
        BoardStore(path),
        DiscordForumClient(delivery_client=delivery, no_post=False),
    )


def test_acceptance_timeout_restart_applies_the_same_thread_and_starter_ids(tmp_path):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    delivery.accept_then_timeout = True
    owner = new_owner(store.path, delivery)
    owner.submit(example_buy_event(), now)

    assert owner.drain(now=now) == 0
    operation = store.operations_for_ticker("SCMA")[0]
    stable_key = operation.dedupe_key
    shared_key = operation_key(stable_key)
    assert operation.status == "pending"
    assert delivery.submit_calls[0].key == shared_key
    assert operation.payload["applied_tag_ids"] == ["100000000000000001"]
    assert store.active_episode("SCMA").thread_id is None

    restarted = new_owner(store.path, delivery)
    assert restarted.drain(now=now + timedelta(hours=1)) == 1
    episode = store.active_episode("SCMA")
    assert (episode.thread_id, episode.starter_message_id) == ("901", "901")
    assert [item.key for item in delivery.submit_calls] == [shared_key]
    assert delivery.status_calls[-1] == shared_key
    assert restarted.drain(now=now + timedelta(hours=2)) == 0
    assert (store.active_episode("SCMA").thread_id,
            store.active_episode("SCMA").starter_message_id) == ("901", "901")


def test_service_unavailable_retries_only_the_persisted_operation_key(tmp_path):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    delivery.fail_before_accept = True
    owner = new_owner(store.path, delivery)
    owner.submit(example_buy_event(), now)

    assert owner.drain(now=now) == 0
    operation = store.operations_for_ticker("SCMA")[0]
    shared_key = operation_key(operation.dedupe_key)
    assert operation.status == "pending"
    assert delivery.submit_calls[0].key == shared_key

    assert owner.drain(now=now + timedelta(hours=1)) == 1
    assert len(delivery.submit_calls) == 2
    assert {item.key for item in delivery.submit_calls} == {shared_key}
    assert store.active_episode("SCMA").thread_id == "901"


def test_pending_reconciliation_restart_applies_receipt_without_second_create(tmp_path):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    delivery.next_status = "pending_reconciliation"
    owner = new_owner(store.path, delivery)
    owner.submit(example_buy_event(), now)

    assert owner.drain(now=now) == 0
    stable_key = operation_key(store.operations_for_ticker("SCMA")[0].dedupe_key)
    delivery.deliver(stable_key, thread_id="990", message_id="991")

    restarted = new_owner(store.path, delivery)
    assert restarted.drain(now=now + timedelta(hours=1)) == 1
    assert (store.active_episode("SCMA").thread_id,
            store.active_episode("SCMA").starter_message_id) == ("990", "991")
    assert [item.key for item in delivery.submit_calls] == [stable_key]


def test_handoff_create_receipt_digest_applies_ids_once_after_board_restart(tmp_path):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    owner = new_owner(store.path, delivery)
    owner.submit(example_buy_event(), now)
    operation = store.operations_for_ticker("SCMA")[0]
    prepared = owner.client.prepare_payload(operation.operation, operation.payload)
    normal = owner.client._intent(operation.operation, prepared, operation.dedupe_key)
    imported = replace(normal, reconcile_before_first_create=True)
    delivery.receipts[normal.key] = OperationReceipt(
        id="adopted-forum-create", key=normal.key, digest=imported.digest,
        status="delivered",
        receipt={"thread_id": "990", "message_id": "991"},
    )

    assert owner.drain(now=now) == 1
    episode = store.active_episode("SCMA")
    assert (episode.thread_id, episode.starter_message_id) == ("990", "991")
    with sqlite3.connect(store.path) as connection:
        completion = connection.execute(
            "SELECT completion_json FROM outbox WHERE id = ?", (operation.id,)
        ).fetchone()[0]
    assert json.loads(completion) == {"starter_message_id": "991", "thread_id": "990"}

    restarted = new_owner(store.path, delivery)
    assert restarted.drain(now=now + timedelta(hours=1)) == 0
    assert (store.active_episode("SCMA").thread_id,
            store.active_episode("SCMA").starter_message_id) == ("990", "991")
    assert [item.key for item in delivery.submit_calls] == []


def test_handoff_heartbeat_receipt_digest_completes_once_after_restart(tmp_path):
    from delivery_handoff import stable_nonce

    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    owner = new_owner(store.path, delivery)
    key_source = "scheduled-heartbeat:handoff:run-1"
    channel_id = "1505162000420835388"
    stable_key = operation_key_for(key_source)
    normal = OperationIntent(
        key=stable_key,
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": "🫀 board", "allowed_mentions": {"parse": []}},
    )
    imported = replace(
        normal,
        reconcile_before_first_create=True,
        legacy_nonce=stable_nonce(key_source),
    )
    delivery.receipts[stable_key] = OperationReceipt(
        id="adopted-heartbeat", key=stable_key, digest=imported.digest,
        status="delivered",
        receipt={"channel_id": channel_id, "message_id": "1550000000000000003"},
    )
    heartbeat = store.enqueue_heartbeat(channel_id, "🫀 board", key_source, now)

    assert owner.drain(now=now) == 1
    assert store.heartbeat_receipt(heartbeat.id) == {"message_id": "1550000000000000003"}

    restarted = new_owner(store.path, delivery)
    assert restarted.drain(now=now + timedelta(hours=1)) == 0
    assert store.heartbeat_receipt(heartbeat.id) == {"message_id": "1550000000000000003"}
    assert delivery.submit_calls == []


def test_ambiguous_and_rejected_owner_outcomes_never_generate_a_new_create(tmp_path):
    for status in ("ambiguous", "rejected"):
        now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
        store = BoardStore(tmp_path / f"{status}.sqlite3")
        delivery = FakeDeliveryOwner(store)
        delivery.next_status = status
        owner = new_owner(store.path, delivery)
        owner.submit(example_buy_event(), now)

        assert owner.drain(now=now) == 0
        operation = store.operations_for_ticker("SCMA")[0]
        shared_key = operation_key(operation.dedupe_key)
        assert operation.status == "pending"
        assert store.active_episode("SCMA").thread_id is None

        restarted = new_owner(store.path, delivery)
        assert restarted.drain(now=now + timedelta(hours=1)) == 0
        assert [item.key for item in delivery.submit_calls] == [shared_key]
        assert operation_key(store.operations_for_ticker("SCMA")[0].dedupe_key) == shared_key


def test_legacy_create_snapshot_waits_for_handoff_instead_of_submitting(tmp_path):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    delivery = FakeDeliveryOwner(store)
    owner = new_owner(store.path, delivery)
    owner.submit(example_buy_event(), now)
    operation = store.operations_for_ticker("SCMA")[0]
    payload = dict(operation.payload)
    payload["create_snapshot"] = {"content": payload["content"], "after_id": "100"}
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE outbox SET payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), operation.id),
        )

    assert owner.drain(now=now) == 0
    assert delivery.submit_calls == []
    assert store.operations_for_ticker("SCMA")[0].status == "pending"
