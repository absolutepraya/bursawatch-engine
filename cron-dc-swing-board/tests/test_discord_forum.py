from datetime import datetime, timezone
from dataclasses import replace
import hashlib
from pathlib import Path
import sys

import pytest

from conftest import example_buy_event
from discord_forum import (
    DiscordForumClient,
    DiscordForumError,
    FORUM_CHANNEL_ID,
    forum_thread_url,
    operation_key,
    operation_key_for,
    stable_nonce,
)

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery.models import DiscordQuery, OperationIntent, OperationReceipt


class RecordingOwner:
    def __init__(self):
        self.statuses = {}
        self.submitted = []
        self.queries = []
        self.status_calls = []
        self.submit_status = "delivered"
        self.timeout_after_accept = False
        self.wait_responses = {}
        self.wait_calls = []
        self.submit_responses = {}

    def status(self, key):
        self.status_calls.append(key)
        return self.statuses.get(key)

    def submit(self, intent):
        assert isinstance(intent, OperationIntent)
        self.submitted.append(intent)
        if intent.key in self.submit_responses:
            return self.submit_responses[intent.key]
        receipt = self._receipt(intent, self.submit_status)
        self.statuses[intent.key] = receipt
        if self.timeout_after_accept:
            self.timeout_after_accept = False
            from bursawatch_discord_delivery.client import DeliveryClientError
            raise DeliveryClientError("timeout")
        return receipt

    def wait(self, key, _timeout):
        self.wait_calls.append(key)
        return self.wait_responses.get(key, self.statuses[key])

    def query(self, query):
        assert isinstance(query, DiscordQuery)
        self.queries.append(query)
        if query.kind == "forum_channel_read":
            return {"id": query.channel_id, "guild_id": "940285152335110204", "available_tags": [
                {"id": "100000000000000001", "name": "Primary plan"},
                {"id": "100000000000000002", "name": "Resolved"},
                {"id": "100000000000000003", "name": "TP1 reached"},
            ]}
        if query.kind == "forum_thread_read":
            return {"id": query.thread_id, "parent_id": FORUM_CHANNEL_ID, "name": "SCMA",
                    "thread_metadata": {"archived": False, "locked": False}}
        if query.kind == "thread_message_read":
            return {"id": query.message_id, "content": "old", "attachments": [
                {"id": "1550000000000000002", "filename": "chart.jpg", "description": "chart"}
            ]}
        raise AssertionError(query.kind)

    @staticmethod
    def _receipt(intent, status):
        if intent.kind == "forum_thread_create":
            result = {"thread_id": "1550000000000000001", "message_id": "1550000000000000001"}
        elif intent.kind in {"thread_message_create", "channel_message_create"}:
            result = {"message_id": "1550000000000000003"}
            if intent.kind == "channel_message_create":
                result["channel_id"] = intent.target["channel_id"]
        elif intent.kind in {"forum_thread_update", "forum_thread_archive"}:
            result = {"thread_id": intent.target["thread_id"]}
        elif intent.kind.endswith("_edit"):
            result = {"message_id": intent.target["message_id"]}
        elif intent.kind.endswith("_delete"):
            result = {"message_id": intent.target["message_id"]}
        else:
            result = {}
        return OperationReceipt(
            id=f"receipt-{len(intent.key)}",
            key=intent.key,
            digest=intent.digest,
            status=status,
            receipt=result if status == "delivered" else None,
        )


def test_create_and_update_use_shared_typed_forum_operations():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)

    created = client.execute("create_thread", {
        "name": "SCMA",
        "content": "Primary card",
        "tag_names": ["Primary plan"],
        "_delivery_key": "event:one:create_thread",
    })

    assert created == {
        "thread_id": "1550000000000000001",
        "starter_message_id": "1550000000000000001",
    }
    intent = owner.submitted[0]
    assert intent.kind == "forum_thread_create"
    assert intent.key == operation_key("event:one:create_thread")
    assert intent.target == {"forum_id": FORUM_CHANNEL_ID}
    assert intent.payload["applied_tags"] == ["100000000000000001"]
    assert owner.queries[0].kind == "forum_channel_read"

    for archived in (True, False):
        owner.submitted.clear()
        client.execute("patch_thread", {
            "name": "SCMA",
            "tag_names": ["Resolved", "TP1 reached"],
            "applied_tag_ids": ["100000000000000002", "100000000000000003"],
            "archived": archived,
            "thread_id": "1550000000000000001",
            "_delivery_key": f"tag-update:{archived}",
        })
        update = owner.submitted[0]
        assert update.kind == "forum_thread_update"
        assert update.payload["applied_tags"] == ["100000000000000002", "100000000000000003"]
        assert update.payload["archived"] is archived


def test_typed_forum_and_message_reads_preserve_existing_remote_ids():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)

    thread = client.get_thread("1550000000000000001")
    message = client.get_message("1550000000000000001", "1550000000000000002")

    assert thread["id"] == "1550000000000000001"
    assert message["id"] == "1550000000000000002"
    assert [query.kind for query in owner.queries] == ["forum_thread_read", "thread_message_read"]
    assert forum_thread_url(thread["id"]).endswith("/1550000000000000001")


@pytest.mark.parametrize("mode", ["keep", "clear", "replace"])
def test_starter_edit_maps_explicit_attachment_mode(mode, tmp_path):
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    chart = None
    payload = {
        "thread_id": "1550000000000000001",
        "message_id": "1550000000000000002",
        "content": "updated card",
        "clear_attachments": mode == "clear",
        "_delivery_key": f"edit:{mode}",
    }
    if mode == "replace":
        chart = tmp_path / "chart.jpg"
        chart.write_bytes(b"approved chart bytes")
        payload["chart"] = str(chart)

    client.execute("edit_starter", payload)

    intent = owner.submitted[0]
    assert intent.kind == "thread_message_edit"
    assert intent.payload["attachments_mode"] == mode
    assert (len(intent.attachments) == 1) is (mode == "replace")
    if mode == "replace":
        assert intent.attachments[0].filename == "chart.jpg"
        assert intent.attachments[0].data == b"approved chart bytes"


def test_accepted_timeout_recovers_receipt_without_a_second_submit():
    owner = RecordingOwner()
    owner.timeout_after_accept = True
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    payload = {
        "name": "SCMA", "content": "Primary card", "tag_names": [],
        "applied_tag_ids": [], "_delivery_key": "event:timeout:create_thread",
    }

    with pytest.raises(Exception, match="timed out|timeout|Delivery Owner"):
        client.execute("create_thread", payload)
    result = client.execute("create_thread", payload)

    assert result["thread_id"] == "1550000000000000001"
    assert len(owner.submitted) == 1
    assert owner.status_calls == [operation_key("event:timeout:create_thread")] * 2


def test_forum_create_accepts_imported_digest_only_from_existing_status():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    payload = {
        "name": "SCMA", "content": "Primary card", "tag_names": [],
        "applied_tag_ids": [], "_delivery_key": "event:handoff:create_thread",
    }
    normal = client._intent("create_thread", payload, payload["_delivery_key"])
    imported = replace(normal, reconcile_before_first_create=True)
    owner.statuses[normal.key] = OperationReceipt(
        id="adopted-forum-create", key=imported.key, digest=imported.digest,
        status="delivered",
        receipt={"thread_id": "1550000000000000001", "message_id": "1550000000000000002"},
    )

    result = client.execute("create_thread", payload)

    assert result == {
        "thread_id": "1550000000000000001", "starter_message_id": "1550000000000000002"
    }
    assert owner.submitted == []
    assert owner.status_calls == [normal.key]


def test_heartbeat_wait_validates_the_existing_imported_digest():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    key_source = "scheduled-heartbeat:handoff:run-1"
    stable_key = operation_key_for(key_source)
    normal = OperationIntent(
        key=stable_key,
        kind="channel_message_create",
        ordering_key="channel:1505162000420835388",
        target={"channel_id": "1505162000420835388"},
        payload={"content": "🫀 board", "allowed_mentions": {"parse": []}},
    )
    imported = replace(
        normal,
        reconcile_before_first_create=True,
        legacy_nonce=stable_nonce(key_source),
    )
    owner.statuses[stable_key] = OperationReceipt(
        id="adopted-heartbeat", key=stable_key, digest=imported.digest,
        status="pending_reconciliation", receipt=None,
    )
    owner.wait_responses[stable_key] = OperationReceipt(
        id="adopted-heartbeat", key=stable_key, digest=imported.digest,
        status="delivered",
        receipt={"channel_id": "1505162000420835388", "message_id": "1550000000000000003"},
    )

    result = client.post_heartbeat(
        "1505162000420835388", "🫀 board", operation_key=key_source
    )

    assert result == {"message_id": "1550000000000000003"}
    assert owner.submitted == []
    assert owner.wait_calls == [stable_key]


def test_imported_digest_is_rejected_when_status_is_absent_or_digest_is_arbitrary():
    key_source = "scheduled-heartbeat:submit-must-be-normal"
    stable_key = operation_key_for(key_source)
    for existing_status in (None, "arbitrary"):
        owner = RecordingOwner()
        client = DiscordForumClient(delivery_client=owner, no_post=False)
        normal = OperationIntent(
            key=stable_key,
            kind="channel_message_create",
            ordering_key="channel:1505162000420835388",
            target={"channel_id": "1505162000420835388"},
            payload={"content": "🫀 board", "allowed_mentions": {"parse": []}},
        )
        imported = replace(
            normal,
            reconcile_before_first_create=True,
            legacy_nonce=stable_nonce(key_source),
        )
        if existing_status == "arbitrary":
            owner.statuses[stable_key] = OperationReceipt(
                id="unrelated", key=stable_key, digest="0" * 64,
                status="delivered",
                receipt={"channel_id": "1505162000420835388", "message_id": "1550000000000000004"},
            )
        else:
            owner.submit_responses[stable_key] = OperationReceipt(
                id="new-submit-imported-digest", key=stable_key, digest=imported.digest,
                status="delivered",
                receipt={"channel_id": "1505162000420835388", "message_id": "1550000000000000004"},
            )

        with pytest.raises(DiscordForumError, match="receipt did not match"):
            client.post_heartbeat(
                "1505162000420835388", "🫀 board", operation_key=key_source
            )
        assert len(owner.submitted) == (1 if existing_status is None else 0)


def test_ambiguous_delivery_status_never_submits_another_create():
    owner = RecordingOwner()
    owner.submit_status = "ambiguous"
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    payload = {
        "name": "SCMA", "content": "Primary card", "tag_names": [],
        "applied_tag_ids": [], "_delivery_key": "event:ambiguous:create_thread",
    }

    with pytest.raises(DiscordForumError, match="ambiguous"):
        client.execute("create_thread", payload)
    with pytest.raises(DiscordForumError, match="ambiguous"):
        client.execute("create_thread", payload)

    assert len(owner.submitted) == 1
    assert owner.status_calls == [operation_key("event:ambiguous:create_thread")] * 2


def test_no_post_uses_process_local_fake_without_touching_injected_client():
    external = RecordingOwner()
    client = DiscordForumClient(delivery_client=external, no_post=True)

    result = client.execute("create_thread", {
        "name": "SCMA", "content": "Primary card", "tag_names": ["Primary plan"],
        "_delivery_key": "dry-run:create",
    })

    assert result["thread_id"].isdigit()
    assert result["starter_message_id"].isdigit()
    assert external.submitted == []
    assert external.queries == []
    assert external.status_calls == []


def test_heartbeat_maps_to_a_typed_channel_message_and_returns_receipt_id():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)

    result = client.post_heartbeat(
        "1505162000420835388", "🫀 board", operation_key="scheduled-heartbeat:run-1"
    )

    intent = owner.submitted[0]
    assert intent.kind == "channel_message_create"
    assert intent.target == {"channel_id": "1505162000420835388"}
    assert intent.payload["content"] == "🫀 board"
    assert result == {"message_id": "1550000000000000003"}


def test_old_persisted_create_snapshot_cannot_be_resubmitted_before_handoff():
    owner = RecordingOwner()
    client = DiscordForumClient(delivery_client=owner, no_post=False)
    payload = {
        "name": "SCMA", "content": "Primary card", "tag_names": [],
        "applied_tag_ids": [], "create_snapshot": {"content": "Primary card"},
        "_delivery_key": "legacy:create:one",
    }

    with pytest.raises(DiscordForumError, match="handoff"):
        client.execute("create_thread", payload)

    assert owner.submitted == []


def test_discord_thread_url_rejects_non_snowflake_ids():
    with pytest.raises(ValueError, match="thread_id"):
        forum_thread_url("not-a-snowflake")
