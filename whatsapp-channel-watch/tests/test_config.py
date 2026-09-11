import json

import pytest

from config import load


def profile(**overrides):
    value = {
        "id": "bri-danareksa-sekuritas",
        "enabled": True,
        "channel_jid": "12345@newsletter",
        "channel_url": "https://whatsapp.com/channel/0029Example",
        "display_name": "BRI Danareksa Sekuritas",
        "emoji": "<:bridanareksa:1547932957598285844>",
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
    path.write_text(json.dumps({"version": 1, "profiles": profiles}), encoding="utf-8")
    return path


def test_loads_strict_profile(tmp_path):
    result = load(write_config(tmp_path, [profile()]))
    assert result.profiles[0].channel_jid.endswith("@newsletter")
    assert result.profiles[0].uses_llm is True
    assert result.profiles[0].status_emojis.hold == "<:hold:1531284248235868333>"


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
