import json
import asyncio

import pytest

from discord_delivery.discord_gateway import GatewayError
from discord_delivery.models import Attachment, OperationIntent

from fastapi.testclient import TestClient

from discord_delivery.api import create_app
from discord_delivery.config import Config
from discord_delivery.store import DeliveryStore


def setup_client(tmp_path, executor=None):
    config = Config("127.0.0.1", 9120, "client-secret", "admin-secret",
                    tmp_path / "bot-token", tmp_path / "delivery.sqlite3", tmp_path / "media",
                    emoji_token="emoji-secret")
    store = DeliveryStore(config.state_path, config.media_path)
    return TestClient(create_app(config, store, executor)), store


def operation(key="news:1", **changes):
    value = {"key": key, "kind": "channel_message_create", "ordering_key": "channel:123",
             "target": {"channel_id": "123"},
             "payload": {"content": "Example", "allowed_mentions": {"parse": []}}}
    value.update(changes)
    return value


def test_guild_emoji_contract_is_typed_and_idempotent(tmp_path):
    client, store = setup_client(tmp_path, lambda query: [{"id": "456", "name": "writer"}])
    value = operation("profile-emoji:123:writer", kind="guild_emoji_create",
                      ordering_key="guild-emoji:123", target={"guild_id": "123"},
                      payload={"name": "writer"})
    png = b"\x89PNG\r\n\x1a\npixels"
    files = [("emoji.png", png, "image/png")]
    assert submit(client, value, attachments=files).status_code == 403
    assert store.counts()["pending"] == 0
    assert submit(client, operation("ordinary:emoji-token"), token="emoji-secret").status_code == 403
    assert store.counts()["pending"] == 0
    first = submit(client, value, token="emoji-secret", attachments=files)
    assert first.status_code == 202
    assert submit(client, value, token="emoji-secret", attachments=files).json()["id"] == first.json()["id"]
    assert submit(client, value, token="emoji-secret", attachments=[("emoji.png", png + b"x", "image/png")]).status_code == 409
    assert submit(client, value, token="emoji-secret", attachments=[("emoji.png", b"not a png", "image/png")]).status_code == 422
    assert png not in (tmp_path / "delivery.sqlite3").read_bytes()
    assert store.load_intent(value["key"]).attachments[0].data == png
    headers = {"Authorization": "Bearer client-secret"}
    assert client.post("/v1/queries", json={"kind": "guild_emojis", "guild_id": "123"},
                       headers=headers).json() == [{"id": "456", "name": "writer"}]
    assert client.post("/v1/queries", json={"kind": "guild_emojis", "guild_id": "bad"},
                       headers=headers).status_code == 422
    assert client.post("/v1/queries", json={"kind": "guild_emojis", "guild_id": "123"},
                       headers={"Authorization": "Bearer emoji-secret"}).status_code == 401
    assert client.get("/v1/operations/by-key/profile-emoji:123:writer",
                      headers={"Authorization": "Bearer emoji-secret"}).status_code == 401


def test_unprovisioned_emoji_token_keeps_service_available_and_create_closed(tmp_path, monkeypatch):
    values = {
        "DISCORD_DELIVERY_API_TOKEN": "client-secret",
        "DISCORD_DELIVERY_ADMIN_TOKEN": "admin-secret",
        "DISCORD_DELIVERY_BOT_TOKEN_PATH": str(tmp_path / "bot-token"),
        "DISCORD_DELIVERY_STATE_PATH": str(tmp_path / "delivery.sqlite3"),
        "DISCORD_DELIVERY_MEDIA_PATH": str(tmp_path / "media"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DISCORD_DELIVERY_EMOJI_TOKEN", raising=False)
    config = Config.from_environment()
    assert config.emoji_token is None
    store = DeliveryStore(config.state_path, config.media_path)
    client = TestClient(create_app(config, store))
    emoji = operation("profile-emoji:123:writer", kind="guild_emoji_create",
                      ordering_key="guild-emoji:123", target={"guild_id": "123"},
                      payload={"name": "writer"})
    assert submit(client, emoji, attachments=[("emoji.png", b"\x89PNG\r\n\x1a\npixels", "image/png")]).status_code == 403
    assert submit(client, operation()).status_code == 202
    assert store.get_by_key(emoji["key"]) is None


def submit(client, value, token="client-secret", attachments=()):
    files = [("operation", (None, json.dumps(value), "application/json"))]
    files += [("attachments", item) for item in attachments]
    return client.post("/v1/operations", files=files, headers={"Authorization": f"Bearer {token}"})


def adopt(client, envelope, attachments=(), token="admin-secret"):
    files = [("adoption", (None, json.dumps(envelope), "application/json"))]
    files += [("attachments", (item.filename, item.data, item.mime_type)) for item in attachments]
    return client.post("/v1/operations/adopt", files=files, headers={"Authorization": f"Bearer {token}"})


def make_intent(value, attachments=()):
    return OperationIntent(
        key=value["key"], kind=value["kind"], ordering_key=value["ordering_key"],
        target=value["target"], payload=value["payload"], attachments=tuple(attachments),
        reconcile_before_first_create=value.get("reconcile_before_first_create", False),
        legacy_nonce=value.get("legacy_nonce"),
    )


def test_submit_status_auth_and_private_media(tmp_path):
    client, store = setup_client(tmp_path)
    assert submit(client, operation(), token="admin-secret").status_code == 401
    response = submit(client, operation(), attachments=[("chart.png", b"bytes", "image/png")])
    assert response.status_code == 202
    assert submit(client, operation(), attachments=[("chart.png", b"bytes", "image/png")]).json()["id"] == response.json()["id"]
    status = client.get("/v1/operations/by-key/news:1", headers={"Authorization": "Bearer client-secret"})
    assert status.json()["status"] == "pending"
    assert status.json()["id"] == response.json()["id"]
    assert client.get("/healthz").json()["operations"]["pending"] == 1
    assert list((tmp_path / "media").rglob("chart.png")) == []
    assert len(list((tmp_path / "media").rglob("*chart.png"))) == 1
    assert store.get_by_key("news:1") is not None


def test_invalid_shapes_rejected_before_insert_and_changed_payload_conflicts(tmp_path):
    client, store = setup_client(tmp_path)
    assert submit(client, operation(target={"channel_id": "not-snowflake"})).status_code == 422
    assert submit(client, operation(kind=[])).status_code == 422
    assert submit(client, operation(payload={"content": "x", "allowed_mentions": {"parse": ["everyone"]}})).status_code == 422
    assert store.counts()["pending"] == 0
    assert submit(client, operation()).status_code == 202
    assert submit(client, operation(payload={"content": "changed"})).status_code == 409


def test_forum_thread_tag_ids_survive_api_validation_storage_and_digest(tmp_path):
    client, store = setup_client(tmp_path)
    cases = [
        (
            operation(
                "board:create:1",
                kind="forum_thread_create",
                ordering_key="forum:123",
                target={"forum_id": "123"},
                payload={"name": "SCMA", "content": "starter", "applied_tags": ["11", "22"]},
            ),
            "forum_thread_create",
        ),
        (
            operation(
                "board:update:1",
                kind="forum_thread_update",
                ordering_key="forum:123",
                target={"thread_id": "456"},
                payload={"applied_tags": ["11", "22"]},
            ),
            "forum_thread_update",
        ),
    ]

    for value, _kind in cases:
        response = submit(client, value)
        assert response.status_code == 202
        stored = store.load_intent(value["key"])
        assert stored.payload["applied_tags"] == ["11", "22"]
        assert response.json()["digest"] == stored.digest


@pytest.mark.parametrize(
    ("key", "kind", "target", "payload"),
    [
        ("board:bad-create-tag", "forum_thread_create", {"forum_id": "123"},
         {"name": "SCMA", "content": "starter", "applied_tags": ["bad"]}),
        ("board:bad-update-tag", "forum_thread_update", {"thread_id": "456"},
         {"applied_tags": "11"}),
    ],
)
def test_forum_thread_invalid_tag_ids_never_enter_ledger(tmp_path, key, kind, target, payload):
    client, store = setup_client(tmp_path)
    value = operation(key, kind=kind, ordering_key="forum:123", target=target, payload=payload)

    response = submit(client, value)

    assert response.status_code == 422
    assert store.get_by_key(key) is None


def test_thread_edit_modes_and_archived_state_survive_api_storage_and_digest(tmp_path):
    client, store = setup_client(tmp_path)
    attachments = []
    cases = [
        ("board:edit:keep", {"content": "updated", "attachments_mode": "keep"}, ()),
        ("board:edit:clear", {"content": "updated", "attachments_mode": "clear"}, ()),
        ("board:edit:replace", {"content": "updated", "attachments_mode": "replace"},
         [Attachment("chart.png", "image/png", b"chart")]),
    ]
    for key, payload, operation_attachments in cases:
        value = operation(
            key,
            kind="thread_message_edit",
            ordering_key="thread:456",
            target={"thread_id": "456", "message_id": "789"},
            payload=payload,
        )
        response = submit(
            client,
            value,
            attachments=[(item.filename, item.data, item.mime_type) for item in operation_attachments],
        )
        assert response.status_code == 202
        stored = store.load_intent(key)
        assert stored.payload == payload
        assert stored.digest == response.json()["digest"]
        assert [item.data for item in stored.attachments] == [item.data for item in operation_attachments]

    for archived in (True, False):
        key = f"board:archived:{archived}"
        value = operation(
            key,
            kind="forum_thread_update",
            ordering_key="forum:123",
            target={"thread_id": "456"},
            payload={"archived": archived},
        )
        response = submit(client, value)
        assert response.status_code == 202
        assert store.load_intent(key).payload == {"archived": archived}


@pytest.mark.parametrize(
    ("key", "kind", "target", "payload", "attachments"),
    [
        ("board:edit:missing-replacement", "thread_message_edit",
         {"thread_id": "456", "message_id": "789"},
         {"content": "updated", "attachments_mode": "replace"}, ()),
        ("board:edit:bad-mode", "thread_message_edit",
         {"thread_id": "456", "message_id": "789"},
         {"content": "updated", "attachments_mode": "append"}, ()),
        ("board:bad-archived", "forum_thread_update", {"thread_id": "456"},
         {"archived": "false"}, ()),
    ],
)
def test_invalid_thread_edit_modes_and_archived_shape_never_enter_ledger(
    tmp_path, key, kind, target, payload, attachments
):
    client, store = setup_client(tmp_path)
    value = operation(key, kind=kind, ordering_key="thread:456", target=target, payload=payload)

    response = submit(
        client,
        value,
        attachments=[(item.filename, item.data, item.mime_type) for item in attachments],
    )

    assert response.status_code == 422
    assert store.get_by_key(key) is None


def test_import_and_admin_retry_are_separate_from_client(tmp_path):
    client, store = setup_client(tmp_path)
    completed = {"action": "completed", "operation": operation("legacy:done"), "receipt": {"message_id": "456"}}
    assert client.post("/v1/operations/adopt", json=completed, headers={"Authorization": "Bearer client-secret"}).status_code == 401
    imported = client.post("/v1/operations/adopt", json=completed, headers={"Authorization": "Bearer admin-secret"})
    assert imported.status_code == 202
    assert imported.json()["receipt"] == {"message_id": "456"}
    assert client.post("/v1/operations/adopt", json={**completed, "payload_digest": "0" * 64}, headers={"Authorization": "Bearer admin-secret"}).status_code == 422
    assert client.post("/v1/operations/adopt", json={**completed, "receipt": {"message_id": "789"}}, headers={"Authorization": "Bearer admin-secret"}).status_code == 409
    pending = {"action": "pending", "operation": operation("legacy:pending")}
    assert client.post("/v1/operations/adopt", json=pending, headers={"Authorization": "Bearer admin-secret"}).status_code == 422
    pending["operation"]["reconcile_before_first_create"] = True
    assert client.post("/v1/operations/adopt", json=pending, headers={"Authorization": "Bearer admin-secret"}).json()["status"] == "pending_reconciliation"
    store.db.execute("UPDATE discord_operations SET status='blocked' WHERE operation_key='legacy:pending'")
    digest = store.get_by_key("legacy:pending").digest
    retry_url = "/v1/admin/operations/legacy:pending/retry"
    assert client.post(retry_url, json={"expected_digest": digest}, headers={"Authorization": "Bearer client-secret"}).status_code == 401
    assert client.post(retry_url, json={"expected_digest": "0" * 64}, headers={"Authorization": "Bearer admin-secret"}).status_code == 409
    assert client.post(retry_url, json={"expected_digest": digest}, headers={"Authorization": "Bearer admin-secret"}).json()["status"] == "retrying"
    listing = client.get("/v1/admin/operations", headers={"Authorization": "Bearer admin-secret"})
    assert listing.status_code == 200
    assert "content" not in listing.text and "media" not in listing.text


def test_query_uses_injected_executor_after_validation(tmp_path):
    seen = []
    client, store = setup_client(tmp_path, lambda query: seen.append(query) or {"messages": []})
    headers = {"Authorization": "Bearer client-secret"}
    assert client.post("/v1/queries", json={"kind": "channel_messages", "channel_id": "123", "limit": 101}, headers=headers).status_code == 422
    assert client.post("/v1/queries", json={"kind": "delete", "channel_id": "123"}, headers=headers).status_code == 422
    assert not seen
    assert client.post("/v1/queries", json={"kind": "channel_messages", "channel_id": "123", "limit": 10}, headers=headers).json() == {"messages": []}
    assert seen == [{"kind": "channel_messages", "channel_id": "123", "limit": 10}]
    assert store.counts()["pending"] == 0


def test_invalid_kind_specific_submission_does_not_enter_ledger(tmp_path):
    client, store = setup_client(tmp_path)
    invalid = operation(kind="channel_message_edit", target={"channel_id": "123"})
    assert submit(client, invalid).status_code == 422
    assert store.get_by_key(invalid["key"]) is None


def test_completed_import_rejects_wrong_receipt_kind(tmp_path):
    client, store = setup_client(tmp_path)
    submitted = {"action": "completed", "operation": operation("legacy:wrong-receipt"),
                 "receipt": {"channel_id": "123"}}
    response = client.post("/v1/operations/adopt", json=submitted,
                           headers={"Authorization": "Bearer admin-secret"})
    assert response.status_code == 422
    assert store.get_by_key("legacy:wrong-receipt") is None


def test_query_executor_runs_outside_event_loop_and_sanitizes_errors(tmp_path):
    def executor(_query):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return {"off_loop": True}
        raise AssertionError("query ran on ASGI event loop")

    client, _ = setup_client(tmp_path, executor)
    headers = {"Authorization": "Bearer client-secret"}
    query = {"kind": "channel_messages", "channel_id": "123"}
    assert client.post("/v1/queries", json=query, headers=headers).json() == {"off_loop": True}

    def failed(_query):
        raise GatewayError("rate_limited", 12)

    client, _ = setup_client(tmp_path / "other", failed)
    response = client.post("/v1/queries", json=query, headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "Discord query unavailable"}
    assert response.headers["Retry-After"] == "12"


def test_legacy_nonce_is_admin_import_only_and_digest_bound(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:nonce", reconcile_before_first_create=True, legacy_nonce="old-123")
    assert submit(client, value).status_code == 422
    headers = {"Authorization": "Bearer admin-secret"}
    imported = client.post("/v1/operations/adopt", json={"action": "pending", "operation": value}, headers=headers)
    assert imported.status_code == 202
    assert store.load_intent("legacy:nonce").legacy_nonce == "old-123"
    changed = {**value, "legacy_nonce": "old-456"}
    assert client.post("/v1/operations/adopt", json={"action": "pending", "operation": changed}, headers=headers).status_code == 409
    too_long = operation("legacy:bad", reconcile_before_first_create=True, legacy_nonce="x" * 26)
    assert client.post("/v1/operations/adopt", json={"action": "pending", "operation": too_long}, headers=headers).status_code == 422


def test_legacy_nonce_accepts_printable_space_at_25_character_boundary(tmp_path):
    client, store = setup_client(tmp_path)
    headers = {"Authorization": "Bearer admin-secret"}
    value = operation("legacy:space", reconcile_before_first_create=True, legacy_nonce="x" * 24 + " ")
    response = client.post("/v1/operations/adopt", json={"action": "pending", "operation": value}, headers=headers)
    assert response.status_code == 202
    assert store.load_intent("legacy:space").legacy_nonce == "x" * 24 + " "
    too_long = operation("legacy:space26", reconcile_before_first_create=True, legacy_nonce="x" * 25 + " ")
    assert client.post("/v1/operations/adopt", json={"action": "pending", "operation": too_long}, headers=headers).status_code == 422


def test_pending_media_adoption_preserves_attachment_order_and_digest_without_discord_calls(tmp_path):
    query_calls = []
    client, store = setup_client(tmp_path, lambda query: query_calls.append(query) or {})
    value = operation("legacy:pending:media", reconcile_before_first_create=True,
                      legacy_nonce="x" * 24 + " ")
    attachments = (
        Attachment("first.png", "image/png", b"FIRST\x00PNG"),
        Attachment("second.jpg", "image/jpeg", b"SECOND\xffJPEG"),
    )
    intent = make_intent(value, attachments)

    response = adopt(client, {"action": "pending", "operation": value, "payload_digest": intent.digest}, attachments)

    assert response.status_code == 202
    assert response.json()["digest"] == intent.digest
    assert response.json()["status"] == "pending_reconciliation"
    stored = store.load_intent(value["key"])
    assert [(item.filename, item.mime_type, item.data) for item in stored.attachments] == [
        ("first.png", "image/png", b"FIRST\x00PNG"),
        ("second.jpg", "image/jpeg", b"SECOND\xffJPEG"),
    ]
    assert stored.legacy_nonce == "x" * 24 + " "
    metadata = store.stored_attachments(value["key"])
    assert [(item["filename"], item["mime_type"]) for item in metadata] == [
        ("first.png", "image/png"), ("second.jpg", "image/jpeg")
    ]
    assert query_calls == []


def test_completed_media_adoption_preserves_order_and_receipt_without_discord_calls(tmp_path):
    query_calls = []
    client, store = setup_client(tmp_path, lambda query: query_calls.append(query) or {})
    value = operation("legacy:completed:media")
    attachments = (
        Attachment("chart.webp", "image/webp", b"CHART-WEBP"),
        Attachment("source.png", "image/png", b"SOURCE-PNG"),
    )
    intent = make_intent(value, attachments)
    old_receipt = {"channel_id": "123", "message_id": "456"}

    response = adopt(client, {
        "action": "completed", "operation": value, "receipt": old_receipt,
        "payload_digest": intent.digest,
    }, attachments)

    assert response.status_code == 202
    assert response.json()["status"] == "delivered"
    assert response.json()["receipt"] == old_receipt
    stored = store.load_intent(value["key"])
    assert [(item.filename, item.mime_type, item.data) for item in stored.attachments] == [
        ("chart.webp", "image/webp", b"CHART-WEBP"),
        ("source.png", "image/png", b"SOURCE-PNG"),
    ]
    assert query_calls == []


def test_completed_and_pending_adoption_are_idempotent_without_discord_queries(tmp_path):
    query_calls = []
    client, store = setup_client(tmp_path, lambda query: query_calls.append(query) or {})
    completed_operation = operation("legacy:completed:idempotent")
    completed = {
        "action": "completed",
        "operation": completed_operation,
        "receipt": {"channel_id": "123", "message_id": "456"},
    }
    headers = {"Authorization": "Bearer admin-secret"}

    first_completed = adopt(client, completed)
    repeated_completed = adopt(client, completed)
    assert first_completed.status_code == repeated_completed.status_code == 202
    assert first_completed.json()["id"] == repeated_completed.json()["id"]
    assert repeated_completed.json()["receipt"] == completed["receipt"]
    assert store.get_by_key(completed_operation["key"]).status == "delivered"

    pending_operation = operation(
        "legacy:pending:idempotent",
        reconcile_before_first_create=True,
    )
    pending = {
        "action": "pending",
        "operation": pending_operation,
        "preflight": {"boundary_observed": True, "boundary": "700"},
    }
    first_pending = client.post("/v1/operations/adopt", json=pending, headers=headers)
    repeated_pending = client.post("/v1/operations/adopt", json=pending, headers=headers)
    assert first_pending.status_code == repeated_pending.status_code == 202
    assert first_pending.json()["id"] == repeated_pending.json()["id"]
    assert repeated_pending.json()["status"] == "pending_reconciliation"
    assert store.get_by_key(pending_operation["key"]).status == "pending_reconciliation"
    assert query_calls == []


@pytest.mark.parametrize("preflight", [
    {"boundary_observed": False, "boundary": "700"},
    {"boundary_observed": True, "boundary": "not-a-snowflake"},
    {"boundary_observed": True, "boundary": 700},
    {"boundary_observed": True},
    {"boundary_observed": True, "boundary": None, "extra": "field"},
])
def test_pending_adoption_rejects_invalid_preflight_boundary(tmp_path, preflight):
    client, store = setup_client(tmp_path)
    value = operation("legacy:invalid-preflight", reconcile_before_first_create=True)

    response = client.post("/v1/operations/adopt", json={
        "action": "pending", "operation": value, "preflight": preflight,
    }, headers={"Authorization": "Bearer admin-secret"})

    assert response.status_code == 422
    assert store.get_by_key(value["key"]) is None


def test_completed_adoption_rejects_preflight_metadata(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:completed-no-preflight")
    response = client.post("/v1/operations/adopt", json={
        "action": "completed", "operation": value,
        "receipt": {"channel_id": "123", "message_id": "456"},
        "preflight": {"boundary_observed": True, "boundary": "700"},
    }, headers={"Authorization": "Bearer admin-secret"})

    assert response.status_code == 422
    assert store.get_by_key(value["key"]) is None


def test_pending_adoption_cannot_replace_an_accepted_preflight_boundary(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:preflight-immutable", reconcile_before_first_create=True)
    headers = {"Authorization": "Bearer admin-secret"}
    first = client.post("/v1/operations/adopt", json={
        "action": "pending", "operation": value,
        "preflight": {"boundary_observed": True, "boundary": "700"},
    }, headers=headers)
    changed = client.post("/v1/operations/adopt", json={
        "action": "pending", "operation": value,
        "preflight": {"boundary_observed": True, "boundary": "701"},
    }, headers=headers)

    assert first.status_code == 202
    assert first.json()["digest"] == make_intent(value).digest
    assert changed.status_code == 409
    assert store.create_snapshot(value["key"])["boundary"] == "700"


def test_pending_adoption_accepts_explicit_empty_destination_boundary(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:empty-preflight", reconcile_before_first_create=True)

    response = client.post("/v1/operations/adopt", json={
        "action": "pending", "operation": value,
        "preflight": {"boundary_observed": True, "boundary": None},
    }, headers={"Authorization": "Bearer admin-secret"})

    assert response.status_code == 202
    assert store.create_snapshot(value["key"])["boundary_observed"] is True
    assert store.create_snapshot(value["key"])["boundary"] is None


def test_pending_preflight_rejects_create_kind_without_safe_readback(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:unsupported-preflight", reconcile_before_first_create=True,
                      kind="forum_channel_create", target={"guild_id": "77"},
                      payload={"name": "Board"})

    response = client.post("/v1/operations/adopt", json={
        "action": "pending", "operation": value,
        "preflight": {"boundary_observed": True, "boundary": "700"},
    }, headers={"Authorization": "Bearer admin-secret"})

    assert response.status_code == 422
    assert store.get_by_key(value["key"]) is None


def test_multipart_adoption_rejects_attachment_digest_mismatch_before_acceptance(tmp_path):
    client, store = setup_client(tmp_path)
    value = operation("legacy:pending:media-digest", reconcile_before_first_create=True)
    expected = (Attachment("chart.png", "image/png", b"expected"),)
    changed = (Attachment("chart.png", "image/png", b"changed"),)
    expected_digest = make_intent(value, expected).digest

    response = adopt(client, {
        "action": "pending", "operation": value, "payload_digest": expected_digest,
    }, changed)

    assert response.status_code == 422
    assert store.get_by_key(value["key"]) is None
