"""Typed Delivery Owner adapter for the deterministic Swing Board.

This module contains no Discord REST transport or bot credential. The Board
persists each desired operation in its SQLite outbox, then uses the shared
Delivery Owner client to submit and recover it by one stable operation key.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
import sys
from typing import Any, Mapping

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import (
    DELIVERY_RECEIPT_WAIT_SECONDS,
    Attachment,
    DeliveryClient,
    DeliveryClientError,
    DiscordQuery,
    OperationIntent,
    OperationReceipt,
)


DISCORD_GUILD_ID = "940285152335110204"
FORUM_CHANNEL_ID = "1548273399069933720"
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
DELIVERY_OPERATION_PREFIX = "bursawatch-swing-board"
_NON_TERMINAL = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


def forum_thread_url(thread_id: str) -> str:
    """Return the stable deep link for one forum topic."""
    value = _identifier(thread_id)
    if value is None:
        raise ValueError("thread_id must be a Discord identifier")
    return f"https://discord.com/channels/{DISCORD_GUILD_ID}/{value}"


class DiscordForumError(RuntimeError):
    """A safe Board delivery error, suitable for durable retry state."""


class DiscordRateLimitError(DiscordForumError):
    """Compatibility error for callers that supply a retry delay."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("Delivery Owner rate limited the operation")
        self.retry_after = retry_after


class DiscordRejectedError(DiscordForumError):
    """Compatibility error for a definite provider rejection."""


def delivery_client_from_environment() -> DeliveryClient:
    """Build the standard client using the loopback URL and private token file."""
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", DELIVERY_OWNER_URL)
    token_path = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / DELIVERY_CLIENT_TOKEN_FILE),
        )
    ).expanduser()
    return DeliveryClient(base_url, token_path)


def operation_key(board_key: str) -> str:
    """Map any durable Board dedupe key into the shared operation-key grammar."""
    if not isinstance(board_key, str) or not board_key.strip():
        raise ValueError("Board delivery identity must be non-empty")
    digest = hashlib.sha256(board_key.encode("utf-8")).hexdigest()
    return f"{DELIVERY_OPERATION_PREFIX}:{digest}"


def stable_nonce(value: str) -> str:
    """Map a historical Board create key to a deterministic bounded nonce."""
    if not isinstance(value, str) or not value:
        raise ValueError("Board legacy create key must be non-empty")
    return "swb-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


class DiscordForumClient:
    """Board-shaped typed adapter over the shared Delivery Owner client."""

    def __init__(self, *, delivery_client: object | None = None, no_post: bool | None = None) -> None:
        self.no_post = (
            os.environ.get("IDX_SWING_PLAN_BOARD_NO_POST") == "1"
            if no_post is None
            else bool(no_post)
        )
        if self.no_post:
            # The local fake is selected before reading live URL/token settings.
            self._delivery = _FakeDeliveryClient()
        else:
            self._delivery = delivery_client if delivery_client is not None else delivery_client_from_environment()

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        """Read a forum topic through an allowlisted Delivery Owner query."""
        result = self._query(DiscordQuery(kind="forum_thread_read", thread_id=_id(thread_id)))
        return _mapping(result, "Delivery Owner returned an invalid forum thread")

    def get_message(self, thread_id: str, message_id: str) -> dict[str, Any]:
        """Read one forum message through an allowlisted Delivery Owner query."""
        result = self._query(DiscordQuery(
            kind="thread_message_read", thread_id=_id(thread_id), message_id=_id(message_id)
        ))
        return _mapping(result, "Delivery Owner returned an invalid forum message")

    def execute(
        self, operation: object, payload: Mapping[str, object] | None = None
    ) -> dict[str, str]:
        """Submit one already-persisted Board operation and return its receipt IDs."""
        operation_name, operation_payload = _operation(operation, payload)
        operation_payload = self.prepare_payload(operation_name, operation_payload)
        stable_key = operation_payload.get("_delivery_key") or operation_payload.get("nonce_value")
        if not isinstance(stable_key, str) or not stable_key.strip():
            raise DiscordForumError("Board operation has no persisted delivery key")
        intent = self._intent(operation_name, operation_payload, stable_key)
        snapshot = operation_payload.get("create_snapshot")
        nonce_source = (
            snapshot.get("operation_key")
            if isinstance(snapshot, Mapping) and isinstance(snapshot.get("operation_key"), str)
            else stable_key
        )
        # Legacy Board snapshots describe a create that may already have
        # reached Discord. They must first be adopted by the owner handoff,
        # which performs bounded read-back before any possible create.
        receipt = self._submit_or_lookup(
            intent,
            require_existing=bool(operation_payload.get("create_snapshot")),
            imported_legacy_nonce=stable_nonce(nonce_source),
        )
        value = receipt.receipt or {}
        if operation_name == "create_thread":
            thread_id = _identifier(value.get("thread_id"))
            starter_id = _identifier(value.get("message_id"))
            if thread_id is None or starter_id is None:
                raise DiscordForumError("Delivery Owner returned incomplete forum thread IDs")
            return {"thread_id": thread_id, "starter_message_id": starter_id}
        if operation_name in {"post_source_reply", "post_history_reply"}:
            message_id = _identifier(value.get("message_id"))
            if message_id is None:
                raise DiscordForumError("Delivery Owner returned an invalid reply ID")
            return {"message_id": message_id}
        return {}

    def prepare_payload(
        self, operation: object, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Resolve tag names through the typed read path before Board persists them."""
        operation_name, value = _operation(operation, payload)
        if operation_name in {"create_thread", "patch_thread"}:
            if "applied_tag_ids" not in value:
                value["applied_tag_ids"] = self._tag_ids(_tag_names(value))
            else:
                tag_ids = value["applied_tag_ids"]
                if (not isinstance(tag_ids, list)
                        or any(_identifier(item) is None for item in tag_ids)
                        or len(set(tag_ids)) != len(tag_ids)):
                    raise DiscordForumError("persisted forum tag IDs are invalid")
        return value

    def post_heartbeat(
        self,
        channel_id: str,
        content: str,
        *,
        operation_key: str | None = None,
    ) -> dict[str, str]:
        """Submit a scheduler heartbeat as a typed channel-message operation."""
        destination = _id(channel_id)
        key_source = operation_key or f"heartbeat:{destination}:{datetime.now(timezone.utc).isoformat()}"
        intent = OperationIntent(
            key=operation_key_for(key_source),
            kind="channel_message_create",
            ordering_key=f"channel:{destination}",
            target={"channel_id": destination},
            payload={"content": _text(content, "heartbeat content"), "allowed_mentions": {"parse": []}},
        )
        receipt = self._submit_or_lookup(
            intent, imported_legacy_nonce=stable_nonce(key_source)
        )
        message_id = _identifier((receipt.receipt or {}).get("message_id"))
        if message_id is None:
            raise DiscordForumError("Delivery Owner returned an invalid heartbeat message ID")
        return {"message_id": message_id}

    def _intent(
        self,
        operation: str,
        payload: Mapping[str, object],
        board_key: str,
    ) -> OperationIntent:
        key = operation_key(board_key)
        if operation == "create_thread":
            tag_ids = _persisted_tag_ids(payload)
            media = _attachment(payload.get("chart") or payload.get("media"))
            return OperationIntent(
                key=key,
                kind="forum_thread_create",
                ordering_key=f"forum:{FORUM_CHANNEL_ID}",
                target={"forum_id": FORUM_CHANNEL_ID},
                payload={
                    "name": _text(payload.get("name"), "thread name"),
                    "content": _content(payload.get("content")),
                    "allowed_mentions": {"parse": []},
                    "applied_tags": tag_ids,
                },
                attachments=() if media is None else (media,),
            )
        if operation == "edit_starter":
            thread_id = _id(payload.get("thread_id"))
            message_id = _id(payload.get("message_id"))
            chart = _attachment(payload.get("chart") or payload.get("media"))
            clear = _bool(payload.get("clear_attachments", False), "clear_attachments")
            if chart is not None and clear:
                raise ValueError("cannot clear attachments and provide a chart")
            mode = "replace" if chart is not None else "clear" if clear else "keep"
            return OperationIntent(
                key=key,
                kind="thread_message_edit",
                ordering_key=f"thread:{thread_id}",
                target={"thread_id": thread_id, "message_id": message_id},
                payload={
                    "content": _content(payload.get("content")),
                    "allowed_mentions": {"parse": []},
                    "attachments_mode": mode,
                },
                attachments=() if chart is None else (chart,),
            )
        if operation in {"post_source_reply", "post_history_reply"}:
            thread_id = _id(payload.get("thread_id"))
            media = _attachment(payload.get("media"))
            content = _reply_content(payload)
            return OperationIntent(
                key=key,
                kind="thread_message_create",
                ordering_key=f"thread:{thread_id}",
                target={"thread_id": thread_id},
                payload={"content": content, "allowed_mentions": {"parse": []}},
                attachments=() if media is None else (media,),
            )
        if operation == "delete_message":
            thread_id = _id(payload.get("thread_id"))
            message_id = _id(payload.get("message_id"))
            return OperationIntent(
                key=key,
                kind="thread_message_delete",
                ordering_key=f"thread:{thread_id}",
                target={"thread_id": thread_id, "message_id": message_id},
                payload={},
            )
        if operation == "patch_thread":
            thread_id = _id(payload.get("thread_id"))
            return OperationIntent(
                key=key,
                kind="forum_thread_update",
                ordering_key=f"thread:{thread_id}",
                target={"thread_id": thread_id},
                payload={
                    "name": _text(payload.get("name"), "thread name"),
                    "applied_tags": _persisted_tag_ids(payload),
                    "archived": _bool(payload.get("archived"), "archived"),
                },
            )
        raise ValueError(f"unsupported Board delivery operation: {operation}")

    def _tag_ids(self, names: tuple[str, ...]) -> list[str]:
        if not names:
            return []
        result = self._query(DiscordQuery(kind="forum_channel_read", channel_id=FORUM_CHANNEL_ID))
        channel = _mapping(result, "Delivery Owner returned an invalid forum tag catalog")
        catalog = channel.get("available_tags")
        if not isinstance(catalog, list):
            raise DiscordForumError("Delivery Owner returned an invalid forum tag catalog")
        resolved: list[str] = []
        for name in names:
            matches = [
                _identifier(tag.get("id"))
                for tag in catalog
                if isinstance(tag, Mapping) and tag.get("name") == name
            ]
            if len(matches) != 1 or matches[0] is None:
                raise DiscordForumError(f"Board forum tag is not uniquely available: {name}")
            resolved.append(matches[0])
        return resolved

    def _query(self, query: DiscordQuery) -> object:
        try:
            return self._delivery.query(query)  # type: ignore[attr-defined]
        except DeliveryClientError:
            raise
        except Exception as exc:
            raise DiscordForumError("Delivery Owner query failed") from exc

    def _submit_or_lookup(
        self,
        intent: OperationIntent,
        *,
        require_existing: bool = False,
        imported_legacy_nonce: str | None = None,
    ) -> OperationReceipt:
        try:
            receipt = self._delivery.status(intent.key)  # type: ignore[attr-defined]
            from_existing_status = receipt is not None
            if receipt is None:
                if require_existing:
                    raise DiscordForumError("legacy create requires Delivery Owner handoff")
                receipt = self._delivery.submit(intent)  # type: ignore[attr-defined]
            expected_digest = self._matching_digest(
                intent,
                receipt,
                from_existing_status=from_existing_status,
                imported_legacy_nonce=imported_legacy_nonce,
            )
            if receipt.status in _NON_TERMINAL:
                receipt = self._delivery.wait(
                    intent.key, DELIVERY_RECEIPT_WAIT_SECONDS
                )  # type: ignore[attr-defined]
                self._require_matching_receipt(intent, receipt, expected_digest)
        except DeliveryClientError:
            raise
        except DiscordForumError:
            raise
        except Exception as exc:
            raise DiscordForumError("Delivery Owner acceptance could not be confirmed") from exc
        if receipt.status != "delivered":
            raise DiscordForumError(f"Delivery Owner operation is {receipt.status}")
        if not isinstance(receipt.receipt, dict):
            raise DiscordForumError("Delivery Owner returned no operation receipt")
        return receipt

    @staticmethod
    def _matching_digest(
        intent: OperationIntent,
        receipt: object,
        *,
        from_existing_status: bool,
        imported_legacy_nonce: str | None,
    ) -> str:
        if isinstance(receipt, OperationReceipt) and receipt.key == intent.key:
            if receipt.digest == intent.digest:
                return intent.digest
            if (from_existing_status and intent.kind.endswith("_create")
                    and imported_legacy_nonce is not None):
                candidate = replace(
                    intent,
                    reconcile_before_first_create=True,
                    **({"legacy_nonce": imported_legacy_nonce}
                       if intent.kind in {"channel_message_create", "thread_message_create"}
                       else {}),
                )
                if receipt.digest == candidate.digest:
                    return candidate.digest
        DiscordForumClient._require_matching_receipt(intent, receipt, intent.digest)
        raise AssertionError("receipt matcher did not return a digest")

    @staticmethod
    def _require_matching_receipt(
        intent: OperationIntent, receipt: object, expected_digest: str
    ) -> None:
        if (not isinstance(receipt, OperationReceipt)
                or receipt.key != intent.key
                or receipt.digest != expected_digest):
            raise DiscordForumError("Delivery Owner receipt did not match the Board operation")


class _FakeDeliveryClient:
    """Process-local Delivery Owner fake used only by explicit no-post runs."""

    def __init__(self) -> None:
        self._receipts: dict[str, OperationReceipt] = {}
        self._tag_catalog = [
            "Primary plan", "Supporting setup", "Chart context", "Resolved", "Source plan",
            "Below entry", "Entry zone", "Above entry", "TP1 reached", "TP2 reached",
            "TP3 reached", "TP4 reached", "TP5 reached", "TP6 reached", "Stop-loss breached",
        ]

    def status(self, operation_key: str) -> OperationReceipt | None:
        return self._receipts.get(operation_key)

    def submit(self, operation: OperationIntent) -> OperationReceipt:
        existing = self._receipts.get(operation.key)
        if existing is not None:
            if existing.digest != operation.digest:
                raise DeliveryClientError("conflict")
            return existing
        identity = str(1_000_000_000_000_000_000 + int(operation.digest[:15], 16))
        if operation.kind == "forum_thread_create":
            value = {"thread_id": identity, "message_id": identity}
        elif operation.kind == "forum_thread_update":
            value = {"thread_id": operation.target["thread_id"]}
        elif operation.kind.startswith("forum_thread_"):
            value = {"thread_id": operation.target["thread_id"]}
        elif operation.kind == "thread_message_edit":
            value = {"message_id": operation.target["message_id"]}
        elif operation.kind.endswith("_delete"):
            value = {"message_id": operation.target["message_id"]}
        elif operation.kind.startswith("thread_message_"):
            value = {"message_id": identity}
        elif operation.kind.startswith("channel_message_"):
            value = {"message_id": identity, "channel_id": operation.target["channel_id"]}
        else:
            value = {}
        receipt = OperationReceipt(
            id=f"dry-run:{identity}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt=value,
        )
        self._receipts[operation.key] = receipt
        return receipt

    def wait(self, operation_key: str, _timeout_seconds: float) -> OperationReceipt:
        result = self._receipts.get(operation_key)
        if result is None:
            raise DeliveryClientError("not_found")
        return result

    def query(self, query: DiscordQuery) -> object:
        if query.kind == "forum_channel_read":
            return {
                "id": query.channel_id,
                "guild_id": DISCORD_GUILD_ID,
                "available_tags": [
                    {"id": str(1_500_000_000_000_000_000 + index), "name": name}
                    for index, name in enumerate(self._tag_catalog, start=1)
                ],
            }
        if query.kind == "forum_thread_read":
            return {
                "id": query.thread_id,
                "parent_id": FORUM_CHANNEL_ID,
                "name": "SCMA",
                "thread_metadata": {"archived": False, "locked": False},
            }
        if query.kind == "thread_message_read":
            return {"id": query.message_id, "content": "", "attachments": []}
        raise DeliveryClientError("invalid_query")


def operation_key_for(board_key: str) -> str:
    """Public helper for the heartbeat path, using the same stable key mapping."""
    return operation_key(board_key)


def _operation(operation: object, payload: Mapping[str, object] | None) -> tuple[str, dict[str, object]]:
    if isinstance(operation, str):
        name = operation
        value = dict(payload or {})
    else:
        name = getattr(operation, "operation", None)
        value = dict(getattr(operation, "payload", {}) if payload is None else payload)
    if not isinstance(name, str):
        raise ValueError("Board operation name is invalid")
    return name, value


def _attachment(value: object) -> Attachment | None:
    if value is None:
        return None
    try:
        path = Path(value)
        data = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise DiscordForumError("Board attachment is unavailable") from None
    if not path.is_file() or not data:
        raise DiscordForumError("Board attachment is unavailable")
    return Attachment(path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream", data)


def _tag_names(payload: Mapping[str, object]) -> tuple[str, ...]:
    value = payload.get("tag_names", ())
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("Board tag names are invalid")
    if len(value) > 5 or len(set(value)) != len(value):
        raise ValueError("Board tag names are invalid")
    return tuple(value)


def _persisted_tag_ids(payload: Mapping[str, object]) -> list[str]:
    value = payload.get("applied_tag_ids")
    if (not isinstance(value, list)
            or any(_identifier(item) is None for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("persisted forum tag IDs are invalid")
    return list(value)


def _reply_content(payload: Mapping[str, object]) -> str:
    value = payload.get("content")
    if value == "" and (payload.get("media") or payload.get("media_url")):
        return ""
    return _content(value)


def _content(value: object) -> str:
    result = _text(value, "message content")
    if len(result.encode("utf-16-le")) // 2 > 2000:
        raise ValueError("Discord message content exceeds 2000 characters")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _id(value: object) -> str:
    result = _identifier(value)
    if result is None:
        raise ValueError("Discord identifier is invalid")
    return result


def _identifier(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and value.isdigit() and 1 <= len(value) <= 20 else None


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DiscordForumError(message)
    return dict(value)
