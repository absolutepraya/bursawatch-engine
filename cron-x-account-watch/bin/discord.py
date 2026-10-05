from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
import re
import sys

import requests

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import (
    DELIVERY_RECEIPT_WAIT_SECONDS,
    Attachment,
    DeliveryClient,
    DiscordQuery,
    OperationIntent,
    OperationReceipt,
)
from bursawatch_discord_delivery.client import DeliveryClientError
from swing_format import replace_board_topic_link


DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
DELIVERY_OPERATION_PREFIX = "bursawatch-x-account-watch"
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


class DiscordRetryAfter(RuntimeError):
    """Compatibility error for local retry scheduling after rejected acceptance."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Delivery Owner rate limited for {retry_after:g} seconds")


class DeliveryOwnerPending(RuntimeError):
    """The Delivery Owner accepted an operation whose Discord result is pending."""


class DeliveryOwnerError(RuntimeError):
    """A sanitized Delivery Owner request failure."""


class MediaUnavailable(RuntimeError):
    """A source media URL returned a confirmed permanent absence."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"media unavailable HTTP {status_code}")


def nonce(event_key: str, leg: str) -> str:
    """Retain the stable, bounded nonce used by the former sender for handoff."""
    return hashlib.sha256(f"x-post-watch:{event_key}:{leg}".encode()).hexdigest()[:24]


def operation_key(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("delivery identity requires a nonempty event and leg")
    return f"{DELIVERY_OPERATION_PREFIX}:{hashlib.sha256(f'{event_key}:{leg}'.encode()).hexdigest()}"


def operation_key_for_nonce(nonce_value: str) -> str:
    if not isinstance(nonce_value, str) or not re.fullmatch(r"[0-9a-f]{24}", nonce_value):
        raise ValueError("delivery nonce is invalid")
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


def _message_operation(
    content: str,
    channel_id: str,
    event_key: str,
    leg: str,
    *,
    attachment: Attachment | None = None,
) -> OperationIntent:
    if len(content) > 2000:
        raise ValueError("Discord text exceeds 2000 characters")
    return OperationIntent(
        key=operation_key(event_key, leg),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=() if attachment is None else (attachment,),
    )


def _submit_or_lookup(
    operation: OperationIntent,
    client: object,
    *,
    legacy_nonce: str | None = None,
) -> OperationReceipt:
    receipt = client.status(operation.key)  # type: ignore[attr-defined]
    existing = receipt is not None
    expected_digest = operation.digest
    if existing and isinstance(receipt, OperationReceipt) and receipt.digest != operation.digest:
        if legacy_nonce is None:
            raise DeliveryOwnerError("Delivery Owner operation identity conflict")
        from dataclasses import replace

        imported = replace(operation, reconcile_before_first_create=True, legacy_nonce=legacy_nonce)
        if receipt.digest != imported.digest:
            raise DeliveryOwnerError("Delivery Owner operation identity conflict")
        expected_digest = imported.digest
    if not existing:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
        raise DeliveryOwnerError("Delivery Owner returned an invalid operation receipt")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = client.wait(operation.key, DELIVERY_RECEIPT_WAIT_SECONDS)  # type: ignore[attr-defined]
        if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
            raise DeliveryOwnerError("Delivery Owner returned an invalid operation receipt")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        raise DeliveryOwnerPending("Delivery Owner accepted pending work")
    if receipt.status != "delivered":
        raise DeliveryOwnerError(f"Delivery Owner operation is {receipt.status}")
    return receipt


def _delivered_message_id(receipt: OperationReceipt, channel_id: str) -> str:
    value = receipt.receipt
    if not isinstance(value, dict) or value.get("channel_id") not in (None, channel_id):
        raise DeliveryOwnerError("Delivery Owner returned an invalid message receipt")
    message_id = value.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise DeliveryOwnerError("Delivery Owner returned an invalid message receipt")
    return message_id


def _submit_message(
    operation: OperationIntent,
    *,
    client: object | None,
    legacy_nonce: str | None = None,
) -> str:
    receipt = _submit_message_receipt(operation, client=client, legacy_nonce=legacy_nonce)
    return _delivered_message_id(receipt, operation.target["channel_id"])


def _submit_message_receipt(
    operation: OperationIntent,
    *,
    client: object | None,
    legacy_nonce: str | None = None,
) -> OperationReceipt:
    owner = client if client is not None else delivery_client_from_environment()
    try:
        receipt = _submit_or_lookup(operation, owner, legacy_nonce=legacy_nonce)
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRetryAfter(60) from None
        raise DeliveryOwnerError("Delivery Owner request failed") from None
    return receipt


def _receipt_result(
    operation: OperationIntent,
    receipt: OperationReceipt,
) -> tuple[str, OperationIntent, OperationReceipt]:
    return _delivered_message_id(receipt, operation.target["channel_id"]), operation, receipt


def post_text(
    content: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    event_key: str | None = None,
    operation_leg: str = "message",
    client: object | None = None,
) -> str | None:
    if len(content) > 2000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run"
    identity = event_key if event_key is not None else nonce_value
    operation = _message_operation(content, channel_id, identity, operation_leg)
    if event_key is None:
        operation = OperationIntent(
            key=operation_key_for_nonce(nonce_value),
            kind=operation.kind,
            ordering_key=operation.ordering_key,
            target=operation.target,
            payload=operation.payload,
            attachments=operation.attachments,
        )
    legacy = nonce(event_key, operation_leg) if event_key is not None else nonce_value
    return _submit_message(operation, client=client, legacy_nonce=legacy)


def post_text_with_receipt(
    content: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    event_key: str | None = None,
    operation_leg: str = "message",
    client: object | None = None,
) -> tuple[str | None, OperationIntent | None, OperationReceipt | None]:
    """Create one message and return the exact Delivery Owner receipt."""
    if len(content) > 2000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run", None, None
    identity = event_key if event_key is not None else nonce_value
    operation = _message_operation(content, channel_id, identity, operation_leg)
    if event_key is None:
        operation = OperationIntent(
            key=operation_key_for_nonce(nonce_value),
            kind=operation.kind,
            ordering_key=operation.ordering_key,
            target=operation.target,
            payload=operation.payload,
            attachments=operation.attachments,
        )
    legacy = nonce(event_key, operation_leg) if event_key is not None else nonce_value
    return _receipt_result(operation, _submit_message_receipt(operation, client=client, legacy_nonce=legacy))


def _read_channel_message_content(client: object, channel_id: str, message_id: str) -> str | None:
    try:
        target_id = int(message_id)
    except (TypeError, ValueError):
        return None
    cursor = str(target_id + 1)
    previous_cursor: str | None = None
    for _ in range(100):
        result = client.query(  # type: ignore[attr-defined]
            DiscordQuery(kind="channel_messages", channel_id=channel_id, before=cursor, limit=100)
        )
        messages = result.get("messages") if isinstance(result, dict) else result
        if not isinstance(messages, list) or not messages:
            return None
        ids: list[int] = []
        for item in messages:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isdigit():
                return None
            ids.append(int(item["id"]))
            if item["id"] == message_id:
                content = item.get("content")
                return content if isinstance(content, str) else None
        oldest = min(ids)
        if oldest <= target_id or previous_cursor == str(oldest):
            return None
        previous_cursor, cursor = cursor, str(oldest)
    return None


def edit_board_links(
    channel_id: str,
    message_ids: object,
    board_url: object,
    dry_run: bool,
    *,
    event_key: str = "x-board-link",
    client: object | None = None,
) -> bool:
    """Read and patch existing All Swing messages through typed owner calls."""
    if not isinstance(board_url, str) or not board_url:
        return True
    if not isinstance(message_ids, list):
        return False
    if dry_run:
        print(f"[dry-run] Discord board links {channel_id} -> {board_url}")
        return True
    owner = client if client is not None else delivery_client_from_environment()
    for index, message_id in enumerate(message_ids):
        if not isinstance(message_id, str) or not message_id.isdigit():
            return False
        try:
            current = _read_channel_message_content(owner, channel_id, message_id)
            if current is None:
                return False
            updated = replace_board_topic_link(current, board_url)
            if updated == current:
                continue
            operation = OperationIntent(
                key=operation_key(event_key, f"board-link:{index}"),
                kind="channel_message_edit",
                ordering_key=f"channel:{channel_id}",
                target={"channel_id": channel_id, "message_id": message_id},
                payload={"content": updated, "allowed_mentions": {"parse": []}},
            )
            _submit_message(operation, client=owner)
        except DeliveryOwnerPending:
            raise
        except DeliveryClientError as error:
            if error.category == "rate_limited":
                raise DiscordRetryAfter(60) from None
            return False
        except DeliveryOwnerError:
            return False
    return True


def post_media(
    url: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    directory: Path,
    *,
    event_key: str | None = None,
    operation_leg: str = "media",
    client: object | None = None,
    source_reference: dict | None = None,
) -> str | None:
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {url}")
        return "dry-run"
    from source_media import reference_id
    ref = reference_id(url)
    if ref is None:
        # Legacy source retrieval stays available for already queued events.
        attachment = download_source_attachment(url, nonce_value)
    else:
        attachment = attachment_from_source_reference(ref, source_reference, nonce_value)
    identity = event_key if event_key is not None else nonce_value
    operation = _message_operation("", channel_id, identity, operation_leg, attachment=attachment)
    if event_key is None:
        operation = OperationIntent(
            key=operation_key_for_nonce(nonce_value),
            kind=operation.kind,
            ordering_key=operation.ordering_key,
            target=operation.target,
            payload=operation.payload,
            attachments=operation.attachments,
        )
    legacy = nonce(event_key, operation_leg) if event_key is not None else nonce_value
    return _submit_message(operation, client=client, legacy_nonce=legacy)


def post_media_with_receipt(
    url: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    directory: Path,
    *,
    event_key: str | None = None,
    operation_leg: str = "media",
    client: object | None = None,
    source_reference: dict | None = None,
) -> tuple[str | None, OperationIntent | None, OperationReceipt | None]:
    """Upload one source image and return its exact Delivery Owner receipt."""
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {url}")
        return "dry-run", None, None
    from source_media import reference_id
    ref = reference_id(url)
    if ref is None:
        attachment = download_source_attachment(url, nonce_value)
    else:
        attachment = attachment_from_source_reference(ref, source_reference, nonce_value)
    identity = event_key if event_key is not None else nonce_value
    operation = _message_operation("", channel_id, identity, operation_leg, attachment=attachment)
    if event_key is None:
        operation = OperationIntent(
            key=operation_key_for_nonce(nonce_value),
            kind=operation.kind,
            ordering_key=operation.ordering_key,
            target=operation.target,
            payload=operation.payload,
            attachments=operation.attachments,
        )
    legacy = nonce(event_key, operation_leg) if event_key is not None else nonce_value
    return _receipt_result(operation, _submit_message_receipt(operation, client=client, legacy_nonce=legacy))


def attachment_from_source_reference(ref: str, reference: dict | None, nonce_value: str) -> Attachment:
    from source_media import client_from_environment, verified_download
    if not isinstance(reference, dict) or reference.get("ref") != ref:
        raise DeliveryOwnerError("X media reference metadata is missing")
    data, suffix = verified_download(reference, client_from_environment())
    return Attachment(f"x-post-{nonce_value}{suffix}", reference["content_type"], data)


def download_source_attachment(url: str, nonce_value: str) -> Attachment:
    """Retrieve one X source asset locally for a later owner upload."""
    response = requests.get(url, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        if response.status_code in {404, 410}:
            raise MediaUnavailable(response.status_code) from error
        raise
    content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
    extension = mimetypes.guess_extension(content_type) or ".bin"
    filename = f"x-post-{nonce_value}{extension}"
    return Attachment(filename, content_type, response.content)


def delete_message(
    channel_id: str,
    message_id: str,
    dry_run: bool,
    *,
    event_key: str | None = None,
    client: object | None = None,
) -> None:
    if dry_run:
        print(f"[dry-run] Discord delete {channel_id}/{message_id}")
        return
    identity = event_key if event_key is not None else f"cleanup:{channel_id}:{message_id}"
    operation = OperationIntent(
        key=operation_key(identity, "delete"),
        kind="channel_message_delete",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id, "message_id": message_id},
        payload={},
    )
    _submit_message(operation, client=client)
