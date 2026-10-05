"""Receipt-bound Swing Board published actions."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
from typing import Any

import discord_forum
from store import BoardStore, _publication_identity


OWNER_ID = "bursawatch-dc-swing-board"
_FLAG = "IDX_SWING_PLAN_BOARD_PUBLICATION_ENABLED"


def enabled() -> bool:
    raw = os.environ.get("BURSAWATCH_PUBLICATION_CUTOVER_AT")
    if os.environ.get(_FLAG) != "1" or not raw:
        return False
    try:
        boundary = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return boundary.tzinfo is not None and boundary.utcoffset() is not None


def _clients() -> tuple[Any, Any]:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("IDX_SWING_PLAN_BOARD_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Swing Board publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Swing Board publication token permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Swing Board publication token file is empty")
    library = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    if not library.is_dir():
        library = Path.home() / ".agents/skills/lib-bursawatch-control/bin"
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient
    return PublicationClient(url, token), discord_forum.delivery_client_from_environment()


def publication_id(owner_key: str) -> str:
    return _publication_identity(OWNER_ID, owner_key)


def _build_snapshot(saved: dict[str, Any], delivery: Any) -> dict[str, Any] | None:
    from bursawatch_discord_delivery import OperationReceipt
    from dataclasses import asdict

    snapshot = saved["snapshot"]
    operation_name = snapshot["_operation"]
    payload = snapshot["_payload"]
    dedupe_key = snapshot["owner_key"]
    # Select the local fake before any live credential is read, and use it only
    # to reconstruct the exact operation digest from persisted Board intent.
    adapter = discord_forum.DiscordForumClient(no_post=True)
    try:
        operation = adapter._intent(operation_name, payload, dedupe_key)
        raw = delivery.status(operation.key)
        if not isinstance(raw, OperationReceipt):
            return None
        # status() validates the response shape; bind it to this saved operation
        # and validate the receipt kind/target before projecting its delivery.
        receipt = OperationReceipt.from_json(asdict(raw), operation)
    except Exception:
        return None
    details = receipt.receipt
    if receipt.status != "delivered" or receipt.key != operation.key or receipt.digest != operation.digest or not isinstance(details, dict):
        return None
    thread_id = snapshot["_completion"].get("thread_id")
    if operation_name == "create_thread":
        message_id = details.get("message_id")
        if (details.get("thread_id") != thread_id
                or message_id != snapshot["_completion"].get("starter_message_id")):
            return None
        destination = str(thread_id)
        receipt_id = str(message_id)
    elif operation_name in {"post_source_reply", "post_history_reply"}:
        message_id = details.get("message_id")
        destination = str(operation.target.get("thread_id") or "")
        if not destination or details.get("message_id") != snapshot["_completion"].get("message_id"):
            return None
        receipt_id = str(message_id)
    elif operation_name == "edit_starter":
        destination = str(operation.target.get("thread_id") or "")
        receipt_id = str(operation.target.get("message_id") or "")
        if not destination or details.get("message_id") != receipt_id:
            return None
    else:  # thread lifecycle/tag/archive action
        destination = str(operation.target.get("thread_id") or "")
        receipt_id = destination
        if not destination or details.get("thread_id") != destination:
            return None
    if not destination.isdigit() or not receipt_id.isdigit():
        return None
    message_url = None
    if operation_name != "patch_thread":
        message_url = f"https://discord.com/channels/940285152335110204/{destination}/{receipt_id}"
    attachments = [
        {"filename": item.filename, "content_type": item.mime_type, "discord_url": None}
        for item in operation.attachments
    ]
    leg = {
        "operation_key": operation.key, "operation_digest": operation.digest,
        "receipt_operation_id": receipt.id, "destination": destination,
        "receipt_id": receipt_id, "status": "delivered", "message_url": message_url,
        "text": operation.payload.get("content") if isinstance(operation.payload.get("content"), str) and operation.payload.get("content") else None,
        "attachments": attachments,
    }
    return {
        key: value for key, value in snapshot.items() if not key.startswith("_")
    } | {"required_operation_keys": [operation.key], "legs": [leg]}


def checkpoint_comparison(store: BoardStore, compared_at: datetime) -> dict[str, Any]:
    rows = store.all_publication_intents()
    ordered = sorted(rows, key=lambda row: (row["snapshot"]["delivery_confirmed_at"], row["id"]))
    confirmed = max((row["snapshot"]["delivery_confirmed_at"] for row in rows), default=None)
    accepted = None
    for row in ordered:
        if row["ack"] is None:
            break
        accepted = row["snapshot"]["delivery_confirmed_at"]
    if confirmed is not None and all(row["ack"] is not None for row in rows):
        accepted = confirmed
    return {
        "compared_at": compared_at.astimezone(timezone.utc).isoformat(),
        "confirmed_through_at": confirmed,
        "accepted_through_at": accepted,
        "outstanding_count": sum(row["ack"] is None for row in rows),
    }


def drain(store: BoardStore, now: datetime, *, publication_client: Any | None = None,
          delivery_owner: Any | None = None) -> dict[str, int]:
    if not enabled():
        return {"accepted": 0, "pending": len(store.all_publication_intents())}
    try:
        if publication_client is None or delivery_owner is None:
            configured_client, configured_owner = _clients()
            publication_client = publication_client or configured_client
            delivery_owner = delivery_owner or configured_owner
    except Exception:
        return {"accepted": 0, "pending": len(store.all_publication_intents())}
    accepted = 0
    for saved in store.pending_publication_intents(now):
        owner_key = saved["owner_key"]
        try:
            snapshot = _build_snapshot(saved, delivery_owner)
            if snapshot is None:
                store.fail_publication_intent(owner_key, now, "receipt_unavailable")
                continue
            ack = publication_client.submit(snapshot)
            if (set(ack) != {"publication_id", "version", "digest"}
                    or ack.get("publication_id") != publication_id(owner_key)
                    or ack.get("version") != 1
                    or not isinstance(ack.get("digest"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", ack["digest"])):
                store.fail_publication_intent(owner_key, now, "ack_invalid")
                continue
            store.acknowledge_publication_intent(owner_key, ack)
            accepted += 1
        except Exception:
            store.fail_publication_intent(owner_key, now, "projection_unavailable")
    comparison = checkpoint_comparison(store, now)
    try:
        ack = publication_client.checkpoint(comparison)
        if (set(ack) == {"compared_at", "confirmed_through_at", "accepted_through_at", "outstanding_count"}
                and ack.get("compared_at") == comparison["compared_at"]
                and ack.get("confirmed_through_at") == comparison["confirmed_through_at"]
                and ack.get("accepted_through_at") == comparison["accepted_through_at"]
                and ack.get("outstanding_count") == comparison["outstanding_count"]):
            store.save_publication_checkpoint(comparison, ack)
    except Exception:
        pass
    return {"accepted": accepted, "pending": len(store.all_publication_intents()) - sum(
        1 for row in store.all_publication_intents() if row["ack"] is not None
    )}
