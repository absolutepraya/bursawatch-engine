import pytest

import discord
from bursawatch_discord_delivery import Attachment, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError


class Owner:
    def __init__(self, query_result=None):
        self.query_result = query_result
        self.queries = []
        self.submitted = []

    def query(self, query):
        self.queries.append(query)
        return self.query_result

    def status(self, key):
        return None

    def submit(self, operation):
        self.submitted.append(operation)
        return OperationReceipt(
            id="operation-1",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={
                "channel_id": operation.target["channel_id"],
                "message_id": operation.target.get("message_id", "123456789012345678"),
            },
        )

    def wait(self, key, timeout):
        raise AssertionError("delivered operation must not need a wait")


class DeliveredOwner(Owner):
    def __init__(self, receipt):
        super().__init__()
        self.receipt = receipt

    def status(self, key):
        return self.receipt

    def submit(self, operation):
        raise AssertionError("existing delivered operation must not be resubmitted")


@pytest.mark.parametrize("media", [False, True])
def test_existing_message_only_receipt_finishes_without_resubmitting(tmp_path, media):
    nonce = discord.nonce("event", "media:0" if media else "text:0")
    attachment = Attachment("chart.jpg", "image/jpeg", b"chart") if media else None
    operation = discord._message_operation("" if media else "news", "42", nonce, attachment=attachment)
    owner = DeliveredOwner(OperationReceipt(
        id="operation-1", key=operation.key, digest=operation.digest,
        status="delivered", receipt={"message_id": "123456789012345678"},
    ))

    if media:
        path = tmp_path / "chart"
        path.write_bytes(b"chart")
        message_id = discord.post_media(path, "42", False, nonce, filename="chart.jpg", mime="image/jpeg", client=owner)
    else:
        message_id = discord.post_text("news", "42", False, nonce, client=owner)

    assert message_id == "123456789012345678"


@pytest.mark.parametrize("field,replacement", [
    ("channel_id", "99"), ("channel_id", None),
    ("message_id", "invalid"), ("key", "wrong-operation"), ("digest", "f" * 64),
])
def test_conflicting_or_invalid_delivered_receipt_is_rejected(field, replacement):
    nonce = discord.nonce("event", "text:0")
    operation = discord._message_operation("news", "42", nonce)
    document = {
        "id": "operation-1", "key": operation.key, "digest": operation.digest,
        "status": "delivered", "receipt": {"message_id": "123456789012345678"},
    }
    if field in {"channel_id", "message_id"}:
        document["receipt"][field] = replacement
    else:
        document[field] = replacement

    with pytest.raises(DeliveryClientError):
        discord.post_text("news", "42", False, nonce, client=DeliveredOwner(OperationReceipt(**document)))


def test_media_filename_adds_real_jpeg_extension():
    assert discord.media_filename("image", "image/jpeg", 0, prefix="bri-chart") == "bri-chart-0.jpg"
    assert discord.media_filename("video", "video/mp4", 1) == "whatsapp-channel-1.mp4"


def test_post_media_preserves_archive_bytes_and_presentation_filename(tmp_path, monkeypatch):
    media = tmp_path / "archive-hash"  # archive files remain extensionless
    media.write_bytes(b"chart")
    owner = Owner()
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "ignored-legacy-token")

    assert discord.post_media(
        media,
        "42",
        False,
        discord.nonce("event", "media:0"),
        filename="bri-chart-0.jpg",
        mime="image/jpeg",
        client=owner,
    ) == "123456789012345678"

    operation = owner.submitted[0]
    assert operation.kind == "channel_message_create"
    assert operation.attachments[0].filename == "bri-chart-0.jpg"
    assert operation.attachments[0].mime_type == "image/jpeg"
    assert operation.attachments[0].data == b"chart"


def test_edit_board_link_uses_bounded_read_then_owner_edit_without_reposting(monkeypatch):
    owner = Owner([{
        "id": "123456789012345678",
        "content": "**Board:** <#1548273399069933720>",
    }])
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "ignored-legacy-token")

    assert discord.edit_board_link(
        "42",
        ["123456789012345678"],
        "https://discord.com/channels/940285152335110204/999",
        False,
        discord.nonce("event", "board-link"),
        client=owner,
    ) is True

    assert len(owner.queries) == 1
    assert owner.queries[0].kind == "channel_messages"
    assert owner.queries[0].channel_id == "42"
    assert owner.queries[0].limit == 1
    assert len(owner.submitted) == 1
    assert owner.submitted[0].kind == "channel_message_edit"
    assert owner.submitted[0].target == {
        "channel_id": "42", "message_id": "123456789012345678"
    }
    assert owner.submitted[0].payload["content"] == (
        "**Board:** https://discord.com/channels/940285152335110204/999"
    )
