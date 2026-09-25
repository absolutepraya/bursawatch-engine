from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import replace
from pathlib import Path
import re
import sys
from typing import Any

try:
    from bursawatch_discord_delivery import Attachment, DeliveryClient, DiscordQuery, OperationIntent, OperationReceipt
    from bursawatch_discord_delivery.client import DeliveryClientError
except ModuleNotFoundError:
    _ROOT = Path(__file__).resolve().parents[2]
    _SHARED_BIN = _ROOT / "lib-bursawatch-discord-delivery" / "bin"
    if not _SHARED_BIN.is_dir():
        _SHARED_BIN = Path.home() / ".agents/skills/lib-bursawatch-discord-delivery/bin"
    if str(_SHARED_BIN) not in sys.path:
        sys.path.insert(0, str(_SHARED_BIN))
    from bursawatch_discord_delivery import Attachment, DeliveryClient, DiscordQuery, OperationIntent, OperationReceipt
    from bursawatch_discord_delivery.client import DeliveryClientError


BOARD_URL = "https://discord.com/channels/940285152335110204/1548273399069933720"
BOARD_MENTION = "<#1548273399069933720>"
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
DELIVERY_OPERATION_PREFIX = "bursawatch-wa-channel-watch"
NON_TERMINAL_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


class DiscordRetryAfter(RuntimeError):
    """Compatibility exception for the watcher's bounded retry handling."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Delivery Owner rate limited for {retry_after:g} seconds")


class DeliveryOwnerPending(RuntimeError):
    """The Delivery Owner durably accepted this leg but has not completed it."""


class DiscordDeliveryError(RuntimeError):
    """A sanitized Delivery Owner failure."""


def nonce(event_key: str, leg: str) -> str:
    return hashlib.sha256(f"whatsapp-channel-watch:{event_key}:{leg}".encode()).hexdigest()[:24]


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


def _message_operation(
    content: str,
    channel_id: str,
    nonce_value: str,
    *,
    attachment: Attachment | None = None,
) -> OperationIntent:
    if not isinstance(content, str) or len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    return OperationIntent(
        key=operation_key_for_nonce(nonce_value),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=() if attachment is None else (attachment,),
    )


def _edit_operation(channel_id: str, message_id: str, content: str) -> OperationIntent:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    identity = hashlib.sha256(f"{channel_id}:{message_id}:{content}".encode("utf-8")).hexdigest()
    return OperationIntent(
        key=f"{DELIVERY_OPERATION_PREFIX}:edit:{identity}",
        kind="channel_message_edit",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id, "message_id": message_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
    )


def _receipt_for_operation(
    operation: OperationIntent,
    owner: object,
    *,
    legacy_nonce: str | None = None,
) -> OperationReceipt:
    receipt = owner.status(operation.key)  # type: ignore[attr-defined]
    expected_digest = operation.digest
    if receipt is not None and isinstance(receipt, OperationReceipt) and receipt.digest != operation.digest:
        if legacy_nonce is None:
            raise DeliveryClientError("conflict")
        imported = replace(
            operation,
            reconcile_before_first_create=True,
            legacy_nonce=legacy_nonce,
        )
        if receipt.digest != imported.digest:
            raise DeliveryClientError("conflict")
        expected_digest = imported.digest
    if receipt is None:
        receipt = owner.submit(operation)  # type: ignore[attr-defined]
    if (
        not isinstance(receipt, OperationReceipt)
        or receipt.key != operation.key
        or receipt.digest != expected_digest
    ):
        raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_STATUSES:
        receipt = owner.wait(operation.key, 0)  # type: ignore[attr-defined]
        if (
            not isinstance(receipt, OperationReceipt)
            or receipt.key != operation.key
            or receipt.digest != expected_digest
        ):
            raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_STATUSES:
        raise DeliveryOwnerPending("Delivery Owner accepted pending work")
    if receipt.status != "delivered":
        raise DiscordDeliveryError("Delivery Owner did not complete the operation")
    return receipt


def _message_id(receipt: OperationReceipt, channel_id: str) -> str:
    value = receipt.receipt
    if not isinstance(value, dict) or value.get("channel_id") != channel_id:
        raise DeliveryClientError("invalid_response")
    message_id = value.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise DeliveryClientError("invalid_response")
    return message_id


def post_text(
    content: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    client: object | None = None,
) -> str | None:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run"
    operation = _message_operation(content, channel_id, nonce_value)
    owner = client if client is not None else delivery_client_from_environment()
    receipt = _receipt_for_operation(operation, owner, legacy_nonce=nonce_value)
    return _message_id(receipt, channel_id)


def media_filename(kind: str, mime: str | None, index: int = 0, *, prefix: str = "whatsapp-channel") -> str:
    extension = mimetypes.guess_extension(mime or "") if mime else None
    if extension == ".jpe":
        extension = ".jpg"
    if not extension:
        extension = {"image": ".jpg", "video": ".mp4"}.get(kind, ".bin")
    return f"{prefix}-{index}{extension}"


def post_media(
    path: Path,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    filename: str | None = None,
    mime: str | None = None,
    client: object | None = None,
) -> str | None:
    if not path.is_file():
        raise FileNotFoundError(f"source media is unavailable: {path.name}")
    upload_name = filename or path.name
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {upload_name}")
        return "dry-run"
    content = path.read_bytes()
    attachment = Attachment(
        upload_name,
        mime or mimetypes.guess_type(upload_name)[0] or "application/octet-stream",
        content,
    )
    operation = _message_operation("", channel_id, nonce_value, attachment=attachment)
    owner = client if client is not None else delivery_client_from_environment()
    receipt = _receipt_for_operation(operation, owner, legacy_nonce=nonce_value)
    return _message_id(receipt, channel_id)


def _query(owner: object, query: DiscordQuery) -> object:
    return owner.query(query)  # type: ignore[attr-defined]


def list_messages(
    channel_id: str,
    *,
    limit: int = 100,
    before: str | None = None,
    client: object | None = None,
) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("Discord message limit must be between 1 and 100")
    owner = client if client is not None else delivery_client_from_environment()
    result = _query(
        owner,
        DiscordQuery(kind="channel_messages", channel_id=channel_id, before=before, limit=limit),
    )
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)][:limit]


def get_message(
    channel_id: str,
    message_id: str,
    *,
    client: object | None = None,
) -> dict[str, object] | None:
    if not message_id.isdigit():
        raise ValueError("Discord message ID is invalid")
    owner = client if client is not None else delivery_client_from_environment()
    # Discord message IDs are snowflakes. Asking for the single newest item
    # before the next integer gives a bounded query that can include only this
    # exact ID; the returned item is still checked explicitly.
    result = _query(
        owner,
        DiscordQuery(
            kind="channel_messages",
            channel_id=channel_id,
            before=str(int(message_id) + 1),
            limit=1,
        ),
    )
    if not isinstance(result, list):
        return None
    for item in result:
        if isinstance(item, dict) and item.get("id") == message_id:
            return item
    return None


def _replace_board_topic_link(content: str, board_url: str) -> str:
    if not board_url.startswith("https://discord.com/channels/"):
        raise ValueError("board_url must be a Discord channel or topic URL")
    replacement = f"**Board:** {board_url}"
    legacy = {f"**Board:** {BOARD_MENTION}", f"**Board:** {BOARD_URL}", f"**Board:** <{BOARD_URL}>"}
    lines = content.split("\n")
    changed = False
    for index, line in enumerate(lines):
        if line.strip() in legacy:
            lines[index] = replacement
            changed = True
    return "\n".join(lines) if changed else content


def edit_board_link(
    channel_id: str,
    message_ids: list[str] | tuple[str, ...],
    board_url: str | None,
    dry_run: bool,
    nonce_value: str,
    *,
    client: object | None = None,
) -> bool:
    if not board_url or not message_ids:
        return True
    if dry_run:
        for message_id in message_ids:
            print(f"[dry-run] Discord board link {channel_id}/{message_id} -> {board_url} ({nonce_value})")
        return True
    owner = client if client is not None else delivery_client_from_environment()
    for message_id in message_ids:
        current = get_message(channel_id, str(message_id), client=owner)
        content = current.get("content") if current else None
        if not isinstance(content, str):
            return False
        updated = _replace_board_topic_link(content, board_url)
        if updated == content:
            continue
        operation = _edit_operation(channel_id, str(message_id), updated)
        receipt = _receipt_for_operation(operation, owner)
        if receipt.receipt is None or receipt.receipt.get("message_id") != str(message_id):
            raise DeliveryClientError("invalid_response")
    return True


def edit_message_content(
    channel_id: str,
    message_id: str,
    content: str,
    *,
    dry_run: bool = False,
    client: object | None = None,
) -> bool:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord edit {channel_id}/{message_id}: {content}")
        return True
    owner = client if client is not None else delivery_client_from_environment()
    current = get_message(channel_id, message_id, client=owner)
    if current is None:
        return False
    operation = _edit_operation(channel_id, message_id, content)
    receipt = _receipt_for_operation(operation, owner)
    return receipt.receipt is not None and receipt.receipt.get("message_id") == message_id
