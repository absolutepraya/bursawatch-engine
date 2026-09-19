from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
from typing import Iterator


CONFIG_VERSION = 1
WATCHER_ID = "bursawatch-tg-kelas-investasi-gtw"
_DISCORD_ID_RE = re.compile(r"\d{17,20}")
_TELEGRAM_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")

_SOURCE_FIELDS = {"telegram_channel_id", "telegram_username"}
_DESTINATION_FIELDS = {"alert_discord_channel_id", "heartbeat_discord_channel_id"}
_CONFIG_FIELDS = {"version", "source", "destinations", "additional_prompt_instruction"}
_DEFAULT_CONFIG_DATA = {
    "version": CONFIG_VERSION,
    "source": {
        "telegram_channel_id": 2142109618,
        "telegram_username": "kelasinvestasiid",
    },
    "destinations": {
        "alert_discord_channel_id": "1525102458253217803",
        "heartbeat_discord_channel_id": "1505162000420835388",
    },
    "additional_prompt_instruction": "",
}


@dataclass(frozen=True)
class WatchConfig:
    telegram_channel_id: int
    telegram_username: str
    alert_discord_channel_id: str
    heartbeat_discord_channel_id: str
    additional_prompt_instruction: str


@dataclass(frozen=True)
class LoadedWatchConfig:
    config: WatchConfig
    revision: int | None


def _expect_object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def _expect_fields(value: dict[str, object], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ValueError(f"{label} must contain only {', '.join(sorted(fields))}")


def _discord_id(value: object, label: str) -> str:
    if type(value) is not str or not _DISCORD_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be a Discord snowflake")
    return value


def _additional_prompt_instruction(value: object) -> str:
    if type(value) is not str:
        raise ValueError("additional_prompt_instruction must be text")
    instruction = " ".join(value.split())
    if len(instruction) > 800:
        raise ValueError("additional_prompt_instruction must not exceed 800 characters")
    return instruction


def load_watch_config_data(raw: object) -> WatchConfig:
    """Validate the complete Kelas Investasi GTW operator configuration."""
    root = _expect_object(raw, "watch configuration")
    _expect_fields(root, _CONFIG_FIELDS, "watch configuration")
    if root["version"] != CONFIG_VERSION:
        raise ValueError(f"watch configuration version must be {CONFIG_VERSION}")

    source = _expect_object(root["source"], "source")
    _expect_fields(source, _SOURCE_FIELDS, "source")
    source_channel_id = source["telegram_channel_id"]
    if type(source_channel_id) is not int or not 1 <= source_channel_id <= 9_999_999_999:
        raise ValueError("source.telegram_channel_id must be a positive Telegram channel ID")
    username = source["telegram_username"]
    if type(username) is not str or not _TELEGRAM_USERNAME_RE.fullmatch(username):
        raise ValueError("source.telegram_username must be a Telegram username")

    destinations = _expect_object(root["destinations"], "destinations")
    _expect_fields(destinations, _DESTINATION_FIELDS, "destinations")
    alert_channel_id = _discord_id(destinations["alert_discord_channel_id"], "destinations.alert_discord_channel_id")
    heartbeat_channel_id = _discord_id(
        destinations["heartbeat_discord_channel_id"],
        "destinations.heartbeat_discord_channel_id",
    )
    if alert_channel_id == heartbeat_channel_id:
        raise ValueError("alert and heartbeat Discord destinations must differ")
    return WatchConfig(
        telegram_channel_id=source_channel_id,
        telegram_username=username,
        alert_discord_channel_id=alert_channel_id,
        heartbeat_discord_channel_id=heartbeat_channel_id,
        additional_prompt_instruction=_additional_prompt_instruction(root["additional_prompt_instruction"]),
    )


def default_watch_config() -> WatchConfig:
    return load_watch_config_data(_DEFAULT_CONFIG_DATA)


_ACTIVE_CONFIG: ContextVar[WatchConfig | None] = ContextVar("kelas_investasi_gtw_watch_config", default=None)


def active_watch_config() -> WatchConfig:
    return _ACTIVE_CONFIG.get() or default_watch_config()


@contextmanager
def activate_watch_config(watch_config: WatchConfig) -> Iterator[None]:
    token = _ACTIVE_CONFIG.set(watch_config)
    try:
        yield
    finally:
        _ACTIVE_CONFIG.reset(token)


def _fetch_live_config():
    try:
        from control_plane_client import fetch_config, live_config_settings
    except ModuleNotFoundError as exc:
        raise ValueError("live config mode requires lib-bursawatch-control") from exc
    settings = live_config_settings("KELAS_INVESTASI_GTW")
    if settings is None:
        raise ValueError("live config mode was requested without a control-plane URL")
    base_url, watcher_id, token, timeout = settings
    return fetch_config(base_url, watcher_id, token, timeout=timeout)


def load_watch_config_for_run() -> LoadedWatchConfig:
    """Load one frozen snapshot, using reviewed defaults only while live mode is off."""
    if os.environ.get("KELAS_INVESTASI_GTW_CONTROL_PLANE_URL", "").strip():
        snapshot = _fetch_live_config()
        if snapshot.watcher_id != os.environ.get(
            "KELAS_INVESTASI_GTW_CONTROL_PLANE_WATCHER_ID", WATCHER_ID
        ):
            raise ValueError("control-plane returned the wrong watcher ID")
        return LoadedWatchConfig(load_watch_config_data(snapshot.config), snapshot.revision)
    return LoadedWatchConfig(default_watch_config(), None)
