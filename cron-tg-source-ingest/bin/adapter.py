"""Future-only Telegram intake for the source event inbox.

The existing source jobs remain the production readers until a reviewed cutover.
This module has no Discord or Board credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from source_event_client import SourceEventHandoff


PILOT = {
    "telegram:phintraprofits": ("1444713822", frozenset({"trading_plans"})),
    "telegram:phintasprofits": (None, frozenset({"company_news", "macro_news", "stock_status"})),
    "telegram:kelasinvestasiid": ("2142109618", frozenset({"swing_support"})),
}
# Classified from checked-in canonical IDs. Tuntun remains on the old News reader.
KNOWN_UNMIGRATED = frozenset({"telegram:tuntunsekuritas"})
MAX_BATCH = 20


class IntakeBlocked(RuntimeError):
    """A source message needs an operator-reviewed migration or durable media."""


def endpoints(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Accept one effective catalog snapshot, rejecting unknown enabled work."""
    if type(snapshot) is not dict or type(snapshot.get("subscriptions")) is not list:
        raise ValueError("effective source catalog is invalid")
    grouped: dict[str, dict[str, Any]] = {}
    for row in snapshot["subscriptions"]:
        if row.get("platform") != "telegram" or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        if endpoint_id in KNOWN_UNMIGRATED:
            continue
        expected = PILOT.get(endpoint_id)
        if expected is None or row.get("capability_id") not in expected[1]:
            raise IntakeBlocked("enabled Telegram endpoint or capability is not onboarded")
        if row.get("verification_status") != "verified" or row.get("provider_id") != expected[0] or row.get("address") != endpoint_id.split(":", 1)[1] or row.get("publisher_id") not in {"phintraco", "kelas-investasi"}:
            raise IntakeBlocked("Telegram endpoint identity is not verified")
        current = grouped.setdefault(endpoint_id, {"endpoint_id": endpoint_id, "publisher_id": row["publisher_id"], "address": row["address"], "provider_id": row["provider_id"], "capabilities": set()})
        if (current["publisher_id"], current["address"], current["provider_id"]) != (row["publisher_id"], row["address"], row["provider_id"]):
            raise IntakeBlocked("Telegram endpoint identity changed within snapshot")
        current["capabilities"].add(row["capability_id"])
    return grouped


def _read_cursor(path: Path) -> int | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if type(data) is not dict or type(data.get("cursor")) is not int or data["cursor"] < 0:
        raise IntakeBlocked("Telegram cursor is invalid")
    return data["cursor"]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".cursor-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _save_cursor(path: Path, value: int) -> None:
    _write_json(path, {"cursor": value})


def _stamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IntakeBlocked("Telegram source timestamp is missing")
    return value.astimezone(timezone.utc).isoformat()


def envelope(endpoint: dict[str, Any], message: Any, observed_at: datetime, *, reply_parent: Any = None) -> dict[str, Any]:
    message_id = getattr(message, "id", None)
    if type(message_id) is not int or message_id <= 0:
        raise IntakeBlocked("Telegram message identity is invalid")
    text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
    if type(text) is not str:
        raise IntakeBlocked("Telegram message text is invalid")
    # No verified object store exists. A photo/document must stay in the local
    # source boundary so it can be retried after storage is approved.
    if getattr(message, "media", None) is not None or getattr(message, "photo", None) is not None:
        raise IntakeBlocked("Telegram media requires durable storage")
    reply = getattr(message, "reply_to_msg_id", None)
    if reply is not None and (type(reply) is not int or reply <= 0):
        raise IntakeBlocked("Telegram reply identity is invalid")
    body = {"text": text, "reply_to_message_id": reply}
    if reply_parent is not None:
        if getattr(reply_parent, "id", None) != reply:
            raise IntakeBlocked("Telegram reply parent identity is invalid")
        body["reply_parent"] = {"message_id": reply, "text": getattr(reply_parent, "raw_text", None) or getattr(reply_parent, "message", "") or "", "published_at": _stamp(reply_parent.date), "has_photo": getattr(reply_parent, "photo", None) is not None}
    content_hash = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"version": 1, "endpoint_id": endpoint["endpoint_id"], "publisher_id": endpoint["publisher_id"], "platform": "telegram", "provider_event_id": str(message_id), "published_at": _stamp(message.date), "observed_at": _stamp(observed_at), "source_url": f"https://t.me/{endpoint['address']}/{message_id}", "parser_version": "telegram-pilot-1", "content_hash": content_hash, "payload": body, "media_refs": [], "media_required": False}


async def ingest_endpoint(client: Any, endpoint: dict[str, Any], state_root: Path, inbox: Any, observed_at: datetime, *, batch: int = MAX_BATCH) -> dict[str, Any]:
    if type(batch) is not int or not 1 <= batch <= MAX_BATCH:
        raise ValueError("Telegram batch must be between 1 and 20")
    root = state_root / endpoint["endpoint_id"].replace(":", "-")
    cursor_path = root / "cursor.json"
    cursor = _read_cursor(cursor_path)
    entity = await client.get_entity(endpoint["address"])
    if endpoint["provider_id"] is not None and str(getattr(entity, "id", "")) != endpoint["provider_id"]:
        raise IntakeBlocked("Telegram resolved identity does not match catalog")
    if endpoint["provider_id"] is None and str(getattr(entity, "username", "")).casefold() != endpoint["address"].casefold():
        raise IntakeBlocked("Telegram resolved handle does not match catalog")
    if cursor is None:
        newest = await client.get_messages(entity, limit=1)
        first = newest[0] if isinstance(newest, list) and newest else newest
        high = getattr(first, "id", 0) if first is not None else 0
        if type(high) is not int or high < 0:
            raise IntakeBlocked("Telegram bootstrap identity is invalid")
        _save_cursor(cursor_path, high)
        return {"endpoint_id": endpoint["endpoint_id"], "bootstrapped": True, "cursor": high, "accepted": 0}
    accepted = 0
    handoff = SourceEventHandoff(root / "handoff", inbox)
    # A previously staged request must be acknowledged before this endpoint
    # reads further. Each endpoint has its own durable spool and cursor.
    pending = handoff.spool.pending()
    if pending:
        if len(pending) != 1 or pending[0].endpoint != "/v1/source-events":
            raise IntakeBlocked("Telegram endpoint handoff is inconsistent")
        staged = pending[0].payload["envelope"]
        staged_id = int(staged["provider_event_id"])
        if staged["endpoint_id"] != endpoint["endpoint_id"] or staged_id <= cursor:
            raise IntakeBlocked("Telegram endpoint handoff identity is inconsistent")
        receipts = handoff.flush(limit=1)
        if len(receipts) != 1:
            raise IntakeBlocked("Telegram endpoint handoff was not acknowledged")
        _save_cursor(cursor_path, staged_id)
        cursor = staged_id
    messages = [message async for message in client.iter_messages(entity, min_id=cursor, reverse=True, limit=batch)]
    for message in sorted(messages, key=lambda item: item.id):
        if message.id <= cursor:
            continue
        if getattr(message, "media", None) is not None or getattr(message, "photo", None) is not None:
            _write_json(root / "blocked-media.json", {"endpoint_id": endpoint["endpoint_id"], "message_id": message.id, "published_at": _stamp(message.date), "media_type": type(getattr(message, "media", None)).__name__})
            raise IntakeBlocked("Telegram media requires durable storage")
        reply_id = getattr(message, "reply_to_msg_id", None)
        parent = await client.get_messages(entity, ids=reply_id) if reply_id is not None and endpoint["endpoint_id"] == "telegram:phintraprofits" else None
        if reply_id is not None and endpoint["endpoint_id"] == "telegram:phintraprofits" and parent is None:
            raise IntakeBlocked("Telegram reply parent is unavailable")
        item = envelope(endpoint, message, observed_at, reply_parent=parent)
        handoff.stage(item)
        receipts = handoff.flush(limit=1)
        if len(receipts) != 1:
            raise IntakeBlocked("Telegram source handoff was not acknowledged")
        _save_cursor(cursor_path, message.id)
        (root / "blocked-media.json").unlink(missing_ok=True)
        cursor = message.id
        accepted += 1
    return {"endpoint_id": endpoint["endpoint_id"], "bootstrapped": False, "cursor": cursor, "accepted": accepted}


async def ingest_all(client: Any, snapshot: dict[str, Any], state_root: Path, inbox: Any, observed_at: datetime) -> list[dict[str, Any]]:
    """Poll each known endpoint independently after validating the full snapshot."""
    selected = endpoints(snapshot)
    outcomes = []
    for endpoint in selected.values():
        try:
            outcomes.append(await ingest_endpoint(client, endpoint, state_root, inbox, observed_at))
        except Exception:
            # Keep source text and provider errors out of routine run summaries.
            outcomes.append({"endpoint_id": endpoint["endpoint_id"], "status": "blocked"})
    return outcomes
