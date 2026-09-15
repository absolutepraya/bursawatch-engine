import hashlib
import json
from pathlib import Path

import pytest

import discord_forum
from discord_forum import (
    DiscordForumClient,
    DiscordRateLimitError,
    FORUM_CHANNEL_ID,
)


class Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self) -> object:
        return self._payload


def test_create_thread_posts_starter_with_title_tags_and_stable_nonce(monkeypatch) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return Response(201, {"id": "thread-1", "message": {"id": "starter-1"}})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    created = client.create_forum_thread(
        "SCMA: Buy", "card", ("primary-tag", "tp1-tag"), None, "episode:1:create"
    )

    assert created.thread_id == "thread-1"
    assert created.starter_message_id == "starter-1"
    assert calls == [
        {
            "method": "POST",
            "url": f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}/threads",
            "headers": {"Authorization": "Bot token", "Content-Type": "application/json"},
            "timeout": 30,
            "json": {
                "name": "SCMA: Buy",
                "applied_tags": ["primary-tag", "tp1-tag"],
                "message": {
                    "content": "card",
                    "nonce": hashlib.sha256(b"episode:1:create").hexdigest()[:24],
                    "enforce_nonce": True,
                    "allowed_mentions": {"parse": []},
                },
            },
        }
    ]


def test_edit_starter_retains_existing_attachment_when_chart_is_unchanged(monkeypatch) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "GET":
            return Response(200, {"attachments": [{"id": "42", "filename": "chart.jpg", "description": "Source chart", "url": "private"}]})
        return Response(200, {"id": "starter-1"})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    client.edit_starter("thread-1", "starter-1", "revised card", None)

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/channels/thread-1/messages/starter-1")
    assert calls[1]["method"] == "PATCH"
    assert calls[1]["json"] == {
        "content": "revised card",
        "attachments": [{"id": "42", "filename": "chart.jpg", "description": "Source chart"}],
        "allowed_mentions": {"parse": []},
    }


def test_edit_starter_replaces_attachment_with_chart_file(tmp_path: Path, monkeypatch) -> None:
    chart = tmp_path / "source-chart.jpg"
    chart.write_bytes(b"chart")
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return Response(200, {"id": "starter-1"})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    client.edit_starter("thread-1", "starter-1", "revised card", chart)

    assert len(calls) == 1
    assert calls[0]["method"] == "PATCH"
    assert json.loads(calls[0]["data"]["payload_json"]) == {
        "content": "revised card",
        "attachments": [{"id": "0", "filename": "source-chart.jpg"}],
        "allowed_mentions": {"parse": []},
    }
    assert calls[0]["files"]["files[0]"][0] == "source-chart.jpg"


def test_reply_patch_and_execute_use_complete_desired_state(monkeypatch) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "POST":
            return Response(200, {"id": "reply-1"})
        return Response(200, {})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    assert client.post_reply("thread-1", "history", None, "history:1") == "reply-1"
    client.patch_thread("thread-1", "SCMA: Buy", ("resolved", "tp1"), True)
    result = client.execute(
        "post_history_reply",
        {"thread_id": "thread-1", "content": "history 2", "nonce": "history:2"},
    )

    assert result == {"message_id": "reply-1"}
    assert calls[1]["method"] == "PATCH"
    assert calls[1]["json"] == {
        "name": "SCMA: Buy",
        "applied_tags": ["resolved", "tp1"],
        "archived": True,
    }
    assert calls[2]["json"]["nonce"] == hashlib.sha256(b"history:2").hexdigest()[:24]


def test_rate_limit_exposes_the_provider_retry_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        discord_forum.requests,
        "request",
        lambda *_args, **_kwargs: Response(429, {"retry_after": 2.5}),
    )

    with pytest.raises(DiscordRateLimitError) as error:
        DiscordForumClient(token="token").post_reply("thread-1", "history", None, "history:1")

    assert error.value.retry_after == 2.5


def test_no_post_makes_no_http_request(monkeypatch) -> None:
    monkeypatch.setattr(
        discord_forum.requests,
        "request",
        lambda *_args, **_kwargs: pytest.fail("no-post must not contact Discord"),
    )
    client = DiscordForumClient(token="token", no_post=True)

    created = client.create_forum_thread("SCMA: Buy", "card", ("primary",), None, "create")
    assert created.thread_id == "dry-run-thread"
    assert client.post_reply("dry-run-thread", "history", None, "reply") == "dry-run-message"
    client.patch_thread("dry-run-thread", "SCMA: Buy", ("primary",), False)
