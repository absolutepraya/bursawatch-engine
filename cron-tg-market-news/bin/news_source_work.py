"""Frozen source-work provenance in the existing Market News owner state."""
from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any, Mapping

import config
from domain import Destination
from state import StateBlockedError


_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CAPABILITIES = frozenset({"company_news", "macro_news"})
_NEWS_SOURCE_HANDLES = {
    "phintraco": "phintasprofits",
    "tuntun": "tuntunsekuritas",
}
_STATS_KEY = "news_source_work"


def _config_data(value: config.WatchConfig) -> dict[str, Any]:
    fields = asdict(value)
    return {
        "version": config.CONFIG_VERSION,
        "providers": {
            "phintraco": {"telegram_username": fields["phintraco_username"]},
            "tuntun": {"telegram_username": fields["tuntun_username"]},
        },
        "destinations": {
            "id_stocks_news_discord_channel_id": fields["id_stocks_news_channel_id"],
            "macro_news_discord_channel_id": fields["macro_news_channel_id"],
            "industry_news_discord_channel_id": fields["industry_news_channel_id"],
            "heartbeat_discord_channel_id": fields["heartbeat_channel_id"],
        },
        "additional_prompt_instruction": fields["additional_prompt_instruction"],
    }


def _records(state: Mapping[str, object]) -> dict[str, object]:
    stats = state.get("stats")
    if not isinstance(stats, dict):
        raise StateBlockedError("malformed Market News stats")
    records = stats.get(_STATS_KEY, {})
    if not isinstance(records, dict):
        raise StateBlockedError("malformed News source-work provenance")
    return records


def _validated(record: object, candidate_key: str) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) - {"summary_media_refs"} != {
        "candidate_key", "event_key", "version", "content_hash", "source_url",
        "enabled_capabilities", "work_keys", "watch_config", "watch_config_revision",
    }:
        raise StateBlockedError("malformed News source-work provenance")
    if record["candidate_key"] != candidate_key or any(
        not isinstance(record[field], str) or not _HEX.fullmatch(record[field])
        for field in ("event_key", "content_hash")
    ) or type(record["version"]) is not int or record["version"] < 1:
        raise StateBlockedError("News source-work identity is invalid")
    capabilities = record["enabled_capabilities"]
    keys = record["work_keys"]
    if (not isinstance(capabilities, list) or not capabilities or
        any(not isinstance(capability, str) for capability in capabilities) or
        len(capabilities) != len(set(capabilities)) or
        not set(capabilities) <= _CAPABILITIES or
        not isinstance(keys, dict) or set(keys) != set(capabilities) or
        any(not isinstance(key, str) or not _HEX.fullmatch(key) for key in keys.values())):
        raise StateBlockedError("News source-work capabilities are invalid")
    match = re.fullmatch(r"(phintraco|tuntun):([1-9][0-9]*):[A-Za-z0-9_-]+", candidate_key)
    if match is None or record["source_url"] != f"https://t.me/{_NEWS_SOURCE_HANDLES[match.group(1)]}/{match.group(2)}":
        raise StateBlockedError("News source-work URL is invalid")
    revision = record["watch_config_revision"]
    if revision is not None and (type(revision) is not int or revision < 1):
        raise StateBlockedError("News source-work config revision is invalid")
    try:
        config.load_watch_config_data(record["watch_config"])
    except (TypeError, ValueError) as error:
        raise StateBlockedError("News source-work config is invalid") from error
    return record


def provenance(state: Mapping[str, object], candidate_key: str) -> dict[str, Any] | None:
    value = _records(state).get(candidate_key)
    return None if value is None else _validated(value, candidate_key)


def put_provenance(
    state: dict[str, object], candidate_key: str, *, event_key: str, version: int,
    content_hash: str, source_url: str, work_keys: dict[str, str],
    loaded_config: config.LoadedWatchConfig, summary_media_refs: list | None = None,
) -> bool:
    stats = state["stats"]
    assert isinstance(stats, dict)
    records = stats.setdefault(_STATS_KEY, {})
    assert isinstance(records, dict)
    existing = provenance(state, candidate_key)
    if existing is not None:
        if (existing["event_key"], existing["version"], existing["content_hash"],
            existing["source_url"], existing["work_keys"]) != (
            event_key, version, content_hash, source_url, work_keys
        ):
            raise StateBlockedError("News candidate has conflicting source-work provenance")
        return False
    record = {
        "candidate_key": candidate_key,
        "event_key": event_key,
        "version": version,
        "content_hash": content_hash,
        "source_url": source_url,
        "enabled_capabilities": sorted(work_keys),
        "work_keys": dict(work_keys),
        "watch_config": _config_data(loaded_config.config),
        "watch_config_revision": loaded_config.revision,
    }
    if summary_media_refs is not None:
        record["summary_media_refs"] = summary_media_refs
    records[candidate_key] = _validated(record, candidate_key)
    return True


def loaded_config_for(state: Mapping[str, object], candidate_key: str) -> config.LoadedWatchConfig | None:
    record = provenance(state, candidate_key)
    if record is None:
        return None
    return config.LoadedWatchConfig(
        config.load_watch_config_data(record["watch_config"]),
        record["watch_config_revision"],
    )


def route_enabled(state: Mapping[str, object], candidate_key: str, route: Destination) -> bool:
    record = provenance(state, candidate_key)
    if record is None or route is Destination.EXCLUDE:
        return True
    capability = "company_news" if route is Destination.ID_STOCKS_NEWS else "macro_news"
    return capability in record["enabled_capabilities"]


def candidate_keys(state: Mapping[str, object]) -> set[str]:
    candidates = state.get("candidates")
    if not isinstance(candidates, dict):
        raise StateBlockedError("malformed Market News candidates")
    keys = set(_records(state))
    if not keys <= set(candidates):
        raise StateBlockedError("News source-work provenance has no candidate")
    return {key for key in keys if provenance(state, key) is not None}
