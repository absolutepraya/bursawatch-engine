"""Receipt-bound Kelas Investasi publication projection."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sys
from typing import Any

import discord
import state


OWNER_ID = "bursawatch-tg-kelas-investasi-gtw"
RENDERER_VERSION = "kelas-gtw-v1"
_FLAG = "BURSAWATCH_TG_KELAS_INVESTASI_GTW_PUBLICATION_ENABLED"


class IncompletePublication(ValueError):
    """The owner lacks confirmed receipts for every required delivery leg."""


def enabled() -> bool:
    return os.environ.get(_FLAG) == "1"


def publication_id(owner_key: str) -> str:
    import json
    raw = json.dumps([OWNER_ID, owner_key], separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _cutover() -> datetime | None:
    raw = os.environ.get("BURSAWATCH_PUBLICATION_CUTOVER_AT")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo is not None and value.utcoffset() is not None else None


def _ledger(value: dict[str, Any]) -> dict[str, Any]:
    ledger = value["publication_projection"]
    if type(ledger) is not dict or set(ledger) != {"records", "checkpoint_ack"} or type(ledger["records"]) is not dict:
        raise ValueError("Kelas Investasi publication ledger is invalid")
    return ledger


def _descriptor(event: dict[str, Any], state_path: Path, media_root: Path, channel_id: str) -> tuple[dict[str, Any], list[tuple[Any, str | None]]]:
    from bursawatch_discord_delivery import Attachment

    chunks = discord.render_event(event)
    from render import saved_presentation
    presentation = saved_presentation(event)
    if presentation is not None:
        channel_id = presentation["destination"]
    text_ids = event.get("text_message_ids")
    media = discord._media(event)
    if (event.get("text_index") != len(chunks) or not isinstance(text_ids, list)
            or len(text_ids) != len(chunks) or event.get("next_media_index") != len(media)):
        raise IncompletePublication("Kelas Investasi delivery is incomplete")
    if not chunks or any(not isinstance(item, str) or not item.isdigit() for item in text_ids):
        raise IncompletePublication("Kelas Investasi text receipt evidence is incomplete")
    operations: list[tuple[Any, str | None]] = []
    descriptors: list[dict[str, Any]] = []
    for index, content in enumerate(chunks):
        operation = discord._message_operation(content, channel_id, event["event_key"], leg=f"text:{index}")
        operations.append((operation, content))
        descriptors.append({"operation_key": operation.key, "operation_digest": operation.digest,
                            "destination": channel_id, "text": content, "attachments": []})
    for index, item in enumerate(media):
        path = discord._media_path(item, media_root)
        try:
            data = path.read_bytes()
        except OSError:
            raise IncompletePublication("Kelas Investasi cached image is unavailable") from None
        if not data:
            raise IncompletePublication("Kelas Investasi cached image is empty")
        attachment = Attachment(path.name, discord._mime_type(path), data)
        operation = discord._message_operation("", channel_id, event["event_key"],
                                               leg=f"media:{index}", attachments=(attachment,))
        operations.append((operation, None))
        descriptors.append({"operation_key": operation.key, "operation_digest": operation.digest,
                            "destination": channel_id, "text": None,
                            "attachments": [{"filename": attachment.filename,
                                             "content_type": attachment.mime_type,
                                             "discord_url": None}]})
    if not operations:
        raise IncompletePublication("Kelas Investasi publication has no delivered legs")
    published_at = event.get("source_published_at")
    if not isinstance(published_at, str):
        raise IncompletePublication("Kelas Investasi source timestamp is unavailable")
    key = str(event["event_key"])
    title = event.get("title")
    summary = event.get("summary")
    if not isinstance(title, str) or not title or not isinstance(summary, str) or not summary:
        raise IncompletePublication("Kelas Investasi validated output is unavailable")
    confirmed_at = event.get("all_delivery_completed_at")
    if not isinstance(confirmed_at, str):
        raise IncompletePublication("Kelas Investasi delivery confirmation time is unavailable")
    snapshot = {
        "api_version": 1, "owner_key": key, "version": 1, "supersedes_version": None,
        "type": "swing_bundle", "route": "id_stocks_swing", "source_event_key": key,
        "source_name": "Kelas Investasi", "source_url": f"https://t.me/kelasinvestasiid/{event['header_message_id']}",
        "source_published_at": published_at, "market_data_as_of": None,
        "delivery_confirmed_at": confirmed_at,
        "title": title[:300], "ticker": event["ticker"], "broker_levels": None,
        "parent_publication_id": None, "board_episode_id": None, "config_revision": None,
        "renderer_version": RENDERER_VERSION, "source_version": "kelas-gtw-bundle-v1",
        "required_operation_keys": [operation.key for operation, _ in operations], "legs": [],
        "_operation_descriptors": descriptors,
    }
    return snapshot, operations


def record_confirmed_outbox(value: dict[str, Any], state_path: Path, now: datetime,
                            *, channel_id: str = discord.DISCORD_CHANNEL_ID,
                            media_root: Path | None = None) -> int:
    cutover = _cutover()
    if not enabled() or cutover is None:
        return 0
    root = (media_root or discord._configured_media_root(state_path)).resolve()
    ledger = _ledger(value)["records"]
    created = 0
    for event in value.get("outbox", []):
        if not isinstance(event, dict):
            continue
        try:
            snapshot, _operations = _descriptor(event, state_path, root, channel_id)
        except (IncompletePublication, OSError, ValueError):
            continue
        if datetime.fromisoformat(snapshot["delivery_confirmed_at"].replace("Z", "+00:00")).astimezone(timezone.utc) < cutover:
            continue
        key = snapshot["owner_key"]
        prior = ledger.get(key)
        if prior is not None:
            if prior.get("snapshot") != snapshot:
                # The first durable intent is immutable; retries keep its exact timestamp and digest.
                stable = dict(snapshot)
                stable["delivery_confirmed_at"] = prior["snapshot"].get("delivery_confirmed_at")
                if prior.get("snapshot") != stable:
                    raise ValueError("Kelas Investasi publication identity conflicts with its snapshot")
            continue
        ledger[key] = {"snapshot": snapshot, "ack": None}
        state.save_state(state_path, value)
        created += 1
    return created


def pending_publication_intents(value: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    records = _ledger(value)["records"]
    return sorted(((key, row["snapshot"]) for key, row in records.items() if row["ack"] is None),
                  key=lambda pair: (pair[1]["delivery_confirmed_at"], pair[0]))


def _clients() -> tuple[Any, Any]:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_TG_KELAS_INVESTASI_GTW_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Kelas Investasi publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Kelas Investasi publication token permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Kelas Investasi publication token file is empty")
    library = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    if not library.is_dir():
        library = Path.home() / ".agents/skills/lib-bursawatch-control/bin"
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient
    return PublicationClient(url, token), discord.delivery_client_from_environment()


def _resolve(snapshot: dict[str, Any], operations: list[tuple[Any, str | None]], owner: Any) -> dict[str, Any] | None:
    from bursawatch_discord_delivery import OperationReceipt

    legs = []
    for (operation, text), descriptor in zip(operations, snapshot["_operation_descriptors"], strict=True):
        try:
            raw = owner.status(operation.key)
            receipt = OperationReceipt.from_json(raw, operation)
        except Exception:
            return None
        delivered = receipt.receipt
        if (receipt.status != "delivered" or receipt.key != operation.key or receipt.digest != operation.digest
                or not isinstance(delivered, dict) or delivered.get("channel_id") != descriptor["destination"]):
            return None
        message_id = delivered.get("message_id")
        if not isinstance(message_id, str) or not message_id.isdigit():
            return None
        legs.append({"operation_key": operation.key, "operation_digest": operation.digest,
                     "receipt_operation_id": receipt.id, "destination": descriptor["destination"],
                     "receipt_id": message_id, "status": "delivered", "message_url": None,
                     "text": text, "attachments": descriptor["attachments"]})
    resolved = {key: value for key, value in snapshot.items() if not key.startswith("_")}
    resolved["legs"] = legs
    return resolved


def checkpoint_comparison(value: dict[str, Any], compared_at: datetime) -> dict[str, Any]:
    records = _ledger(value)["records"]
    ordered = sorted(records.items(), key=lambda pair: (pair[1]["snapshot"]["delivery_confirmed_at"], pair[0]))
    confirmed = max((row["snapshot"]["delivery_confirmed_at"] for row in records.values()), default=None)
    accepted = None
    for _key, row in ordered:
        if row["ack"] is None:
            break
        accepted = row["snapshot"]["delivery_confirmed_at"]
    if confirmed is not None and all(row["ack"] is not None for row in records.values()):
        accepted = confirmed
    return {"compared_at": compared_at.astimezone(timezone.utc).isoformat(),
            "confirmed_through_at": confirmed, "accepted_through_at": accepted,
            "outstanding_count": sum(row["ack"] is None for row in records.values())}


def drain(value: dict[str, Any], state_path: Path, now: datetime, *,
          publication_client: Any | None = None, delivery_owner: Any | None = None,
          dry_run: bool = False) -> dict[str, int]:
    pending = pending_publication_intents(value)
    if dry_run or not enabled():
        return {"accepted": 0, "pending": len(pending)}
    try:
        if publication_client is None or delivery_owner is None:
            configured_client, configured_owner = _clients()
            publication_client = publication_client or configured_client
            delivery_owner = delivery_owner or configured_owner
    except Exception:
        return {"accepted": 0, "pending": len(pending)}
    accepted = 0
    records = _ledger(value)["records"]
    for owner_key, snapshot in pending:
        try:
            if "_operation_descriptors" in snapshot:
                event = next(item for item in value["outbox"] if item.get("event_key") == owner_key)
                destination = snapshot["_operation_descriptors"][0]["destination"]
                operations = _descriptor(event, state_path, discord._configured_media_root(state_path), destination)[1]
                resolved = _resolve(snapshot, operations, delivery_owner)
                if resolved is None:
                    continue
                records[owner_key]["snapshot"] = resolved
                state.save_state(state_path, value)
                snapshot = resolved
            ack = publication_client.submit(snapshot)
            if (set(ack) != {"publication_id", "version", "digest"}
                    or ack.get("publication_id") != publication_id(owner_key)
                    or ack.get("version") != 1 or not isinstance(ack.get("digest"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", ack["digest"])):
                continue
            records[owner_key]["ack"] = ack
            state.save_state(state_path, value)
            accepted += 1
        except Exception:
            continue
    try:
        checkpoint_ack = publication_client.checkpoint(checkpoint_comparison(value, now))
        _ledger(value)["checkpoint_ack"] = checkpoint_ack
        state.save_state(state_path, value)
    except Exception:
        pass
    return {"accepted": accepted, "pending": len(pending_publication_intents(value))}
