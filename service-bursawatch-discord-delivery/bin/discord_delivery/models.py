"""Validated public operation and query contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

SNOWFLAKE = re.compile(r"^[0-9]{1,20}$")
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_./-]{0,199}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
KINDS = frozenset({
    "channel_message_create", "channel_message_edit", "channel_message_delete",
    "forum_thread_create", "forum_thread_update", "forum_thread_archive",
    "thread_message_create", "thread_message_edit", "thread_message_delete",
    "forum_channel_create", "forum_channel_edit", "forum_channel_delete",
    "guild_emoji_create",
})
QUERIES = frozenset({"forum_thread_read", "thread_message_read", "forum_channel_read",
                     "channel_messages", "thread_messages", "forum_threads", "guild_emojis"})
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
    "guild_emoji_create": frozenset({"guild_id"}),
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
    "guild_emoji_create": frozenset({"name"}),
}
MAX_CONTENT = 2000
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class ValidationError(ValueError):
    pass


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
    kind: str
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
        if self.kind == "guild_emoji_create":
            name = payload.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", name):
                raise ValidationError("invalid emoji name")
            if (len(self.attachments) != 1 or self.attachments[0].filename != "emoji.png"
                    or self.attachments[0].mime_type != "image/png"
                    or not 8 <= len(self.attachments[0].data) <= 256 * 1024
                    or not self.attachments[0].data.startswith(b"\x89PNG\r\n\x1a\n")):
                raise ValidationError("invalid emoji PNG")
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
            "channel_message_create", "thread_message_create", "forum_thread_create", "thread_message_edit", "guild_emoji_create"
        }:
            raise ValidationError("attachments not supported for operation kind")
        if not isinstance(self.reconcile_before_first_create, bool):
            raise ValidationError("invalid reconciliation flag")
        if self.legacy_nonce is not None:
            if (not self.reconcile_before_first_create or
                    self.kind not in {"channel_message_create", "thread_message_create"} or
                    not isinstance(self.legacy_nonce, str) or
                    not re.fullmatch(r"[\x20-\x7e]{1,25}", self.legacy_nonce)):
                raise ValidationError("invalid legacy nonce")

    @property
    def digest(self) -> str:
        canonical = {
            "kind": self.kind, "ordering_key": self.ordering_key,
            "target": self.target, "payload": self.payload,
            "attachments": [{"filename": a.filename, "mime_type": a.mime_type,
                             "sha256": hashlib.sha256(a.data).hexdigest()} for a in self.attachments],
            "reconcile_before_first_create": self.reconcile_before_first_create,
        }
        if self.legacy_nonce is not None:
            canonical["legacy_nonce"] = self.legacy_nonce
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class OperationRecord:
    id: str
    key: str
    digest: str
    kind: str
    ordering_key: str
    target: dict[str, str]
    status: str
    receipt: dict[str, str] | None
    attempt_count: int
    error_category: str | None
    created_at: str
    updated_at: str


def validate_receipt(receipt: Mapping[str, str], kind: str,
                     target: Mapping[str, str]) -> dict[str, str]:
    if kind.startswith("forum_thread_"):
        required = {"thread_id"}
        allowed = {"thread_id", "message_id"}
    elif kind.startswith("forum_channel_"):
        required = {"channel_id"}
        allowed = {"channel_id"}
    elif kind == "guild_emoji_create":
        required = {"emoji_id"}
        allowed = {"emoji_id"}
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
    for key, value in receipt.items():
        _snowflake(value, key)
        if key in target and value != target[key]:
            raise ValidationError("receipt destination mismatch")
    return dict(receipt)


def validate_preflight(value: Mapping[str, Any] | None, kind: str | None = None) -> dict[str, Any] | None:
    """Validate a source-observed history boundary for pending create recovery."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"boundary_observed", "boundary"}:
        raise ValidationError("invalid preflight boundary")
    if value["boundary_observed"] is not True:
        raise ValidationError("preflight boundary was not observed")
    if kind is not None and kind not in {
        "channel_message_create", "thread_message_create", "forum_thread_create",
    }:
        raise ValidationError("operation kind does not support preflight recovery")
    boundary = value["boundary"]
    if boundary is not None:
        _snowflake(boundary, "preflight boundary")
    return {"boundary_observed": True, "boundary": boundary}


def validate_query(value: Any) -> dict[str, Any]:
    query = _object(value, "query")
    if not isinstance(query.get("kind"), str) or query["kind"] not in QUERIES:
        raise ValidationError("invalid query kind")
    fields = {
        "forum_thread_read": ({"kind", "thread_id"}, {"kind", "thread_id"}),
        "thread_message_read": ({"kind", "thread_id", "message_id"}, {"kind", "thread_id", "message_id"}),
        "forum_channel_read": ({"kind", "channel_id"}, {"kind", "channel_id"}),
        "channel_messages": ({"kind", "channel_id"}, {"kind", "channel_id", "before", "after", "limit"}),
        "thread_messages": ({"kind", "thread_id"}, {"kind", "thread_id", "before", "after", "limit"}),
        "forum_threads": ({"kind", "channel_id"}, {"kind", "channel_id", "before", "limit"}),
        "guild_emojis": ({"kind", "guild_id"}, {"kind", "guild_id"}),
    }
    required, allowed = fields[query["kind"]]
    if not required <= set(query) or set(query) - allowed:
        raise ValidationError("invalid query fields")
    for name in ("channel_id", "thread_id", "message_id", "guild_id", "before", "after"):
        if name in query:
            _snowflake(query[name], name)
    if "limit" in query and (type(query["limit"]) is not int or not 1 <= query["limit"] <= 100):
        raise ValidationError("invalid query limit")
    return query
