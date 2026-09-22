from dataclasses import replace
from datetime import datetime, timezone

from config import ChannelProfile, DiscordChannel, StatusEmojis
from normalize import normalize_bridge_event
from render import render_post


def profile():
    return ChannelProfile(
        id="channel", enabled=True, mode="forward", channel_jid="1@newsletter",
        channel_url="https://whatsapp.com/channel/example", display_name="BRI Danareksa Sekuritas",
        emoji="<:bridanareksa:1551797903927025797>",
        status_emojis=StatusEmojis(
            up="<:up:1531285100346740766>",
            down="<:down:1531285063986053200>",
            hold="<:hold:1531284248235868333>",
        ),
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
    assert "<:bridanareksa:1551797903927025797>" in messages[0]
    assert "-# BRI Danareksa Sekuritas" not in messages[0]
    assert "*(Ringkasan)*" in messages[0]
    assert "https://whatsapp.com/channel/example" in messages[0]
    assert len(messages[0]) <= 2000


def test_render_splits_long_source_without_exceeding_discord_limit():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "x", "published_at": datetime.now(timezone.utc).isoformat(),
        "text": "word " * 1000, "media": [],
    })
    assert all(len(message) <= 2000 for message in render_post(profile(), event))


def test_render_uses_phintraco_shaped_bri_swing_shell(tmp_path):
    chart = tmp_path / "tins-chart.jpg"
    chart.write_bytes(b"chart")
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "technical", "published_at": "2026-09-11T03:03:00Z",
        "text": "_*#TechnicalReview #ClientRequest*_\nTINS masih berada dalam bullish trend.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(chart)}],
    })
    message = render_post(profile(), event, title="TINS: Tren Bullish", summary="Rebound bertahan di atas support.", route="id_stocks_swing", sentiment="Bullish")[0]
    assert "-# BRI Danareksa Sekuritas" in message
    assert "**Sentiment:** Bullish <:up:1531285100346740766>" in message
    assert "**Sentiment date:** 11 Sep 2026 10:03 WIB" in message
    assert "**Reasons:** Rebound bertahan di atas support." in message
    assert "**Last updated:** 11 Sep 2026 10:03 WIB" in message
    assert "**Board:** <#1548273399069933720>" in message
    assert "[View on WhatsApp](<https://whatsapp.com/channel/example>)" in message
    assert "Status:" not in message
    assert "Chart:" not in message


def test_render_does_not_put_media_state_in_the_swing_text():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "missing-chart", "published_at": "2026-09-11T03:03:00Z",
        "text": "#TechnicalReview\nTINS bullish.", "media": [],
    })
    message = render_post(profile(), event, title="TINS: Tren Bullish", summary="TINS bullish.", route="id_stocks_swing", sentiment="Bullish")[0]
    assert "**Sentiment:** Bullish" in message
    assert "Chart:" not in message


def test_render_preserves_down_and_hold_status_emojis():
    cases = (
        ("#TechnicalReview\nSektor ini bearish.", "Bearish<:down:1531285063986053200>"),
        ("#TechnicalReview\nRekomendasi saham: Hold.", "Hold<:hold:1531284248235868333>"),
    )
    for index, (text, expected) in enumerate(cases):
        event = normalize_bridge_event({
            "channel_jid": "1@newsletter", "message_id": f"status-{index}",
            "published_at": "2026-09-11T03:03:00Z", "text": text, "media": [],
        })
        sentiment = "Bearish" if index == 0 else "Sideways"
        message = render_post(profile(), event, title="BBCA: Status", summary="Status sumber.", route="id_stocks_swing", sentiment=sentiment)[0]
        assert f"**Sentiment:** {sentiment}" in message


def test_render_keeps_sentiment_without_emoji_configuration():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "plain-status",
        "published_at": "2026-09-11T03:03:00Z", "text": "#TechnicalReview\nBBCA remains Overweight.", "media": [],
    })
    no_status_emojis = replace(profile(), status_emojis=StatusEmojis(up=None, down=None, hold=None))
    message = render_post(no_status_emojis, event, title="BBCA: Outlook", summary="Outlook.", route="id_stocks_swing", sentiment="Bullish")[0]
    assert "**Sentiment:** Bullish" in message
    assert "Status: Overweight<:" not in message


def test_render_does_not_infer_status_from_generic_sentiment():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "positive", "published_at": "2026-09-11T03:03:00Z",
        "text": "Prospek perusahaan positif dan kinerja membaik.", "media": [],
    })
    message = render_post(profile(), event, title="BBCA: Kinerja Membaik", summary="*(Ringkasan)* Kinerja membaik.")[0]
    assert "Status:" not in message
    assert "[View on WhatsApp Channel]" in message


def test_render_omits_status_and_date_for_macro_news():
    event = normalize_bridge_event({
        "channel_jid": "1@newsletter", "message_id": "macro-status",
        "published_at": "2026-09-16T05:03:00Z",
        "text": "Broad market outlook is Bearish after higher UST yields.", "media": [],
    })
    message = render_post(
        profile(),
        event,
        title="Menkeu Baru dan Revisi HPM Nikel",
        summary="*(Ringkasan)* IHSG turun setelah kenaikan yield UST dan harga minyak.",
        route="macro_news",
    )[0]
    assert "Menkeu Baru dan Revisi HPM Nikel" in message
    assert "Status:" not in message
    assert "Status date:" not in message
    assert "[View on WhatsApp Channel]" in message
