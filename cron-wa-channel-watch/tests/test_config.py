import json
from types import SimpleNamespace

import pytest

import config
from config import load


def profile(**overrides):
    value = {
        "id": "bri-danareksa-sekuritas",
        "enabled": True,
        "mode": "forward",
        "channel_jid": "12345@newsletter",
        "channel_url": "https://whatsapp.com/channel/0029Example",
        "display_name": "BRI Danareksa Sekuritas",
        "emoji": "<:bridanareksa:1549256273109848124>",
        "status_emojis": {
            "up": "<:up:1531285100346740766>",
            "down": "<:down:1531285063986053200>",
            "hold": "<:hold:1531284248235868333>",
        },
        "discord_channels": [{"key": "macro_news", "channel_id": "1505162000420835388", "description": "Macro and market news"}],
        "forward_media": True,
        "enable_llm_title": True,
        "enable_llm_summary": True,
        "enable_llm_routing": True,
        "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market",
        "additional_prompt_instruction": "",
        "max_items_per_poll": 20,
    }
    value.update(overrides)
    return value


def write_config(tmp_path, profiles):
    path = tmp_path / "watches.json"
    path.write_text(json.dumps({"version": 2, "profiles": profiles}), encoding="utf-8")
    return path


def test_loads_strict_profile(tmp_path):
    result = load(write_config(tmp_path, [profile()]))
    assert result.profiles[0].channel_jid.endswith("@newsletter")
    assert result.profiles[0].uses_llm is True
    assert result.profiles[0].status_emojis.hold == "<:hold:1531284248235868333>"


def test_live_config_snapshot_is_validated_once(tmp_path, monkeypatch):
    payload = profile()
    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID", "bursawatch-wa-channel-watch")
    monkeypatch.setattr(
        "config._fetch_live_config",
        lambda: SimpleNamespace(
            watcher_id="bursawatch-wa-channel-watch",
            revision=8,
            config={"version": 2, "profiles": [payload]},
        ),
    )

    loaded = __import__("config").load_for_run()

    assert loaded.revision == 8
    assert loaded.config.profiles[0].channel_jid == "12345@newsletter"


def test_live_config_does_not_fall_back_to_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID", "bursawatch-wa-channel-watch")
    monkeypatch.setattr("config._fetch_live_config", lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    with pytest.raises(RuntimeError, match="offline"):
        __import__("config").load_for_run(write_config(tmp_path, [profile()]))


@pytest.mark.parametrize("change", [
    {"channel_jid": "12345@g.us"},
    {"emoji": "not-an-emoji"},
    {"status_emojis": {"up": "not-an-emoji", "down": None, "hold": None}},
    {"discord_channels": []},
    {"max_items_per_poll": 51},
    {"unknown": True},
])
def test_rejects_invalid_profile(tmp_path, change):
    value = profile()
    value.update(change)
    with pytest.raises(ValueError):
        load(write_config(tmp_path, [value]))


def test_rejects_duplicate_channel_ids(tmp_path):
    with pytest.raises(ValueError, match="channel JIDs"):
        load(write_config(tmp_path, [profile(), profile(id="other")]))


def test_observe_profile_needs_no_discord_presentation(tmp_path):
    observed = profile(
        id="ins",
        channel_jid="120363405187024421@newsletter",
        mode="observe",
        emoji=None,
        discord_channels=[],
        enable_llm_title=False,
        enable_llm_summary=False,
        enable_llm_routing=False,
        enable_llm_relevance_filter=False,
        forward_media=False,
    )

    loaded = config.load_data({"version": 2, "profiles": [observed]})

    assert loaded.profiles[0].is_observing is True
    assert loaded.profiles[0].is_forwarding is False


def test_forward_profile_requires_routes_and_presentation():
    with pytest.raises(ValueError, match="forward profile requires"):
        config.load_data({"version": 2, "profiles": [profile(mode="forward", emoji=None)]})
