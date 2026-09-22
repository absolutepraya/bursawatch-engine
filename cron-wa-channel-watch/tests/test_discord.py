import discord


class Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_media_filename_adds_real_jpeg_extension():
    assert discord.media_filename("image", "image/jpeg", 0, prefix="bri-chart") == "bri-chart-0.jpg"
    assert discord.media_filename("video", "video/mp4", 1) == "whatsapp-channel-1.mp4"


def test_post_media_uses_presentation_filename_for_extensionless_archive(tmp_path, monkeypatch):
    media = tmp_path / "archive-hash"  # keep the archive fixture extensionless
    media.write_bytes(b"chart")
    captured = {}
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-for-test")

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return Response(200, {"id": "123"})

    monkeypatch.setattr(discord.requests, "request", request)
    assert discord.post_media(
        media,
        "42",
        False,
        "nonce",
        filename="bri-chart-0.jpg",
        mime="image/jpeg",
    ) == "123"
    assert captured["files"]["files[0]"][0] == "bri-chart-0.jpg"
    assert captured["files"]["files[0]"][2] == "image/jpeg"


def test_edit_board_link_patches_existing_message_without_reposting(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-for-test")
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return Response(200, {"id": "123", "content": "**Board:** <#1548273399069933720>"})
        return Response(200, {"id": "123", "content": "updated"})

    monkeypatch.setattr(discord.requests, "request", request)
    assert discord.edit_board_link(
        "42",
        ["123"],
        "https://discord.com/channels/940285152335110204/999",
        False,
        "nonce",
    ) is True
    assert [call[0] for call in calls] == ["GET", "PATCH"]
    assert calls[-1][2]["json"]["content"] == "**Board:** https://discord.com/channels/940285152335110204/999"
