"""Durable, receipt-bound Market News projection into the Published Feed."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import state
from domain import Destination, Provider, SourceKind
from selection import SelectionCandidate


OWNER_ID = "bursawatch-tg-market-news"
RENDERER_VERSION = "market-news-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class IncompletePublication(ValueError):
    """A required delivery leg lacks a matching confirmed owner receipt."""


def validate_required_legs(required_operation_keys: object, legs: object) -> list[dict[str, Any]]:
    """Require one complete confirmed receipt record for every durable required key."""
    if (
        not isinstance(required_operation_keys, list)
        or not required_operation_keys
        or any(not isinstance(key, str) or not key for key in required_operation_keys)
        or len(required_operation_keys) != len(set(required_operation_keys))
        or not isinstance(legs, list)
    ):
        raise IncompletePublication("publication required delivery legs are invalid")
    by_key: dict[str, dict[str, Any]] = {}
    for raw in legs:
        if not isinstance(raw, dict) or not isinstance(raw.get("operation_key"), str):
            raise IncompletePublication("publication delivery leg is invalid")
        key = raw["operation_key"]
        if key in by_key or raw.get("status") != "delivered":
            raise IncompletePublication("publication delivery leg is duplicated or unconfirmed")
        digest = raw.get("operation_digest")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise IncompletePublication("publication delivery digest is invalid")
        if not isinstance(raw.get("receipt_operation_id"), str) or not raw["receipt_operation_id"]:
            raise IncompletePublication("publication receipt operation identity is missing")
        destination, receipt_id = raw.get("destination"), raw.get("receipt_id")
        if (
            not isinstance(destination, str) or not destination.isdigit()
            or not isinstance(receipt_id, str) or not receipt_id.isdigit()
        ):
            raise IncompletePublication("publication receipt destination or message identity is invalid")
        if raw.get("receipt_key") != key or raw.get("receipt_digest") != digest:
            raise IncompletePublication("publication receipt does not match its operation")
        if raw.get("receipt_destination") != destination or raw.get("receipt_message_id") != receipt_id:
            raise IncompletePublication("publication receipt does not match its destination")
        by_key[key] = {
            "operation_key": key,
            "operation_digest": digest,
            "receipt_operation_id": raw["receipt_operation_id"],
            "destination": destination,
            "receipt_id": receipt_id,
            "status": "delivered",
            "message_url": raw.get("message_url"),
            "text": raw.get("text"),
            "attachments": raw.get("attachments", []),
        }
    if set(by_key) != set(required_operation_keys):
        raise IncompletePublication("publication is missing a required confirmed delivery leg")
    return [by_key[key] for key in required_operation_keys]


def _stored_receipt_leg(
    operation: Any,
    raw_receipt: object,
    *,
    text: str | None,
) -> dict[str, Any]:
    try:
        from bursawatch_discord_delivery import OperationReceipt

        receipt = OperationReceipt.from_json(raw_receipt, operation)
    except (ImportError, TypeError, ValueError):
        raise IncompletePublication("stored delivery receipt is invalid") from None
    target_channel = operation.target.get("channel_id")
    receipt_destination = (
        receipt.receipt.get("channel_id", target_channel)
        if receipt.receipt is not None else None
    )
    if (
        receipt.status != "delivered"
        or receipt.key != operation.key
        or receipt.digest != operation.digest
        or receipt.receipt is None
        or not isinstance(target_channel, str)
        or not target_channel.isdigit()
        or receipt_destination != target_channel
    ):
        raise IncompletePublication("delivery receipt is not a confirmed matching operation")
    message_id = receipt.receipt.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise IncompletePublication("delivery receipt has no Discord message ID")
    attachments = [
        {
            "filename": item.filename,
            "content_type": item.mime_type,
            "discord_url": None,
        }
        for item in operation.attachments
    ]
    return {
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt_operation_id": receipt.id,
        "destination": target_channel,
        "receipt_id": message_id,
        "status": "delivered",
        "message_url": None,
        "text": text,
        "attachments": attachments,
        "receipt_key": receipt.key,
        "receipt_digest": receipt.digest,
        "receipt_destination": receipt_destination,
        "receipt_message_id": message_id,
    }


def _finish_snapshot(
    *,
    owner_key: str,
    kind: str,
    route: str,
    source_event_key: str | None,
    source_name: str,
    source_url: str,
    source_published_at: str | None,
    title: str,
    ticker: str | None,
    config_revision: int | None,
    source_version: str | None,
    confirmed_at: datetime,
    required_operation_keys: list[str],
    raw_legs: list[dict[str, Any]],
) -> dict[str, Any]:
    legs = validate_required_legs(required_operation_keys, raw_legs)
    return {
        "api_version": 1,
        "owner_key": owner_key,
        "version": 1,
        "supersedes_version": None,
        "type": kind,
        "route": route,
        "source_event_key": source_event_key,
        "source_name": source_name,
        "source_url": source_url,
        "source_published_at": source_published_at,
        "market_data_as_of": None,
        "delivery_confirmed_at": confirmed_at.isoformat(),
        "title": title[:300],
        "ticker": ticker,
        "broker_levels": None,
        "parent_publication_id": None,
        "board_episode_id": None,
        "config_revision": config_revision,
        "renderer_version": RENDERER_VERSION,
        "source_version": source_version,
        "required_operation_keys": required_operation_keys,
        "legs": legs,
    }


def _publication_type(item: SelectionCandidate) -> tuple[str, str]:
    if item.candidate.source_kind is SourceKind.TUNTUN_UPDATE_INDUSTRY:
        return "industry_news", "id_industry_news"
    if item.route is Destination.MACRO_NEWS:
        return "macro_news", "macro_news"
    return "idx_company_news", "id_stocks_news"


def news_snapshot(
    source: Mapping[str, Any],
    item: SelectionCandidate,
    content: str,
    operation: Any,
    receipt_document: object,
    confirmed_at: datetime,
    required_operation_keys: list[str],
) -> dict[str, Any]:
    if source.get("candidate_key") != item.key:
        raise IncompletePublication("news source provenance does not match the candidate")
    kind, route = _publication_type(item)
    first_line = content.splitlines()[0].strip().lstrip("# ").strip()
    title = item.title or first_line
    if not title:
        raise IncompletePublication("news publication has no title")
    leg = _stored_receipt_leg(operation, receipt_document, text=content)
    provenance_key = source.get("event_key")
    if not isinstance(provenance_key, str) or not _SHA256.fullmatch(provenance_key):
        raise IncompletePublication("news source event identity is missing")
    config_revision = source.get("watch_config_revision")
    if config_revision is not None and (type(config_revision) is not int or config_revision < 1):
        raise IncompletePublication("news config revision is invalid")
    return _finish_snapshot(
        owner_key=f"news:{item.key}",
        kind=kind,
        route=route,
        source_event_key=provenance_key,
        source_name="Phintraco" if item.provider is Provider.PHINTRACO else "Tuntun",
        source_url=source["source_url"],
        source_published_at=item.published_at.isoformat(),
        title=title,
        ticker=item.ticker,
        config_revision=config_revision,
        source_version=str(source["version"]),
        confirmed_at=confirmed_at,
        required_operation_keys=required_operation_keys,
        raw_legs=[leg],
    )


def stock_status_snapshot(
    source_event_key: str,
    source_message_id: int,
    source_url: str,
    content: str,
    config_revision: int | None,
    operation: Any,
    receipt_document: object,
    confirmed_at: datetime,
    required_operation_keys: list[str],
) -> dict[str, Any]:
    leg = _stored_receipt_leg(operation, receipt_document, text=content)
    return _finish_snapshot(
        owner_key=f"stock-status:phintraco:{source_message_id}",
        kind="stock_status",
        route="id_stocks_news",
        source_event_key=source_event_key,
        source_name="Phintraco",
        source_url=source_url,
        source_published_at=None,
        title="Phintraco Stock Information",
        ticker=None,
        config_revision=config_revision,
        source_version=None,
        confirmed_at=confirmed_at,
        required_operation_keys=required_operation_keys,
        raw_legs=[leg],
    )


def _feature_enabled() -> bool:
    return os.environ.get("BURSAWATCH_TG_MARKET_NEWS_PUBLICATION_ENABLED") == "1"


def record_news_intent(state_data: dict[str, object], item: SelectionCandidate, confirmed_at: datetime) -> bool:
    if not _feature_enabled():
        return False
    from delivery import _channel_message_operation, _delivery_records
    from news_source_work import provenance

    records = _delivery_records(state_data)
    record = records.get(item.key)
    if not isinstance(record, dict):
        raise state.StateBlockedError("delivered Market News item has no saved output")
    source = provenance(state_data, item.key)
    if source is None:
        # Legacy candidates without source-inbox provenance predate this feed boundary.
        return False
    content, channel_id = record.get("content"), record.get("channel_id")
    handoff = record.get("delivery_handoff")
    if not isinstance(content, str) or not isinstance(channel_id, str) or not isinstance(handoff, dict):
        raise state.StateBlockedError("delivered Market News item has incomplete durable output")
    operation = _channel_message_operation(content, channel_id, f"{item.key}:text")
    required = record.get("required_operation_keys", [operation.key])
    snapshot = news_snapshot(
        source, item, content, operation, handoff.get("receipt"), confirmed_at,
        required if isinstance(required, list) else [],
    )
    snapshot["market_data_as_of"] = record.get("market_data_as_of")
    snapshot["renderer_version"] = record.get("renderer_version", snapshot["renderer_version"])
    return state.record_publication_intent(state_data, snapshot)


def record_stock_status_intent(
    state_data: dict[str, object], event_key: str, confirmed_at: datetime
) -> bool:
    if not _feature_enabled():
        return False
    from delivery import _channel_message_operation

    stats = state_data.get("stats")
    events = stats.get("stock_status_events") if isinstance(stats, dict) else None
    event = events.get(event_key) if isinstance(events, dict) else None
    if not isinstance(event, dict):
        raise state.StateBlockedError("delivered stock status has no durable event")
    source_event_key = event.get("source_event_key")
    if not isinstance(source_event_key, str):
        return False
    message_id, source_url = event.get("source_message_id"), event.get("source_url")
    content, channel_id = event.get("content"), event.get("channel_id")
    handoff = event.get("delivery_handoff")
    if (
        type(message_id) is not int or not isinstance(source_url, str)
        or not isinstance(content, str) or not isinstance(channel_id, str)
        or not isinstance(handoff, dict)
    ):
        raise state.StateBlockedError("delivered stock status has incomplete durable output")
    operation = _channel_message_operation(content, channel_id, event_key)
    snapshot = stock_status_snapshot(
        source_event_key, message_id, source_url, content, event.get("config_revision"),
        operation, handoff.get("receipt"), confirmed_at,
        event.get("required_operation_keys", [operation.key]),
    )
    return state.record_publication_intent(state_data, snapshot)


def publication_client_from_environment() -> Any | None:
    if not _feature_enabled():
        return None
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_TG_MARKET_NEWS_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Market News publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Market News publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Market News publication token file is empty")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents" / "skills" / "lib-bursawatch-control" / "bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient

    return PublicationClient(url, token)


def drain(state_data: dict[str, object], now: datetime, client: Any | None = None) -> dict[str, int]:
    """Retry pending read-model projections independently of Discord delivery."""
    client = client if client is not None else publication_client_from_environment()
    if client is None:
        return {"accepted": 0, "pending": len(state.pending_publication_intents(state_data))}
    accepted = 0
    for owner_key, snapshot in state.pending_publication_intents(state_data):
        try:
            acknowledgment = client.submit(snapshot)
            state.acknowledge_publication_intent(state_data, owner_key, acknowledgment)
            accepted += 1
        except Exception:
            # Preserve the immutable intent for the next owner run.
            continue
    comparison = state.publication_checkpoint_comparison(state_data, now)
    try:
        client.checkpoint(comparison)
    except Exception:
        pass
    return {"accepted": accepted, "pending": len(state.pending_publication_intents(state_data))}
