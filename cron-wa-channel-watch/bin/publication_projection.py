"""Receipt-bound WhatsApp Channel owner projection into the Published Feed."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any

import archive
import discord
import render
import state
from normalize import deserialize_queue_event


OWNER_ID = "bursawatch-wa-channel-watch"
RENDERER_VERSION = "whatsapp-channel-watch-v1"
_FLAG = "BURSAWATCH_WA_CHANNEL_WATCH_PUBLICATION_ENABLED"


def enabled() -> bool:
    return os.environ.get(_FLAG) == "1"


def _client() -> Any:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_WA_CHANNEL_WATCH_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("WhatsApp publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("WhatsApp publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("WhatsApp publication token file is empty")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents/skills/lib-bursawatch-control/bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient
    return PublicationClient(url, token)


def _delivery_owner() -> Any:
    return discord.delivery_client_from_environment()


def publication_type_for_route(route: str) -> str:
    return {
        "id_stocks_news": "idx_company_news",
        "id_industry_news": "industry_news",
        "macro_news": "macro_news",
        "id_stocks_swing": "swing_context",
    }[route]


def _receipt_document(receipt: object) -> dict[str, Any] | None:
    if isinstance(receipt, dict):
        return receipt
    if all(hasattr(receipt, key) for key in ("id", "key", "digest", "status", "receipt")):
        return {key: getattr(receipt, key) for key in ("id", "key", "digest", "status", "receipt")}
    return None


def _capture_record(value: dict[str, object], record: dict[str, Any], profiles: dict[str, Any], archive_root: Path, confirmed_at: datetime) -> list[dict[str, Any]]:
    import scan
    from normalize import deserialize_queue_event
    if record.get("agent_phase") != "delivered":
        return []
    try:
        event = deserialize_queue_event(record["event"])
        profile = profiles[str(record["profile_id"])]
    except (KeyError, TypeError, ValueError):
        return []
    if not profile.is_forwarding or not isinstance(record.get("items"), list):
        return []
    raw_items = record["items"]
    if not raw_items or any(not isinstance(item, dict) for item in raw_items):
        return []
    try:
        archive_rows = archive.query(archive_root, event_key=event.event_key)
        media_rows = archive_rows[0].data.get("media", []) if len(archive_rows) == 1 else []
        by_media = {item["index"]: item for item in media_rows if isinstance(item, dict) and item.get("capture_status") == "captured"}
        text_operations: list[tuple[int, int, Any, str]] = []
        owner_keys: list[str] = []
        selected: list[tuple[int, str, dict[str, Any], list[str]]] = []
        for item_index, item in enumerate(raw_items):
            route = item.get("route")
            if route not in {"macro_news", "id_stocks_news", "id_industry_news", "id_stocks_swing"}:
                continue
            channel_id = scan._delivery_channel(profile, item)
            create_messages = render.render_post(
                profile, event,
                title=item.get("title") if profile.enable_llm_title else None,
                summary=item.get("summary") if profile.enable_llm_summary else None,
                route=route, sentiment=item.get("sentiment"), board_url=None,
            )
            board_ack = record.get("board_acknowledgement")
            board_url = (
                board_ack.get("board_url")
                if route == "id_stocks_swing" and record.get("board_link_phase") == "patched"
                and isinstance(board_ack, dict) and isinstance(board_ack.get("board_url"), str)
                else None
            )
            messages = render.render_post(
                profile, event,
                title=item.get("title") if profile.enable_llm_title else None,
                summary=item.get("summary") if profile.enable_llm_summary else None,
                route=route, sentiment=item.get("sentiment"), board_url=board_url,
            )
            if not messages or len(create_messages) != len(messages):
                continue
            owner_key = f"{event.event_key}:item:{item_index}"
            owner_keys.append(owner_key)
            selected.append((item_index, owner_key, item, messages))
            for message_index, content in enumerate(create_messages):
                nonce = discord.nonce(event.event_key, f"item:{item_index}:text:{message_index}")
                op = discord._message_operation(content, channel_id, nonce)
                text_operations.append((item_index, message_index, op, messages[message_index]))
        if not owner_keys:
            return []
        descriptor_groups: dict[str, list[dict[str, Any]]] = {key: [] for key in owner_keys}
        for item_index, message_index, operation, content in text_operations:
            owner_key = f"{event.event_key}:item:{item_index}"
            descriptor_groups[owner_key].append({
                "operation_key": operation.key, "operation_digest": operation.digest,
                "destination": operation.target["channel_id"], "text": content,
                "attachments": [],
            })
        if profile.forward_media:
            media_indexes = scan.agent_protocol.media_delivery_indexes(item_count=len(raw_items), media_count=len(event.media))
            skipped = set(record.get("media_skipped_indexes", []))
            delivered_assets = [by_media[index] for index in media_indexes if index not in skipped and index in by_media]
            for pos, media_row in enumerate(delivered_assets):
                index = media_row["index"]
                relative = media_row.get("archive_path")
                path = archive_root / str(relative)
                data = path.read_bytes()
                from bursawatch_discord_delivery import Attachment
                attachment = Attachment(discord.media_filename(media_row["kind"], media_row.get("mime"), index), media_row.get("mime") or "application/octet-stream", data)
                target = descriptor_groups[owner_keys[0]][0]["destination"]
                nonce = discord.nonce(event.event_key, f"media:{index}")
                operation = discord._message_operation("", target, nonce, attachment=attachment)
                descriptor_groups[owner_keys[0]].append({
                    "operation_key": operation.key, "operation_digest": operation.digest,
                    "destination": target, "text": None,
                    "attachments": [{"filename": attachment.filename, "content_type": attachment.mime_type, "discord_url": None}],
                })
        result: list[dict[str, Any]] = []
        for item_index, owner_key, item, messages in selected:
            descriptors = descriptor_groups[owner_key]
            route = item["route"]
            kind = publication_type_for_route(route)
            title = item.get("title") or messages[0].splitlines()[0].strip().lstrip("# ").strip()
            if not isinstance(title, str) or not title:
                continue
            result.append({
                "api_version": 1, "owner_key": owner_key, "version": 1, "supersedes_version": None,
                "type": kind, "route": route, "source_event_key": event.event_key,
                "source_name": profile.display_name, "source_url": profile.channel_url,
                "source_published_at": event.published_at.isoformat(), "market_data_as_of": None,
                "delivery_confirmed_at": str(record.get("delivered_at") or confirmed_at.isoformat()), "title": title[:300], "ticker": None,
                "broker_levels": None, "parent_publication_id": None, "board_episode_id": None,
                "config_revision": None, "renderer_version": RENDERER_VERSION,
                "source_version": event.message_id,
                "required_operation_keys": [row["operation_key"] for row in descriptors], "legs": [],
                "_receipt_pending": True, "_operation_descriptors": descriptors,
            })
        return result
    except Exception:
        return []


def record_intents(value: dict[str, object], profiles: dict[str, Any], archive_root: Path, confirmed_at: datetime) -> int:
    if not enabled():
        return 0
    created = 0
    for record in value.get("outbox", []):
        if not isinstance(record, dict):
            continue
        if record.get("agent_phase") != "delivered":
            continue
        profile = profiles.get(str(record.get("profile_id")))
        if profile is not None and not profile.is_forwarding:
            continue
        snapshots = _capture_record(value, record, profiles, archive_root, confirmed_at)
        if not snapshots:
            owner_key = f"blocked:{record.get('event_key', 'unknown')}"
            state.record_publication_intent(value, {
                "owner_key": owner_key,
                "delivery_confirmed_at": str(record.get("delivered_at") or confirmed_at.isoformat()),
                "_projection_blocked": True,
            })
        for snapshot in snapshots:
            created += int(state.record_publication_intent(value, snapshot))
    return created


def _resolve(snapshot: dict[str, Any], owner: Any) -> dict[str, Any] | None:
    legs = []
    for descriptor in snapshot.get("_operation_descriptors", []):
        try:
            receipt = _receipt_document(owner.status(descriptor["operation_key"]))
        except Exception:
            return None
        if (receipt is None or receipt.get("key") != descriptor["operation_key"]
                or receipt.get("digest") != descriptor["operation_digest"] or receipt.get("status") != "delivered"):
            return None
        delivered = receipt.get("receipt")
        if not isinstance(delivered, dict) or delivered.get("channel_id") != descriptor["destination"]:
            return None
        message_id = delivered.get("message_id")
        if not isinstance(message_id, str) or not message_id.isdigit() or not isinstance(receipt.get("id"), str):
            return None
        legs.append({
            "operation_key": descriptor["operation_key"], "operation_digest": descriptor["operation_digest"],
            "receipt_operation_id": receipt["id"], "destination": descriptor["destination"],
            "receipt_id": message_id, "status": "delivered", "message_url": None,
            "text": descriptor["text"], "attachments": descriptor["attachments"],
        })
    if not legs or [item["operation_key"] for item in legs] != snapshot.get("required_operation_keys"):
        return None
    result = {key: val for key, val in snapshot.items() if not key.startswith("_")}
    result["legs"] = legs
    return result


def drain(value: dict[str, object], now: datetime, publication_client: Any | None = None, delivery_owner: Any | None = None) -> dict[str, int]:
    if not enabled():
        return {"accepted": 0, "pending": len(state.pending_publication_intents(value))}
    projection = publication_client if publication_client is not None else _client()
    owner = delivery_owner if delivery_owner is not None else _delivery_owner()
    accepted = 0
    for owner_key, snapshot in state.pending_publication_intents(value):
        if snapshot.get("_projection_blocked"):
            continue
        if snapshot.get("_receipt_pending"):
            resolved = _resolve(snapshot, owner)
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
