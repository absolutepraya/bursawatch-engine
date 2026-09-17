from datetime import datetime, timedelta
import pytest
import requests

from conftest import example_buy_event, social_event
from discord_forum import DiscordForumClient, FORUM_CHANNEL_ID
from engine import BoardEngine
from store import BoardStore


class Response:
    def __init__(self, value, status=200):
        self.value, self.status_code = value, status

    def json(self):
        return self.value


class RemoteDiscord:
    """Mock the real REST boundary, including acceptance before lost response."""

    def __init__(self, store):
        self.store = store
        self.threads = []
        self.messages = {}
        self.posts = 0
        self.failure = None
        self.archived = False
        self.empty_recovery = False
        self.rejection = None

    def request(self, method, url, **kwargs):
        path = url.split("/api/v10", 1)[1]
        if method == "POST":
            self.posts += 1
            op = [op for op in self.store.operations_for_ticker("SCMA") if op.status == "claimed"][0]
            snapshot = op.payload["create_snapshot"]
            assert snapshot["operation_key"] == op.dedupe_key
            if self.rejection:
                rejection, self.rejection = self.rejection, None
                return rejection
            # This assertion runs before the server accepts anything: the
            # recovery identity and boundary must survive a killed process.
            message_id = str(max([int(snapshot["after_id"]), *map(int, self.messages)]) + 100)
            payload = kwargs["json"]
            is_thread = path.endswith("/threads")
            content = payload["message"]["content"] if is_thread else payload["content"]
            message = {"id": message_id, "content": content, "author": {"id": "99"}, "attachments": []}
            # Omit nonce from the read-back response. It is not a long-term
            # idempotency contract and recovery must not depend on it.
            self.messages[message_id] = message
            if is_thread:
                self.threads.append({"id": message_id, "parent_id": FORUM_CHANNEL_ID,
                                     "thread_metadata": {"archive_timestamp": datetime.now().astimezone().isoformat()}})
            failure, self.failure = self.failure, None
            if failure:
                raise failure
            return Response({"id": message_id, "message": message} if is_thread else message)
        if path == "/users/@me":
            return Response({"id": "99"})
        if path == f"/channels/{FORUM_CHANNEL_ID}":
            return Response({"guild_id": "55", "available_tags": [{"name": "Primary plan", "id": "11"}]})
        if path == "/guilds/55/threads/active":
            return Response({"threads": [] if self.archived or self.empty_recovery else self.threads})
        if path.endswith("/threads/archived/public"):
            return Response({"threads": self.threads if self.archived and not self.empty_recovery else [], "has_more": False})
        if path.endswith("/messages"):
            messages = [] if self.empty_recovery else sorted(self.messages.values(), key=lambda item: int(item["id"]), reverse=True)
            return Response(messages[:kwargs["params"]["limit"]])
        if "/messages/" in path:
            return Response(self.messages[path.rsplit("/", 1)[1]])
        raise AssertionError((method, path))


@pytest.mark.parametrize("operation", ["create_thread", "post_source_reply", "post_history_reply"])
@pytest.mark.parametrize("failure", [requests.Timeout("raw private transport detail"), KeyboardInterrupt()])
def test_restart_recovers_accepted_create_without_second_post(tmp_path, monkeypatch, operation, failure):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    remote = RemoteDiscord(store)
    monkeypatch.setattr("discord_forum.requests.request", remote.request)
    owner = BoardEngine(store, DiscordForumClient(token="unused-test-token"))
    owner.submit(example_buy_event(), now)
    if operation != "create_thread":
        assert owner.drain(now=now) == 1
        if operation == "post_source_reply":
            owner.submit(social_event("source:102", "SCMA", "SCMA: source update"), now)
        else:
            with store.transaction() as tx:
                tx.enqueue_outbox("post_history_reply", tx.active_episode("SCMA").id,
                                  {"content": "> 21 Sep\n> Source status confirmed", "media": None, "nonce_value": "history:102"}, "history:102", now)
    remote.failure = failure
    if isinstance(failure, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            owner.drain(now=now)
    else:
        assert owner.drain(now=now) == 0
    posts = remote.posts
    assert store.pending_outbox_count() == 1
    restarted = BoardEngine(BoardStore(store.path), DiscordForumClient(token="unused-test-token"))
    remote.archived = operation == "create_thread"
    assert restarted.drain(now=now + timedelta(minutes=6)) == 1
    assert remote.posts == posts
    assert store.pending_outbox_count() == 0
    assert store.active_episode("SCMA").thread_id is not None


def test_inconclusive_recovery_keeps_intent_pending_without_recreating(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    remote = RemoteDiscord(store)
    monkeypatch.setattr("discord_forum.requests.request", remote.request)
    owner = BoardEngine(store, DiscordForumClient(token="unused-test-token"))
    owner.submit(example_buy_event(), now)
    remote.failure = requests.Timeout("credential-like private exception")
    assert owner.drain(now=now) == 0
    remote.empty_recovery = True
    assert owner.drain(now=now + timedelta(minutes=2)) == 0
    assert remote.posts == 1
    op = store.operations_for_ticker("SCMA")[0]
    assert op.payload["create_snapshot"]
    assert op.last_error == "DiscordForumError"
    assert store.outbox_health() == {"pending": 1, "failed": 1}


def test_definite_create_rejection_retries_only_after_discord_delay(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    store = BoardStore(tmp_path / "board.sqlite3")
    remote = RemoteDiscord(store)
    monkeypatch.setattr("discord_forum.requests.request", remote.request)
    owner = BoardEngine(store, DiscordForumClient(token="unused-test-token"))
    owner.submit(example_buy_event(), now)
    remote.rejection = Response({"retry_after": 900}, 429)
    assert owner.drain(now=now) == 0
    assert "create_snapshot" not in store.operations_for_ticker("SCMA")[0].payload
    assert owner.drain(now=now + timedelta(minutes=2)) == 0
    assert remote.posts == 1
    assert owner.drain(now=now + timedelta(minutes=15)) == 1
    assert remote.posts == 2 and len(remote.threads) == 1
