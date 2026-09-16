from datetime import datetime

import pytest

from swing_format import (
    BOARD_URL,
    GREEN_EMOJI,
    HOLD_EMOJI,
    RED_EMOJI,
    GREY_EMOJI,
    SwingMessage,
    fields,
    render_message,
    source_status_emoji,
)
from bri_adapter import build_message


NOW = datetime(2026, 9, 19, 6, 50, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Jakarta"))


def message(status: str = "New setup") -> SwingMessage:
    return SwingMessage(
        source_emoji="<:phintraco:1>",
        title="PYFA: Buy",
        analyst_name="Alrich Paskalis T",
        institution="Phintraco Sekuritas",
        fields=fields(("Type", "Buy on Support <:up:2>"), ("Entry", ">=246"), ("Stop-loss", "<236")),
        body=("**Reasons:** Potensi rebound.",),
        source_status=status,
        updated_at=NOW,
        source_url="https://t.me/phintraprofits/35168",
        footer_label="View in Telegram",
    )


def test_all_message_places_board_directly_after_last_updated() -> None:
    rendered = render_message(message(), include_board=True)

    assert "**Source status:** New setup " + GREY_EMOJI in rendered
    assert "**Last updated:** 19 Sep 2026 06:50 WIB\n**Board:** <" + BOARD_URL + ">" in rendered
    assert "\n\n**Board:**" not in rendered
    assert rendered.endswith("[View in Telegram](<https://t.me/phintraprofits/35168>)")


def test_board_copy_omits_board_link_and_preserves_spacing() -> None:
    rendered = render_message(message(), include_board=False)

    assert "**Board:**" not in rendered
    assert "\n\n**Source status:**" in rendered
    assert "Support <:up:2>" in rendered


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Stop-loss hit", RED_EMOJI),
        ("First target 274 achieved", GREEN_EMOJI),
        ("On track", HOLD_EMOJI),
        ("On support", HOLD_EMOJI),
        ("New setup", GREY_EMOJI),
    ],
)
def test_status_emoji_precedence(status: str, expected: str) -> None:
    assert source_status_emoji(status) == expected


def test_byline_falls_back_to_institution() -> None:
    rendered = render_message(SwingMessage(
        source_emoji="<:phintraco:1>", title="PYFA: Hold", analyst_name=None,
        institution="Phintraco Sekuritas", body=(), source_status="On track",
        updated_at=NOW, source_url=None, footer_label="View in Telegram",
    ))
    assert "-# Phintraco Sekuritas" in rendered
    assert "Investment Advisor" not in rendered


def test_bri_adapter_is_future_ready_without_changing_live_routes() -> None:
    rendered = render_message(build_message(
        ticker="BBRI",
        title="Hold",
        body=("**Reasons:** Source text.",),
        source_status="On track",
        published_at=NOW,
        source_url="https://wa.example/101",
    ))
    assert "BRI Danareksa" in rendered
    assert "BBRI: Hold" in rendered
    assert "[View on WhatsApp](<https://wa.example/101>)" in rendered
