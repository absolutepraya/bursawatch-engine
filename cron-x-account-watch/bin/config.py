from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from models import DiscordChannel, Profile, ThreadHandling, WatchConfig

# The reviewed source-catalog crosswalk is shared by the X adapter and owner.
REVIEWED_PUBLISHERS = {
    "kutekians": "x-kutekians", "rickyho1989": "x-rickyho1989",
    "writingtorch": "x-writingtorch", "arvinhonami": "x-arvinhonami",
    "insidertracker": "x-insidertracker", "doktermarket": "x-doktermarket",
    "txthariansaham": "x-txthariansaham", "wavetiga": "x-wavetiga",
    "aldotjahjadi8": "x-aldotjahjadi8", "kobeissiletter": "x-kobeissiletter",
}


CONFIG_VERSION = 1
PROFILE_FIELDS = {
    "id",
    "enabled",
    "profile_url",
    "handle",
    "display_name",
    "twitter_emoji",
    "emoji",
    "discord_channels",
    "forward_normal_post",
    "forward_quote_post",
    "forward_reply",
    "forward_repost",
    "forward_media",
    "enable_llm_title",
    "enable_llm_summary",
    "enable_llm_routing",
    "enable_llm_relevance_filter",
    "relevance_scope",
    "additional_prompt_instruction",
    "max_items_per_poll",
    "thread_handling",
}
OPTIONAL_PROFILE_FIELDS = {"source", "media_policy", "relevance_scope", "show_quoted_post"}
MEDIA_POLICIES = {"all", "omit_last"}
RELEVANCE_SCOPES = {"stock_market", "financial_market", "indonesia_economy"}
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
HANDLE_RE = re.compile(r"[A-Za-z0-9_]{1,15}")
EMOJI_RE = re.compile(r"<:[A-Za-z0-9_]+:\d{17,20}>")
DISCORD_ID_RE = re.compile(r"\d{17,20}")


def _expect_object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def _expect_string(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _expect_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _parse_channels(value: object, label: str) -> tuple[DiscordChannel, ...]:
    if type(value) is not list or not value:
        raise ValueError(f"{label} must be a non-empty array")
    channels: list[DiscordChannel] = []
    for index, raw_channel in enumerate(value):
        channel = _expect_object(raw_channel, f"{label}[{index}]")
        if set(channel) != {"key", "channel_id", "description"}:
            raise ValueError(f"{label}[{index}] must contain only key, channel_id, and description")
        key = _expect_string(channel["key"], f"{label}[{index}].key")
        if not ID_RE.fullmatch(key):
            raise ValueError(f"{label}[{index}].key must use lowercase letters, digits, _ or -")
        channel_id = _expect_string(channel["channel_id"], f"{label}[{index}].channel_id")
        if not DISCORD_ID_RE.fullmatch(channel_id):
            raise ValueError(f"{label}[{index}].channel_id must be a Discord snowflake")
        description = _expect_string(channel["description"], f"{label}[{index}].description")
        channels.append(DiscordChannel(key=key, channel_id=channel_id, description=description))
    keys = [channel.key for channel in channels]
    channel_ids = [channel.channel_id for channel in channels]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{label} keys must be unique")
    if len(channel_ids) != len(set(channel_ids)):
        raise ValueError(f"{label} destination channel ids must differ")
    return tuple(channels)


def _parse_thread_handling(value: object, label: str) -> ThreadHandling:
    thread = _expect_object(value, label)
    if set(thread) != {"mode", "max_posts", "max_age_minutes", "settle_minutes"}:
        raise ValueError(f"{label} must contain only mode, max_posts, max_age_minutes, and settle_minutes")
    mode = _expect_string(thread["mode"], f"{label}.mode")
    if mode not in {"self_chain", "disabled"}:
        raise ValueError(f"{label}.mode must be self_chain or disabled")
    max_posts = thread["max_posts"]
    max_age_minutes = thread["max_age_minutes"]
    settle_minutes = thread["settle_minutes"]
    if type(max_posts) is not int or not 1 <= max_posts <= 20:
        raise ValueError(f"{label}.max_posts must be an integer from 1 to 20")
    if type(max_age_minutes) is not int or not 1 <= max_age_minutes <= 1440:
        raise ValueError(f"{label}.max_age_minutes must be an integer from 1 to 1440")
    if type(settle_minutes) is not int or not 1 <= settle_minutes <= 240:
        raise ValueError(f"{label}.settle_minutes must be an integer from 1 to 240")
    return ThreadHandling(mode, max_posts, max_age_minutes, settle_minutes)


def _parse_additional_prompt_instruction(value: object, label: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    instruction = " ".join(value.split())
    if len(instruction) > 800:
        raise ValueError(f"{label} must not exceed 800 characters")
    return instruction


def _parse_media_policy(value: object, label: str) -> str:
    policy = _expect_string(value, label)
    if policy not in MEDIA_POLICIES:
        raise ValueError(f"{label} must be all or omit_last")
    return policy


def _parse_relevance_scope(value: object, label: str) -> str:
    scope = _expect_string(value, label)
    if scope not in RELEVANCE_SCOPES:
        raise ValueError(f"{label} must be stock_market, financial_market, or indonesia_economy")
    return scope


def _validate_profile_url(profile_url: str, handle: str) -> None:
    parsed = urlparse(profile_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"x.com", "www.x.com"}:
        raise ValueError("profile_url must be an https://x.com/<handle> URL")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("profile_url must not include query, fragment, or parameters")
    expected_path = f"/{handle}"
    if parsed.path.lower() != expected_path.lower():
        raise ValueError("profile_url path must match handle")


def _parse_profile(index: int, value: object) -> Profile:
    profile = _expect_object(value, f"profiles[{index}]")
    fields = set(profile)
    missing = PROFILE_FIELDS - fields - OPTIONAL_PROFILE_FIELDS
    unknown = fields - PROFILE_FIELDS - OPTIONAL_PROFILE_FIELDS
    if missing:
        raise ValueError(f"profiles[{index}] missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"profiles[{index}] unknown fields: {', '.join(sorted(unknown))}")

    profile_id = _expect_string(profile["id"], f"profiles[{index}].id")
    if not ID_RE.fullmatch(profile_id):
        raise ValueError(f"profiles[{index}].id must use lowercase letters, digits, _ or -")
    handle = _expect_string(profile["handle"], f"profiles[{index}].handle")
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError(f"profiles[{index}].handle must be a valid X handle")
    profile_url = _expect_string(profile["profile_url"], f"profiles[{index}].profile_url")
    _validate_profile_url(profile_url, handle)
    display_name = _expect_string(profile["display_name"], f"profiles[{index}].display_name")
    twitter_emoji = _expect_string(profile["twitter_emoji"], f"profiles[{index}].twitter_emoji")
    emoji = _expect_string(profile["emoji"], f"profiles[{index}].emoji")
    if not EMOJI_RE.fullmatch(twitter_emoji) or not EMOJI_RE.fullmatch(emoji):
        raise ValueError(f"profiles[{index}] emoji values must use <:emoji_name:emoji_id> syntax")
    channels = _parse_channels(profile["discord_channels"], f"profiles[{index}].discord_channels")
    enable_llm_routing = _expect_bool(profile["enable_llm_routing"], f"profiles[{index}].enable_llm_routing")
    if enable_llm_routing and len(channels) < 2:
        raise ValueError(f"profiles[{index}].discord_channels must contain at least two channels when enable_llm_routing is true")
    if not enable_llm_routing and len(channels) != 1:
        raise ValueError(f"profiles[{index}].discord_channels must contain exactly one channel when enable_llm_routing is false")
    max_items = profile["max_items_per_poll"]
    if type(max_items) is not int or not 1 <= max_items <= 100:
        raise ValueError(f"profiles[{index}].max_items_per_poll must be an integer from 1 to 100")
    source = profile.get("source", "rsshub")
    if source not in {"rsshub", "direct_x", "hybrid"}:
        raise ValueError("profiles[].source must be rsshub, direct_x, or hybrid")
    media_policy = _parse_media_policy(profile.get("media_policy", "all"), f"profiles[{index}].media_policy")
    relevance_scope = _parse_relevance_scope(profile.get("relevance_scope", "stock_market"), f"profiles[{index}].relevance_scope")
    show_quoted_post = _expect_bool(profile.get("show_quoted_post", False), f"profiles[{index}].show_quoted_post")

    return Profile(
        id=profile_id,
        enabled=_expect_bool(profile["enabled"], f"profiles[{index}].enabled"),
        profile_url=profile_url,
        handle=handle,
        display_name=display_name,
        twitter_emoji=twitter_emoji,
        emoji=emoji,
        discord_channels=channels,
        forward_normal_post=_expect_bool(profile["forward_normal_post"], f"profiles[{index}].forward_normal_post"),
        forward_quote_post=_expect_bool(profile["forward_quote_post"], f"profiles[{index}].forward_quote_post"),
        forward_reply=_expect_bool(profile["forward_reply"], f"profiles[{index}].forward_reply"),
        forward_repost=_expect_bool(profile["forward_repost"], f"profiles[{index}].forward_repost"),
        forward_media=_expect_bool(profile["forward_media"], f"profiles[{index}].forward_media"),
        enable_llm_title=_expect_bool(profile["enable_llm_title"], f"profiles[{index}].enable_llm_title"),
        enable_llm_summary=_expect_bool(profile["enable_llm_summary"], f"profiles[{index}].enable_llm_summary"),
        enable_llm_routing=enable_llm_routing,
        enable_llm_relevance_filter=_expect_bool(profile["enable_llm_relevance_filter"], f"profiles[{index}].enable_llm_relevance_filter"),
        relevance_scope=relevance_scope,
        additional_prompt_instruction=_parse_additional_prompt_instruction(profile["additional_prompt_instruction"], f"profiles[{index}].additional_prompt_instruction"),
        max_items_per_poll=max_items,
        thread_handling=_parse_thread_handling(profile["thread_handling"], f"profiles[{index}].thread_handling"),
        source=source,
        media_policy=media_policy,
        show_quoted_post=show_quoted_post,
    )


def load_watch_config_data(raw: object) -> WatchConfig:
    """Validate one complete X watcher configuration object."""
    root = _expect_object(raw, "watch configuration")
    if set(root) != {"version", "profiles"}:
        raise ValueError("watch configuration must contain only version and profiles")
    if root["version"] != CONFIG_VERSION:
        raise ValueError(f"watch configuration version must be {CONFIG_VERSION}")
    if type(root["profiles"]) is not list or not root["profiles"]:
        raise ValueError("watch configuration profiles must be a non-empty array")

    profiles = tuple(_parse_profile(index, value) for index, value in enumerate(root["profiles"]))
    ids = [profile.id for profile in profiles]
    handles = [profile.handle.lower() for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("watch configuration profile ids must be unique")
    if len(handles) != len(set(handles)):
        raise ValueError("watch configuration handles must be unique ignoring case")
    return WatchConfig(version=CONFIG_VERSION, profiles=profiles)


def load_watch_config(path: Path) -> WatchConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"watch configuration is invalid JSON: {exc.msg}") from exc
    return load_watch_config_data(raw)


@dataclass(frozen=True)
class LoadedWatchConfig:
    config: WatchConfig
    revision: int | None


def _fetch_live_config():
    try:
        from control_plane_client import fetch_config, live_config_settings
    except ModuleNotFoundError as exc:
        raise ValueError("live config mode requires lib-bursawatch-control") from exc
    settings = live_config_settings("X_POST_WATCH")
    if settings is None:
        raise ValueError("live config mode was requested without a control-plane URL")
    base_url, watcher_id, token, timeout = settings
    return fetch_config(base_url, watcher_id, token, timeout=timeout)


def load_watch_config_for_run(static_path: Path | None = None) -> LoadedWatchConfig:
    """Load a frozen config snapshot, using the static file only when live mode is off."""
    if os.environ.get("X_POST_WATCH_CONTROL_PLANE_URL", "").strip():
        snapshot = _fetch_live_config()
        if snapshot.watcher_id != os.environ.get(
            "X_POST_WATCH_CONTROL_PLANE_WATCHER_ID", "bursawatch-x-account-watch"
        ):
            raise ValueError("control-plane returned the wrong watcher ID")
        return LoadedWatchConfig(load_watch_config_data(snapshot.config), snapshot.revision)
    if static_path is None:
        static_path = Path(
            os.environ.get(
                "X_POST_WATCH_CONFIG_PATH",
                str(Path(__file__).resolve().parent.parent / "config" / "watches.json"),
            )
        )
    return LoadedWatchConfig(load_watch_config(static_path), None)
