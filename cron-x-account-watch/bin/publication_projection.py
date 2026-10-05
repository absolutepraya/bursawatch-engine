"""Receipt-bound X publication snapshots for the Published feed."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from models import Profile


OWNER_ID = "bursawatch-x-account-watch"
RENDERER_VERSION = "x-account-watch-v1"
MAX_PUBLICATION_LEGS = 64
_LEDGER_KEY = "publication_projection"
_TICKER = re.compile(r"^([A-Z0-9][A-Z0-9.\-]{0,19}):(?:\s|$)")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ROUTES = {
    "id_stocks_news": "idx_company_news",
    "us_stocks_news": "us_company_news",
    "macro_news": "macro_news",
    "id_stocks_swing": "swing_context",
}


class IncompletePublication(ValueError):
    """A required delivery leg lacks matching confirmed receipt evidence."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def publication_id(owner_key: str) -> str:
    return hashlib.sha256(_canonical([OWNER_ID, owner_key])).hexdigest()


def _ledger(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    projection = state.setdefault(_LEDGER_KEY, {"records": {}})
    if type(projection) is not dict or set(projection) != {"records"} or type(projection["records"]) is not dict:
        raise ValueError("X publication ledger is invalid")
    for record in projection["records"].values():
        if type(record) is not dict or set(record) != {"delivery_id", "snapshot", "ack"}:
            raise ValueError("X publication record is invalid")
        if type(record["delivery_id"]) is not str or type(record["snapshot"]) is not dict:
            raise ValueError("X publication record is invalid")
        if record["ack"] is not None and type(record["ack"]) is not dict:
            raise ValueError("X publication acknowledgment is invalid")
    return projection["records"]


def confirmed_leg(operation: Any, receipt: Any, *, text: str | None) -> dict[str, Any]:
    """Return safe, JSON-serializable evidence for one confirmed Discord operation."""
    receipt_value = getattr(receipt, "receipt", None)
    channel_id = operation.target.get("channel_id")
    message_id = receipt_value.get("message_id") if isinstance(receipt_value, dict) else None
    receipt_channel_id = receipt_value.get("channel_id") if isinstance(receipt_value, dict) else None
    if (
        getattr(receipt, "status", None) != "delivered"
        or getattr(receipt, "key", None) != operation.key
        or not isinstance(getattr(receipt, "digest", None), str)
        or len(receipt.digest) != 64
        or any(character not in "0123456789abcdef" for character in receipt.digest)
        or not isinstance(getattr(receipt, "id", None), str)
        or not receipt.id
        or not isinstance(channel_id, str)
        or receipt_channel_id not in (None, channel_id)
        or not isinstance(message_id, str)
        or not message_id.isdigit()
    ):
        raise IncompletePublication("X delivery receipt does not confirm its operation")
    attachments = [
        {"filename": attachment.filename, "content_type": attachment.mime_type, "discord_url": None}
        for attachment in operation.attachments
    ]
    return {
        "operation_key": operation.key,
        # A legacy-nonce adoption may intentionally submit a reconciled
        # operation whose digest differs from the base intent. The delivery
        # client has already validated this receipt against that submitted
        # operation, so persist the digest the owner actually confirmed.
        "operation_digest": receipt.digest,
        "receipt_operation_id": receipt.id,
        "destination": channel_id,
        "receipt_id": message_id,
        "status": "delivered",
        "message_url": None,
        "text": text,
        "attachments": attachments,
        "receipt_key": receipt.key,
        "receipt_digest": receipt.digest,
        "receipt_destination": channel_id,
        "receipt_message_id": message_id,
    }


def _validated_legs(raw_legs: object) -> tuple[list[str], list[dict[str, Any]]]:
    if type(raw_legs) is not list or not raw_legs or len(raw_legs) > MAX_PUBLICATION_LEGS:
        raise IncompletePublication("X publication has an invalid number of delivery legs")
    required: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    for raw in raw_legs:
        if type(raw) is not dict:
            raise IncompletePublication("X publication delivery leg is invalid")
        key = raw.get("operation_key")
        digest = raw.get("operation_digest")
        receipt_id = raw.get("receipt_id")
        destination = raw.get("destination")
        if (
            not isinstance(key, str) or not key or key in by_key
            or not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            or raw.get("status") != "delivered"
            or not isinstance(raw.get("receipt_operation_id"), str) or not raw["receipt_operation_id"]
            or not isinstance(destination, str) or not destination.isdigit()
            or not isinstance(receipt_id, str) or not receipt_id.isdigit()
            or raw.get("receipt_key") != key
            or raw.get("receipt_digest") != digest
            or raw.get("receipt_destination") != destination
            or raw.get("receipt_message_id") != receipt_id
        ):
            raise IncompletePublication("X publication delivery receipt is invalid")
        attachments = raw.get("attachments")
        if type(attachments) is not list or any(
            type(item) is not dict
            or set(item) != {"filename", "content_type", "discord_url"}
            or type(item.get("filename")) is not str
            or type(item.get("content_type")) is not str
            or item.get("discord_url") is not None
            for item in attachments
        ):
            raise IncompletePublication("X publication attachment metadata is invalid")
        text = raw.get("text")
        if text is not None and type(text) is not str:
            raise IncompletePublication("X publication text is invalid")
        if text is None and not attachments:
            raise IncompletePublication("X publication delivery leg has no public output")
        required.append(key)
        by_key[key] = {
            "operation_key": key,
            "operation_digest": digest,
            "receipt_operation_id": raw["receipt_operation_id"],
            "destination": destination,
            "receipt_id": receipt_id,
            "status": "delivered",
            "message_url": None,
            "text": text,
            "attachments": attachments,
        }
    return required, [by_key[key] for key in required]


def _version_identity(state: dict[str, Any], event: dict[str, Any]) -> tuple[str, int, int | None]:
    records = _ledger(state)
    replacements = set(event.get("replacement_of", []))
    item_index = event.get("news_item_index")
    parents = [record for record in records.values()
               if (record["delivery_id"] in replacements and item_index in (None, 0))
               or (item_index is not None and record["delivery_id"].endswith(f":item:{item_index}")
                   and record["delivery_id"].rsplit(":item:", 1)[0] in replacements)]
    parent = max(parents, key=lambda record: record["snapshot"]["version"], default=None)
    if parent is not None:
        owner_key = parent["snapshot"]["owner_key"]
    else:
        owner_key = f"x:{event['profile_id']}:{event.get('thread_root_id', event['post_id'])}"
    if parent is None and "news_item_index" in event:
        owner_key += f":item:{event['news_item_index']}"
    prior_versions = [
        record["snapshot"]["version"]
        for record in records.values()
        if record["snapshot"]["owner_key"] == owner_key
    ]
    version = max(prior_versions, default=0) + 1
    return owner_key, version, version - 1 if version > 1 else None


def publication_snapshot(
    state: dict[str, Any],
    event: dict[str, Any],
    profile: Profile,
    confirmed_at: datetime,
) -> dict[str, Any]:
    route = event.get("route")
    publication_type = _ROUTES.get(route)
    if publication_type is None:
        raise IncompletePublication("X event route has no Published type")
    if confirmed_at.tzinfo is None or confirmed_at.utcoffset() is None:
        raise IncompletePublication("X delivery confirmation time is not timezone-aware")
    operation_keys, legs = _validated_legs(event.get("publication_legs"))
    owner_key, version, supersedes = _version_identity(state, event)
    title = event.get("title") if isinstance(event.get("title"), str) and event["title"].strip() else profile.display_name
    ticker_match = _TICKER.match(title)
    ticker = ticker_match.group(1) if ticker_match else None
    source_key = event.get("source_event_key")
    source_version = None
    if isinstance(source_key, str):
        source_record = state.get("source_events", {}).get(source_key)
        if isinstance(source_record, dict) and type(source_record.get("version")) is int:
            source_version = f"{source_record['version']}"
    revision = event.get("source_catalog_revision", event.get("config_revision"))
    if type(revision) is not int:
        revision = None
    post = event.get("post")
    thread_posts = event.get("thread_posts") or [post]
    source_url = post.get("url") if isinstance(post, dict) else None
    source_published_at = post.get("published_at") if isinstance(post, dict) else None
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise IncompletePublication("X source URL is missing")
    if not isinstance(source_published_at, str):
        source_published_at = None
    source_name = profile.handle
    delivery_id = f"{event['profile_id']}:{event['post_id']}" + (f":item:{event['news_item_index']}" if "news_item_index" in event else "")
    return {
        "api_version": 1,
        "owner_key": owner_key,
        "version": version,
        "supersedes_version": supersedes,
        "type": publication_type,
        "route": route,
        "source_event_key": source_key if isinstance(source_key, str) else None,
        "source_name": source_name,
        "source_url": source_url,
        "source_published_at": source_published_at,
        "market_data_as_of": event.get("market_data_as_of"),
        "delivery_confirmed_at": confirmed_at.astimezone(timezone.utc).isoformat(),
        "title": title[:300],
        "ticker": ticker,
        "broker_levels": None,
        "parent_publication_id": None,
        "board_episode_id": None,
        "config_revision": revision,
        "renderer_version": "stock-news-v1" if "news_item_index" in event else RENDERER_VERSION,
        "source_version": source_version,
        "required_operation_keys": operation_keys,
        "legs": legs,
        "_delivery_id": delivery_id,
    }


def record_confirmed_event(
    state: dict[str, Any],
    event: dict[str, Any],
    profile: Profile,
    confirmed_at: datetime,
) -> bool:
    """Persist a pending snapshot after the complete All bundle has receipts."""
    if not _feature_enabled():
        return False
    if event.get("news_cards") is not None:
        offset = 0
        changed = False
        for index, card in enumerate(event["news_cards"]):
            count = len(card["messages"])
            text_legs = [leg for leg in event["publication_legs"] if leg.get("text") is not None]
            media_legs = [leg for leg in event["publication_legs"] if leg.get("text") is None]
            item_event = {**event, **card, "news_item_index": index,
                          "publication_legs": text_legs[offset:offset + count] + (media_legs if index == 0 else [])}
            item_event.pop("news_cards")
            changed = record_confirmed_event(state, item_event, profile, confirmed_at) or changed
            offset += count
        return changed
    records = _ledger(state)
    delivery_id = f"{event['profile_id']}:{event['post_id']}" + (f":item:{event['news_item_index']}" if "news_item_index" in event else "")
    prior = next((record for record in records.values() if record["delivery_id"] == delivery_id), None)
    if prior is not None:
        operation_keys, legs = _validated_legs(event.get("publication_legs"))
        snapshot = prior["snapshot"]
        post = event.get("post")
        title = event.get("title") if isinstance(event.get("title"), str) and event["title"].strip() else profile.display_name
        if (
            snapshot["route"] != event.get("route")
            or snapshot["source_event_key"] != event.get("source_event_key")
            or snapshot["source_url"] != (post.get("url") if isinstance(post, dict) else None)
            or snapshot["title"] != title[:300]
            or snapshot["required_operation_keys"] != operation_keys
            or snapshot["legs"] != legs
        ):
            raise ValueError("X publication retry conflicts with its durable output snapshot")
        return False
    snapshot = publication_snapshot(state, event, profile, confirmed_at)
    snapshot.pop("_delivery_id")
    owner_key = snapshot["owner_key"]
    storage_key = f"{owner_key}@{snapshot['version']}"
    existing = records.get(storage_key)
    record = {"delivery_id": delivery_id, "snapshot": snapshot, "ack": None}
    if existing is not None:
        if existing["delivery_id"] == delivery_id and existing["snapshot"] == snapshot:
            return False
        raise ValueError("X publication owner identity conflicts with its durable snapshot")
    records[storage_key] = record
    return True


def pending_publication_intents(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    records = _ledger(state)
    pending = [(key, record["snapshot"]) for key, record in records.items() if record["ack"] is None]
    return sorted(pending, key=lambda pair: (pair[1]["delivery_confirmed_at"], pair[0]))


def checkpoint_comparison(state: dict[str, Any], compared_at: datetime) -> dict[str, Any]:
    records = _ledger(state)
    ordered = sorted(records.items(), key=lambda pair: (pair[1]["snapshot"]["delivery_confirmed_at"], pair[0]))
    confirmed = max((record["snapshot"]["delivery_confirmed_at"] for record in records.values()), default=None)
    accepted = None
    for _key, record in ordered:
        if record["ack"] is None:
            break
        accepted = record["snapshot"]["delivery_confirmed_at"]
    if confirmed is not None and all(record["ack"] is not None for record in records.values()):
        accepted = confirmed
    return {
        "compared_at": compared_at.astimezone(timezone.utc).isoformat(),
        "confirmed_through_at": confirmed,
        "accepted_through_at": accepted,
        "outstanding_count": sum(record["ack"] is None for record in records.values()),
    }


def _feature_enabled() -> bool:
    return os.environ.get("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_ENABLED") == "1"


def enabled() -> bool:
    """Return whether this owner's forward projection has been explicitly enabled."""
    return _feature_enabled()


def _client() -> Any:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_X_ACCOUNT_WATCH_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("X publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("X publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("X publication token file is empty")
    library = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    if not library.is_dir():
        library = Path.home() / ".agents/skills/lib-bursawatch-control/bin"
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient

    return PublicationClient(url, token)


def drain(
    state: dict[str, Any],
    compared_at: datetime,
    *,
    dry_run: bool = False,
    client: Any | None = None,
    persist=None,
) -> dict[str, int]:
    if dry_run or not _feature_enabled():
        return {"accepted": 0, "pending": len(pending_publication_intents(state))}
    try:
        client = client or _client()
    except Exception:
        return {"accepted": 0, "pending": len(pending_publication_intents(state))}
    records = _ledger(state)
    accepted_count = 0
    for storage_key, snapshot in pending_publication_intents(state):
        try:
            ack = client.submit(snapshot)
            expected_id = publication_id(snapshot["owner_key"])
            if (
                type(ack) is not dict
                or set(ack) != {"publication_id", "version", "digest"}
                or ack.get("publication_id") != expected_id
                or ack.get("version") != snapshot["version"]
                or not isinstance(ack.get("digest"), str)
                or not _SHA256.fullmatch(ack["digest"])
            ):
                break
            records[storage_key]["ack"] = ack
            if persist is not None:
                persist()
            accepted_count += 1
        except Exception:
            break
    try:
        client.checkpoint(checkpoint_comparison(state, compared_at))
    except Exception:
        pass
    return {"accepted": accepted_count, "pending": len(pending_publication_intents(state))}
