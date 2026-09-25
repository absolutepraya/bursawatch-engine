import discord
from bursawatch_discord_delivery import OperationReceipt


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
