from datetime import datetime
from dataclasses import replace
from zoneinfo import ZoneInfo

from conftest import example_buy_event
from models import Checkpoint, MarketState
from render import (
    discord_length,
    format_wib,
    render_history,
    render_history_replies,
    render_primary_card,
    render_source_only_card,
)


WIB = ZoneInfo("Asia/Jakarta")


def test_primary_card_uses_ticker_first_and_live_fields() -> None:
    checkpoint = Checkpoint.market(
        session_date="2026-09-19",
        checked_at="2026-09-19T16:30:00+07:00",
        close_price="230",
        state=MarketState.TP1_REACHED,
    )

    event = replace(
        example_buy_event(),
        all_content=(
            "### <:phintraco:1531272488645038091> SCMA: Buy\n"
            "-# Alrich Paskalis T, Investment Advisor"
        ),
    )
    card = render_primary_card(event, checkpoint)

    assert card.startswith(
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Alrich Paskalis T, Investment Advisor\n\n"
    )
    assert "**Entry:** 208 to 212" in card
    assert "**Stop-loss:** <200" in card
    assert "**Target 1:** 230" in card
    assert "**Source status:** New setup" in card
    assert "**Market checkpoint:** TP1 reached" in card
    assert "**Closing price:** Rp230" in card
    assert "**Last checked:** 19 Sep 2026 16:30 WIB" in card
    assert "**Source:**" not in card
    assert card.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_primary_card_uses_firm_byline_when_source_has_none() -> None:
    card = render_primary_card(example_buy_event())

    assert card.startswith(
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Phintraco Sekuritas\n\n"
    )
    assert "Alrich Paskalis T" not in card


def test_unavailable_checkpoint_preserves_the_source_card_without_fabricating_price() -> None:
    checkpoint = Checkpoint.unavailable_at(
        session_date="2026-09-19", checked_at="2026-09-19T17:00:00+07:00"
    )

    card = render_primary_card(example_buy_event(), checkpoint)

    assert "**Market checkpoint:** Market check unavailable" in card
    assert "**Closing price:**" not in card
    assert "**Last checked:**" not in card


def test_unavailable_checkpoint_can_retain_the_last_valid_market_facts() -> None:
    unavailable = Checkpoint.unavailable_at(
        session_date="2026-09-19", checked_at="2026-09-19T17:00:00+07:00"
    )
    last_valid = Checkpoint.market(
        session_date="2026-09-18",
        checked_at="2026-09-18T16:30:00+07:00",
        close_price="225",
        state=MarketState.ABOVE_ENTRY,
    )

    card = render_primary_card(example_buy_event(), unavailable, last_valid)

    assert "**Market checkpoint:** Market check unavailable" in card
    assert "**Closing price:** Rp225" in card
    assert "**Last checked:** 18 Sep 2026 16:30 WIB" in card


def test_source_only_card_escapes_the_exact_source_title() -> None:
    assert render_source_only_card("KPIG: setup *pending*") == (
        "### KPIG: setup \\*pending\\*\n\n"
        "**Primary plan:** No Phintraco plan yet"
    )


def test_system_history_is_a_two_line_quote() -> None:
    assert render_history(
        "19 Sep 2026 16:30 WIB", "Market checkpoint: TP1 reached at Rp230"
    ) == (
        "> 19 Sep 2026 16:30 WIB\n"
        "> Market checkpoint: TP1 reached at Rp230"
    )


def test_long_history_is_losslessly_chunked_with_quote_prefixes() -> None:
    detail = "Source Status: " + ("📈 status detail " * 500)
    replies = render_history_replies("19 Sep 2026 16:30 WIB", detail)

    assert len(replies) > 1
    assert all(discord_length(reply) <= 2_000 for reply in replies)
    assert replies[0].startswith("> 19 Sep 2026 16:30 WIB\n> ")
    assert all(reply.startswith("> ") for reply in replies)
    first_detail = replies[0].split("\n> ", 1)[1]
    assert first_detail + "".join(reply[2:] for reply in replies[1:]) == detail


def test_history_splits_without_whitespace_and_preserves_utf16_units() -> None:
    detail = "Source Status: " + ("📈" * 2_500)
    replies = render_history_replies("19 Sep 2026 16:30 WIB", detail)

    assert all(discord_length(reply) <= 2_000 for reply in replies)
    first_detail = replies[0].split("\n> ", 1)[1]
    assert first_detail + "".join(reply[2:] for reply in replies[1:]) == detail


def test_format_wib_converts_an_aware_timestamp() -> None:
    assert format_wib(datetime(2026, 9, 19, 9, 30, tzinfo=ZoneInfo("UTC"))) == (
        "19 Sep 2026 16:30 WIB"
    )
