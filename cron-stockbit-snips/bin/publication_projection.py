"""Durable, receipt-bound Stockbit projection into the Published Feed."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any

import discord
import state
from models import Analysis, Article, Route


OWNER_ID = "bursawatch-stockbit-snips"
RENDERER_VERSION = "stockbit-snips-v1"


class IncompletePublication(ValueError):
    """A Stockbit delivery lacks a matching confirmed Delivery Owner receipt."""


def _feature_enabled() -> bool:
    return os.environ.get("BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_ENABLED") == "1"


def _receipt_leg(
    article_key: str,
    content: str,
    channel_id: str,
    receipt_document: object,
) -> tuple[list[str], list[dict[str, Any]]]:
    from bursawatch_discord_delivery import OperationReceipt

    operation, _nonce = discord._operation(content, channel_id, article_key, "news")
    try:
        receipt = OperationReceipt.from_json(receipt_document, operation)
    except (TypeError, ValueError):
        raise IncompletePublication("saved Stockbit delivery receipt is invalid") from None
    receipt_value = receipt.receipt
    if (
        receipt.status != "delivered"
        or receipt.key != operation.key
        or receipt.digest != operation.digest
        or not isinstance(receipt_value, dict)
        or receipt_value.get("channel_id") != channel_id
        or not isinstance(receipt_value.get("message_id"), str)
        or not receipt_value["message_id"].isdigit()
    ):
        raise IncompletePublication("Stockbit delivery receipt does not confirm its operation")
    return [operation.key], [{
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt_operation_id": receipt.id,
        "destination": channel_id,
        "receipt_id": receipt_value["message_id"],
        "status": "delivered",
        "message_url": None,
        "text": content,
        "attachments": [],
    }]


def _snapshot(value: dict[str, object], article_key: str, confirmed_at: datetime) -> dict[str, Any] | None:
    articles = value.get("articles")
    record = articles.get(article_key) if isinstance(articles, dict) else None
    if not isinstance(record, dict):
        raise IncompletePublication("Stockbit article has no durable owner record")
    # The source adapter's accepted work is the authority for forward-only eligibility.
    source_work = record.get("source_work")
    if not isinstance(source_work, dict):
        return None
    event_key = source_work.get("event_key")
    if not isinstance(event_key, str) or len(event_key) != 64 or any(c not in "0123456789abcdef" for c in event_key):
        raise IncompletePublication("Stockbit source event identity is invalid")
    article = state.article_from_record(article_key, record)
    feed_records = value.get("feeds")
    feed_record = feed_records.get(article.lane.value) if isinstance(feed_records, dict) else None
    if isinstance(feed_record, dict) and feed_record.get("enabled") is False:
        return None
    analysis_data = record.get("analysis")
    if not isinstance(analysis_data, dict):
        raise IncompletePublication("Stockbit article has no saved analysis")
    try:
        analysis = Analysis(
            candidate_key=article_key,
            ticker=analysis_data["ticker"],
            title=analysis_data["title"],
            summary=analysis_data["summary"],
            material_facts=tuple(analysis_data["material_facts"]),
            dedupe_facts=tuple(analysis_data["dedupe_facts"]),
            eligible=analysis_data["eligible"],
            route=Route(analysis_data["route"]),
            source_evidence=analysis_data["source_evidence"],
        )
    except (KeyError, TypeError, ValueError):
        raise IncompletePublication("Stockbit saved analysis is invalid") from None
    if analysis.route is Route.EXCLUDE or not analysis.eligible:
        return None
    if analysis.route is Route.ID_STOCKS_NEWS:
        publication_type = "idx_company_news"
    elif analysis.route is Route.MACRO_NEWS:
        publication_type = "macro_news"
    else:
        raise IncompletePublication("Stockbit article route is invalid")
    frozen = record.get("config_snapshot")
    if not state._valid_config_snapshot(frozen):
        raise IncompletePublication("Stockbit article has no valid frozen configuration")
    delivery = record.get("delivery")
    content, channel_id = record.get("rendered"), delivery.get("channel_id") if isinstance(delivery, dict) else None
    receipt_document = delivery.get("receipt") if isinstance(delivery, dict) else None
    if not isinstance(content, str) or not isinstance(channel_id, str) or not isinstance(delivery, dict):
        raise IncompletePublication("Stockbit delivered article has incomplete saved output")
    required_keys, legs = _receipt_leg(article_key, content, channel_id, receipt_document)
    if (
        delivery.get("message_id") != legs[0]["receipt_id"]
        or delivery.get("operation_key") != legs[0]["operation_key"]
        or delivery.get("operation_digest") != legs[0]["operation_digest"]
    ):
        raise IncompletePublication("Stockbit owner receipt fields do not match the saved delivery")
    return {
        "api_version": 1,
        "owner_key": f"article:{article_key}",
        "version": 1,
        "supersedes_version": None,
        "type": publication_type,
        "route": analysis.route.value,
        "source_event_key": event_key,
        "source_name": "Stockbit",
        "source_url": article.url,
        "source_published_at": article.published_at.isoformat(),
        "market_data_as_of": None,
        "delivery_confirmed_at": delivery.get("delivered_at", confirmed_at.isoformat()),
        "title": analysis.title[:300],
        "ticker": analysis.ticker if analysis.route is Route.ID_STOCKS_NEWS else None,
        "broker_levels": None,
        "parent_publication_id": None,
        "board_episode_id": None,
        "config_revision": frozen["revision"],
        "renderer_version": RENDERER_VERSION,
        "source_version": str(source_work.get("version", "1")),
        "required_operation_keys": required_keys,
        "legs": legs,
    }


def record_intent(value: dict[str, object], article_key: str, confirmed_at: datetime) -> bool:
    if not _feature_enabled():
        return False
    snapshot = _snapshot(value, article_key, confirmed_at)
    if snapshot is None:
        return False
    return state.record_publication_intent(value, snapshot)


def publication_client_from_environment() -> Any | None:
    if not _feature_enabled():
        return None
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Stockbit publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Stockbit publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Stockbit publication token file is empty")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents" / "skills" / "lib-bursawatch-control" / "bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient

    return PublicationClient(url, token)


def drain(
    value: dict[str, object], path: Path, now: datetime, client: Any | None = None,
) -> dict[str, int]:
    """Drain immutable intents and save acknowledgments without calling Discord."""
    client = client if client is not None else publication_client_from_environment()
    if client is None:
        return {"accepted": 0, "pending": len(state.pending_publication_intents(value))}
    accepted = 0
    for owner_key, snapshot in state.pending_publication_intents(value):
        try:
            ack = client.submit(snapshot)
            state.acknowledge_publication_intent(value, owner_key, ack)
            state.save_state(path, value)
            accepted += 1
        except Exception:
            # Retry the same frozen snapshot next run. Never re-enter Discord delivery here.
            continue
    comparison = state.publication_checkpoint_comparison(value, now)
    try:
        client.checkpoint(comparison)
    except Exception:
        pass
    return {"accepted": accepted, "pending": len(state.pending_publication_intents(value))}
