from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
import re
import sys

try:
    from bursawatch_discord_delivery import DeliveryClient, OperationIntent, OperationReceipt
    from bursawatch_discord_delivery.client import DeliveryClientError
except ModuleNotFoundError:
    _ROOT = Path(__file__).resolve().parents[2]
    _SHARED_BIN = _ROOT / "lib-bursawatch-discord-delivery" / "bin"
    if not _SHARED_BIN.is_dir():
        _SHARED_BIN = Path.home() / ".agents/skills/lib-bursawatch-discord-delivery/bin"
    if str(_SHARED_BIN) not in sys.path:
        sys.path.insert(0, str(_SHARED_BIN))
    from bursawatch_discord_delivery import DeliveryClient, OperationIntent, OperationReceipt
    from bursawatch_discord_delivery.client import DeliveryClientError


DELIVERY_OWNER_URL = "http://127.0.0.1:9120"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
DELIVERY_OPERATION_PREFIX = "bursawatch-stockbit-snips"
NON_TERMINAL_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


class DiscordRateLimited(RuntimeError):
    """Compatibility error used by existing Stockbit delivery retry state."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Delivery Owner rate limited for {retry_after:g} seconds")


class DeliveryOwnerPending(RuntimeError):
    """The Delivery Owner accepted the item and continues its retry lifecycle."""


def nonce(event_key: str, leg: str) -> str:
    return hashlib.sha256(f"stockbit-snips:{event_key}:{leg}".encode()).hexdigest()[:24]


def operation_key_for_nonce(nonce_value: str) -> str:
    if not isinstance(nonce_value, str) or re.fullmatch(r"[0-9a-f]{24}", nonce_value) is None:
        raise ValueError("Discord nonce is invalid")
    return f"{DELIVERY_OPERATION_PREFIX}:{nonce_value}"


def delivery_client_from_environment(*, include_admin: bool = False) -> DeliveryClient:
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", DELIVERY_OWNER_URL)
    token_path = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / DELIVERY_CLIENT_TOKEN_FILE),
        )
    ).expanduser()
    admin_path = None
    if include_admin:
        configured = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured:
            raise DeliveryClientError("admin_credentials_required")
        admin_path = Path(configured).expanduser()
    return DeliveryClient(base_url, token_path, admin_token_file=admin_path)


def _operation(
    content: str,
    channel_id: str,
    event_key: str,
    leg: str,
) -> tuple[OperationIntent, str]:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2,000 characters")
    nonce_value = nonce(event_key, leg)
    intent = OperationIntent(
        key=operation_key_for_nonce(nonce_value),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
    )
    return intent, nonce_value


def _submit_or_lookup(operation: OperationIntent, client: object, *, legacy_nonce: str) -> OperationReceipt:
    receipt = client.status(operation.key)  # type: ignore[attr-defined]
    expected_digest = operation.digest
    if receipt is not None and isinstance(receipt, OperationReceipt) and receipt.digest != operation.digest:
        adopted = replace(operation, reconcile_before_first_create=True, legacy_nonce=legacy_nonce)
        if receipt.digest != adopted.digest:
            raise DeliveryClientError("conflict")
        expected_digest = adopted.digest
    if receipt is None:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    if (
        not isinstance(receipt, OperationReceipt)
        or receipt.key != operation.key
        or receipt.digest != expected_digest
    ):
        raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_STATUSES:
        receipt = client.wait(operation.key, 0)  # type: ignore[attr-defined]
        if (
            not isinstance(receipt, OperationReceipt)
            or receipt.key != operation.key
            or receipt.digest != expected_digest
        ):
            raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_STATUSES:
        raise DeliveryOwnerPending("Delivery Owner accepted pending work")
    if receipt.status != "delivered":
        raise RuntimeError("Delivery Owner did not complete the Stockbit message")
    return receipt


def post_text(
    content: str,
    channel_id: str,
    *,
    dry_run: bool,
    event_key: str,
    leg: str,
    client: object | None = None,
) -> str | None:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2,000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}:\n{content}")
        return "dry-run"
    operation, nonce_value = _operation(content, channel_id, event_key, leg)
    owner = client if client is not None else delivery_client_from_environment()
    receipt = _submit_or_lookup(operation, owner, legacy_nonce=nonce_value)
    value = receipt.receipt
    if not isinstance(value, dict) or value.get("channel_id") != channel_id:
        raise DeliveryClientError("invalid_response")
    message_id = value.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise DeliveryClientError("invalid_response")
    return message_id
