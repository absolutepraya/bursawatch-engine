import pytest
import requests

import discord
from bursawatch_discord_delivery.models import OperationReceipt


def test_post_media_marks_confirmed_missing_source_as_terminal(monkeypatch, tmp_path):
    class Missing:
        status_code = 404
        headers = {}
        content = b""

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(discord.requests, "get", lambda *args, **kwargs: Missing())

    with pytest.raises(discord.MediaUnavailable) as error:
        discord.post_media(
            "https://pbs.twimg.com/media/missing.jpg",
            "channel",
            False,
            "nonce",
            tmp_path,
        )

    assert error.value.status_code == 404


class _DeliveryOwner:
    def __init__(self):
        self.operations = {}
        self.submissions = []
        self.queries = []

    def status(self, operation_key):
        return self.operations.get(operation_key)

    def submit(self, operation):
        self.submissions.append(operation)
        receipt = OperationReceipt(
            id=f"operation-{len(self.submissions)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={"channel_id": operation.target["channel_id"], "message_id": "7001"},
        )
        self.operations[operation.key] = receipt
        return receipt

    def query(self, query):
        self.queries.append(query)
        return {"messages": [{"id": "7001", "content": "**Board:** <#1548273399069933720>"}]}


def test_source_media_download_stays_local_and_retry_uses_original_owner_message_id(monkeypatch, tmp_path):
    class Source:
        status_code = 200
        headers = {"Content-Type": "image/jpeg"}
        content = b"source-image-bytes"

        def raise_for_status(self):
            return None

    source_requests = []
    monkeypatch.setattr(discord.requests, "get", lambda url, **kwargs: source_requests.append(url) or Source())
    owner = _DeliveryOwner()
    leg_nonce = discord.nonce("writer:123", "media:0")

    first = discord.post_media(
        "https://pbs.twimg.com/media/source.jpg",
        "123456789012345678",
        False,
        leg_nonce,
        tmp_path,
        event_key="writer:123",
        operation_leg="media:0",
        client=owner,
    )
    retried = discord.post_media(
        "https://pbs.twimg.com/media/source.jpg",
        "123456789012345678",
        False,
        leg_nonce,
        tmp_path,
        event_key="writer:123",
        operation_leg="media:0",
        client=owner,
    )

    assert source_requests == ["https://pbs.twimg.com/media/source.jpg"] * 2
    assert first == retried == "7001"
    assert len(owner.submissions) == 1
    assert owner.submissions[0].kind == "channel_message_create"
    assert owner.submissions[0].attachments[0].data == b"source-image-bytes"


def test_board_link_edit_reads_and_edits_existing_channel_message_through_owner():
    owner = _DeliveryOwner()

    assert discord.edit_board_links(
        "123456789012345678",
        ["7001"],
        "https://discord.com/channels/940285152335110204/8001",
        False,
        event_key="writer:123",
        client=owner,
    ) is True

    assert [query.kind for query in owner.queries] == ["channel_messages"]
    assert len(owner.submissions) == 1
    operation = owner.submissions[0]
    assert operation.kind == "channel_message_edit"
    assert operation.target == {"channel_id": "123456789012345678", "message_id": "7001"}
    assert "8001" in operation.payload["content"]


def test_supersession_delete_uses_explicit_id_and_stable_owner_operation():
    owner = _DeliveryOwner()

    discord.delete_message(
        "123456789012345678",
        "7001",
        False,
        event_key="cleanup:writer:old:7001",
        client=owner,
    )
    discord.delete_message(
        "123456789012345678",
        "7001",
        False,
        event_key="cleanup:writer:old:7001",
        client=owner,
    )

    assert len(owner.submissions) == 1
    operation = owner.submissions[0]
    assert operation.kind == "channel_message_delete"
    assert operation.target == {"channel_id": "123456789012345678", "message_id": "7001"}
