"""Shared observation contract exercised against the loopback HTTP adapter."""
from __future__ import annotations

import json

import pytest

from bursawatch_discord_delivery import (
    DeliveryClient, DeliveryClientError, OperationIntent, observe_operation,
)


@pytest.fixture
def operation():
    return OperationIntent(
        key="heartbeat:example:20261022", kind="channel_message_create",
        ordering_key="channel:123", target={"channel_id": "123"},
        payload={"content": "Synthetic heartbeat", "allowed_mentions": {"parse": []}},
    )


def document(operation, status="delivered", **changes):
    return {
        "id": "operation-1", "key": operation.key, "digest": operation.digest,
        "status": status, "receipt": {"message_id": "456"} if status == "delivered" else None,
    } | changes


def test_existing_delivery_is_observed_without_submission(fake_owner, token_file, operation):
    fake_owner.state["accepted"][operation.key] = document(operation)
    receipt = observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation)
    assert receipt.status == "delivered"
    assert receipt.receipt == {"message_id": "456"}
    assert [r["method"] for r in fake_owner.state["requests"]] == ["GET"]


def test_absent_operation_submits_once_then_waits_on_same_key(fake_owner, token_file, operation):
    # Initial absence, then wait's immediate lookup observes delivery.
    fake_owner.respond(404, method="GET")
    fake_owner.state["status_sequences"][operation.key] = [document(operation)]
    receipt = observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation)
    assert receipt.status == "delivered"
    requests = fake_owner.state["requests"]
    assert [r["method"] for r in requests] == ["GET", "POST", "GET"]
    assert requests[0]["path"] == requests[2]["path"]
    assert fake_owner.state["accepted"][operation.key]["digest"] == operation.digest


@pytest.mark.parametrize("status", ["pending", "pending_reconciliation", "retrying", "delivering"])
def test_expired_wait_returns_latest_pending_receipt_without_submission(
    fake_owner, token_file, operation, status,
):
    fake_owner.state["accepted"][operation.key] = document(operation, status)
    receipt = observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation, timeout_seconds=0)
    assert receipt.status == status
    assert [r["method"] for r in fake_owner.state["requests"]] == ["GET", "GET"]


@pytest.mark.parametrize("status", ["rejected", "blocked", "ambiguous"])
def test_terminal_failure_is_returned_without_waiting_or_resubmission(fake_owner, token_file, operation, status):
    fake_owner.state["accepted"][operation.key] = document(operation, status)
    receipt = observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation)
    assert receipt.status == status
    assert [r["method"] for r in fake_owner.state["requests"]] == ["GET"]


@pytest.mark.parametrize("stage", ["lookup", "submit", "wait"])
@pytest.mark.parametrize("change", [
    {"key": "another:operation"},
    {"digest": "f" * 64},
    {"receipt": {"message_id": "456", "channel_id": "999"}},
])
def test_mismatched_receipt_fails_closed_at_every_observation_stage(
    fake_owner, token_file, operation, stage, change,
):
    bad = document(operation, **change)
    if stage == "submit":
        fake_owner.respond(404, method="GET")
        fake_owner.respond(202, json.dumps(bad).encode(), method="POST")
    elif stage == "wait":
        fake_owner.state["status_sequences"][operation.key] = [document(operation, "pending"), bad]
    else:
        fake_owner.state["accepted"][operation.key] = bad
    with pytest.raises(DeliveryClientError) as caught:
        observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation, timeout_seconds=0)
    assert caught.value.category == "invalid_response"
    assert str(caught.value) == "delivery service returned an invalid response"
    assert sum(r["method"] == "POST" for r in fake_owner.state["requests"]) == (stage == "submit")


def test_lost_submit_response_is_not_retried_and_next_observation_uses_existing_operation(
    fake_owner, token_file, operation,
):
    client = DeliveryClient(fake_owner.base_url, token_file)
    fake_owner.state["drop_after_accept"] = True
    with pytest.raises(DeliveryClientError) as caught:
        observe_operation(client, operation)
    assert caught.value.category == "network_error"
    fake_owner.state["accepted"][operation.key].update(status="delivered", receipt={"message_id": "456"})
    receipt = observe_operation(client, operation)
    assert receipt.status == "delivered"
    assert [r["method"] for r in fake_owner.state["requests"]] == ["GET", "POST", "GET"]


@pytest.mark.parametrize("stage", ["lookup", "submit", "wait"])
def test_transport_error_propagates_without_another_write(fake_owner, token_file, operation, stage):
    if stage == "submit":
        fake_owner.respond(404, method="GET")
    elif stage == "wait":
        fake_owner.respond(200, json.dumps(document(operation, "pending")).encode(), method="GET")
    fake_owner.respond(503, b'{"detail":"private provider body"}')
    with pytest.raises(DeliveryClientError) as caught:
        observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation)
    assert caught.value.category == "server_error"
    assert "private" not in str(caught.value)
    assert [r["method"] for r in fake_owner.state["requests"]] == (
        ["GET", "POST"] if stage == "submit" else ["GET", "GET"] if stage == "wait" else ["GET"]
    )


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan"), "10"])
def test_invalid_wait_budget_fails_before_any_request(fake_owner, token_file, operation, timeout):
    with pytest.raises(DeliveryClientError) as caught:
        observe_operation(DeliveryClient(fake_owner.base_url, token_file), operation, timeout_seconds=timeout)
    assert caught.value.category == "invalid_timeout"
    assert fake_owner.state["requests"] == []
