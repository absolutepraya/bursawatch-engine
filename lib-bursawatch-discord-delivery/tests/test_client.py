from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from bursawatch_discord_delivery import (
    Attachment,
    DeliveryClient,
    DeliveryClientError,
    DiscordQuery,
    OperationIntent,
)
from bursawatch_discord_delivery.handoff import (
    HandoffError,
    handoff_summary,
    hash_source_bytes,
    import_handoff_item,
    operation_key_digest,
    require_apply_authorization,
    write_private_backup,
)
from bursawatch_discord_delivery import models as client_models
from bursawatch_discord_delivery import client as client_module


def make_operation(
    key: str = "news:event-1:text",
    *,
    content: str = "Example message",
    attachments: tuple[Attachment, ...] = (),
) -> OperationIntent:
    return OperationIntent(
        key=key,
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=attachments,
    )


def load_service_models():
    path = Path(__file__).resolve().parents[2] / "service-bursawatch-discord-delivery" / "bin" / "discord_delivery" / "models.py"
    module_name = "_bursawatch_delivery_service_models_for_client_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def client_for(fake_owner, token_file: Path, **kwargs) -> DeliveryClient:
    return DeliveryClient(fake_owner.base_url, token_file, **kwargs)


def test_loads_private_client_token_and_parses_accepted_receipt(fake_owner, token_file):
    client = client_for(fake_owner, token_file)
    operation = make_operation()

    receipt = client.submit(operation)

    assert receipt.key == operation.key
    assert receipt.digest == operation.digest
    assert receipt.status == "pending"
    request = fake_owner.state["requests"][0]
    assert request["headers"]["Authorization"] == "Bearer test-client-token"
    assert "test-client-token" not in repr(receipt)
    assert "test-admin-token" not in repr(receipt)


def test_refuses_group_or_world_readable_token_file(fake_owner, tmp_path):
    token_path = tmp_path / "unsafe.token"
    token_path.write_text("secret-value", encoding="utf-8")
    token_path.chmod(0o644)

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_path)

    assert caught.value.category == "invalid_token_file"
    assert str(token_path) not in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_refuses_symlinked_token_file(fake_owner, token_file, tmp_path):
    link = tmp_path / "token-link"
    link.symlink_to(token_file)

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, link)

    assert caught.value.category == "invalid_token_file"


def test_operation_json_matches_service_submission_contract(fake_owner, token_file):
    operation = make_operation(key="board/episode-2:starter")
    receipt = client_for(fake_owner, token_file).submit(operation)

    request = fake_owner.state["requests"][0]
    assert request["path"] == "/v1/operations"
    assert request["headers"]["Authorization"] == "Bearer test-client-token"
    assert request["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    body = request["body"]
    assert b'"key": "board/episode-2:starter"' in body
    assert b'"kind": "channel_message_create"' in body
    assert b'"ordering_key": "channel:123"' in body
    assert b'"target": {"channel_id": "123"}' in body
    assert b'"payload": {"allowed_mentions": {"parse": []}, "content": "Example message"}' in body
    assert b'"reconcile_before_first_create": false' in body
    assert receipt.digest == operation.digest


def test_operation_and_query_kind_sets_match_service_contract():
    service_models = load_service_models()

    assert client_models.KINDS == service_models.KINDS
    assert client_models.QUERY_KINDS == service_models.QUERIES
    assert client_models.STATUSES == {
        "pending", "pending_reconciliation", "retrying", "delivering",
        "delivered", "rejected", "blocked", "ambiguous",
    }


@pytest.mark.parametrize(
    ("kind", "target", "payload"),
    [
        (
            "forum_thread_create",
            {"forum_id": "123"},
            {
                "name": "SCMA",
                "content": "starter card",
                "allowed_mentions": {"parse": []},
                "applied_tags": ["456", "789"],
            },
        ),
        (
            "forum_thread_update",
            {"thread_id": "123"},
            {"applied_tags": ["456", "789"]},
        ),
    ],
)
def test_forum_thread_tag_ids_match_service_contract(kind, target, payload):
    service_models = load_service_models()
    operation = OperationIntent("board:episode-1:tags", kind, "forum:123", target, payload)
    service_operation = service_models.OperationIntent(
        key=operation.key,
        kind=operation.kind,
        ordering_key=operation.ordering_key,
        target=dict(operation.target),
        payload=dict(operation.payload),
    )

    assert operation.digest == service_operation.digest


@pytest.mark.parametrize(
    ("kind", "target", "payload"),
    [
        (
            "forum_thread_create",
            {"forum_id": "123"},
            {"name": "SCMA", "content": "starter", "applied_tags": ["not-a-snowflake"]},
        ),
        (
            "forum_thread_create",
            {"forum_id": "123"},
            {"name": "SCMA", "content": "starter", "applied_tags": "456"},
        ),
        (
            "forum_thread_update",
            {"thread_id": "123"},
            {"applied_tags": ["456", "not-a-snowflake"]},
        ),
        (
            "forum_thread_update",
            {"thread_id": "123"},
            {"applied_tags": ["456", 789]},
        ),
    ],
)
def test_forum_thread_tag_ids_reject_invalid_shapes(kind, target, payload):
    with pytest.raises(client_models.ValidationError):
        OperationIntent("board:episode-1:invalid-tags", kind, "forum:123", target, payload)


def test_thread_message_edit_attachment_modes_match_service_contract():
    service_models = load_service_models()
    attachment = Attachment("chart.png", "image/png", b"chart bytes")
    cases = [
        ({"content": "updated", "attachments_mode": "keep"}, ()),
        ({"content": "updated", "attachments_mode": "clear"}, ()),
        ({"content": "updated", "attachments_mode": "replace"}, (attachment,)),
    ]

    operations = []
    for index, (payload, attachments) in enumerate(cases):
        operation = OperationIntent(
            f"board:edit:{index}", "thread_message_edit", "thread:123",
            {"thread_id": "123", "message_id": "456"}, payload,
            attachments=attachments,
        )
        service_operation = service_models.OperationIntent(
            key=operation.key,
            kind=operation.kind,
            ordering_key=operation.ordering_key,
            target=dict(operation.target),
            payload=dict(operation.payload),
            attachments=tuple(
                service_models.Attachment(item.filename, item.mime_type, item.data)
                for item in operation.attachments
            ),
        )
        assert operation.digest == service_operation.digest
        operations.append(operation)

    assert len({item.digest for item in operations}) == 3


@pytest.mark.parametrize(
    ("payload", "attachments"),
    [
        ({"content": "updated", "attachments_mode": "replace"}, ()),
        ({"content": "updated", "attachments_mode": "keep"}, (Attachment("chart.png", "image/png", b"bytes"),)),
        ({"content": "updated", "attachments_mode": "append"}, ()),
    ],
)
def test_thread_message_edit_rejects_invalid_attachment_mode(payload, attachments):
    with pytest.raises(client_models.ValidationError):
        OperationIntent(
            "board:invalid-edit", "thread_message_edit", "thread:123",
            {"thread_id": "123", "message_id": "456"}, payload,
            attachments=attachments,
        )


@pytest.mark.parametrize("archived", [True, False])
def test_forum_thread_archive_state_matches_service_contract(archived):
    service_models = load_service_models()
    operation = OperationIntent(
        f"board:archive:{archived}", "forum_thread_update", "forum:123",
        {"thread_id": "123"}, {"archived": archived},
    )
    service_operation = service_models.OperationIntent(
        key=operation.key, kind=operation.kind, ordering_key=operation.ordering_key,
        target=dict(operation.target), payload=dict(operation.payload),
    )
    assert operation.digest == service_operation.digest


@pytest.mark.parametrize("archived", [None, 0, "false"])
def test_forum_thread_archive_state_rejects_non_boolean(archived):
    with pytest.raises(client_models.ValidationError):
        OperationIntent(
            "board:bad-archive", "forum_thread_update", "forum:123",
            {"thread_id": "123"}, {"archived": archived},
        )


def test_legacy_nonce_and_attachment_digest_match_service_model():
    service_models = load_service_models()
    attachment_bytes = b"legacy image\x00bytes"
    operation = OperationIntent(
        key="swing:legacy-episode:starter",
        kind="thread_message_create",
        ordering_key="thread:123",
        target={"thread_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        attachments=(Attachment("legacy.png", "image/png", attachment_bytes),),
        reconcile_before_first_create=True,
        legacy_nonce="legacy nonce with space",
    )
    service_operation = service_models.OperationIntent(
        key=operation.key,
        kind=operation.kind,
        ordering_key=operation.ordering_key,
        target=dict(operation.target),
        payload=dict(operation.payload),
        attachments=(service_models.Attachment("legacy.png", "image/png", attachment_bytes),),
        reconcile_before_first_create=True,
        legacy_nonce="legacy nonce with space",
    )

    assert operation.digest == service_operation.digest
    with pytest.raises(client_models.ValidationError):
        operation.as_dict()
    assert operation.as_dict(include_legacy_nonce=True)["legacy_nonce"] == "legacy nonce with space"


def test_multipart_submission_preserves_attachment_bytes_and_metadata(fake_owner, token_file):
    image_bytes = b"PNG\x00\xff\r\n--not-a-real-boundary\x10"
    attachment = Attachment("chart.png", "image/png", image_bytes)
    operation = make_operation(attachments=(attachment,))

    client_for(fake_owner, token_file).submit(operation)

    request = fake_owner.state["requests"][0]
    body = request["body"]
    assert b'name="attachments"; filename="chart.png"' in body
    assert b"Content-Type: image/png" in body
    assert image_bytes in body
    assert hashlib.sha256(image_bytes).hexdigest().encode() not in body


def test_status_looks_up_encoded_operation_key_and_returns_none_for_missing(fake_owner, token_file):
    operation = make_operation(key="watcher/event-4/text")
    client = client_for(fake_owner, token_file)
    accepted = client.submit(operation)

    found = client.status(operation.key)
    missing = client.status("news:not-yet-accepted")

    assert found == accepted
    assert missing is None
    assert unquote(fake_owner.state["requests"][1]["path"]) == "/v1/operations/by-key/watcher/event-4/text"


def test_query_uses_allowlisted_typed_query_and_returns_json(fake_owner, token_file):
    fake_owner.state["query_response"] = [{"id": "123", "content": "read-only result"}]
    query = DiscordQuery(kind="channel_messages", channel_id="123", limit=20, before="999")

    result = client_for(fake_owner, token_file).query(query)

    assert result == fake_owner.state["query_response"]
    request = fake_owner.state["requests"][0]
    assert request["path"] == "/v1/queries"
    assert request["headers"]["Authorization"] == "Bearer test-client-token"
    assert json.loads(request["body"]) == {
        "kind": "channel_messages", "channel_id": "123", "before": "999", "limit": 20,
    }


def test_wait_polls_status_until_terminal_receipt_without_resubmitting(fake_owner, token_file):
    operation = make_operation()
    client = client_for(fake_owner, token_file)
    pending = client.submit(operation)
    delivered = {
        "id": pending.id,
        "key": pending.key,
        "digest": pending.digest,
        "status": "delivered",
        "receipt": {"message_id": "456", "channel_id": "123"},
    }
    fake_owner.state["status_sequences"][operation.key] = [
        {"id": pending.id, "key": pending.key, "digest": pending.digest, "status": "pending", "receipt": None},
        delivered,
    ]
    before = len(fake_owner.state["requests"])

    result = client.wait(operation.key, timeout_seconds=1.0)

    new_requests = fake_owner.state["requests"][before:]
    assert result.status == "delivered"
    assert result.receipt == {"message_id": "456", "channel_id": "123"}
    assert [item["method"] for item in new_requests] == ["GET", "GET"]
    assert all(item["path"].startswith("/v1/operations/by-key/") for item in new_requests)
    assert not any(item["method"] == "POST" for item in new_requests)


def test_wait_returns_latest_pending_state_at_deadline_without_resubmission(fake_owner, token_file):
    operation = make_operation()
    client = client_for(fake_owner, token_file)
    accepted = client.submit(operation)
    before = len(fake_owner.state["requests"])

    result = client.wait(operation.key, timeout_seconds=0)

    assert result == accepted
    new_requests = fake_owner.state["requests"][before:]
    assert len(new_requests) == 1
    assert new_requests[0]["method"] == "GET"


def test_wait_zero_budget_does_one_immediate_lookup_and_no_poll_sleep(fake_owner, token_file, monkeypatch):
    operation = make_operation()
    client = client_for(fake_owner, token_file)
    accepted = client.submit(operation)
    clock = SimpleNamespace(monotonic=lambda: 12.0, sleep=lambda _delay: pytest.fail("unexpected poll sleep"))
    monkeypatch.setattr(client_module, "time", clock)
    before = len(fake_owner.state["requests"])

    result = client.wait(operation.key, timeout_seconds=0)

    assert result == accepted
    new_requests = fake_owner.state["requests"][before:]
    assert len(new_requests) == 1
    assert new_requests[0]["method"] == "GET"


def test_wait_caps_each_poll_request_to_remaining_budget_and_stops_at_deadline(
    fake_owner, token_file, monkeypatch
):
    operation = make_operation()
    client = client_for(fake_owner, token_file, timeout_seconds=10)
    client.submit(operation)
    current_time = [12.0]
    clock = SimpleNamespace(
        monotonic=lambda: current_time[0],
        sleep=lambda delay: current_time.__setitem__(0, current_time[0] + delay),
    )
    monkeypatch.setattr(client_module, "time", clock)
    monkeypatch.setattr(client_module, "POLL_INTERVAL_SECONDS", 0.02)
    request_timeouts = []
    original_request = client._request

    def record_request_timeout(method, path, **kwargs):
        if method == "GET":
            request_timeouts.append(kwargs.get("timeout_seconds", client.timeout_seconds))
        return original_request(method, path, **kwargs)

    monkeypatch.setattr(client, "_request", record_request_timeout)
    before = len(fake_owner.state["requests"])

    result = client.wait(operation.key, timeout_seconds=0.05)

    assert result.status == "pending"
    assert request_timeouts[0] == 10
    poll_timeouts = request_timeouts[1:]
    assert len(poll_timeouts) == 2
    assert poll_timeouts == pytest.approx([0.03, 0.01])
    assert all(0 < timeout <= 0.05 for timeout in poll_timeouts)
    new_requests = fake_owner.state["requests"][before:]
    assert len(new_requests) == len(request_timeouts)
    assert all(item["method"] == "GET" for item in new_requests)


def test_status_after_lost_submit_response_allows_same_key_same_payload_resubmit(fake_owner, token_file):
    operation = make_operation()
    client = client_for(fake_owner, token_file)
    fake_owner.state["drop_after_accept"] = True

    with pytest.raises(DeliveryClientError) as caught:
        client.submit(operation)
    assert caught.value.category in {"network_error", "timeout"}

    recovered = client.status(operation.key)
    retried = client.submit(operation)

    assert recovered is not None
    assert retried.id == recovered.id
    assert retried.digest == operation.digest
    submit_requests = [item for item in fake_owner.state["requests"] if item["path"] == "/v1/operations"]
    assert len(submit_requests) == 2
    assert fake_owner.state["accepted"][operation.key]["id"] == retried.id


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "unauthorized"),
        (409, "conflict"),
        (429, "rate_limited"),
        (500, "server_error"),
        (503, "server_error"),
    ],
)
def test_http_error_categories_are_stable_and_sanitized(fake_owner, token_file, status, category):
    fake_owner.respond(
        status,
        b"opaque private response body with test-client-token and /private/media/chart.png",
        headers={"X-Private-Header": "header-secret", "Retry-After": "9876"},
        method="POST",
        path="/v1/operations",
    )

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).submit(make_operation())

    message = str(caught.value)
    assert caught.value.category == category
    assert "test-client-token" not in message
    assert "header-secret" not in message
    assert "9876" not in message
    assert "private response body" not in message
    assert "/private/media/chart.png" not in message


def test_malformed_json_response_has_sanitized_category(fake_owner, token_file):
    fake_owner.respond(202, b"invalid JSON containing secret-value", method="POST", path="/v1/operations")

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).submit(make_operation())

    assert caught.value.category == "invalid_response"
    assert "secret-value" not in str(caught.value)


def test_redirect_is_not_followed_to_another_loopback_host(fake_owner, token_file, fake_capture_server):
    capture_url, capture_state = fake_capture_server
    fake_owner.respond(
        307,
        b"redirect body must stay private",
        headers={"Location": f"{capture_url}/capture"},
        method="POST",
        path="/v1/operations",
    )

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).submit(make_operation())

    assert caught.value.category == "redirect"
    assert capture_state["requests"] == []


def test_adoption_requires_separate_admin_token_and_keeps_client_token_for_queries(fake_owner, token_file, admin_token_file):
    operation = OperationIntent(
        key="legacy:pending:1",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
        legacy_nonce="old nonce 25 char",
    )
    client = client_for(fake_owner, token_file, admin_token_file=admin_token_file)

    adopted = client.adopt_pending(operation)
    client.query(DiscordQuery(kind="forum_channel_read", channel_id="123"))

    adoption = fake_owner.state["last_adoption"]
    assert adopted.status == "pending_reconciliation"
    assert adoption["action"] == "pending"
    assert adoption["operation"]["legacy_nonce"] == "old nonce 25 char"
    assert adoption["payload_digest"] == operation.digest
    assert fake_owner.state["last_adoption_token"] == "Bearer test-admin-token"
    assert fake_owner.state["requests"][-1]["headers"]["Authorization"] == "Bearer test-client-token"


def test_pending_adoption_without_admin_token_fails_before_request(fake_owner, token_file, admin_token_file):
    operation = OperationIntent(
        key="legacy:pending:2",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
    )

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).adopt_pending(operation)

    assert caught.value.category == "admin_credentials_required"
    assert fake_owner.state["requests"] == []


def test_legacy_nonce_cannot_be_submitted_as_a_new_operation(fake_owner, token_file):
    operation = OperationIntent(
        key="legacy:pending:3",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
        legacy_nonce="old nonce",
    )

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).submit(operation)

    assert caught.value.category == "invalid_operation"
    assert fake_owner.state["requests"] == []


def test_completed_adoption_uses_old_receipt_and_admin_token(fake_owner, token_file, admin_token_file):
    operation = make_operation(key="legacy:completed:1")
    client = client_for(fake_owner, token_file, admin_token_file=admin_token_file)

    adopted = client.adopt_completed(operation, {"channel_id": "123", "message_id": "456"})

    assert adopted.status == "delivered"
    assert fake_owner.state["last_adoption"]["action"] == "completed"
    assert fake_owner.state["last_adoption"]["receipt"] == {"channel_id": "123", "message_id": "456"}
    assert fake_owner.state["last_adoption_token"] == "Bearer test-admin-token"


def test_pending_media_adoption_preserves_ordered_bytes_metadata_and_admin_auth(
    fake_owner, token_file, admin_token_file
):
    attachments = (
        Attachment("first.png", "image/png", b"FIRST\x00PNG"),
        Attachment("second.jpg", "image/jpeg", b"SECOND\xffJPEG"),
    )
    operation = OperationIntent(
        key="legacy:pending:media",
        kind="thread_message_create",
        ordering_key="thread:123",
        target={"thread_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        attachments=attachments,
        reconcile_before_first_create=True,
        legacy_nonce="old message nonce",
    )

    adopted = client_for(fake_owner, token_file, admin_token_file=admin_token_file).adopt_pending(operation)

    request = fake_owner.state["requests"][-1]
    body = request["body"]
    assert adopted.status == "pending_reconciliation"
    assert request["headers"]["Authorization"] == "Bearer test-admin-token"
    assert request["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="adoption"' in body
    assert body.index(b'filename="first.png"') < body.index(b'filename="second.jpg"')
    parsed = fake_owner.state["last_adoption_attachments"]
    assert [(item.filename, item.mime_type, item.data) for item in parsed] == [
        ("first.png", "image/png", b"FIRST\x00PNG"),
        ("second.jpg", "image/jpeg", b"SECOND\xffJPEG"),
    ]
    assert fake_owner.state["last_adoption"]["payload_digest"] == operation.digest
    assert fake_owner.state["last_adoption"]["operation"]["legacy_nonce"] == "old message nonce"


def test_pending_adoption_carries_observed_boundary_outside_intent_digest(
    fake_owner, token_file, admin_token_file
):
    operation = OperationIntent(
        key="legacy:pending:boundary",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
    )
    preflight = {"boundary_observed": True, "boundary": "987654321"}

    adopted = client_for(fake_owner, token_file, admin_token_file=admin_token_file).adopt_pending(
        operation, preflight=preflight
    )

    assert adopted.status == "pending_reconciliation"
    assert fake_owner.state["last_adoption"]["preflight"] == preflight
    assert fake_owner.state["last_adoption"]["payload_digest"] == operation.digest


@pytest.mark.parametrize("preflight", [
    {"boundary_observed": False, "boundary": "987654321"},
    {"boundary_observed": True, "boundary": "not-a-snowflake"},
    {"boundary_observed": True, "boundary": 987654321},
    {"boundary_observed": True},
    {"boundary_observed": True, "boundary": None, "extra": "field"},
])
def test_pending_adoption_rejects_invalid_preflight_without_request(
    fake_owner, token_file, admin_token_file, preflight
):
    operation = OperationIntent(
        key="legacy:pending:bad-boundary",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
    )

    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file, admin_token_file=admin_token_file).adopt_pending(
            operation, preflight=preflight
        )

    assert caught.value.category == "invalid_operation"
    assert fake_owner.state["requests"] == []


def test_completed_media_adoption_preserves_ordered_bytes_metadata_and_old_receipt(
    fake_owner, token_file, admin_token_file
):
    attachments = (
        Attachment("chart.webp", "image/webp", b"CHART-WEBP"),
        Attachment("source.png", "image/png", b"SOURCE-PNG"),
    )
    operation = OperationIntent(
        key="legacy:completed:media",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        attachments=attachments,
    )
    old_receipt = {"channel_id": "123", "message_id": "456"}

    adopted = client_for(fake_owner, token_file, admin_token_file=admin_token_file).adopt_completed(
        operation, old_receipt
    )

    request = fake_owner.state["requests"][-1]
    assert adopted.status == "delivered"
    assert adopted.receipt == old_receipt
    assert request["headers"]["Authorization"] == "Bearer test-admin-token"
    assert request["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert request["body"].index(b'filename="chart.webp"') < request["body"].index(b'filename="source.png"')
    parsed = fake_owner.state["last_adoption_attachments"]
    assert [(item.filename, item.mime_type, item.data) for item in parsed] == [
        ("chart.webp", "image/webp", b"CHART-WEBP"),
        ("source.png", "image/png", b"SOURCE-PNG"),
    ]
    assert fake_owner.state["last_adoption"]["receipt"] == old_receipt


def test_adoption_requires_preflight_for_pending_import(fake_owner, token_file, admin_token_file):
    operation = make_operation(key="legacy:pending:no-preflight")
    client = client_for(fake_owner, token_file, admin_token_file=admin_token_file)

    with pytest.raises(DeliveryClientError) as caught:
        client.adopt_pending(operation)

    assert caught.value.category == "invalid_operation"
    assert fake_owner.state["requests"] == []


def test_client_rejects_non_loopback_base_url_before_reading_or_sending_secret(token_file):
    with pytest.raises(DeliveryClientError) as caught:
        DeliveryClient("https://example.invalid", token_file)

    assert caught.value.category == "invalid_configuration"
    assert "example.invalid" not in str(caught.value)
    assert "test-client-token" not in str(caught.value)


def test_wait_rejects_negative_timeout(fake_owner, token_file):
    with pytest.raises(DeliveryClientError) as caught:
        client_for(fake_owner, token_file).wait("news:event-1:text", timeout_seconds=-0.1)

    assert caught.value.category == "invalid_timeout"
    assert fake_owner.state["requests"] == []


def test_handoff_summary_contains_hashes_and_counts_but_no_payload():
    operation = make_operation(content="private message body")
    source = b"legacy-state-snapshot"

    summary = handoff_summary(hash_source_bytes(source), [operation])

    assert summary == {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "operation_count": 1,
        "operation_key_sha256": [operation_key_digest(operation.key)],
        "payload_sha256": [operation.digest],
    }
    assert "private message body" not in repr(summary)
    assert operation.key not in repr(summary)


@pytest.mark.parametrize(
    ("apply", "environment"),
    [
        (False, {"BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY": "1"}),
        (True, {}),
        (True, {"BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY": "true"}),
    ],
)
def test_handoff_apply_requires_both_flag_and_exact_environment_gate(apply, environment):
    with pytest.raises(HandoffError):
        require_apply_authorization(apply=apply, environment=environment)


def test_handoff_apply_gate_accepts_explicit_flag_and_environment():
    require_apply_authorization(
        apply=True,
        environment={"BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY": "1"},
    )


def test_private_handoff_backup_is_mode_0600_and_never_overwritten(tmp_path):
    backup = tmp_path / "private" / "snapshot.bin"

    write_private_backup(b"legacy state", backup)

    assert backup.read_bytes() == b"legacy state"
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(HandoffError):
        write_private_backup(b"replacement", backup)
    assert backup.read_bytes() == b"legacy state"


def test_import_acknowledges_only_after_matching_durable_adoption(fake_owner, token_file, admin_token_file):
    operation = OperationIntent(
        key="legacy:pending:ack-order",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
    )
    client = client_for(fake_owner, token_file, admin_token_file=admin_token_file)
    observed: list[str] = []

    accepted = import_handoff_item(
        client,
        operation,
        receipt=None,
        acknowledge=lambda receipt: observed.append(receipt.key),
    )

    assert accepted.key == operation.key
    assert accepted.digest == operation.digest
    assert observed == [operation.key]
    assert fake_owner.state["last_adoption"]["operation"]["key"] == operation.key


def test_import_does_not_acknowledge_when_service_rejects_before_acceptance(fake_owner, token_file):
    operation = OperationIntent(
        key="legacy:pending:no-admin",
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": "old delivery", "allowed_mentions": {"parse": []}},
        reconcile_before_first_create=True,
    )
    observed: list[str] = []

    with pytest.raises(HandoffError):
        import_handoff_item(
            client_for(fake_owner, token_file),
            operation,
            receipt=None,
            acknowledge=lambda receipt: observed.append(receipt.key),
        )

    assert observed == []
    assert fake_owner.state["requests"] == []
