import hashlib
import json

import pytest

from discord_delivery.discord_gateway import DiscordGateway, GatewayError, StoredAttachment
from discord_delivery.models import Attachment, OperationIntent, ValidationError


class Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self.body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def intent(kind, target, payload):
    return OperationIntent("delivery:event:1", kind, "dest:123", target, payload)


@pytest.mark.parametrize("kind,target,payload,method,path,body,response,receipt", [
    ("channel_message_create", {"channel_id": "123"}, {"content": "hi"}, "POST", "/channels/123/messages", {"content": "hi"}, {"id": "456"}, {"message_id": "456"}),
    ("channel_message_edit", {"channel_id": "123", "message_id": "456"}, {"content": "edit"}, "PATCH", "/channels/123/messages/456", {"content": "edit"}, {"id": "456"}, {"message_id": "456"}),
    ("channel_message_delete", {"channel_id": "123", "message_id": "456"}, {}, "DELETE", "/channels/123/messages/456", {}, {}, {"message_id": "456"}),
    ("thread_message_create", {"thread_id": "123"}, {"content": "hi"}, "POST", "/channels/123/messages", {"content": "hi"}, {"id": "456"}, {"message_id": "456"}),
    ("thread_message_delete", {"thread_id": "123", "message_id": "456"}, {}, "DELETE", "/channels/123/messages/456", {}, {}, {"message_id": "456"}),
    ("forum_thread_create", {"forum_id": "123"}, {"name": "Topic", "content": "starter"}, "POST", "/channels/123/threads", {"name": "Topic", "message": {"content": "starter", "allowed_mentions": {"parse": []}}}, {"id": "456", "message": {"id": "789"}}, {"thread_id": "456", "message_id": "789"}),
    ("forum_thread_create", {"forum_id": "123"}, {"name": "SCMA", "content": "starter", "applied_tags": ["11", "22"]}, "POST", "/channels/123/threads", {"name": "SCMA", "applied_tags": ["11", "22"], "message": {"content": "starter", "allowed_mentions": {"parse": []}}}, {"id": "456", "message": {"id": "789"}}, {"thread_id": "456", "message_id": "789"}),
    ("forum_thread_update", {"thread_id": "123"}, {"name": "Renamed"}, "PATCH", "/channels/123", {"name": "Renamed"}, {"id": "123"}, {"thread_id": "123"}),
    ("forum_thread_update", {"thread_id": "123"}, {"name": "SCMA", "applied_tags": ["11", "22"]}, "PATCH", "/channels/123", {"name": "SCMA", "applied_tags": ["11", "22"]}, {"id": "123"}, {"thread_id": "123"}),
    ("forum_thread_update", {"thread_id": "123"}, {"archived": True}, "PATCH", "/channels/123", {"archived": True}, {"id": "123"}, {"thread_id": "123"}),
    ("forum_thread_update", {"thread_id": "123"}, {"archived": False}, "PATCH", "/channels/123", {"archived": False}, {"id": "123"}, {"thread_id": "123"}),
    ("forum_thread_archive", {"thread_id": "123"}, {}, "PATCH", "/channels/123", {"archived": True}, {"id": "123"}, {"thread_id": "123"}),
    ("forum_channel_create", {"guild_id": "123"}, {"name": "Board"}, "POST", "/guilds/123/channels", {"name": "Board", "type": 15}, {"id": "456"}, {"channel_id": "456"}),
    ("forum_channel_edit", {"channel_id": "123"}, {"name": "Board"}, "PATCH", "/channels/123", {"name": "Board"}, {"id": "123"}, {"channel_id": "123"}),
    ("forum_channel_delete", {"channel_id": "123"}, {}, "DELETE", "/channels/123", {}, {}, {"channel_id": "123"}),
])
def test_typed_mutations(kind, target, payload, method, path, body, response, receipt):
    session = Session([Response(body=response)])
    gateway = DiscordGateway("bot-secret", session=session)
    actual = gateway.execute(intent(kind, target, payload), ())
    assert actual == receipt
    called_method, url, kwargs = session.calls[0]
    assert (called_method, url) == (method, "https://discord.com/api/v10" + path)
    assert kwargs["headers"]["Authorization"] == "Bot bot-secret"
    assert kwargs["timeout"] == (3.05, 15)
    sent = {} if method == "DELETE" else (kwargs.get("json") or json.loads(kwargs["data"]["payload_json"]))
    if kind in {"channel_message_create", "thread_message_create"}:
        assert sent["nonce"] == gateway.nonce("delivery:event:1")
        assert sent["enforce_nonce"] is True
    else:
        assert "nonce" not in sent
    if kind in {"channel_message_create", "thread_message_create", "channel_message_edit", "thread_message_edit"}:
        assert sent["allowed_mentions"] == {"parse": []}
    for key, value in body.items():
        assert sent[key] == value


def test_upload_uses_numbered_file_part_and_metadata(tmp_path):
    media = tmp_path / "chart.png"
    media.write_bytes(b"chart")
    attachment = StoredAttachment("chart.png", "image/png", media, hashlib.sha256(b"chart").hexdigest())
    session = Session([Response(body={"id": "456"})])
    gateway = DiscordGateway("secret", session=session)
    assert gateway.execute(intent("channel_message_create", {"channel_id": "123"}, {"content": "chart"}), [attachment]) == {"message_id": "456"}
    kwargs = session.calls[0][2]
    assert list(kwargs["files"]) == ["files[0]"]
    assert kwargs["files"]["files[0]"][0] == "chart.png"
    assert kwargs["files"]["files[0]"][2] == "image/png"
    assert json.loads(kwargs["data"]["payload_json"])["attachments"] == [{"id": 0, "filename": "chart.png"}]


def _thread_edit(mode, attachments=()):
    return OperationIntent(
        "board:episode-1:starter-edit", "thread_message_edit", "thread:123",
        {"thread_id": "123", "message_id": "456"},
        {"content": "updated card", "attachments_mode": mode},
        attachments=tuple(attachments),
    )


def test_thread_message_edit_keep_reads_and_preserves_every_attachment():
    session = Session([
        Response(body={"attachments": [
            {"id": "700", "filename": "chart.jpg"},
            {"id": "701", "filename": "other.png"},
        ]}),
        Response(body={"id": "456"}),
    ])

    result = DiscordGateway("secret", session=session).execute(_thread_edit("keep"), ())

    assert result == {"message_id": "456"}
    assert [(method, url) for method, url, _ in session.calls] == [
        ("GET", "https://discord.com/api/v10/channels/123/messages/456"),
        ("PATCH", "https://discord.com/api/v10/channels/123/messages/456"),
    ]
    assert session.calls[1][2]["json"]["attachments"] == [
        {"id": "700", "filename": "chart.jpg"},
        {"id": "701", "filename": "other.png"},
    ]
    assert "attachments_mode" not in session.calls[1][2]["json"]


def test_thread_message_edit_clear_sends_empty_attachment_set():
    session = Session([Response(body={"id": "456"})])

    result = DiscordGateway("secret", session=session).execute(_thread_edit("clear"), ())

    assert result == {"message_id": "456"}
    assert len(session.calls) == 1
    assert session.calls[0][2]["json"]["attachments"] == []


def test_thread_message_edit_replace_uploads_only_the_replacement_set(tmp_path):
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(b"chart")
    attachment = StoredAttachment(
        "replacement.png", "image/png", replacement, hashlib.sha256(b"chart").hexdigest()
    )
    session = Session([Response(body={"id": "456"})])

    intent_value = _thread_edit("replace", (Attachment("replacement.png", "image/png", b"chart"),))
    result = DiscordGateway("secret", session=session).execute(intent_value, (attachment,))

    assert result == {"message_id": "456"}
    kwargs = session.calls[0][2]
    assert json.loads(kwargs["data"]["payload_json"])["attachments"] == [
        {"id": 0, "filename": "replacement.png"},
    ]
    assert "attachments_mode" not in json.loads(kwargs["data"]["payload_json"])
    assert kwargs["files"]["files[0]"][0] == "replacement.png"


@pytest.mark.parametrize("query,path,params", [
    ({"kind": "forum_thread_read", "thread_id": "123"}, "/channels/123", None),
    ({"kind": "thread_message_read", "thread_id": "123", "message_id": "456"}, "/channels/123/messages/456", None),
    ({"kind": "forum_channel_read", "channel_id": "123"}, "/channels/123", None),
    ({"kind": "channel_messages", "channel_id": "123", "limit": 10}, "/channels/123/messages", {"limit": 10}),
    ({"kind": "thread_messages", "thread_id": "123", "before": "456", "limit": 10}, "/channels/123/messages", {"before": "456", "limit": 10}),
])
def test_queries_are_get_only(query, path, params):
    session = Session([Response(body={"id": "123"})])
    assert DiscordGateway("secret", session=session).query(query) == {"id": "123"}
    method, url, kwargs = session.calls[0]
    assert (method, url, kwargs.get("params")) == ("GET", "https://discord.com/api/v10" + path, params)


def test_forum_threads_read_covers_active_and_archived():
    session = Session([Response(body={"guild_id": "77"}),
                       Response(body={"threads": [{"id": "1", "parent_id": "123"}]}),
                       Response(body={"threads": [{"id": "2", "parent_id": "123"}], "has_more": False})])
    result = DiscordGateway("secret", session=session).query({"kind": "forum_threads", "channel_id": "123", "limit": 10})
    assert result == {"threads": [{"id": "1", "parent_id": "123"}, {"id": "2", "parent_id": "123"}], "has_more": False}
    assert [(method, url) for method, url, _ in session.calls] == [
        ("GET", "https://discord.com/api/v10/channels/123"),
        ("GET", "https://discord.com/api/v10/guilds/77/threads/active"),
        ("GET", "https://discord.com/api/v10/channels/123/threads/archived/public")]


def test_invalid_paths_and_mutating_queries_rejected():
    gateway = DiscordGateway("secret", session=Session([]))
    with pytest.raises(ValidationError):
        gateway.query({"kind": "DELETE", "path": "/channels/123"})
    with pytest.raises(ValidationError):
        gateway.query({"kind": "channel_messages", "channel_id": "123/456"})


@pytest.mark.parametrize(
    ("kind", "target", "payload"),
    [
        ("forum_thread_create", {"forum_id": "123"},
         {"name": "SCMA", "content": "starter", "applied_tags": ["not-a-snowflake"]}),
        ("forum_thread_create", {"forum_id": "123"},
         {"name": "SCMA", "content": "starter", "applied_tags": "11"}),
        ("forum_thread_update", {"thread_id": "123"},
         {"applied_tags": ["11", "not-a-snowflake"]}),
        ("forum_thread_update", {"thread_id": "123"},
         {"applied_tags": [11]}),
    ],
)
def test_forum_thread_tag_writes_reject_invalid_id_shapes(kind, target, payload):
    with pytest.raises(ValidationError):
        intent(kind, target, payload)


def test_rate_limit_and_repeated_delete():
    gateway = DiscordGateway("secret", session=Session([Response(429, {"retry_after": 7.5}, {"Retry-After": "2"})]))
    with pytest.raises(GatewayError) as raised:
        gateway.execute(intent("channel_message_create", {"channel_id": "123"}, {"content": "hi"}), ())
    assert raised.value.category == "rate_limited"
    assert raised.value.retry_after == 7.5
    gateway = DiscordGateway("secret", session=Session([Response(404)]))
    assert gateway.execute(intent("channel_message_delete", {"channel_id": "123", "message_id": "456"}, {}), ()) == {"message_id": "456"}


def test_outbound_nonce_is_stable_and_within_discord_limit():
    first = DiscordGateway.nonce("operation:alpha")
    assert first == DiscordGateway.nonce("operation:alpha")
    assert first != DiscordGateway.nonce("operation:beta")
    assert len(first) <= 25


@pytest.mark.parametrize("status", [401, 403])
def test_delete_auth_failures_are_blocked(status):
    gateway = DiscordGateway("secret", session=Session([Response(status)]))
    with pytest.raises(GatewayError) as raised:
        gateway.execute(intent("channel_message_delete", {"channel_id": "123", "message_id": "456"}, {}), ())
    assert raised.value.category == "permission"
