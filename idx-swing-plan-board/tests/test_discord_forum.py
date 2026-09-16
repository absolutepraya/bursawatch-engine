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
        if method == "GET":
            return Response(
                200,
                {
                    "available_tags": [
                        {"id": "primary-tag-id", "name": "Primary plan"},
                        {"id": "tp1-tag-id", "name": "TP1 reached"},
                    ]
                },
            )
        return Response(201, {"id": "thread-1", "message": {"id": "starter-1"}})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    created = client.create_forum_thread(
        "SCMA: Buy", "card", ("Primary plan", "TP1 reached"), None, "episode:1:create"
    )

    assert created.thread_id == "thread-1"
    assert created.starter_message_id == "starter-1"
    assert calls[0] == {
        "method": "GET",
        "url": f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}",
        "headers": {"Authorization": "Bot token"},
        "timeout": 30,
    }
    assert calls[1] == {
        "method": "POST",
        "url": f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}/threads",
        "headers": {"Authorization": "Bot token", "Content-Type": "application/json"},
        "timeout": 30,
        "json": {
            "name": "SCMA: Buy",
            "applied_tags": ["primary-tag-id", "tp1-tag-id"],
            "message": {
                "content": "card",
                "nonce": hashlib.sha256(b"episode:1:create").hexdigest()[:24],
                "enforce_nonce": True,
                "allowed_mentions": {"parse": []},
            },
        },
    }


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


def test_edit_starter_explicitly_clears_attachments_without_fetching_old_chart(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return Response(200, {})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")
    client.execute("edit_starter", {
        "thread_id": "thread-1", "message_id": "starter-1", "content": "chartless replacement",
        "chart": None, "clear_attachments": True,
    })

    assert len(calls) == 1
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["json"]["attachments"] == []
    assert "files" not in calls[0]


def test_delete_message_uses_the_forum_message_delete_endpoint(monkeypatch) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return Response(204, {})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    DiscordForumClient(token="token").delete_message("thread-1", "history-7")

    assert calls == [{
        "method": "DELETE",
        "url": "https://discord.com/api/v10/channels/thread-1/messages/history-7",
        "headers": {"Authorization": "Bot token"},
        "timeout": 30,
    }]


def test_reply_patch_and_execute_use_complete_desired_state(monkeypatch) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if method == "GET" and url.endswith(f"/channels/{FORUM_CHANNEL_ID}"):
            return Response(
                200,
                {
                    "available_tags": [
                        {"id": "resolved-id", "name": "Resolved"},
                        {"id": "tp1-id", "name": "TP1 reached"},
                    ]
                },
            )
        if method == "POST":
            return Response(200, {"id": "reply-1"})
        return Response(200, {})

    monkeypatch.setattr(discord_forum.requests, "request", request)
    client = DiscordForumClient(token="token")

    assert client.post_reply("thread-1", "history", None, "history:1") == "reply-1"
    client.patch_thread("thread-1", "SCMA: Buy", ("Resolved", "TP1 reached"), True)
    result = client.execute(
        "post_history_reply",
        {"thread_id": "thread-1", "content": "history 2", "nonce": "history:2"},
    )

    assert result == {"message_id": "reply-1"}
    assert calls[1]["method"] == "GET"
    assert calls[1]["url"].endswith(f"/channels/{FORUM_CHANNEL_ID}")
    assert calls[2]["method"] == "PATCH"
    assert calls[2]["json"] == {
        "name": "SCMA: Buy",
        "applied_tags": ["resolved-id", "tp1-id"],
        "archived": True,
    }
    assert calls[3]["json"]["nonce"] == hashlib.sha256(b"history:2").hexdigest()[:24]


@pytest.mark.parametrize(
    "available_tags",
    [
        [{"id": "primary-id", "name": "Primary plan"}],
        [
            {"id": "primary-id", "name": "Primary plan"},
            {"id": "duplicate-id", "name": "Primary plan"},
        ],
    ],
    ids=["missing", "duplicate"],
)
def test_create_thread_fails_closed_when_a_required_tag_name_is_not_exactly_resolvable(
    available_tags: list[dict[str, str]], monkeypatch
) -> None:
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return Response(200, {"available_tags": available_tags})

    monkeypatch.setattr(discord_forum.requests, "request", request)

    with pytest.raises(discord_forum.DiscordForumError, match="tag"):
        DiscordForumClient(token="token").create_forum_thread(
            "SCMA: Buy", "card", ("Primary plan", "TP1 reached"), None, "create"
        )

    assert [call["method"] for call in calls] == ["GET"]


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

    created = client.create_forum_thread("SCMA: Buy", "card", ("Primary plan",), None, "create")
    assert created.thread_id == "dry-run-thread"
    assert client.post_reply("dry-run-thread", "history", None, "reply") == "dry-run-message"
    client.patch_thread("dry-run-thread", "SCMA: Buy", ("Primary plan",), False)
