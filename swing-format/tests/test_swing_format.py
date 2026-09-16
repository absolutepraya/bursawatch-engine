from datetime import datetime

import pytest

from swing_format import (
    BOARD_URL,
    canonicalize_phintraco_message,
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


def test_legacy_phintraco_buy_is_rewritten_with_analyst_and_canonical_dates() -> None:
    legacy = (
        "### <:phintraco:1531272488645038091> BUY: **PYFA**\n\n"
        "**Type:** Buy on Support<:up:1531285100346740766>\n"
        "**Entry:** >=246\n**Stop-loss:** <236\n**Target 1:** 274\n"
        "**Target 2:** 296\n"
        "**Signal date:** Fri, Sep 11 2026, 06:50 WIB\n\n"
        "**Reasons:** Potensi rebound.\n\n"
        "**Source:** [Phintraco Sekuritas](<https://t.me/phintraprofits/35168>) | "
        "Alrich Paskalis T, Investment Advisor"
    )
    rendered = canonicalize_phintraco_message(legacy, include_board=True, has_chart=True)

    assert rendered.startswith(
        "### <:phintraco:1531272488645038091> PYFA: Buy\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Type:** Buy on Support <:up:1531285100346740766>\n"
    )
    assert "**Signal date:** 11 Sep 2026 06:50 WIB" in rendered
    assert "**Board:** <" + BOARD_URL + ">" in rendered
    assert "**Chart:**" not in rendered


def test_legacy_phintraco_hold_uses_institution_fallback_and_drops_chart_line() -> None:
    legacy = (
        "### <:phintraco:1531272488645038091> HOLD: **UVCR**\n\n"
        "**Status:** On track<:hold:1531284248235868333>\n"
        "**Status date:** Thu, Sep 10 2026, 10:13 WIB\n"
        "**Source:** [Phintraco Sekuritas](<https://t.me/phintraprofits/35139>)\n"
        "**Chart:** Unavailable from source"
    )
    rendered = canonicalize_phintraco_message(legacy)

    assert "### <:phintraco:1531272488645038091> UVCR: Hold" in rendered
    assert "-# Phintraco Sekuritas" in rendered
    assert "**Source status:** On track <:hold:1531284248235868333>" in rendered
    assert "**Last updated:** 10 Sep 2026 10:13 WIB" in rendered
    assert "**Chart:**" not in rendered


def test_legacy_phintraco_reminder_promotes_outcome_to_source_status() -> None:
    legacy = (
        "### <:phintraco:1531272488645038091> REMINDER: **UVCR**\n\n"
        "**Outcome:** First target 167 achieved\n**Target 2:** 180\n"
        "**Reminder date:** Tue, Sep 15 2026, 11:05 WIB\n"
        "**Source:** [Phintraco Sekuritas](<https://t.me/phintraprofits/35230>) | "
        "Alrich Paskalis T, Investment Advisor"
    )
    rendered = canonicalize_phintraco_message(legacy)

    assert "### <:phintraco:1531272488645038091> UVCR: Reminder" in rendered
    assert "-# Alrich Paskalis T, Phintraco Sekuritas" in rendered
    assert "**Target 2:** 180" in rendered
    assert "**Source status:** First target 167 achieved <:green:1531274822221434911>" in rendered
    assert "**Last updated:** 15 Sep 2026 11:05 WIB" in rendered


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
