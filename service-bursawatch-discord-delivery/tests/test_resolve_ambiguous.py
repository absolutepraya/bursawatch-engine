"""Settling an ambiguous message create from a message Discord itself confirms (2026-10-18).

A lost-response heartbeat stayed ambiguous at the head of the shared #hermes chain. Automatic
read-back looks only at the newest 300 messages, so two days of channel traffic put the message
out of its reach and 1,876 later heartbeats waited behind it. The message was in Discord exactly
once, but the service offered no way to record that proof.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from discord_delivery.api import create_app
from discord_delivery.config import Config
from discord_delivery.discord_gateway import GatewayError
from discord_delivery.models import OperationIntent
from discord_delivery.store import DeliveryStore, OperationStateConflict
from discord_delivery.worker import resolve_ambiguous_create

import manage



def snowflake(offset_seconds):
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return str((int(moment.timestamp() * 1000) - 1420070400000) << 22)


CHANNEL = "1505162000420835388"
BOUNDARY = snowflake(-30)
SENT = snowflake(0)
NONCE = "a473c3ee20881375987419b8f"
CONTENT = "heartbeat 03:36"
ADMIN = {"Authorization": "Bearer admin-secret"}


def ambiguous(store, key="hb:1", category="create_outcome_unknown", nonce=NONCE, boundary=BOUNDARY,
              chain=f"channel:{CHANNEL}", **snapshot):
    store.accept(OperationIntent(key, "channel_message_create", chain,
                                 {"channel_id": CHANNEL}, {"content": CONTENT, "allowed_mentions": {"parse": []}}, ()))
    claimed = store.claim_next("2999-01-01T00:00:00.000Z")
    store.save_create_snapshot(claimed.key, {
        "boundary": boundary, "boundary_observed": True, "attachments": [],
        "request": {"method": "POST", "path": f"/channels/{CHANNEL}/messages",
                    "body": {"content": CONTENT, "nonce": nonce, "enforce_nonce": True}}, **snapshot})
    store.finish(claimed.key, "ambiguous", error_category=category)
    return store.get_by_key(key)


def discord_message(**changes):
    # A REST read carries no nonce; the author is the bot.
    return {"id": SENT, "channel_id": CHANNEL, "content": CONTENT, "author": {"id": "1", "bot": True},
            "attachments": [], **changes}


class Reader:
    """Discord double: the single-message read, then the first page after the boundary."""

    def __init__(self, message, page=None):
        self.message, self.queries = message, []
        self.page = page if page is not None else (
            [message] if isinstance(message, dict) and message.get("id") else [])

    def __call__(self, query):
        self.queries.append(query)
        if isinstance(self.message, Exception):
            raise self.message
        return self.message if query["kind"] == "thread_message_read" else self.page


@pytest.fixture
def store(tmp_path):
    return DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")


def test_a_confirmed_message_settles_the_head_and_releases_the_chain(store):
    head = ambiguous(store)
    store.accept(OperationIntent("hb:2", "channel_message_create", f"channel:{CHANNEL}",
                                 {"channel_id": CHANNEL}, {"content": "later", "allowed_mentions": {"parse": []}}, ()))
    assert store.claim_next("2999-01-01T00:00:00.000Z") is None  # blocked behind the ambiguous head
    reader = Reader(discord_message())

    settled = resolve_ambiguous_create(store, reader, "hb:1", head.digest, SENT)

    assert (settled.status, settled.receipt) == ("delivered", {"message_id": SENT})
    assert reader.queries == [
        {"kind": "thread_message_read", "thread_id": CHANNEL, "message_id": SENT},
        {"kind": "channel_messages", "channel_id": CHANNEL, "after": BOUNDARY, "limit": 100}]
    assert store.claim_next("2999-01-01T00:00:00.000Z").key == "hb:2"


@pytest.mark.parametrize("message", [
    discord_message(content="different"),
    discord_message(author={"id": "7", "bot": False}),
    discord_message(author=None),
    discord_message(id=snowflake(1)),
    discord_message(channel_id="999"),
    discord_message(attachments=[{"filename": "extra.png"}]),
    None,
    [],
])
def test_a_message_that_does_not_match_leaves_the_operation_ambiguous(store, message):
    head = ambiguous(store)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(message), "hb:1", head.digest, SENT)
    assert store.get_by_key("hb:1").status == "ambiguous"


def test_a_message_from_before_the_send_boundary_is_refused_without_reading_discord(store):
    head = ambiguous(store)
    reader = Reader(discord_message(id=BOUNDARY))
    for older in (BOUNDARY, str(int(BOUNDARY) - 1)):
        with pytest.raises(OperationStateConflict):
            resolve_ambiguous_create(store, reader, "hb:1", head.digest, older)
    assert reader.queries == []


def test_requires_the_saved_boundary_exact_digest_state_and_category(store):
    head = ambiguous(store)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message()), "hb:1", "0" * 64, SENT)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message()), "missing", head.digest, SENT)
    unbounded = ambiguous(store, "hb:nobound", boundary=None, chain="chain:b")
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message()), "hb:nobound", unbounded.digest, SENT)
    deadline = ambiguous(store, "hb:deadline", category="attempt_outcome_unknown", chain="chain:c")
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message()), "hb:deadline", deadline.digest, SENT)
    resolve_ambiguous_create(store, Reader(discord_message()), "hb:1", head.digest, SENT)
    with pytest.raises(OperationStateConflict):  # no second settlement of a delivered operation
        resolve_ambiguous_create(store, Reader(discord_message()), "hb:1", head.digest, SENT)


def test_a_message_sent_outside_the_operations_lifetime_is_refused(store):
    head = ambiguous(store)
    # Same content and author, but sent an hour after the operation went ambiguous.
    late = snowflake(3600)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message(id=late)), "hb:1", head.digest, late)
    assert store.get_by_key("hb:1").status == "ambiguous"


def test_identical_content_from_the_bot_in_the_same_window_is_refused(store):
    head = ambiguous(store)
    twin = discord_message(id=str(int(SENT) + 4194304))
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message(), page=[discord_message(), twin]),
                                 "hb:1", head.digest, SENT)
    assert store.get_by_key("hb:1").status == "ambiguous"


def test_a_message_outside_the_first_page_after_the_boundary_is_refused(store):
    head = ambiguous(store)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message(), page=[]), "hb:1", head.digest, SENT)


def test_a_human_authored_copy_does_not_count_as_a_twin(store):
    head = ambiguous(store)
    human = discord_message(id=str(int(SENT) + 4194304), author={"id": "7", "bot": False})
    settled = resolve_ambiguous_create(store, Reader(discord_message(), page=[discord_message(), human]),
                                       "hb:1", head.digest, SENT)
    assert settled.status == "delivered"


def test_one_message_cannot_back_two_operations(store):
    first = ambiguous(store, "hb:1")
    second = ambiguous(store, "hb:2", chain="chain:d")
    resolve_ambiguous_create(store, Reader(discord_message()), "hb:1", first.digest, SENT)
    with pytest.raises(OperationStateConflict):
        resolve_ambiguous_create(store, Reader(discord_message()), "hb:2", second.digest, SENT)
    assert store.get_by_key("hb:2").status == "ambiguous"


def test_an_unreadable_message_leaves_the_operation_ambiguous(store):
    head = ambiguous(store)
    with pytest.raises(GatewayError):
        resolve_ambiguous_create(store, Reader(GatewayError("timeout")), "hb:1", head.digest, SENT)
    assert store.get_by_key("hb:1").status == "ambiguous"


def api(tmp_path, reader):
    config = Config("127.0.0.1", 9140, "client-secret", "admin-secret",
                    tmp_path / "bot-token", tmp_path / "delivery.sqlite3", tmp_path / "media")
    store = DeliveryStore(config.state_path, config.media_path)
    return TestClient(create_app(config, store, reader)), store


def test_the_admin_route_is_admin_only_and_verifies_before_recording(tmp_path):
    client, store = api(tmp_path, Reader(discord_message()))
    head = ambiguous(store)
    url = "/v1/admin/operations/hb:1/resolve"
    body = {"expected_digest": head.digest, "message_id": SENT}
    assert client.post(url, json=body, headers={"Authorization": "Bearer client-secret"}).status_code == 401
    assert client.post(url, json={**body, "extra": 1}, headers=ADMIN).status_code == 422
    assert client.post(url, json={**body, "expected_digest": "0" * 64}, headers=ADMIN).status_code == 409
    assert store.get_by_key("hb:1").status == "ambiguous"
    response = client.post(url, json=body, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"
    assert "content" not in response.text


def test_the_admin_route_reports_an_unavailable_discord_read(tmp_path):
    client, store = api(tmp_path, Reader(GatewayError("timeout")))
    head = ambiguous(store)
    response = client.post("/v1/admin/operations/hb:1/resolve", headers=ADMIN,
                           json={"expected_digest": head.digest, "message_id": SENT})
    assert response.status_code == 503
    assert store.get_by_key("hb:1").status == "ambiguous"


def row(status="ambiguous"):
    return {"key": "hb:1", "target": {"channel_id": CHANNEL}, "digest": "a" * 64, "status": status,
            "created_at": "2026-10-15T20:36:32Z", "error_category": "create_outcome_unknown"}


def test_manage_resolve_previews_then_applies_only_for_the_matching_digest(monkeypatch, capsys):
    calls = []

    def fake(method, path, data=None):
        calls.append((method, path, data))
        return {"operations": [row()]} if method == "GET" else row("delivered")

    monkeypatch.setattr(manage, "_request", fake)
    args = ["resolve", "hb:1", "--expected-digest", "a" * 64, "--message-id", SENT]
    assert manage.main(args) == 0
    assert all(call[0] == "GET" for call in calls)
    with pytest.raises(RuntimeError):
        manage.main(["resolve", "hb:1", "--expected-digest", "b" * 64, "--message-id", SENT, "--apply"])
    assert all(call[0] == "GET" for call in calls)
    assert manage.main(args + ["--apply"]) == 0
    assert calls[-1] == ("POST", "/v1/admin/operations/hb%3A1/resolve",
                         {"expected_digest": "a" * 64, "message_id": SENT})
