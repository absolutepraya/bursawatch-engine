from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import Attachment, DeliveryClient, OperationIntent, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError


DISCORD_TIMEOUT_SECONDS = 30
DISCORD_LIMIT = 2_000
MAX_MEDIA_PATH_CHARACTERS = 4_096
MAX_MEDIA_BYTES = 25 * 1024 * 1024
RETRY_FALLBACK_SECONDS = 60.0
RETRY_MAX_SECONDS = 15 * 60.0
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
DELIVERY_OPERATION_PREFIX = "bursawatch-ig-account-watch"
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})

_ALLOWED_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}


class DiscordDeliveryError(RuntimeError):
    """A Discord delivery failure with no provider body or secret details."""


class DiscordRetryAfter(DiscordDeliveryError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__("Discord rate limited")


class DeliveryOwnerPending(DiscordDeliveryError):
    """The Delivery Owner accepted an operation whose Discord result is pending."""


def discord_length(value: str) -> int:
    """Return Discord's UTF-16 code-unit length for a text value."""
    if not isinstance(value, str):
        raise TypeError("Discord content must be text")
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


def nonce(event_key: str, leg: str) -> str:
    """Return one deterministic nonce for one durable Instagram delivery leg."""
    if not isinstance(event_key, str) or not isinstance(leg, str):
        raise ValueError("Discord nonce inputs are invalid")
    digest = hashlib.sha256(f"instagram-post-watch:{event_key}:{leg}".encode("utf-8")).hexdigest()[:24]
    return digest


def operation_key(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("delivery identity requires a nonempty event and leg")
    digest = hashlib.sha256(f"instagram-post-watch:{event_key}:{leg}".encode("utf-8")).hexdigest()
    return f"{DELIVERY_OPERATION_PREFIX}:{digest}"


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
    attachments: tuple[Attachment, ...] = (),
) -> OperationIntent:
    if discord_length(content) > DISCORD_LIMIT:
        raise ValueError("Discord text content exceeds 2,000 characters")
    return OperationIntent(
        key=operation_key(event_key, leg),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=attachments,
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
            raise DeliveryClientError("conflict")
        from dataclasses import replace

        imported = replace(operation, reconcile_before_first_create=True, legacy_nonce=legacy_nonce)
        if receipt.digest != imported.digest:
            raise DeliveryClientError("conflict")
        expected_digest = imported.digest
    if not existing:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
        raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = client.wait(operation.key, 0)  # type: ignore[attr-defined]
        if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
            raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        raise DeliveryOwnerPending("Delivery Owner accepted pending work")
    if receipt.status != "delivered":
        raise DiscordDeliveryError(f"Delivery Owner operation is {receipt.status}")
    return receipt


def _delivered_message_id(receipt: OperationReceipt, channel_id: str) -> str:
    value = receipt.receipt
    if not isinstance(value, dict) or value.get("channel_id") not in (None, channel_id):
        raise DiscordDeliveryError("Delivery Owner returned an invalid message receipt")
    message_id = value.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise DiscordDeliveryError("Delivery Owner returned an invalid message receipt")
    return message_id


def _submit_message(
    operation: OperationIntent,
    channel_id: str,
    *,
    client: object | None,
    legacy_nonce: str | None = None,
) -> str:
    owner = client if client is not None else delivery_client_from_environment()
    try:
        receipt = _submit_or_lookup(operation, owner, legacy_nonce=legacy_nonce)
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRetryAfter(RETRY_FALLBACK_SECONDS) from None
        raise DiscordDeliveryError("Delivery Owner request failed") from None
    return _delivered_message_id(receipt, channel_id)


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
    if not isinstance(content, str) or discord_length(content) > DISCORD_LIMIT:
        raise ValueError("Discord text content exceeds 2,000 characters")
    if dry_run:
        print(f"[dry-run] Discord text channel={channel_id} nonce={nonce_value}")
        return None
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
    return _submit_message(operation, channel_id, client=client, legacy_nonce=legacy)


def _lstat_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise ValueError("Discord media path is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("Discord media path is invalid")


def _validated_media_root() -> Path:
    configured_root = os.environ.get("INSTAGRAM_POST_WATCH_MEDIA_ROOT")
    if not configured_root:
        raise ValueError("Discord media root is unavailable")
    root = Path(configured_root)
    if (
        not root.is_absolute()
        or root == Path(root.anchor)
        or len(configured_root) > MAX_MEDIA_PATH_CHARACTERS
        or "\x00" in configured_root
        or "://" in configured_root
        or any(part in {".", ".."} for part in configured_root.split(os.sep))
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise ValueError("Discord media root is invalid")
    try:
        _lstat_components(root)
        mode = os.lstat(root).st_mode
        if not stat.S_ISDIR(mode):
            raise ValueError("Discord media root is invalid")
        return root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Discord media root is invalid") from exc


def _validated_media_path(path: Path) -> tuple[Path, str]:
    root = _validated_media_root()
    if not isinstance(path, Path):
        path = Path(path)
    path_text = str(path)
    if (
        not path.is_absolute()
        or not path_text
        or len(path_text) > MAX_MEDIA_PATH_CHARACTERS
        or "\x00" in path_text
        or "://" in path_text
        or any(part in {".", ".."} for part in path_text.split(os.sep))
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("Discord media path is invalid")
    _lstat_components(path)
    try:
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("Discord media path is invalid")
        resolved = path.resolve(strict=True)
        size = resolved.stat().st_size
    except (OSError, RuntimeError) as exc:
        raise ValueError("Discord media path is unavailable") from exc
    if size <= 0 or size > MAX_MEDIA_BYTES:
        raise ValueError("Discord media size is invalid")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Discord media path is outside the watcher media root") from exc

    media_type = mimetypes.guess_type(resolved.name)[0]
    if media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("Discord media type is unsupported")
    return resolved, media_type


def _temporary_upload_copy(source: Path) -> Path:
    temporary: Path | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".instagram-post-watch-upload-",
            suffix=source.suffix,
            dir=source.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        with handle, source.open("rb") as original:
            shutil.copyfileobj(original, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except (OSError, ValueError) as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise DiscordDeliveryError("Discord media staging failed") from exc


def read_media_attachment(path: Path) -> Attachment:
    """Validate and privately stage one watcher-owned asset before reading bytes."""
    source, content_type = _validated_media_path(Path(path))
    temporary: Path | None = None
    try:
        temporary = _temporary_upload_copy(source)
        return Attachment(source.name, content_type, temporary.read_bytes())
    except DiscordDeliveryError:
        raise
    except (OSError, ValueError) as exc:
        raise DiscordDeliveryError("Discord media staging failed") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def post_media(
    path: Path,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    event_key: str | None = None,
    operation_leg: str = "media",
    client: object | None = None,
) -> str | None:
    source, content_type = _validated_media_path(path)
    if dry_run:
        print(f"[dry-run] Discord media channel={channel_id} nonce={nonce_value}")
        return None

    try:
        attachment = read_media_attachment(source)
        identity = event_key if event_key is not None else nonce_value
        operation = _message_operation("", channel_id, identity, operation_leg, attachments=(attachment,))
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
        return _submit_message(operation, channel_id, client=client, legacy_nonce=legacy)
    except DiscordDeliveryError:
        raise
    except (OSError, ValueError) as exc:
        raise DiscordDeliveryError("Discord media upload failed") from exc
