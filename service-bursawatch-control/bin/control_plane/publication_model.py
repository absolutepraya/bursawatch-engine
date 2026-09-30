"""Strict, owner-scoped snapshots of confirmed public Discord output."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


API_VERSION = 1
OWNER_ROUTES: dict[str, dict[str, set[str]]] = {
    "bursawatch-tg-market-news": {
        "idx_company_news": {"id_stocks_news"},
        "industry_news": {"id_industry_news"},
        "macro_news": {"macro_news"},
        "stock_status": {"id_stocks_news"},
    },
    "bursawatch-stockbit-snips": {
        "idx_company_news": {"id_stocks_news"},
        "macro_news": {"macro_news"},
    },
    "bursawatch-x-account-watch": {
        "idx_company_news": {"id_stocks_news"},
        "us_company_news": {"us_stocks_news"},
        "macro_news": {"macro_news"},
        "swing_context": {"id_stocks_swing"},
    },
    "bursawatch-ig-account-watch": {
        "idx_company_news": {"id_stocks_news"},
        "macro_news": {"macro_news"},
    },
    "bursawatch-wa-channel-watch": {
        "idx_company_news": {"id_stocks_news"},
        "industry_news": {"id_industry_news"},
        "macro_news": {"macro_news"},
        "swing_context": {"id_stocks_swing"},
    },
    "bursawatch-tg-phintraco-swing": {"broker_swing_plan": {"id_stocks_swing"}},
    "bursawatch-tg-kelas-investasi-gtw": {"swing_bundle": {"id_stocks_swing"}},
    "bursawatch-dc-swing-board": {"swing_board_update": {"swing_board"}},
}
SNAPSHOT_FIELDS = {
    "api_version", "owner_key", "version", "supersedes_version", "type", "route",
    "source_event_key", "source_name", "source_url", "source_published_at",
    "market_data_as_of", "delivery_confirmed_at", "title", "ticker",
    "broker_levels", "parent_publication_id", "board_episode_id", "config_revision",
    "renderer_version", "source_version", "legs",
}
LEG_FIELDS = {
    "operation_key", "destination", "receipt_id", "status", "message_url",
    "text", "attachments",
}
ATTACHMENT_FIELDS = {"filename", "content_type", "discord_url"}
LEVEL_FIELDS = {"entry", "stop", "targets", "units", "attribution"}
DISCORD_ID = re.compile(r"[0-9]{17,20}\Z")
TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,19}\Z")
HEX_ID = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _text(value: object, name: str, minimum: int, maximum: int) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise ValueError(f"{name} must be bounded text")
    if any(ord(char) < 32 and char not in "\n\t" for char in value) or "\x7f" in value:
        raise ValueError(f"{name} contains control characters")
    return value


def _optional_text(value: object, name: str, maximum: int) -> str | None:
    return None if value is None else _text(value, name, 1, maximum)


def _time(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or len(value) > 64:
        raise ValueError(f"{name} must be an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be an aware timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def _url(value: object, name: str, *, optional: bool = False, discord: bool = False, attachment: bool = False) -> str | None:
    if value is None and optional:
        return None
    url = _text(value, name, 1, 2048)
    if any(char.isspace() for char in url):
        raise ValueError(f"{name} must be a safe HTTPS URL")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{name} must be a safe HTTPS URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must be a safe HTTPS URL") from exc
    if port not in {None, 443} or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"{name} must be a safe HTTPS URL")
    if discord and (parsed.hostname not in {"discord.com", "www.discord.com"} or not parsed.path.startswith("/channels/")):
        raise ValueError(f"{name} must be a Discord message URL")
    if attachment and (
        parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}
        or not parsed.path.startswith("/attachments/")
    ):
        raise ValueError(f"{name} must be a Discord attachment URL")
    return url


def _broker_levels(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != LEVEL_FIELDS:
        raise ValueError("broker levels require entry, stop, targets, units, and attribution")
    result = {
        "entry": _text(value["entry"], "broker levels entry", 1, 200),
        "stop": _text(value["stop"], "broker levels stop", 1, 200),
        "units": _text(value["units"], "broker levels units", 1, 80),
        "attribution": _text(value["attribution"], "broker levels attribution", 1, 200),
    }
    targets = value["targets"]
    if type(targets) is not list or not 1 <= len(targets) <= 10:
        raise ValueError("broker levels require bounded targets")
    result["targets"] = [_text(item, "broker levels target", 1, 200) for item in targets]
    return result


def _leg(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != LEG_FIELDS:
        raise ValueError("delivery leg has unexpected fields")
    if value["status"] != "delivered":
        raise ValueError("delivery leg must have a confirmed receipt")
    destination = _text(value["destination"], "delivery leg destination", 17, 20)
    receipt_id = _text(value["receipt_id"], "delivery leg receipt_id", 17, 20)
    if not DISCORD_ID.fullmatch(destination) or not DISCORD_ID.fullmatch(receipt_id):
        raise ValueError("delivery leg must have Discord destination and receipt IDs")
    attachments = value["attachments"]
    if type(attachments) is not list or len(attachments) > 10:
        raise ValueError("delivery leg attachments must be bounded")
    safe_attachments = []
    for item in attachments:
        if type(item) is not dict or set(item) != ATTACHMENT_FIELDS:
            raise ValueError("attachment contains private or unexpected metadata")
        safe_attachments.append({
            "filename": _text(item["filename"], "attachment filename", 1, 255),
            "content_type": _text(item["content_type"], "attachment content_type", 1, 100),
            "discord_url": _url(item["discord_url"], "attachment discord_url", optional=True, attachment=True),
        })
    text = _optional_text(value["text"], "delivery leg text", 16_000)
    if text is None and not safe_attachments:
        raise ValueError("delivery leg has no published output")
    return {
        "operation_key": _text(value["operation_key"], "delivery leg operation_key", 1, 256),
        "destination": destination,
        "receipt_id": receipt_id,
        "status": "delivered",
        "message_url": _url(value["message_url"], "delivery leg message_url", optional=True, discord=True),
        "text": text,
        "attachments": safe_attachments,
    }


def validate_publication(payload: object, owner_id: str) -> dict[str, Any]:
    """Return an immutable-format public record from one scoped owner snapshot."""
    if owner_id not in OWNER_ROUTES:
        raise ValueError("publication owner is not supported")
    if type(payload) is not dict or set(payload) != SNAPSHOT_FIELDS:
        raise ValueError("publication snapshot has unexpected fields")
    if payload["api_version"] != API_VERSION:
        raise ValueError("publication API version is unsupported")
    kind = payload["type"]
    route = payload["route"]
    if type(kind) is not str or type(route) is not str or route not in OWNER_ROUTES[owner_id].get(kind, set()):
        raise ValueError("publication type or route is unsupported for owner")
    owner_key = _text(payload["owner_key"], "publication owner_key", 1, 256)
    version = payload["version"]
    supersedes = payload["supersedes_version"]
    if type(version) is not int or not 1 <= version <= 1_000_000:
        raise ValueError("publication version is invalid")
    if (version == 1 and supersedes is not None) or (version > 1 and supersedes != version - 1):
        raise ValueError("publication supersedes_version is invalid")
    levels = payload["broker_levels"]
    if kind == "broker_swing_plan":
        if owner_id != "bursawatch-tg-phintraco-swing":
            raise ValueError("broker plan owner is unsupported")
        levels = _broker_levels(levels)
    elif levels is not None:
        raise ValueError("broker levels are only for validated broker plans")
    ticker = payload["ticker"]
    if ticker is not None and (type(ticker) is not str or not TICKER.fullmatch(ticker)):
        raise ValueError("publication ticker is invalid")
    parent = payload["parent_publication_id"]
    if parent is not None and (type(parent) is not str or not HEX_ID.fullmatch(parent)):
        raise ValueError("parent_publication_id is invalid")
    config_revision = payload["config_revision"]
    if config_revision is not None and (type(config_revision) is not int or config_revision < 1):
        raise ValueError("config_revision is invalid")
    legs = payload["legs"]
    if type(legs) is not list or not 1 <= len(legs) <= 10:
        raise ValueError("publication requires bounded delivery legs")
    safe_legs = [_leg(item) for item in legs]
    operation_keys = [item["operation_key"] for item in safe_legs]
    if len(operation_keys) != len(set(operation_keys)):
        raise ValueError("publication has duplicate delivery legs")
    identity = hashlib.sha256(_canonical([owner_id, owner_key])).hexdigest()
    record = {
        "api_version": API_VERSION,
        "publication_id": identity,
        "owner_id": owner_id,
        "owner_key": owner_key,
        "version": version,
        "supersedes_version": supersedes,
        "type": kind,
        "route": route,
        "source_event_key": _optional_text(payload["source_event_key"], "source_event_key", 256),
        "source_name": _text(payload["source_name"], "source_name", 1, 200),
        "source_url": _url(payload["source_url"], "source_url", optional=True),
        "source_published_at": _time(payload["source_published_at"], "source_published_at", optional=True),
        "market_data_as_of": _time(payload["market_data_as_of"], "market_data_as_of", optional=True),
        "delivery_confirmed_at": _time(payload["delivery_confirmed_at"], "delivery_confirmed_at"),
        "title": _text(payload["title"], "title", 1, 300),
        "ticker": ticker,
        "broker_levels": levels,
        "parent_publication_id": parent,
        "board_episode_id": _optional_text(payload["board_episode_id"], "board_episode_id", 128),
        "config_revision": config_revision,
        "renderer_version": _text(payload["renderer_version"], "renderer_version", 1, 100),
        "source_version": _optional_text(payload["source_version"], "source_version", 100),
        "legs": safe_legs,
    }
    record["digest"] = hashlib.sha256(_canonical(record)).hexdigest()
    return deepcopy(record)
