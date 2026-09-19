from __future__ import annotations

from dataclasses import dataclass
import os
import re


CONFIG_VERSION = 1
WATCHER_ID = "bursawatch-dc-swing-board"
_DISCORD_ID_RE = re.compile(r"\d{17,20}")
_DEFAULT_CONFIG_DATA = {
    "version": CONFIG_VERSION,
    "destinations": {
        "heartbeat_discord_channel_id": "1505162000420835388",
    },
}


@dataclass(frozen=True)
class BoardConfig:
    heartbeat_discord_channel_id: str


@dataclass(frozen=True)
class LoadedBoardConfig:
    config: BoardConfig
    revision: int | None


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def _discord_id(value: object, label: str) -> str:
    if type(value) is not str or not _DISCORD_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be a Discord snowflake")
    return value


def load_board_config_data(raw: object) -> BoardConfig:
    """Validate the small, safe Swing Board operator configuration surface."""
    root = _object(raw, "board configuration")
    if set(root) != {"version", "destinations"} or root["version"] != CONFIG_VERSION:
        raise ValueError("board configuration has an unsupported schema or version")
    destinations = _object(root["destinations"], "destinations")
    if set(destinations) != {"heartbeat_discord_channel_id"}:
        raise ValueError("destinations must contain only heartbeat_discord_channel_id")
    return BoardConfig(
        heartbeat_discord_channel_id=_discord_id(
            destinations["heartbeat_discord_channel_id"],
            "destinations.heartbeat_discord_channel_id",
        )
    )


def default_board_config() -> BoardConfig:
    return load_board_config_data(_DEFAULT_CONFIG_DATA)


def _fetch_live_config():
    try:
        from control_plane_client import fetch_config, live_config_settings
    except ModuleNotFoundError as exc:
        raise ValueError("live config mode requires lib-bursawatch-control") from exc
    settings = live_config_settings("IDX_SWING_PLAN_BOARD")
    if settings is None:
        raise ValueError("live config mode was requested without a control-plane URL")
    base_url, watcher_id, token, timeout = settings
    return fetch_config(base_url, watcher_id, token, timeout=timeout)


def load_board_config_for_run() -> LoadedBoardConfig:
    """Load one frozen snapshot, with reviewed defaults while live mode is off."""
    if os.environ.get("IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL", "").strip():
        snapshot = _fetch_live_config()
        if snapshot.watcher_id != os.environ.get(
            "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_WATCHER_ID", WATCHER_ID
        ):
            raise ValueError("control-plane returned the wrong watcher ID")
        return LoadedBoardConfig(load_board_config_data(snapshot.config), snapshot.revision)
    return LoadedBoardConfig(default_board_config(), None)
