from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
from typing import Iterator


CONFIG_VERSION = 1
WATCHER_ID = "bursawatch-tg-market-news"
_DISCORD_ID_RE = re.compile(r"\d{17,20}")
_TELEGRAM_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
_PROVIDERS = {"phintraco", "tuntun"}
_DESTINATIONS = {
    "id_stocks_news_discord_channel_id",
    "macro_news_discord_channel_id",
    "industry_news_discord_channel_id",
    "heartbeat_discord_channel_id",
}
_DEFAULT = {
    "version": CONFIG_VERSION,
    "providers": {
        "phintraco": {"telegram_username": "phintasprofits"},
        "tuntun": {"telegram_username": "tuntunsekuritas"},
    },
    "destinations": {
        "id_stocks_news_discord_channel_id": "1525102508714889257",
        "macro_news_discord_channel_id": "1531655369884045382",
        "industry_news_discord_channel_id": "1549418098807930880",
        "heartbeat_discord_channel_id": "1505162000420835388",
    },
    "additional_prompt_instruction": "",
}


@dataclass(frozen=True)
class WatchConfig:
    phintraco_username: str
    tuntun_username: str
    id_stocks_news_channel_id: str
    macro_news_channel_id: str
    industry_news_channel_id: str
    heartbeat_channel_id: str
    additional_prompt_instruction: str


@dataclass(frozen=True)
class LoadedWatchConfig:
    config: WatchConfig
    revision: int | None


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def _username(value: object, label: str) -> str:
    if type(value) is not str or not _TELEGRAM_USERNAME_RE.fullmatch(value):
        raise ValueError(f"{label} must be a Telegram username")
    return value


def _discord(value: object, label: str) -> str:
    if type(value) is not str or not _DISCORD_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be a Discord snowflake")
    return value


def load_watch_config_data(raw: object) -> WatchConfig:
    """Validate the complete Telegram Market News operator configuration."""
    root = _object(raw, "watch configuration")
    if (
        set(root) != {"version", "providers", "destinations", "additional_prompt_instruction"}
        or root["version"] != CONFIG_VERSION
    ):
        raise ValueError("watch configuration has an unsupported schema or version")
    providers = _object(root["providers"], "providers")
    if set(providers) != _PROVIDERS:
        raise ValueError("providers must contain only phintraco and tuntun")
    phintraco = _object(providers["phintraco"], "providers.phintraco")
    tuntun = _object(providers["tuntun"], "providers.tuntun")
    if set(phintraco) != {"telegram_username"} or set(tuntun) != {"telegram_username"}:
        raise ValueError("each provider must contain only telegram_username")
    destinations = _object(root["destinations"], "destinations")
    if set(destinations) != _DESTINATIONS:
        raise ValueError("destinations has an unsupported schema")
    values = {
        key: _discord(destinations[key], f"destinations.{key}")
        for key in _DESTINATIONS
    }
    if len(set(values.values())) != len(values):
        raise ValueError("Discord destinations must differ")
    prompt = root["additional_prompt_instruction"]
    if type(prompt) is not str:
        raise ValueError("additional_prompt_instruction must be text")
    prompt = " ".join(prompt.split())
    if len(prompt) > 800:
        raise ValueError("additional_prompt_instruction must not exceed 800 characters")
    return WatchConfig(
        _username(phintraco["telegram_username"], "providers.phintraco.telegram_username"),
        _username(tuntun["telegram_username"], "providers.tuntun.telegram_username"),
        values["id_stocks_news_discord_channel_id"],
        values["macro_news_discord_channel_id"],
        values["industry_news_discord_channel_id"],
        values["heartbeat_discord_channel_id"],
        prompt,
    )


def default_watch_config() -> WatchConfig:
    return load_watch_config_data(_DEFAULT)


_ACTIVE: ContextVar[WatchConfig | None] = ContextVar("market_news_watch_config", default=None)


def active_watch_config() -> WatchConfig:
    return _ACTIVE.get() or default_watch_config()


@contextmanager
def activate_watch_config(value: WatchConfig) -> Iterator[None]:
    token = _ACTIVE.set(value)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def _fetch_live_config():
    try:
        from control_plane_client import fetch_config, live_config_settings
    except ModuleNotFoundError as exc:
        raise ValueError("live config mode requires lib-bursawatch-control") from exc
    settings = live_config_settings("IDX_MARKET_NEWS")
    if settings is None:
        raise ValueError("live config mode was requested without a control-plane URL")
    base_url, watcher_id, token, timeout = settings
    return fetch_config(base_url, watcher_id, token, timeout=timeout)


def load_watch_config_for_run() -> LoadedWatchConfig:
    """Load one frozen snapshot, using source defaults only while live mode is off."""
    if os.environ.get("IDX_MARKET_NEWS_CONTROL_PLANE_URL", "").strip():
        snapshot = _fetch_live_config()
        if snapshot.watcher_id != os.environ.get(
            "IDX_MARKET_NEWS_CONTROL_PLANE_WATCHER_ID", WATCHER_ID
        ):
            raise ValueError("control-plane returned the wrong watcher ID")
        return LoadedWatchConfig(load_watch_config_data(snapshot.config), snapshot.revision)
    return LoadedWatchConfig(default_watch_config(), None)
