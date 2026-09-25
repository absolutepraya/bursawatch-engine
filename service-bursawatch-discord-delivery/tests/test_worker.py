from datetime import datetime, timezone, timedelta
import json

import pytest
import requests

from discord_delivery.discord_gateway import DiscordGateway
from discord_delivery.models import Attachment, OperationIntent
from discord_delivery.store import DeliveryStore, OperationStateConflict
from discord_delivery.worker import DeliveryWorker
from test_discord_gateway import Response, Session


NOW = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)


def emoji_operation():
    return OperationIntent("profile-emoji:123:writer", "guild_emoji_create", "guild-emoji:123",
                           {"guild_id": "123"}, {"name": "writer"},
                           (Attachment("emoji.png", "image/png", b"\x89PNG\r\n\x1a\npixels"),))


def test_emoji_create_stages_png_outside_sqlite_and_delivers(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[]), Response(body={"id": "456", "name": "writer"})])
    store.accept(emoji_operation())
    assert b"pixels" not in (tmp_path / "state.sqlite3").read_bytes()
    assert delivery.run_once(NOW).status == "delivered"
    assert store.get_by_key("profile-emoji:123:writer").receipt == {"emoji_id": "456"}
    assert b"pixels" not in (tmp_path / "state.sqlite3").read_bytes()
    assert [item[0] for item in session.calls] == ["GET", "POST"]


def test_emoji_lost_response_with_same_name_stays_ambiguous(tmp_path):
    class LostResponse(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("private response")
            if len(self.calls) == 1:
                return Response(body=[])
            return Response(body=[{"id": "456", "name": "writer", "managed": False}])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    store.accept(emoji_operation())
    session = LostResponse([])
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session), alert=lambda *_: None)
    assert delivery.run_once(NOW).status == "ambiguous"
    assert [item[0] for item in session.calls] == ["GET", "POST", "GET"]
    assert store.get_by_key("profile-emoji:123:writer").receipt is None


def test_emoji_create_rejects_existing_name_before_post(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[
        {"id": "456", "name": "writer", "managed": False, "animated": False}
    ])])
    store.accept(emoji_operation())
    assert delivery.run_once(NOW).status == "rejected"
    assert [item[0] for item in session.calls] == ["GET"]


def operation(key="one", *, migrated=False):
    return OperationIntent(key, "channel_message_create", "channel:123", {"channel_id": "123"},
                           {"content": "exact content"}, (), migrated)


def worker(tmp_path, responses):
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = Session(responses)
    return store, session, DeliveryWorker(store, DiscordGateway("secret", session=session))


def test_success_persists_receipt_after_restart(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[]), Response(body={"id": "456"})])
    store.accept(operation())
    assert delivery.run_once(NOW).status == "delivered"
    reopened = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    assert reopened.get_by_key("one").receipt == {"message_id": "456"}
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    snapshot = reopened.create_snapshot("one")
    assert snapshot["request"]["body"]["content"] == "exact content"
    assert snapshot["request"]["body"]["enforce_nonce"] is True


def test_rate_limit_uses_discord_delay(tmp_path):
    store, _, delivery = worker(tmp_path, [Response(body=[]), Response(429, {"retry_after": 8})])
    store.accept(operation())
    assert delivery.run_once(NOW).status == "retrying"
    row = store.db.execute("SELECT next_attempt_at FROM discord_operations WHERE operation_key='one'").fetchone()
    assert datetime.fromisoformat(row[0]) >= NOW + timedelta(seconds=8)


def test_transient_network_failure_schedules_exponential_retry(tmp_path):
    class NetworkSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "PATCH":
                raise requests.ConnectionError("sensitive URL")
            return Response(body=[])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = NetworkSession([])
    store.accept(OperationIntent("one", "channel_message_edit", "channel:123",
                                 {"channel_id": "123", "message_id": "456"}, {"content": "edit"}))
    assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "retrying"
    row = store.db.execute("SELECT next_attempt_at,error_category FROM discord_operations WHERE operation_key='one'").fetchone()
    assert row[1] == "network"
    assert datetime.fromisoformat(row[0]) == NOW + timedelta(seconds=2)
    assert "sensitive" not in str(store.get_by_key("one"))


def test_ambiguous_starter_replacement_retries_same_digest_and_attachment_set(tmp_path):
    class LostAckSession(Session):
        def __init__(self):
            super().__init__([])
            self.remote_attachment_names = ["old.jpg"]

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method != "PATCH":
                raise AssertionError((method, url))
            body = json.loads(kwargs["data"]["payload_json"])
            self.remote_attachment_names = [item["filename"] for item in body["attachments"]]
            if len([call for call in self.calls if call[0] == "PATCH"]) == 1:
                raise requests.Timeout("accepted patch response was lost")
            return Response(body={"id": "456"})

    now = NOW
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = LostAckSession()
    chart = Attachment("new.png", "image/png", b"exact chart bytes")
    edit = OperationIntent(
        "board:episode-1:replace-chart",
        "thread_message_edit",
        "thread:123",
        {"thread_id": "123", "message_id": "456"},
        {"content": "updated card", "attachments_mode": "replace"},
        (chart,),
    )
    store.accept(edit)
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session))

    assert delivery.run_once(now).status == "retrying"
    retained = store.get_by_key(edit.key)
    assert retained.digest == edit.digest
    assert retained.status == "retrying"
    assert session.remote_attachment_names == ["new.png"]

    assert delivery.run_once(now + timedelta(seconds=3)).status == "delivered"
    assert store.get_by_key(edit.key).digest == edit.digest
    assert store.get_by_key(edit.key).receipt == {"message_id": "456"}
    calls = [call for call in session.calls if call[0] == "PATCH"]
    assert len(calls) == 2
    payloads = [json.loads(call[2]["data"]["payload_json"]) for call in calls]
    assert payloads[0] == payloads[1]
    assert [call[2]["files"]["files[0]"][1] for call in calls] == [b"exact chart bytes"] * 2


def test_network_failure_after_create_uses_readback_before_retry(tmp_path):
    class NetworkSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.ConnectionError("unknown outcome")
            return Response(body=[])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = NetworkSession([])
    store.accept(operation())
    assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "pending_reconciliation"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]


def test_permission_failure_blocks_and_admin_digest_retry(tmp_path):
    store, _, delivery = worker(tmp_path, [Response(body=[]), Response(403), Response(body={"id": "456"})])
    original = operation()
    store.accept(original)
    assert delivery.run_once(NOW).status == "blocked"
    with pytest.raises(OperationStateConflict):
        store.retry_blocked("one", "0" * 64)
    store.retry_blocked("one", original.digest)
    assert delivery.run_once(NOW).status == "delivered"


def test_interrupted_create_reconciles_before_another_create(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[{"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")}])])
    store.accept(operation())
    assert store.claim_next().status == "delivering"
    assert delivery.run_once(NOW).status == "delivered"
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize("readback,expected", [
    ([{"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")}], "delivered"),
    ([{"id": "999", "content": "else"}], "ambiguous"),
    ([{"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")}, {"id": "789", "content": "exact content", "nonce": DiscordGateway.nonce("one")}], "ambiguous"),
])
def test_migrated_create_preflight(tmp_path, readback, expected):
    responses = [Response(body=readback)]
    store, session, delivery = worker(tmp_path, responses)
    store.accept(operation(migrated=True))
    assert delivery.run_once(NOW).status == expected
    assert [call[0] for call in session.calls] == ["GET"]


def test_timeout_readback_inconclusive_never_creates_twice(tmp_path):
    class TimeoutSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("unsafe body")
            return Response(body=[] if len(self.calls) == 1 else [{"id": "789", "content": "other"}] * 100)
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = TimeoutSession([])
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session))
    store.accept(operation())
    assert delivery.run_once(NOW).status == "ambiguous"
    assert delivery.run_once(NOW).status == "idle"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET", "GET"]


def test_timeout_unique_readback_completes_without_second_post(tmp_path):
    class TimeoutSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("body")
            return Response(body=[] if len(self.calls) == 1 else [
                {"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")}])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = TimeoutSession([])
    store.accept(operation())
    assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "delivered"
    assert store.get_by_key("one").receipt == {"message_id": "456"}
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]


def test_timeout_proven_absence_waits_for_reconciliation_before_second_post(tmp_path):
    class TimeoutSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("body")
            return Response(body=[])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = TimeoutSession([])
    store.accept(operation())
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session))
    assert delivery.run_once(NOW).status == "pending_reconciliation"
    assert store.get_by_key("one").status == "pending_reconciliation"
    due = store.db.execute("SELECT next_attempt_at FROM discord_operations WHERE operation_key='one'").fetchone()[0]
    assert datetime.fromisoformat(due) > NOW
    assert delivery.run_once(NOW).status == "idle"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]


def test_timeout_readback_rate_limit_retries_reconciliation_without_second_post(tmp_path):
    class TimeoutSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("unknown")
            if len(self.calls) == 3:
                return Response(429, {"retry_after": 19})
            return Response(body=[])

    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = TimeoutSession([])
    store.accept(operation())
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session))
    assert delivery.run_once(NOW).status == "pending_reconciliation"
    row = store.db.execute("SELECT next_attempt_at,error_category FROM discord_operations WHERE operation_key='one'").fetchone()
    assert row[1] == "rate_limited"
    assert datetime.fromisoformat(row[0]) >= NOW + timedelta(seconds=19)
    assert delivery.run_once(NOW).status == "idle"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]


def test_forum_without_saved_boundary_remains_ambiguous_even_with_starter_match(tmp_path):
    forum = OperationIntent("forum:one", "forum_thread_create", "forum:123", {"forum_id": "123"},
                            {"name": "Topic", "content": "starter"}, (), True)
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    store.accept(forum)
    session = Session([
        Response(body={"guild_id": "77"}),
        Response(body={"threads": [{"id": "456", "parent_id": "123", "name": "Topic"}]}),
        Response(body={"threads": [], "has_more": False}),
        Response(body={"id": "456", "content": "starter"}),
    ])
    assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "ambiguous"
    assert store.get_by_key("forum:one").receipt is None
    assert all(call[0] == "GET" for call in session.calls)


def test_forum_incomplete_scope_never_creates(tmp_path):
    forum = OperationIntent("forum:one", "forum_thread_create", "forum:123", {"forum_id": "123"},
                            {"name": "Topic", "content": "starter"}, (), True)
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    store.accept(forum)
    session = Session([Response(body={"guild_id": "77"}), Response(body={"threads": []}),
                       Response(body={"threads": [], "has_more": True})])
    assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "ambiguous"
    assert all(call[0] == "GET" for call in session.calls)


def test_reconcile_pages_older_toward_saved_message_boundary(tmp_path):
    store, session, delivery = worker(tmp_path, [
        Response(body=[{"id": str(n), "content": "other"} for n in range(300, 200, -1)]),
        Response(body=[{"id": str(n), "content": "exact content" if n == 150 else "other",
                        "nonce": DiscordGateway.nonce("one") if n == 150 else None}
                       for n in range(200, 100, -1)]),
        Response(body=[{"id": "100", "content": "old"}]),
    ])
    store.accept(operation())
    claimed = store.claim_next()
    method, path, body = delivery.gateway.request_spec(operation())
    store.save_create_snapshot("one", {"request": {"method": method, "path": path, "body": body},
                                       "boundary": "100", "boundary_observed": True,
                                       "reconcile_before_first_create": False, "attachments": []})
    assert delivery.reconcile(claimed).receipt == {"message_id": "150"}
    assert [call[2].get("params", {}).get("before") for call in session.calls] == [None, "201", "101"]


def test_reconcile_missing_boundary_and_page_budget_are_inconclusive(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[{"id": "456", "content": "other"}])])
    store.accept(operation(migrated=True))
    claimed = store.claim_reconciliation()
    assert delivery.reconcile(claimed).status == "inconclusive"
    assert len(session.calls) == 1

    other = OperationIntent("two", "channel_message_create", "channel:456", {"channel_id": "456"},
                            {"content": "exact content"})
    store.accept(other)
    claimed = store.claim_next()
    method, path, body = delivery.gateway.request_spec(other)
    store.save_create_snapshot("two", {"request": {"method": method, "path": path, "body": body},
                                       "boundary": "100", "boundary_observed": True,
                                       "reconcile_before_first_create": False, "attachments": []})
    session.responses = iter([Response(body=[{"id": str(n), "content": "other"} for n in range(start, start-100, -1)])
                              for start in (500, 400, 300)])
    assert delivery.reconcile(claimed).status == "inconclusive"


def test_forum_reconcile_ignores_old_same_title_and_reads_starter_by_thread_id(tmp_path):
    forum = OperationIntent("forum:bounded", "forum_thread_create", "forum:123", {"forum_id": "123"},
                            {"name": "Topic", "content": "starter"})
    store, session, delivery = worker(tmp_path, [
        Response(body={"guild_id": "77"}),
        Response(body={"threads": [{"id": "300", "parent_id": "123", "name": "Topic"},
                                   {"id": "500", "parent_id": "123", "name": "Topic"}]}),
        Response(body={"threads": [], "has_more": False}),
        Response(body={"id": "500", "content": "starter"}),
    ])
    store.accept(forum)
    claimed = store.claim_next()
    method, path, body = delivery.gateway.request_spec(forum)
    store.save_create_snapshot(forum.key, {"request": {"method": method, "path": path, "body": body},
                                           "boundary": "400", "boundary_observed": True,
                                           "reconcile_before_first_create": False, "attachments": []})
    assert delivery.reconcile(claimed).receipt == {"thread_id": "500", "message_id": "500"}
    assert session.calls[-1][1].endswith("/channels/500/messages/500")
    assert not any("/channels/300/messages" in call[1] for call in session.calls)


def test_transient_readback_keeps_pending_reconciliation_with_retry_after(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(429, {"retry_after": 17})])
    store.accept(operation(migrated=True))
    assert delivery.run_once(NOW).status == "pending_reconciliation"
    row = store.db.execute("SELECT next_attempt_at,error_category FROM discord_operations WHERE operation_key='one'").fetchone()
    assert row[1] == "rate_limited"
    assert datetime.fromisoformat(row[0]) >= NOW + timedelta(seconds=17)
    assert delivery.run_once(NOW).status == "idle"
    assert len(session.calls) == 1


def test_legacy_nonce_matches_history_but_not_outbound_nonce(tmp_path):
    intent = OperationIntent("one", "channel_message_create", "channel:123", {"channel_id": "123"},
                             {"content": "exact content"}, (), True, "legacy-123")
    store, session, delivery = worker(tmp_path, [Response(body=[{"id": "456", "content": "exact content", "nonce": "legacy-123"}])])
    store.adopt_pending(intent)
    assert delivery.run_once(NOW).status == "delivered"
    assert store.get_by_key("one").receipt == {"message_id": "456"}
    assert DiscordGateway.nonce("one") != "legacy-123"
    assert all(call[0] == "GET" for call in session.calls)


def test_adopted_pending_unique_match_is_imported_without_duplicate_create(tmp_path):
    intent = operation(migrated=True)
    store, session, delivery = worker(tmp_path, [Response(body=[{
        "id": "456", "content": "exact content", "nonce": DiscordGateway.nonce(intent.key),
    }])])
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": "400"})

    result = delivery.run_once(NOW)

    assert result.status == "delivered"
    assert store.get_by_key(intent.key).receipt == {"message_id": "456"}
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize("boundary", ["400", None])
def test_adopted_pending_proven_absence_creates_once_after_saved_boundary(tmp_path, boundary):
    intent = operation(migrated=True)
    store, session, delivery = worker(tmp_path, [
        Response(body=[]), Response(body=[]), Response(body=[]), Response(body={"id": "789"}),
    ])
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": boundary})

    first = delivery.run_once(NOW)
    assert first.status == "pending_reconciliation"
    assert store.get_by_key(intent.key).receipt is None
    assert [call[0] for call in session.calls] == ["GET"]

    second = delivery.run_once(NOW + timedelta(seconds=10))
    assert second.status == "delivered"
    assert store.get_by_key(intent.key).receipt == {"message_id": "789"}
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET", "POST"]

    assert delivery.run_once(NOW + timedelta(seconds=20)).status == "idle"
    assert [call[0] for call in session.calls].count("POST") == 1


@pytest.mark.parametrize("readback", [
    [],
    [
        {"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")},
        {"id": "789", "content": "exact content", "nonce": DiscordGateway.nonce("one")},
    ],
])
def test_adopted_pending_without_boundary_stays_ambiguous(tmp_path, readback):
    intent = operation(migrated=True)
    store, session, delivery = worker(tmp_path, [Response(body=readback)])
    store.adopt_pending(intent)

    result = delivery.run_once(NOW)

    assert result.status == "ambiguous"
    assert store.get_by_key(intent.key).receipt is None
    assert [call[0] for call in session.calls] == ["GET"]


def test_adopted_pending_multiple_bounded_matches_stay_ambiguous(tmp_path):
    intent = operation(migrated=True)
    match = {"content": "exact content", "nonce": DiscordGateway.nonce(intent.key)}
    store, session, delivery = worker(tmp_path, [Response(body=[
        {**match, "id": "501"}, {**match, "id": "502"},
    ])])
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": "400"})

    result = delivery.run_once(NOW)

    assert result.status == "ambiguous"
    assert store.get_by_key(intent.key).receipt is None
    assert [call[0] for call in session.calls] == ["GET"]


def test_adopted_pending_page_budget_exhaustion_stays_ambiguous(tmp_path):
    intent = operation(migrated=True)
    pages = [
        [{"id": str(value), "content": "other"} for value in range(start, start - 100, -1)]
        for start in (500, 400, 300)
    ]
    store, session, delivery = worker(tmp_path, [Response(body=page) for page in pages])
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": "1"})

    result = delivery.run_once(NOW)

    assert result.status == "ambiguous"
    assert store.get_by_key(intent.key).receipt is None
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET"]


def forum_operation(key):
    return OperationIntent(
        key,
        "forum_thread_create",
        "forum:123",
        {"forum_id": "123"},
        {"name": "Legacy topic", "content": "exact starter"},
        (),
        True,
    )


def empty_forum_readback():
    return [
        Response(body={"guild_id": "77"}),
        Response(body={"threads": []}),
        Response(body={"threads": [], "has_more": False}),
    ]


def test_adopted_forum_pending_unique_match_uses_saved_boundary_without_create(tmp_path):
    intent = forum_operation("legacy:forum:matched")
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    session = Session([
        Response(body={"guild_id": "77"}),
        Response(body={"threads": [{"id": "500", "parent_id": "123", "name": "Legacy topic"}]}),
        Response(body={"threads": [], "has_more": False}),
        Response(body={"id": "500", "content": "exact starter", "attachments": []}),
    ])
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": "400"})

    result = DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW)

    assert result.status == "delivered"
    assert store.get_by_key(intent.key).receipt == {"thread_id": "500", "message_id": "500"}
    assert [call[0] for call in session.calls] == ["GET"] * 4


def test_adopted_forum_proven_absence_creates_once_after_saved_boundary(tmp_path):
    intent = forum_operation("legacy:forum:absent")
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    responses = empty_forum_readback() + empty_forum_readback() + empty_forum_readback()
    responses.append(Response(body={"id": "900", "message": {"id": "900"}}))
    session = Session(responses)
    delivery = DeliveryWorker(store, DiscordGateway("secret", session=session))
    store.adopt_pending(intent, preflight={"boundary_observed": True, "boundary": "400"})

    assert delivery.run_once(NOW).status == "pending_reconciliation"
    assert not any(call[0] == "POST" for call in session.calls)
    assert delivery.run_once(NOW + timedelta(seconds=10)).status == "delivered"
    assert store.get_by_key(intent.key).receipt == {"thread_id": "900", "message_id": "900"}
    assert [call[0] for call in session.calls].count("POST") == 1
    assert delivery.run_once(NOW + timedelta(seconds=20)).status == "idle"
    assert [call[0] for call in session.calls].count("POST") == 1


def test_default_alert_path_records_sanitized_blocked_and_ambiguous(caplog, tmp_path):
    store, _, delivery = worker(tmp_path, [Response(body=[]), Response(403)])
    store.accept(operation())
    with caplog.at_level("WARNING"):
        assert delivery.run_once(NOW).status == "blocked"
    assert "blocked" in caplog.text
    assert "exact content" not in caplog.text
    assert "secret" not in caplog.text

    caplog.clear()
    ambiguous = OperationIntent("ambiguous", "channel_message_create", "channel:456",
                                {"channel_id": "456"}, {"content": "exact content"}, (), True)
    store.accept(ambiguous)
    delivery.gateway._session = Session([Response(body=[{"id": "999", "content": "other"}])])
    with caplog.at_level("WARNING"):
        assert delivery.run_once(NOW).status == "ambiguous"
    assert "reconciliation_inconclusive" in caplog.text
    assert "exact content" not in caplog.text


@pytest.mark.parametrize("read_status", [401, 403, 404])
@pytest.mark.parametrize("kind", ["message", "forum"])
def test_unknown_create_readback_denial_blocks_then_admin_retry_reconciles_without_second_post(
        tmp_path, caplog, kind, read_status):
    class UnknownPostSession(Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if method == "POST":
                raise requests.Timeout("unknown create outcome")
            return next(self.responses)

    if kind == "message":
        intent = operation()
        readback = [Response(body=[]), Response(read_status), Response(body=[
            {"id": "456", "content": "exact content", "nonce": DiscordGateway.nonce("one")}])]
    else:
        intent = OperationIntent("one", "forum_thread_create", "forum:123", {"forum_id": "123"},
                                 {"name": "Topic", "content": "starter"})
        readback = [Response(body={"guild_id": "77"}), Response(body={"threads": []}),
                    Response(body={"threads": [], "has_more": False}), Response(read_status),
                    Response(body={"guild_id": "77"}),
                    Response(body={"threads": [{"id": "456", "parent_id": "123", "name": "Topic"}]}),
                    Response(body={"threads": [], "has_more": False}),
                    Response(body={"id": "456", "content": "starter"})]
    store = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    store.accept(intent)
    session = UnknownPostSession(readback)
    with caplog.at_level("WARNING"):
        assert DeliveryWorker(store, DiscordGateway("secret", session=session)).run_once(NOW).status == "blocked"
    assert store.get_by_key("one").status == "blocked"
    assert store.get_by_key("one").error_category == (
        "destination_missing" if read_status == 404 else "permission")
    assert store.create_snapshot("one")["reconciliation_required"] is True
    assert "blocked" in caplog.text
    assert "exact content" not in caplog.text and "starter" not in caplog.text
    assert store.retry_blocked("one", intent.digest).status == "pending_reconciliation"
    reopened = DeliveryStore(tmp_path / "state.sqlite3", tmp_path / "media")
    assert DeliveryWorker(reopened, DiscordGateway("secret", session=session)).run_once(NOW).status == "delivered"
    assert [call[0] for call in session.calls].count("POST") == 1


def test_definite_blocked_create_admin_retry_stays_on_normal_send_path(tmp_path):
    store, session, delivery = worker(tmp_path, [Response(body=[]), Response(403), Response(body={"id": "456"})])
    intent = operation()
    store.accept(intent)
    assert delivery.run_once(NOW).status == "blocked"
    assert store.create_snapshot(intent.key).get("reconciliation_required") is not True
    assert store.retry_blocked(intent.key, intent.digest).status == "retrying"
    assert delivery.run_once(NOW).status == "delivered"
    assert [call[0] for call in session.calls] == ["GET", "POST", "POST"]
