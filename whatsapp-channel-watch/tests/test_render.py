from datetime import datetime, timezone

from config import ChannelProfile, DiscordChannel
from normalize import normalize_bridge_event
from render import render_post


def profile():
    return ChannelProfile(
        id="channel", enabled=True, channel_jid="1@newsletter",
        channel_url="https://whatsapp.com/channel/example", display_name="BRI Danareksa Sekuritas",
        discord_channels=(DiscordChannel("macro_news", "1505162000420835388", "Macro"),),
        forward_media=True, enable_llm_title=True, enable_llm_summary=True,
        enable_llm_routing=True, enable_llm_relevance_filter=True,
        relevance_scope="financial_market", additional_prompt_instruction="", max_items_per_poll=20,
    )


def test_render_contains_title_summary_and_channel_source():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "x", "published_at": datetime.now(timezone.utc).isoformat(),
        "text": "source text", "media": [],
    })
    messages = render_post(profile(), event, title="BBCA: Laba Naik", summary="*(Ringkasan)* Ringkasan sumber.")
    assert len(messages) == 1
    assert "BBCA: Laba Naik" in messages[0]
    assert "*(Ringkasan)*" in messages[0]
    assert "https://whatsapp.com/channel/example" in messages[0]
    assert len(messages[0]) <= 2000


def test_render_splits_long_source_without_exceeding_discord_limit():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "x", "published_at": datetime.now(timezone.utc).isoformat(),
        "text": "word " * 1000, "media": [],
    })
    assert all(len(message) <= 2000 for message in render_post(profile(), event))
