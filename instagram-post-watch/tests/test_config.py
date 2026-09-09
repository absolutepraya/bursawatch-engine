import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

import config as config_module
from models import MediaKind, PublicationKind, SourceMedia, SourcePost


def write_config(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_config_parses_the_approved_profile(config_path):
    profile = config_module.load_watch_config(config_path).profiles[0]

    assert profile.id == "beyondthefundamental"
    assert profile.source == "rsshub"
    assert profile.platform_emoji == "📸"
    assert profile.emoji == ""
    assert tuple(channel.key for channel in profile.discord_channels) == ("macro_news", "id_stocks_news")
    assert profile.ocr_languages == ("ind", "eng")
    assert profile.ocr_min_confidence == 0.70
    assert profile.max_reel_frames == 5
    assert profile.uses_llm is True
    assert profile.channel_for("macro_news").channel_id == "1531655369884045382"


def test_load_config_builds_instagram_feed_url(config_path):
    profile = config_module.load_watch_config(config_path).profiles[0]

    assert profile.handle == "beyondthefundamental"
    assert profile.feed_url == (
        "http://127.0.0.1:1201/instagram/2/user/"
        "beyondthefundamental?format=json"
    )


def test_load_config_contains_the_approved_public_profile_rollout():
    watches = config_module.load_watch_config(Path(__file__).parent.parent / "config" / "watches.json")

    assert [profile.id for profile in watches.profiles] == [
        "beyondthefundamental",
        "investart_id",
        "avenirresearch_id",
        "acresresearch",
        "sectorsapp",
    ]
    assert [profile.handle for profile in watches.profiles] == [
        "beyondthefundamental",
        "investart_id",
        "avenirresearch.id",
        "acresresearch",
        "sectorsapp",
    ]
    assert all(profile.enabled and profile.source == "rsshub" for profile in watches.profiles)
    assert all(profile.uses_llm for profile in watches.profiles)
    assert all(profile.max_items_per_poll == 20 for profile in watches.profiles)
    assert all(
        tuple(channel.key for channel in profile.discord_channels) == ("macro_news", "id_stocks_news")
        for profile in watches.profiles
    )


def test_models_are_immutable_normalized_publications():
    media = SourceMedia("https://media.example/image.jpg", MediaKind.IMAGE, 0)
    publication = SourcePost(
        "beyondthefundamental",
        "123",
        "https://www.instagram.com/p/shortcode",
        datetime(2026, 8, 24, tzinfo=UTC),
        "<p>Caption</p>",
        PublicationKind.POST,
        (media,),
    )

    assert publication.media == (media,)
    with pytest.raises(FrozenInstanceError):
        publication.publication_id = "456"


def test_load_config_rejects_duplicate_ids(config_path, profile_payload):
    second = profile_payload | {
        "handle": "other.account",
        "profile_url": "https://instagram.com/other.account",
    }
    write_config(config_path, {"version": 1, "profiles": [profile_payload, second]})

    with pytest.raises(ValueError, match="ids must be unique"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_duplicate_handles_ignoring_case(config_path, profile_payload):
    second = profile_payload | {
        "id": "other",
        "handle": "BEYONDTHEFUNDAMENTAL",
        "profile_url": "https://instagram.com/BEYONDTHEFUNDAMENTAL",
    }
    write_config(config_path, {"version": 1, "profiles": [profile_payload, second]})

    with pytest.raises(ValueError, match="handles must be unique"):
        config_module.load_watch_config(config_path)


@pytest.mark.parametrize(
    ("profile_url", "message"),
    [
        ("https://example.com/beyondthefundamental", "instagram.com"),
        ("https://www.instagram.com/beyondthefundamental?source=feed", "query"),
        ("https://www.instagram.com/beyondthefundamental?", "exactly"),
        ("https://www.instagram.com/beyondthefundamental#top", "fragment"),
        ("https://www.instagram.com/beyondthefundamental#", "exactly"),
        ("https://www.instagram.com/beyondthefundamental/", "path must match"),
        ("https://www.instagram.com/beyondthefundamental/extra", "path must match"),
    ],
)
def test_load_config_rejects_noncanonical_profile_urls(config_path, profile_payload, profile_url, message):
    profile_payload["profile_url"] = profile_url
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match=message):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_invalid_instagram_handle(config_path, profile_payload):
    profile_payload["handle"] = "not-valid!"
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match="valid Instagram handle"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_missing_required_profile_field(config_path, profile_payload):
    del profile_payload["ocr_languages"]
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match="missing fields: ocr_languages"):
        config_module.load_watch_config(config_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"unexpected": True}), "unknown fields"),
        (lambda payload: payload["discord_channels"][0].update({"unexpected": True}), "only key, channel_id, and description"),
    ],
)
def test_load_config_rejects_unknown_object_fields(config_path, profile_payload, mutate, message):
    mutate(profile_payload)
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match=message):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_unknown_root_fields(config_path, profile_payload):
    write_config(config_path, {"version": 1, "profiles": [profile_payload], "unexpected": True})

    with pytest.raises(ValueError, match="only version and profiles"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_duplicate_channel_keys(config_path, profile_payload):
    profile_payload["discord_channels"][1]["key"] = "macro_news"
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match="keys must be unique"):
        config_module.load_watch_config(config_path)


def test_load_config_rejects_invalid_discord_snowflake(config_path, profile_payload):
    profile_payload["discord_channels"][0]["channel_id"] = "not-a-snowflake"
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match="Discord snowflake"):
        config_module.load_watch_config(config_path)


def test_load_config_requires_canonical_news_channels_when_routing_is_enabled(config_path, profile_payload):
    profile_payload["discord_channels"] = [profile_payload["discord_channels"][0]]
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match="macro_news and id_stocks_news"):
        config_module.load_watch_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ocr_languages", ["fra"], "supported OCR language"),
        ("ocr_min_confidence", -0.01, "0 and 1"),
        ("ocr_min_confidence", 1.01, "0 and 1"),
        ("max_reel_frames", 0, "1 to 8"),
        ("max_reel_frames", 9, "1 to 8"),
        ("max_items_per_poll", 0, "1 to 100"),
        ("max_items_per_poll", 101, "1 to 100"),
    ],
)
def test_load_config_rejects_out_of_range_profile_settings(config_path, profile_payload, field, value, message):
    profile_payload[field] = value
    write_config(config_path, {"version": 1, "profiles": [profile_payload]})

    with pytest.raises(ValueError, match=message):
        config_module.load_watch_config(config_path)
