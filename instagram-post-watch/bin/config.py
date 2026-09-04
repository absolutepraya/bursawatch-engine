from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from models import DiscordChannel, Profile, WatchConfig


CONFIG_VERSION = 1
PROFILE_FIELDS = {
    "id",
    "enabled",
    "source",
    "profile_url",
    "handle",
    "display_name",
    "platform_emoji",
    "emoji",
    "discord_channels",
    "forward_post",
    "forward_reel",
    "forward_media",
    "enable_llm_title",
    "enable_llm_summary",
    "enable_llm_routing",
    "enable_llm_relevance_filter",
    "additional_prompt_instruction",
    "max_items_per_poll",
    "ocr_languages",
    "ocr_min_confidence",
    "max_reel_frames",
}
CHANNEL_FIELDS = {"key", "channel_id", "description"}
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
HANDLE_RE = re.compile(r"[A-Za-z0-9._]{1,30}")
DISCORD_ID_RE = re.compile(r"\d{17,20}")
OCR_LANGUAGES = {"eng", "ind"}


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


def _validate_profile_url(profile_url: str, handle: str) -> None:
    parsed = urlparse(profile_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("profile_url must be an https://instagram.com/<handle> URL")
    if parsed.query:
        raise ValueError("profile_url must not include a query")
    if parsed.fragment:
        raise ValueError("profile_url must not include a fragment")
    if parsed.params:
        raise ValueError("profile_url must not include parameters")
    if parsed.path != f"/{handle}":
        raise ValueError("profile_url path must match handle exactly")
    if profile_url not in {
        f"https://instagram.com/{handle}",
        f"https://www.instagram.com/{handle}",
    }:
        raise ValueError("profile_url must exactly match an approved Instagram profile URL")


def _parse_channels(value: object, label: str) -> tuple[DiscordChannel, ...]:
    if type(value) is not list or not value:
        raise ValueError(f"{label} must be a non-empty array")
    channels: list[DiscordChannel] = []
    for index, raw_channel in enumerate(value):
        channel = _expect_object(raw_channel, f"{label}[{index}]")
        if set(channel) != CHANNEL_FIELDS:
            raise ValueError(f"{label}[{index}] must contain only key, channel_id, and description")
        key = _expect_string(channel["key"], f"{label}[{index}].key")
        if not ID_RE.fullmatch(key):
            raise ValueError(f"{label}[{index}].key must use lowercase letters, digits, _ or -")
        channel_id = _expect_string(channel["channel_id"], f"{label}[{index}].channel_id")
        if not DISCORD_ID_RE.fullmatch(channel_id):
            raise ValueError(f"{label}[{index}].channel_id must be a Discord snowflake")
        channels.append(DiscordChannel(key, channel_id, _expect_string(channel["description"], f"{label}[{index}].description")))
    if len({channel.key for channel in channels}) != len(channels):
        raise ValueError(f"{label} keys must be unique")
    if len({channel.channel_id for channel in channels}) != len(channels):
        raise ValueError(f"{label} destination channel ids must differ")
    return tuple(channels)


def _parse_ocr_languages(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or not value or any(type(language) is not str for language in value):
        raise ValueError(f"{label} must be a non-empty array of supported OCR languages")
    languages = tuple(value)
    if any(language not in OCR_LANGUAGES for language in languages):
        raise ValueError(f"{label} contains an unsupported OCR language")
    if len(set(languages)) != len(languages):
        raise ValueError(f"{label} values must be unique")
    return languages


def _parse_profile(index: int, value: object) -> Profile:
    profile = _expect_object(value, f"profiles[{index}]")
    fields = set(profile)
    missing = PROFILE_FIELDS - fields
    unknown = fields - PROFILE_FIELDS
    if missing:
        raise ValueError(f"profiles[{index}] missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"profiles[{index}] unknown fields: {', '.join(sorted(unknown))}")

    profile_id = _expect_string(profile["id"], f"profiles[{index}].id")
    if not ID_RE.fullmatch(profile_id):
        raise ValueError(f"profiles[{index}].id must use lowercase letters, digits, _ or -")
    handle = _expect_string(profile["handle"], f"profiles[{index}].handle")
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError(f"profiles[{index}].handle must be a valid Instagram handle")
    source = _expect_string(profile["source"], f"profiles[{index}].source")
    if source != "rsshub":
        raise ValueError(f"profiles[{index}].source must be rsshub")
    profile_url = _expect_string(profile["profile_url"], f"profiles[{index}].profile_url")
    _validate_profile_url(profile_url, handle)
    channels = _parse_channels(profile["discord_channels"], f"profiles[{index}].discord_channels")
    enable_llm_routing = _expect_bool(profile["enable_llm_routing"], f"profiles[{index}].enable_llm_routing")
    if enable_llm_routing and not {"macro", "id_stock"}.issubset(channel.key for channel in channels):
        raise ValueError(f"profiles[{index}].discord_channels must contain macro and id_stock when enable_llm_routing is true")
    max_items = profile["max_items_per_poll"]
    if type(max_items) is not int or not 1 <= max_items <= 100:
        raise ValueError(f"profiles[{index}].max_items_per_poll must be an integer from 1 to 100")
    confidence = profile["ocr_min_confidence"]
    if type(confidence) not in {int, float} or not 0 <= confidence <= 1:
        raise ValueError(f"profiles[{index}].ocr_min_confidence must be a number between 0 and 1")
    max_reel_frames = profile["max_reel_frames"]
    if type(max_reel_frames) is not int or not 1 <= max_reel_frames <= 8:
        raise ValueError(f"profiles[{index}].max_reel_frames must be an integer from 1 to 8")
    emoji = profile["emoji"]
    if type(emoji) is not str:
        raise ValueError(f"profiles[{index}].emoji must be text")
    instruction = profile["additional_prompt_instruction"]
    if type(instruction) is not str:
        raise ValueError(f"profiles[{index}].additional_prompt_instruction must be text")

    return Profile(
        id=profile_id,
        enabled=_expect_bool(profile["enabled"], f"profiles[{index}].enabled"),
        source=source,
        profile_url=profile_url,
        handle=handle,
        display_name=_expect_string(profile["display_name"], f"profiles[{index}].display_name"),
        platform_emoji=_expect_string(profile["platform_emoji"], f"profiles[{index}].platform_emoji"),
        emoji=emoji,
        discord_channels=channels,
        forward_post=_expect_bool(profile["forward_post"], f"profiles[{index}].forward_post"),
        forward_reel=_expect_bool(profile["forward_reel"], f"profiles[{index}].forward_reel"),
        forward_media=_expect_bool(profile["forward_media"], f"profiles[{index}].forward_media"),
        enable_llm_title=_expect_bool(profile["enable_llm_title"], f"profiles[{index}].enable_llm_title"),
        enable_llm_summary=_expect_bool(profile["enable_llm_summary"], f"profiles[{index}].enable_llm_summary"),
        enable_llm_routing=enable_llm_routing,
        enable_llm_relevance_filter=_expect_bool(profile["enable_llm_relevance_filter"], f"profiles[{index}].enable_llm_relevance_filter"),
        additional_prompt_instruction=instruction,
        max_items_per_poll=max_items,
        ocr_languages=_parse_ocr_languages(profile["ocr_languages"], f"profiles[{index}].ocr_languages"),
        ocr_min_confidence=float(confidence),
        max_reel_frames=max_reel_frames,
    )


def load_watch_config(path: Path) -> WatchConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"watch configuration is invalid JSON: {exc.msg}") from exc
    root = _expect_object(raw, "watch configuration")
    if set(root) != {"version", "profiles"}:
        raise ValueError("watch configuration must contain only version and profiles")
    if root["version"] != CONFIG_VERSION:
        raise ValueError(f"watch configuration version must be {CONFIG_VERSION}")
    if type(root["profiles"]) is not list or not root["profiles"]:
        raise ValueError("watch configuration profiles must be a non-empty array")
    profiles = tuple(_parse_profile(index, profile) for index, profile in enumerate(root["profiles"]))
    if len({profile.id for profile in profiles}) != len(profiles):
        raise ValueError("watch configuration profile ids must be unique")
    if len({profile.handle.lower() for profile in profiles}) != len(profiles):
        raise ValueError("watch configuration handles must be unique ignoring case")
    return WatchConfig(CONFIG_VERSION, profiles)
