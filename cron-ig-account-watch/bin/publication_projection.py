"""Receipt-bound Instagram owner projection into the Published Feed."""
from __future__ import annotations

from datetime import datetime
from dataclasses import replace
import os
from pathlib import Path
import sys
from typing import Any

import discord
import render
import scan
import state


OWNER_ID = "bursawatch-ig-account-watch"
RENDERER_VERSION = "instagram-account-watch-v1"
_FLAG = "BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_ENABLED"


def enabled() -> bool:
    return os.environ.get(_FLAG) == "1"


def _client() -> Any:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_IG_ACCOUNT_WATCH_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Instagram publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Instagram publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Instagram publication token file is empty")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents/skills/lib-bursawatch-control/bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient
    return PublicationClient(url, token)


def _delivery_owner() -> Any:
    return discord.delivery_client_from_environment()


def _confirmed_leg(operation: Any, receipt: object, text: str | None) -> dict[str, Any]:
    from bursawatch_discord_delivery import OperationReceipt
    try:
        accepted = OperationReceipt.from_json(receipt, operation)
    except (TypeError, ValueError):
        raise ValueError("Instagram Discord receipt is invalid") from None
    channel = operation.target.get("channel_id")
    if accepted.status != "delivered" or accepted.key != operation.key or accepted.digest != operation.digest:
        raise ValueError("Instagram Discord receipt does not confirm its saved operation")
    details = accepted.receipt
    if not isinstance(details, dict) or details.get("channel_id") != channel:
        raise ValueError("Instagram Discord receipt destination is invalid")
    message_id = details.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise ValueError("Instagram Discord receipt message ID is invalid")
    return {
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt_operation_id": accepted.id,
        "destination": channel,
        "receipt_id": message_id,
        "status": "delivered",
        "message_url": None,
        "text": text,
        "attachments": [
            {"filename": a.filename, "content_type": a.mime_type, "discord_url": None}
            for a in operation.attachments
        ],
    }


def _candidate(event: dict[str, Any], profile: Any, confirmed_at: datetime) -> tuple[dict[str, Any], list[tuple[Any, str | None]]]:
    post = state.deserialize_post(event["post"])
    channel_id = scan._target_channel(profile, event)
    messages = render.render_publication(
        profile, post,
        event.get("summary") if profile.enable_llm_summary else None,
        event.get("title") if profile.enable_llm_title else None,
    )
    if (event.get("is_relevant") is False or event.get("text_index") != len(messages)
            or len(event.get("text_message_ids", [])) != len(messages)):
        raise ValueError("Instagram publication text delivery is incomplete")
    required: list[str] = []
    operations: list[tuple[Any, str | None]] = []
    descriptors = []
    for index, content in enumerate(messages):
        leg = f"text:{index}"
        key = discord.operation_key_for_nonce(discord.nonce(event["event_key"], leg))
        operation = replace(discord._message_operation(content, channel_id, event["event_key"], leg), key=key)
        required.append(key)
        operations.append((operation, content))
        descriptors.append({"operation_key": key, "operation_digest": operation.digest, "destination": channel_id, "text": content,
                            "attachments": [{"filename": a.filename, "content_type": a.mime_type, "discord_url": None} for a in operation.attachments]})
    downloaded_raw = event.get("downloaded_publication")
    if profile.forward_media and downloaded_raw is not None:
        downloaded = state.deserialize_downloaded_publication(downloaded_raw)
        assets = scan._delivery_media(post, downloaded)
        if event.get("media_index") != len(assets) or len(event.get("media_message_ids", [])) != len(assets):
            raise ValueError("Instagram publication media delivery is incomplete")
        for index, asset in enumerate(assets):
            attachment = discord.read_media_attachment(asset.path)
            leg = f"media:{index}"
            operation = replace(
                discord._message_operation("", channel_id, event["event_key"], leg, attachments=(attachment,)),
                key=discord.operation_key_for_nonce(discord.nonce(event["event_key"], leg)),
            )
            required.append(operation.key)
            operations.append((operation, None))
            descriptors.append({"operation_key": operation.key, "operation_digest": operation.digest, "destination": channel_id, "text": None,
                                "attachments": [{"filename": a.filename, "content_type": a.mime_type, "discord_url": None} for a in operation.attachments]})
    if not messages or not required:
        raise ValueError("Instagram publication has no delivered output")
    route = event.get("route")
    if route not in {"macro_news", "id_stocks_news"}:
        raise ValueError("Instagram publication route is not a Published Feed news route")
    title = event.get("title") or messages[0].splitlines()[0].strip().lstrip("# ").strip()
    if not isinstance(title, str) or not title:
        raise ValueError("Instagram publication title is missing")
    owner_key = f"{event['event_key']}"
    kind = "macro_news" if route == "macro_news" else "idx_company_news"
    snapshot = {
        "api_version": 1, "owner_key": owner_key, "version": 1, "supersedes_version": None,
        "type": kind, "route": route, "source_event_key": event["event_key"],
        "source_name": profile.display_name, "source_url": post.url,
        "source_published_at": post.published_at.isoformat(), "market_data_as_of": None,
        "delivery_confirmed_at": confirmed_at.isoformat(), "title": title[:300], "ticker": None,
        "broker_levels": None, "parent_publication_id": None, "board_episode_id": None,
        "config_revision": None, "renderer_version": RENDERER_VERSION,
        "source_version": post.publication_id, "required_operation_keys": required,
        "legs": [], "_receipt_pending": True, "_operation_descriptors": descriptors,
    }
    return snapshot, operations


def record_intent(value: dict, event: dict, profile: Any, confirmed_at: datetime, delivery_owner: Any | None = None) -> bool:
    if not enabled():
        return False
    if event.get("is_relevant") is False or event.get("route") not in {"macro_news", "id_stocks_news"}:
        return False
    snapshot, _operations = _candidate(event, profile, confirmed_at)
    return state.record_publication_intent(value, snapshot)


def record_blocked(value: dict, event: dict, confirmed_at: datetime) -> None:
    """Keep an unrepresentable delivered event visible as outstanding coverage."""
    if not enabled():
        return
    key = f"blocked:{event.get('event_key', 'unknown')}"
    state.record_publication_intent(value, {
        "owner_key": key,
        "delivery_confirmed_at": confirmed_at.isoformat(),
        "_projection_blocked": True,
    })


def _receipt_document(receipt: object) -> dict[str, Any] | None:
    if isinstance(receipt, dict):
        return receipt
    if all(hasattr(receipt, key) for key in ("id", "key", "digest", "status", "receipt")):
        return {key: getattr(receipt, key) for key in ("id", "key", "digest", "status", "receipt")}
    return None


def _resolve_candidate(snapshot: dict[str, Any], owner: Any) -> dict[str, Any] | None:
    legs = []
    for descriptor in snapshot.get("_operation_descriptors", []):
        try:
            raw = owner.status(descriptor["operation_key"])
        except Exception:
            return None
        receipt = _receipt_document(raw)
        if (receipt is None or receipt.get("key") != descriptor["operation_key"]
                or receipt.get("digest") != descriptor["operation_digest"]
                or receipt.get("status") != "delivered" or not isinstance(receipt.get("id"), str)):
            return None
        delivered = receipt.get("receipt")
        if not isinstance(delivered, dict) or delivered.get("channel_id") != descriptor["destination"]:
            return None
        message_id = delivered.get("message_id")
        if not isinstance(message_id, str) or not message_id.isdigit():
            return None
        legs.append({
            "operation_key": descriptor["operation_key"],
            "operation_digest": descriptor["operation_digest"],
            "receipt_operation_id": receipt["id"],
            "destination": descriptor["destination"], "receipt_id": message_id,
            "status": "delivered", "message_url": None, "text": descriptor["text"],
            "attachments": descriptor["attachments"],
        })
    if [item["operation_key"] for item in legs] != snapshot.get("required_operation_keys"):
        return None
    resolved = {key: val for key, val in snapshot.items() if not key.startswith("_")}
    resolved["legs"] = legs
    return resolved


def drain(value: dict, now: datetime, publication_client: Any | None = None, delivery_owner: Any | None = None) -> dict[str, int]:
    if not enabled():
        return {"accepted": 0, "pending": len(state.pending_publication_intents(value))}
    projection = publication_client if publication_client is not None else _client()
    owner = delivery_owner if delivery_owner is not None else _delivery_owner()
    accepted = 0
    for owner_key, snapshot in state.pending_publication_intents(value):
        if snapshot.get("_projection_blocked"):
            continue
        if snapshot.get("_receipt_pending"):
            resolved = _resolve_candidate(snapshot, owner)
            if resolved is None:
                continue
            value["publication_ledger"][owner_key]["snapshot"] = resolved
            snapshot = resolved
        try:
            ack = projection.submit(snapshot)
            state.acknowledge_publication_intent(value, owner_key, ack)
            accepted += 1
        except Exception:
            continue
    try:
        projection.checkpoint(state.publication_checkpoint_comparison(value, now))
    except Exception:
        pass
    return {"accepted": accepted, "pending": len(state.pending_publication_intents(value))}
