"""Future-only Telegram intake for the source event inbox.

The existing source jobs remain the production readers until a reviewed cutover.
This module has no Discord or Board credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from legacy_cursor_seed import LegacySeedBlocked, plan_seed, read_legacy_snapshot
from source_ingest import bind_catalog_revision
from source_event_client import SourceEventHandoff


PILOT = {
    "telegram:phintraprofits": ("1444713822", "phintraco", frozenset({"trading_plans"})),
    "telegram:phintasprofits": (None, "phintraco", frozenset({"company_news", "macro_news", "stock_status"})),
    "telegram:kelasinvestasiid": ("2142109618", "kelas-investasi", frozenset({"swing_support"})),
}
# Classified from checked-in canonical IDs. Tuntun remains on the old News reader.
KNOWN_UNMIGRATED = {
    "telegram:tuntunsekuritas": (None, "tuntun", frozenset({"company_news", "macro_news"})),
}
MAX_BATCH = 20
MAX_MEDIA_OBJECT_BYTES = 8 * 1024 * 1024


class IntakeBlocked(RuntimeError):
    """A source message needs an operator-reviewed migration or durable media."""


def plan_legacy_cursor_seed(legacy_state_path: Path, state_root: Path, endpoint: dict[str, Any], catalog_revision: int, *, apply: bool = False, expected_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preview or seed the exact Telegram message boundary from a snapshot."""
    if endpoint.get("endpoint_id") == "telegram:phintraprofits":
        field = "observed_message_id"
        pending_key = "outbox"
    elif endpoint.get("endpoint_id") == "telegram:phintasprofits":
        field = "providers.phintraco.observed_message_id"
        pending_key = None
    elif endpoint.get("endpoint_id") == "telegram:kelasinvestasiid":
        field = "cursor"
        pending_key = "pending"
    else:
        raise LegacySeedBlocked("Telegram endpoint has no reviewed legacy cursor mapping")
    expected_provider, expected_publisher, _ = PILOT[endpoint["endpoint_id"]]
    expected = ("telegram", endpoint["endpoint_id"], expected_publisher, endpoint["endpoint_id"].split(":", 1)[1], expected_provider)
    observed = tuple(endpoint.get(key) for key in ("platform", "endpoint_id", "publisher_id", "address", "provider_id"))
    if observed != expected or endpoint.get("catalog_revision") != catalog_revision:
        raise LegacySeedBlocked("Telegram endpoint identity or catalog revision differs from the reviewed binding")
    raw, legacy = read_legacy_snapshot(legacy_state_path)
    if endpoint["endpoint_id"] == "telegram:phintasprofits":
        if legacy.get("version") != 1:
            raise LegacySeedBlocked("Market News state version is unsupported for Phintraco cursor seeding")
        providers = legacy.get("providers")
        lane = providers.get("phintraco") if type(providers) is dict else None
        boundary = lane.get("observed_message_id") if type(lane) is dict else None
        candidates = legacy.get("candidates")
        active_phintraco_phases = {"pending_analysis", "awaiting_agent", "pending_selection", "pending_delivery"}
        if type(candidates) is not dict:
            raise LegacySeedBlocked("Market News candidate state is unavailable for Phintraco cursor seeding")
        for record in candidates.values():
            candidate = record.get("candidate") if type(record) is dict else None
            if type(candidate) is not dict or type(record.get("phase")) is not str:
                raise LegacySeedBlocked("Market News candidate state is malformed")
            if candidate.get("provider") not in {"phintraco", "tuntun"} or record["phase"] not in {
                "pending_analysis", "awaiting_agent", "pending_selection", "pending_delivery",
                "suppressed_rank", "suppressed_duplicate", "suppressed_ineligible",
                "delivered", "delivery_failed", "abandoned",
            }:
                raise LegacySeedBlocked("Market News candidate state contains an unsupported outcome")
            if candidate.get("provider") == "phintraco" and record["phase"] in active_phintraco_phases:
                raise LegacySeedBlocked("pending Phintraco Market News candidates must be reconciled before cursor seeding")
        stats = legacy.get("stats")
        status_events = stats.get("stock_status_events", {}) if type(stats) is dict else None
        if type(status_events) is not dict:
            raise LegacySeedBlocked("Market News stock-status state is unavailable for Phintraco cursor seeding")
        for event in status_events.values():
            if type(event) is not dict or type(event.get("phase")) is not str:
                raise LegacySeedBlocked("Market News stock-status state is malformed")
            if event["phase"] not in {"pending_delivery", "delivered", "rejected"}:
                raise LegacySeedBlocked("Market News stock-status state contains an unsupported outcome")
            if event["phase"] == "pending_delivery":
                raise LegacySeedBlocked("pending Phintraco stock-status deliveries must be reconciled before cursor seeding")
    else:
        boundary = legacy.get(field)
    if type(boundary) is not int or boundary < 0:
        raise LegacySeedBlocked(f"Telegram legacy {field} boundary is invalid")
    pending = legacy.get(pending_key) if pending_key is not None else None
    if pending:
        raise LegacySeedBlocked(f"Telegram legacy {pending_key} work must be reconciled before cursor seeding")
    if endpoint["endpoint_id"] == "telegram:kelasinvestasiid" and legacy.get("outbox"):
        raise LegacySeedBlocked("Kelas legacy outbox work must be reconciled before cursor seeding")
    return plan_seed(
        legacy_state_path=legacy_state_path,
        state_root=state_root,
        endpoint=endpoint,
        snapshot_bytes=raw,
        catalog_revision=catalog_revision,
        anchor=str(boundary),
        cursor_shape="telegram",
        bootstrap_anchor=str(boundary) if endpoint["endpoint_id"] == "telegram:kelasinvestasiid" else None,
        apply=apply,
        expected_plan=expected_plan,
    )


def endpoints(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Accept one effective catalog snapshot, rejecting unknown enabled work."""
    if type(snapshot) is not dict or type(snapshot.get("subscriptions")) is not list or type(snapshot.get("revision")) is not int or snapshot["revision"] < 1:
        raise ValueError("effective source catalog is invalid")
    grouped: dict[str, dict[str, Any]] = {}
    for row in snapshot["subscriptions"]:
        if row.get("platform") != "telegram" or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        expected = PILOT.get(endpoint_id) or KNOWN_UNMIGRATED.get(endpoint_id)
        if expected is None or row.get("capability_id") not in expected[2]:
            raise IntakeBlocked("enabled Telegram endpoint or capability is not onboarded")
        if row.get("verification_status") != "verified" or row.get("provider_id") != expected[0] or row.get("address") != endpoint_id.split(":", 1)[1] or row.get("publisher_id") != expected[1]:
            raise IntakeBlocked("Telegram endpoint identity is not verified")
        if endpoint_id in KNOWN_UNMIGRATED:
            continue
        current = grouped.setdefault(endpoint_id, {"platform": "telegram", "endpoint_id": endpoint_id, "publisher_id": row["publisher_id"], "address": row["address"], "provider_id": row["provider_id"], "catalog_revision": snapshot["revision"], "capabilities": set()})
        if (current["publisher_id"], current["address"], current["provider_id"]) != (row["publisher_id"], row["address"], row["provider_id"]):
            raise IntakeBlocked("Telegram endpoint identity changed within snapshot")
        current["capabilities"].add(row["capability_id"])
    return grouped


def _read_cursor(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if type(data) is not dict or type(data.get("cursor")) is not int or data["cursor"] < 0:
        raise IntakeBlocked("Telegram cursor is invalid")
    if "bootstrap_cursor" in data and (type(data["bootstrap_cursor"]) is not int or not 0 <= data["bootstrap_cursor"] <= data["cursor"]):
        raise IntakeBlocked("Telegram bootstrap cursor is invalid")
    return data


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


def _save_cursor(path: Path, value: int, *, bootstrap_cursor: int | None = None, published_at: str | None = None) -> None:
    record = {"cursor": value}
    if bootstrap_cursor is not None:
        record["bootstrap_cursor"] = bootstrap_cursor
    if path.exists():
        try:
            previous = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise IntakeBlocked("Telegram cursor is invalid") from error
        if type(previous) is dict and isinstance(previous.get("legacy_seed"), dict):
            record["legacy_seed"] = previous["legacy_seed"]
    if published_at is not None:
        record["boundary_published_at"] = published_at
    _write_json(path, record)


def _stamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IntakeBlocked("Telegram source timestamp is missing")
    return value.astimezone(timezone.utc).isoformat()


async def _upload_message_media(client: Any, endpoint: dict[str, Any], message: Any, state_root: Path, media_store: Any) -> list[dict[str, Any]]:
    photo = getattr(message, "photo", None)
    document = getattr(message, "document", None)
    if photo is not None:
        kind, content_type, filename = "image", "image/jpeg", f"telegram-{message.id}.jpg"
    elif document is not None:
        content_type = getattr(document, "mime_type", None)
        if type(content_type) is not str or "/" not in content_type:
            raise IntakeBlocked("Telegram media content type is unavailable")
        major = content_type.split("/", 1)[0]
        kind = major if major in {"image", "video", "audio"} else "document"
        source_file = getattr(message, "file", None)
        filename = getattr(source_file, "name", None) or f"telegram-{message.id}"
    else:
        raise IntakeBlocked("Telegram media type is unsupported")
    if media_store is None:
        raise IntakeBlocked("Telegram media requires the Source Media Owner")
    size_hint = getattr(document, "size", None) if document is not None else None
    if type(size_hint) is int and size_hint > MAX_MEDIA_OBJECT_BYTES:
        raise IntakeBlocked("Telegram media exceeds the 8 MiB object bound")
    staging_root = state_root / "media-staging"
    staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(staging_root, 0o700)
    temporary_dir = Path(tempfile.mkdtemp(prefix="telegram-", dir=staging_root))
    os.chmod(temporary_dir, 0o700)
    temporary_path = temporary_dir / "attachment.bin"
    try:
        def enforce_download_limit(downloaded: int, _total: int) -> None:
            if downloaded > MAX_MEDIA_OBJECT_BYTES:
                raise IntakeBlocked("Telegram media exceeds the 8 MiB object bound")

        await client.download_media(
            message,
            file=str(temporary_path),
            progress_callback=enforce_download_limit,
        )
        if not temporary_path.is_file():
            raise IntakeBlocked("Telegram media download did not produce a file")
        size = temporary_path.stat().st_size
        if not 1 <= size <= MAX_MEDIA_OBJECT_BYTES:
            raise IntakeBlocked("Telegram media size is outside the 8 MiB object bound")
        data = temporary_path.read_bytes()
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    try:
        reference = media_store.upload(
            f"telegram:{endpoint['endpoint_id']}:{message.id}:attachment:0",
            data,
            kind=kind,
            content_type=content_type,
            filename=filename,
        )
    except Exception:
        raise IntakeBlocked("Telegram media upload to the Source Media Owner failed") from None
    if type(reference) is not dict or reference.get("durable") is not True or reference.get("kind") != kind or reference.get("content_type") != content_type or reference.get("size_bytes") != size:
        raise IntakeBlocked("Source Media Owner returned invalid media metadata")
    return [reference]


def envelope(endpoint: dict[str, Any], message: Any, observed_at: datetime, *, reply_parent: Any = None, media_refs: list[dict[str, Any]] | None = None, previous_message_id: int | None = None, bootstrap_message_id: int | None = None) -> dict[str, Any]:
    message_id = getattr(message, "id", None)
    if type(message_id) is not int or message_id <= 0:
        raise IntakeBlocked("Telegram message identity is invalid")
    text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
    if type(text) is not str:
        raise IntakeBlocked("Telegram message text is invalid")
    media_refs = list(media_refs or [])
    if (getattr(message, "media", None) is not None or getattr(message, "photo", None) is not None) and not media_refs:
        raise IntakeBlocked("Telegram media requires a durable media reference")
    reply = getattr(message, "reply_to_msg_id", None)
    if reply is not None and (type(reply) is not int or reply <= 0):
        raise IntakeBlocked("Telegram reply identity is invalid")
    body = {"text": text, "reply_to_message_id": reply}
    if endpoint["endpoint_id"] == "telegram:kelasinvestasiid":
        if type(previous_message_id) is not int or previous_message_id < 0 or previous_message_id >= message_id:
            raise IntakeBlocked("Kelas source predecessor is invalid")
        if type(bootstrap_message_id) is not int or not 0 <= bootstrap_message_id <= previous_message_id:
            raise IntakeBlocked("Kelas bootstrap identity is invalid")
        body["previous_provider_event_id"] = previous_message_id
        body["bootstrap_provider_event_id"] = bootstrap_message_id
    image_refs = [ref["ref"] for ref in media_refs if getattr(message, "photo", None) is not None and ref.get("kind") == "image"]
    if image_refs:
        body["media_ref_ids"] = image_refs
    if reply_parent is not None:
        if getattr(reply_parent, "id", None) != reply:
            raise IntakeBlocked("Telegram reply parent identity is invalid")
        body["reply_parent"] = {"message_id": reply, "text": getattr(reply_parent, "raw_text", None) or getattr(reply_parent, "message", "") or "", "published_at": _stamp(reply_parent.date), "has_photo": getattr(reply_parent, "photo", None) is not None}
    identity = {"payload": body, "media_refs": media_refs}
    content_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"version": 1, "endpoint_id": endpoint["endpoint_id"], "publisher_id": endpoint["publisher_id"], "platform": "telegram", "provider_event_id": str(message_id), "published_at": _stamp(message.date), "observed_at": _stamp(observed_at), "source_url": f"https://t.me/{endpoint['address']}/{message_id}", "parser_version": "telegram-pilot-1", "content_hash": content_hash, "payload": body, "media_refs": media_refs, "media_required": bool(media_refs)}


async def ingest_endpoint(client: Any, endpoint: dict[str, Any], state_root: Path, inbox: Any, observed_at: datetime, *, batch: int = MAX_BATCH, media_store: Any = None, stage_callback: Any = None) -> dict[str, Any]:
    if type(batch) is not int or not 1 <= batch <= MAX_BATCH:
        raise ValueError("Telegram batch must be between 1 and 20")
    def set_stage(value: str) -> None:
        if stage_callback is not None:
            stage_callback(value)

    set_stage("load_cursor")
    root = state_root / endpoint["endpoint_id"].replace(":", "-")
    cursor_path = root / "cursor.json"
    cursor_record = _read_cursor(cursor_path)
    cursor = cursor_record["cursor"] if cursor_record is not None else None
    bootstrap_cursor = cursor_record.get("bootstrap_cursor") if cursor_record is not None else None
    if endpoint["endpoint_id"] == "telegram:kelasinvestasiid" and cursor_record is not None and bootstrap_cursor is None:
        raise IntakeBlocked("Kelas adapter bootstrap cursor is unavailable")
    set_stage("resolve_entity")
    entity = await client.get_entity(endpoint["address"])
    set_stage("validate_identity")
    if endpoint["provider_id"] is not None and str(getattr(entity, "id", "")) != endpoint["provider_id"]:
        raise IntakeBlocked("Telegram resolved identity does not match catalog")
    if endpoint["provider_id"] is None and str(getattr(entity, "username", "")).casefold() != endpoint["address"].casefold():
        raise IntakeBlocked("Telegram resolved handle does not match catalog")
    if cursor is None:
        set_stage("bootstrap_cursor")
        newest = await client.get_messages(entity, limit=1)
        first = newest[0] if isinstance(newest, list) and newest else newest
        high = getattr(first, "id", 0) if first is not None else 0
        if type(high) is not int or high < 0:
            raise IntakeBlocked("Telegram bootstrap identity is invalid")
        if endpoint["endpoint_id"] == "telegram:kelasinvestasiid":
            bootstrap_cursor = high
        _save_cursor(cursor_path, high, bootstrap_cursor=bootstrap_cursor)
        return {"endpoint_id": endpoint["endpoint_id"], "bootstrapped": True, "cursor": high, "accepted": 0}
    accepted = 0
    handoff = SourceEventHandoff(root / "handoff", inbox)
    # A previously staged request must be acknowledged before this endpoint
    # reads further. Each endpoint has its own durable spool and cursor.
    set_stage("reconcile_handoff")
    pending = handoff.spool.pending()
    if pending:
        if len(pending) != 1 or pending[0].endpoint != "/v1/source-events":
            raise IntakeBlocked("Telegram endpoint handoff is inconsistent")
        staged = pending[0].payload["envelope"]
        staged_id = int(staged["provider_event_id"])
        if staged["endpoint_id"] != endpoint["endpoint_id"] or staged_id <= cursor:
            raise IntakeBlocked("Telegram endpoint handoff identity is inconsistent")
        if endpoint["endpoint_id"] == "telegram:kelasinvestasiid" and (
            staged.get("payload", {}).get("bootstrap_provider_event_id") != bootstrap_cursor
            or staged.get("payload", {}).get("previous_provider_event_id") != cursor
        ):
            raise IntakeBlocked("Kelas endpoint handoff sequence is inconsistent")
        set_stage("accept_staged_event")
        receipts = handoff.flush(limit=1)
        if len(receipts) != 1:
            raise IntakeBlocked("Telegram endpoint handoff was not acknowledged")
        _save_cursor(cursor_path, staged_id, bootstrap_cursor=bootstrap_cursor, published_at=staged["published_at"])
        blocked_path = root / "blocked-media.json"
        if blocked_path.exists():
            try:
                blocked = json.loads(blocked_path.read_text())
            except (OSError, ValueError):
                blocked = None
            if type(blocked) is dict and blocked.get("message_id") == staged_id:
                blocked_path.unlink(missing_ok=True)
        cursor = staged_id
    set_stage("read_messages")
    messages = [message async for message in client.iter_messages(entity, min_id=cursor, reverse=True, limit=batch)]
    for message in sorted(messages, key=lambda item: item.id):
        if message.id <= cursor:
            continue
        media_refs: list[dict[str, Any]] = []
        if getattr(message, "media", None) is not None or getattr(message, "photo", None) is not None:
            set_stage("upload_media")
            _write_json(root / "blocked-media.json", {"endpoint_id": endpoint["endpoint_id"], "message_id": message.id, "published_at": _stamp(message.date), "media_type": type(getattr(message, "media", None)).__name__})
            try:
                media_refs = await _upload_message_media(client, endpoint, message, root, media_store)
            except IntakeBlocked:
                raise
            except Exception:
                raise IntakeBlocked("Telegram media upload to the Source Media Owner failed") from None
        reply_id = getattr(message, "reply_to_msg_id", None)
        if reply_id is not None and endpoint["endpoint_id"] == "telegram:phintraprofits":
            set_stage("resolve_reply_parent")
        parent = await client.get_messages(entity, ids=reply_id) if reply_id is not None and endpoint["endpoint_id"] == "telegram:phintraprofits" else None
        if reply_id is not None and endpoint["endpoint_id"] == "telegram:phintraprofits" and parent is None:
            raise IntakeBlocked("Telegram reply parent is unavailable")
        set_stage("build_envelope")
        item = envelope(endpoint, message, observed_at, reply_parent=parent, media_refs=media_refs, previous_message_id=cursor, bootstrap_message_id=bootstrap_cursor)
        set_stage("stage_handoff")
        handoff.stage(item)
        set_stage("accept_event")
        receipts = handoff.flush(limit=1)
        if len(receipts) != 1:
            raise IntakeBlocked("Telegram source handoff was not acknowledged")
        set_stage("advance_cursor")
        _save_cursor(cursor_path, message.id, bootstrap_cursor=bootstrap_cursor)
        (root / "blocked-media.json").unlink(missing_ok=True)
        cursor = message.id
        accepted += 1
    return {"endpoint_id": endpoint["endpoint_id"], "bootstrapped": False, "cursor": cursor, "accepted": accepted}


async def ingest_all(client: Any, snapshot: dict[str, Any], state_root: Path, inbox: Any, observed_at: datetime, *, media_store: Any = None) -> list[dict[str, Any]]:
    """Pin the catalog revision, then poll each known endpoint independently."""
    selected = endpoints(snapshot)
    bind_catalog_revision(state_root, snapshot["revision"])
    outcomes = []
    for endpoint in selected.values():
        diagnostic = {"stage": "start"}
        try:
            outcomes.append(await ingest_endpoint(
                client,
                endpoint,
                state_root,
                inbox,
                observed_at,
                media_store=media_store,
                stage_callback=lambda value: diagnostic.__setitem__("stage", value),
            ))
        except Exception as error:
            # Keep source text and raw provider exception details out of summaries.
            error_type = type(error).__name__
            if not error_type.isascii() or not error_type.isidentifier():
                error_type = "Error"
            outcomes.append({
                "endpoint_id": endpoint["endpoint_id"],
                "status": "blocked",
                "stage": diagnostic["stage"],
                "error_type": error_type,
            })
    return outcomes
