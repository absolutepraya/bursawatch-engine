import json
from pathlib import Path

import pytest

import config as config_module


def write_config(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_config_builds_profile_and_feed_url(config_path):
    config = config_module.load_watch_config(config_path)
    profile = config.profiles[0]
    assert profile.id == "kutekians"
    assert profile.feed_url == "http://127.0.0.1:1200/twitter/user/Kutekians?format=json"
    assert profile.thread_handling.max_posts == 10
    assert profile.thread_handling.max_age_minutes == 240
    assert profile.thread_handling.settle_minutes == 60


def test_canonical_almer_profile_uses_llm_summary():
    canonical_config = Path(__file__).resolve().parents[1] / "config" / "watches.json"
    profiles = {profile.id: profile for profile in config_module.load_watch_config(canonical_config).profiles}

    assert profiles["kutekians"].enable_llm_title is True
    assert profiles["kutekians"].enable_llm_summary is True
    assert profiles["kutekians"].enable_llm_routing is False


def test_canonical_thread_handling_matches_writer_patterns():
    canonical_config = Path(__file__).resolve().parents[1] / "config" / "watches.json"
    profiles = {profile.id: profile for profile in config_module.load_watch_config(canonical_config).profiles}

    assert (profiles["kutekians"].thread_handling.mode, profiles["kutekians"].thread_handling.settle_minutes) == ("disabled", 60)
    assert (profiles["rickyho1989"].thread_handling.mode, profiles["rickyho1989"].thread_handling.settle_minutes) == ("disabled", 60)
    assert (profiles["writingtorch"].thread_handling.mode, profiles["writingtorch"].thread_handling.settle_minutes) == ("self_chain", 15)
    assert (profiles["arvinhonami"].thread_handling.mode, profiles["arvinhonami"].thread_handling.settle_minutes) == ("disabled", 60)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "Uppercase", "id"),
        ("profile_url", "https://twitter.com/Kutekians", "profile_url"),
        ("profile_url", "https://x.com/not-kutekians", "path must match"),
        ("display_name", "", "display_name"),
        ("emoji", "kutekians", "emoji"),
        ("discord_channels", [], "non-empty array"),
        ("forward_quote_post", 1, "boolean"),
        ("enable_llm_title", "yes", "boolean"),
        ("enable_llm_summary", "yes", "boolean"),
        ("enable_llm_routing", "yes", "boolean"),
        ("enable_llm_relevance_filter", "yes", "boolean"),
        ("additional_prompt_instruction", 1, "must be text"),
        ("max_items_per_poll", 101, "1 to 100"),
        ("thread_handling", {"mode": "self_chain", "max_posts": 11, "max_age_minutes": 240, "settle_minutes": 60}, "1 to 10"),
    ],
)
def test_load_config_rejects_invalid_profile_fields(config_path, profile_payload, field, value, message):
    profile_payload[field] = value
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    with pytest.raises(ValueError, match=message):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_duplicate_id(config_path, profile_payload):
    second = profile_payload | {"handle": "OtherUser", "profile_url": "https://x.com/OtherUser"}
    write_config(config_path, {"version": 1, "profiles": [profile_payload, second]})
    with pytest.raises(ValueError, match="ids must be unique"):
        config_module.load_watch_config(config_path)


def test_load_config_normalizes_profile_specific_instruction(config_path, profile_payload):
    profile_payload["additional_prompt_instruction"] = "  Keep only  \n market analysis. "
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    assert config_module.load_watch_config(config_path).profiles[0].additional_prompt_instruction == "Keep only market analysis."


def test_load_config_rejects_duplicate_handle_ignoring_case(config_path, profile_payload):
    second = profile_payload | {"id": "other", "handle": "KUTEKIANS", "profile_url": "https://x.com/KUTEKIANS"}
    write_config(config_path, {"version": 1, "profiles": [profile_payload, second]})
    with pytest.raises(ValueError, match="handles must be unique"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_unknown_fields(config_path, profile_payload):
    profile_payload["secret"] = "must-not-be-accepted"
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    with pytest.raises(ValueError, match="unknown fields"):
        config_module.load_watch_config(config_path)


def test_load_config_requires_multiple_channels_when_llm_routing_is_enabled(config_path, profile_payload):
    profile_payload["enable_llm_routing"] = True
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    with pytest.raises(ValueError, match="at least two"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_duplicate_routing_channel_keys(config_path, profile_payload):
    profile_payload.update({
        "enable_llm_routing": True,
        "discord_channels": [
            {"key": "macro", "channel_id": "1531655369884045382", "description": "Macro"},
            {"key": "macro", "channel_id": "1525102508714889257", "description": "Duplicate"},
        ],
    })
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    with pytest.raises(ValueError, match="keys must be unique"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_duplicate_routing_channel_ids(config_path, profile_payload):
    profile_payload.update({
        "enable_llm_routing": True,
        "discord_channels": [
            {"key": "macro", "channel_id": "1531655369884045382", "description": "Macro"},
            {"key": "id_stock", "channel_id": "1531655369884045382", "description": "IDX"},
        ],
    })
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})
    with pytest.raises(ValueError, match="destination channel ids must differ"):
        config_module.load_watch_config(config_path)
