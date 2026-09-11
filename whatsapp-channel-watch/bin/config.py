from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from models import ChannelProfile, DiscordChannel, WatchConfig


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_JID_RE = re.compile(r"^[^@\s]+@newsletter$")
_DISCORD_ID_RE = re.compile(r"^\d{17,20}$")
_EMOJI_RE = re.compile(r"<:[A-Za-z0-9_]+:\d{17,20}>")
_CHANNEL_KEYS = {"macro_news", "id_stocks_news", "us_stocks_news"}
_SCOPES = {"stock_market", "financial_market", "indonesia_economy"}
_PROFILE_KEYS = {
    "id",
    "enabled",
    "channel_jid",
    "channel_url",
    "display_name",
    "emoji",
    "discord_channels",
    "forward_media",
    "enable_llm_title",
    "enable_llm_summary",
    "enable_llm_routing",
    "enable_llm_relevance_filter",
    "relevance_scope",
    "additional_prompt_instruction",
    "max_items_per_poll",
}
_CHANNEL_KEYS_REQUIRED = {"key", "channel_id", "description"}


def _require_type(value: object, expected: type, label: str) -> object:
    if type(value) is not expected:
        raise ValueError(f"{label} must be {expected.__name__}")
    return value


def _https_url(value: object, label: str) -> str:
    value = _require_type(value, str, label)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS URL")
    return value


def _discord_channel(value: object) -> DiscordChannel:
    if type(value) is not dict or set(value) != _CHANNEL_KEYS_REQUIRED:
        raise ValueError("discord channel has unexpected or missing fields")
    key = _require_type(value["key"], str, "discord channel key")
    channel_id = _require_type(value["channel_id"], str, "discord channel ID")
    description = _require_type(value["description"], str, "discord channel description")
    if key not in _CHANNEL_KEYS:
        raise ValueError("discord channel key is not supported")
    if not _DISCORD_ID_RE.fullmatch(channel_id):
        raise ValueError("discord channel ID must be a 17 to 20 digit ID")
    if not description.strip():
        raise ValueError("discord channel description must not be empty")
    return DiscordChannel(key, channel_id, description.strip())


def _profile(value: object) -> ChannelProfile:
    if type(value) is not dict or set(value) != _PROFILE_KEYS:
        raise ValueError("profile has unexpected or missing fields")
    profile_id = _require_type(value["id"], str, "profile ID")
    if not _ID_RE.fullmatch(profile_id):
        raise ValueError("profile ID is invalid")
    enabled = _require_type(value["enabled"], bool, "enabled")
    channel_jid = _require_type(value["channel_jid"], str, "channel JID")
    if not _JID_RE.fullmatch(channel_jid):
        raise ValueError("channel JID must end with @newsletter")
    channel_url = _https_url(value["channel_url"], "channel URL")
    display_name = _require_type(value["display_name"], str, "display name")
    if not display_name.strip():
        raise ValueError("display name must not be empty")
    emoji = _require_type(value["emoji"], str, "emoji")
    if not _EMOJI_RE.fullmatch(emoji):
        raise ValueError("emoji must use Discord custom emoji syntax")
    raw_channels = _require_type(value["discord_channels"], list, "discord channels")
    channels = tuple(_discord_channel(item) for item in raw_channels)
    if not channels:
        raise ValueError("at least one Discord channel is required")
    if len({item.key for item in channels}) != len(channels):
        raise ValueError("Discord route keys must be unique")
    booleans = {
        key: _require_type(value[key], bool, key)
        for key in (
            "forward_media",
            "enable_llm_title",
            "enable_llm_summary",
            "enable_llm_routing",
            "enable_llm_relevance_filter",
        )
    }
    relevance_scope = _require_type(value["relevance_scope"], str, "relevance scope")
    if relevance_scope not in _SCOPES:
        raise ValueError("relevance scope is not supported")
    additional = _require_type(value["additional_prompt_instruction"], str, "additional prompt instruction")
    max_items = _require_type(value["max_items_per_poll"], int, "max items per poll")
    if not 1 <= max_items <= 50:
        raise ValueError("max items per poll must be from 1 to 50")
    return ChannelProfile(
        id=profile_id,
        enabled=enabled,
        channel_jid=channel_jid,
        channel_url=channel_url,
        display_name=display_name.strip(),
        emoji=emoji,
        discord_channels=channels,
        additional_prompt_instruction=additional,
        relevance_scope=relevance_scope,
        max_items_per_poll=max_items,
        **booleans,
    )


def load(path: Path) -> WatchConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read watcher config: {exc}") from exc
    if type(payload) is not dict or set(payload) != {"version", "profiles"}:
        raise ValueError("watcher config has unexpected or missing fields")
    if payload["version"] != 1:
        raise ValueError("watcher config version must be 1")
    profiles = tuple(_profile(item) for item in _require_type(payload["profiles"], list, "profiles"))
    if len({profile.id for profile in profiles}) != len(profiles):
        raise ValueError("profile IDs must be unique")
    if len({profile.channel_jid for profile in profiles}) != len(profiles):
        raise ValueError("channel JIDs must be unique")
    return WatchConfig(version=1, profiles=profiles)
