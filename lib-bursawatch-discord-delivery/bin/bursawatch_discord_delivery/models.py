"""Typed contracts shared with the local Discord Delivery Owner API."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


SNOWFLAKE = re.compile(r"^[0-9]{1,20}$")
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_./-]{0,199}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")

OperationKind = Literal[
    "channel_message_create",
    "channel_message_edit",
    "channel_message_delete",
    "forum_thread_create",
    "forum_thread_update",
    "forum_thread_archive",
    "thread_message_create",
    "thread_message_edit",
    "thread_message_delete",
    "forum_channel_create",
    "forum_channel_edit",
    "forum_channel_delete",
]
QueryKind = Literal[
    "forum_thread_read",
    "thread_message_read",
    "forum_channel_read",
    "channel_messages",
    "thread_messages",
    "forum_threads",
]
OperationStatus = Literal[
    "pending",
    "pending_reconciliation",
    "retrying",
    "delivering",
    "delivered",
    "rejected",
    "blocked",
    "ambiguous",
]

KINDS = frozenset({
    "channel_message_create", "channel_message_edit", "channel_message_delete",
    "forum_thread_create", "forum_thread_update", "forum_thread_archive",
    "thread_message_create", "thread_message_edit", "thread_message_delete",
    "forum_channel_create", "forum_channel_edit", "forum_channel_delete",
})
QUERY_KINDS = frozenset({
    "forum_thread_read", "thread_message_read", "forum_channel_read",
    "channel_messages", "thread_messages", "forum_threads",
})
STATUSES = frozenset({
    "pending", "pending_reconciliation", "retrying", "delivering",
    "delivered", "rejected", "blocked", "ambiguous",
})
TARGET_FIELDS = {
    "channel_message_create": frozenset({"channel_id"}),
    "channel_message_edit": frozenset({"channel_id", "message_id"}),
    "channel_message_delete": frozenset({"channel_id", "message_id"}),
    "forum_thread_create": frozenset({"forum_id"}),
    "forum_thread_update": frozenset({"thread_id"}),
    "forum_thread_archive": frozenset({"thread_id"}),
    "thread_message_create": frozenset({"thread_id"}),
    "thread_message_edit": frozenset({"thread_id", "message_id"}),
    "thread_message_delete": frozenset({"thread_id", "message_id"}),
    "forum_channel_create": frozenset({"guild_id"}),
    "forum_channel_edit": frozenset({"channel_id"}),
    "forum_channel_delete": frozenset({"channel_id"}),
}
PAYLOAD_FIELDS = {
    "channel_message_create": frozenset({"content", "allowed_mentions"}),
    "channel_message_edit": frozenset({"content", "allowed_mentions"}),
    "channel_message_delete": frozenset(),
    "forum_thread_create": frozenset({"name", "content", "allowed_mentions", "auto_archive_duration", "applied_tags"}),
    "forum_thread_update": frozenset({"name", "auto_archive_duration", "applied_tags", "archived"}),
    "forum_thread_archive": frozenset(),
    "thread_message_create": frozenset({"content", "allowed_mentions"}),
    "thread_message_edit": frozenset({"content", "allowed_mentions", "attachments_mode"}),
    "thread_message_delete": frozenset(),
    "forum_channel_create": frozenset({"name", "topic"}),
    "forum_channel_edit": frozenset({"name", "topic"}),
    "forum_channel_delete": frozenset(),
}
QUERY_FIELDS = {
    "forum_thread_read": ({"thread_id"}, {"thread_id"}),
    "thread_message_read": ({"thread_id", "message_id"}, {"thread_id", "message_id"}),
    "forum_channel_read": ({"channel_id"}, {"channel_id"}),
    "channel_messages": ({"channel_id"}, {"channel_id", "before", "after", "limit"}),
    "thread_messages": ({"thread_id"}, {"thread_id", "before", "after", "limit"}),
    "forum_threads": ({"channel_id"}, {"channel_id", "before", "limit"}),
}
MAX_CONTENT = 2000
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class ValidationError(ValueError):
    """Raised for an invalid operation or query shape."""


def _snowflake(value: Any, name: str) -> None:
    if not isinstance(value, str) or not SNOWFLAKE.fullmatch(value):
        raise ValidationError(f"invalid {name}")


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.filename, str) or len(self.filename) > 128
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.filename)
                or self.filename in {".", ".."}):
            raise ValidationError("invalid attachment filename")
        if (not isinstance(self.mime_type, str) or len(self.mime_type) > 100
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*", self.mime_type)):
            raise ValidationError("invalid attachment MIME type")
        if not isinstance(self.data, bytes) or len(self.data) > MAX_ATTACHMENT_BYTES:
            raise ValidationError("invalid attachment bytes")


@dataclass(frozen=True)
class OperationIntent:
    key: str
    kind: OperationKind | str
    ordering_key: str
    target: Mapping[str, str]
    payload: Mapping[str, Any]
    attachments: tuple[Attachment, ...] = ()
    reconcile_before_first_create: bool = False
    legacy_nonce: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not KEY.fullmatch(self.key):
            raise ValidationError("invalid operation key")
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ValidationError("invalid operation kind")
        if not isinstance(self.ordering_key, str) or not KEY.fullmatch(self.ordering_key):
            raise ValidationError("invalid ordering key")
        target = _object(self.target, "target")
        if set(target) != TARGET_FIELDS[self.kind]:
            raise ValidationError("invalid target fields for operation kind")
        for name, value in target.items():
            _snowflake(value, name)
        payload = _object(self.payload, "payload")
        if set(payload) - PAYLOAD_FIELDS[self.kind]:
            raise ValidationError("invalid payload fields for operation kind")
        if self.kind.endswith("_delete") or self.kind == "forum_thread_archive":
            if payload:
                raise ValidationError("operation takes no payload")
        content = payload.get("content")
        if content is not None and (not isinstance(content, str) or len(content) > MAX_CONTENT):
            raise ValidationError("invalid content")
        if self.kind in {"channel_message_create", "thread_message_create", "forum_thread_create"}:
            if not content and not self.attachments:
                raise ValidationError("create has no message content")
        if self.kind in {"channel_message_edit", "thread_message_edit"} and "content" not in payload:
            raise ValidationError("edit requires content")
        if "allowed_mentions" in payload and payload["allowed_mentions"] != {"parse": []}:
            raise ValidationError("allowed mentions must disable parsing")
        if self.kind in {"forum_thread_create", "forum_channel_create"}:
            name = payload.get("name")
            if not isinstance(name, str) or not 1 <= len(name) <= 100:
                raise ValidationError("invalid thread name")
        if self.kind in {"forum_thread_update", "forum_channel_edit"} and not payload:
            raise ValidationError("update requires a change")
        if "name" in payload and (not isinstance(payload["name"], str) or not 1 <= len(payload["name"]) <= 100):
            raise ValidationError("invalid name")
        if "topic" in payload and (not isinstance(payload["topic"], str) or len(payload["topic"]) > 1024):
            raise ValidationError("invalid topic")
        if "auto_archive_duration" in payload and payload["auto_archive_duration"] not in (60, 1440, 4320, 10080):
            raise ValidationError("invalid archive duration")
        if "applied_tags" in payload:
            tags = payload["applied_tags"]
            if (not isinstance(tags, list) or len(tags) > 5
                    or any(not isinstance(tag, str) or not SNOWFLAKE.fullmatch(tag) for tag in tags)
                    or len(set(tags)) != len(tags)):
                raise ValidationError("invalid applied forum tags")
        if "archived" in payload and type(payload["archived"]) is not bool:
            raise ValidationError("invalid archived state")
        if not isinstance(self.attachments, (tuple, list)) or len(self.attachments) > MAX_ATTACHMENTS:
            raise ValidationError("too many attachments")
        if any(not isinstance(item, Attachment) for item in self.attachments):
            raise ValidationError("invalid attachment")
        if sum(len(item.data) for item in self.attachments) > MAX_ATTACHMENT_BYTES:
            raise ValidationError("attachments too large")
        if self.kind == "thread_message_edit":
            mode = payload.get("attachments_mode")
            if not isinstance(mode, str) or mode not in {"keep", "clear", "replace"}:
                raise ValidationError("invalid attachment mode")
            if mode == "replace" and not self.attachments:
                raise ValidationError("replace mode requires uploaded attachments")
            if mode != "replace" and self.attachments:
                raise ValidationError("only replace mode accepts uploaded attachments")
        if self.attachments and self.kind not in {
            "channel_message_create", "thread_message_create", "forum_thread_create", "thread_message_edit"
        }:
            raise ValidationError("attachments not supported for operation kind")
        if not isinstance(self.reconcile_before_first_create, bool):
            raise ValidationError("invalid reconciliation flag")
        if self.legacy_nonce is not None:
            if (not self.reconcile_before_first_create
                    or self.kind not in {"channel_message_create", "thread_message_create"}
                    or not isinstance(self.legacy_nonce, str)
                    or not re.fullmatch(r"[\x20-\x7e]{1,25}", self.legacy_nonce)):
                raise ValidationError("invalid legacy nonce")
        try:
            json.dumps({"target": target, "payload": payload}, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError("operation contains non-JSON values") from exc

    @property
    def digest(self) -> str:
        canonical: dict[str, Any] = {
            "kind": self.kind,
            "ordering_key": self.ordering_key,
            "target": self.target,
            "payload": self.payload,
            "attachments": [
                {
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "sha256": hashlib.sha256(attachment.data).hexdigest(),
                }
                for attachment in self.attachments
            ],
            "reconcile_before_first_create": self.reconcile_before_first_create,
        }
        if self.legacy_nonce is not None:
            canonical["legacy_nonce"] = self.legacy_nonce
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def as_dict(self, *, include_legacy_nonce: bool = False) -> dict[str, Any]:
        if self.legacy_nonce is not None and not include_legacy_nonce:
            raise ValidationError("legacy nonce is only valid for pending adoption")
        result: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "ordering_key": self.ordering_key,
            "target": dict(self.target),
            "payload": dict(self.payload),
            "reconcile_before_first_create": self.reconcile_before_first_create,
        }
        if include_legacy_nonce and self.legacy_nonce is not None:
            result["legacy_nonce"] = self.legacy_nonce
        return result


@dataclass(frozen=True)
class DiscordQuery:
    kind: QueryKind | str
    channel_id: str | None = None
    thread_id: str | None = None
    message_id: str | None = None
    before: str | None = None
    after: str | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        validate_query(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        for name in ("channel_id", "thread_id", "message_id", "before", "after", "limit"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        return result


@dataclass(frozen=True)
class OperationReceipt:
    id: str
    key: str
    digest: str
    status: OperationStatus | str
    receipt: dict[str, str] | None = None

    @classmethod
    def from_json(cls, value: Any, operation: OperationIntent | None = None) -> "OperationReceipt":
        if not isinstance(value, dict) or set(value) != {"id", "key", "digest", "status", "receipt"}:
            raise ValidationError("invalid operation response")
        operation_id = value["id"]
        key = value["key"]
        digest = value["digest"]
        status = value["status"]
        receipt = value["receipt"]
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
            raise ValidationError("invalid operation response")
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValidationError("invalid operation response")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValidationError("invalid operation response")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValidationError("invalid operation response")
        if receipt is not None:
            if not isinstance(receipt, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in receipt.items()):
                raise ValidationError("invalid operation response")
            if operation is not None:
                validate_receipt(receipt, str(operation.kind), operation.target)
        if operation is not None and (key != operation.key or digest != operation.digest):
            raise ValidationError("operation response does not match request")
        return cls(operation_id, key, digest, status, dict(receipt) if receipt is not None else None)


def validate_receipt(receipt: Mapping[str, str], kind: str, target: Mapping[str, str]) -> dict[str, str]:
    if kind.startswith("forum_thread_"):
        required = {"thread_id"}
        allowed = {"thread_id", "message_id"}
    elif kind.startswith("forum_channel_"):
        required = {"channel_id"}
        allowed = {"channel_id"}
    elif kind.startswith("thread_message_"):
        required = {"message_id"}
        allowed = {"message_id", "thread_id"}
    elif kind.startswith("channel_message_"):
        required = {"message_id"}
        allowed = {"message_id", "channel_id"}
    else:
        raise ValidationError("invalid receipt operation kind")
    if not isinstance(receipt, dict) or not required <= set(receipt) or set(receipt) - allowed:
        raise ValidationError("invalid receipt")
    for name, value in receipt.items():
        _snowflake(value, name)
        if name in target and value != target[name]:
            raise ValidationError("receipt destination mismatch")
    return dict(receipt)


def validate_preflight(value: Mapping[str, Any] | None, kind: str | None = None) -> dict[str, Any] | None:
    """Validate an observed pre-migration destination boundary.

    A null boundary explicitly means the destination was empty when the
    source owner captured its snapshot. Omitting the hint keeps the import
    conservative and does not establish absence coverage.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"boundary_observed", "boundary"}:
        raise ValidationError("invalid preflight boundary")
    if value["boundary_observed"] is not True:
        raise ValidationError("preflight boundary was not observed")
    if kind is not None and kind not in {
        "channel_message_create",
        "thread_message_create",
        "forum_thread_create",
    }:
        raise ValidationError("operation kind does not support preflight recovery")
    boundary = value["boundary"]
    if boundary is not None:
        _snowflake(boundary, "preflight boundary")
    return {"boundary_observed": True, "boundary": boundary}


def validate_query(value: Any) -> dict[str, Any]:
    query = _object(value, "query")
    kind = query.get("kind")
    if not isinstance(kind, str) or kind not in QUERY_KINDS:
        raise ValidationError("invalid query kind")
    required, allowed = QUERY_FIELDS[kind]
    if not required <= set(query) or set(query) - (allowed | {"kind"}):
        raise ValidationError("invalid query fields")
    for name in ("channel_id", "thread_id", "message_id", "before", "after"):
        if name in query:
            _snowflake(query[name], name)
    if "limit" in query and (type(query["limit"]) is not int or not 1 <= query["limit"] <= 100):
        raise ValidationError("invalid query limit")
    return query
