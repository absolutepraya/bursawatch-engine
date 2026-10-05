from datetime import date, datetime

import pytest

from stock_status import (
    StockStatusError,
    format_stock_status,
    is_stock_information,
    parse_stock_information,
)


def test_message_35377_maps_all_sections_and_empty_values(load_fixture):
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )

    assert status.effective_date == date(2026, 9, 23)
    assert status.uma == ()
    assert status.suspend_in == ()
    assert status.suspend_out == ("WAPO", "NASI")
    assert status.fca_in == ()
    assert status.fca_out == ("UNSP",)


def test_message_35326_preserves_source_lists(load_fixture):
    status = parse_stock_information(
        35326, load_fixture("phintraco-stock-status-35326.txt")
    )

    assert status.effective_date == date(2026, 9, 21)
    assert status.uma == ("WAPO", "NASI")
    assert status.suspend_in == ("SEMA", "TEBE", "IDEA", "NICK", "WIKA", "BIKE")
    assert status.suspend_out == ("LIFE", "GRPH", "TRUE")
    assert status.fca_in == ("LIFE", "GRPH")
    assert status.fca_out == ("CSMI",)


def test_indonesian_effective_month_is_accepted():
    text = (
        "Stock Information\nEffective date : 01 Oktober 2026\n"
        "Unusual Market Activity (UMA):\n>SRSN\n"
        "Suspend:\n>BSWD\nUnsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n"
    )

    status = parse_stock_information(35549, text)

    assert status.effective_date == date(2026, 10, 1)
    assert status.uma == ("SRSN",)
    assert status.suspend_in == ("BSWD",)


def test_only_exact_stock_information_header_selects_status_parser():
    assert is_stock_information("Stock Information\nEffective date : 23 September 2026")
    assert not is_stock_information("Stock Information: more text")
    assert not is_stock_information("Company Flash: ABCD")
    assert not is_stock_information(" Stock Information\nEffective date : 23 September 2026")


def test_source_section_order_and_heading_spacing_are_normalized():
    text = (
        "Stock Information\nEffective date : 23 September 2026\n"
        "FCA Out :\n>UNSP\nFCA In:\n>-\nUnsuspend   :\n>WAPO\n"
        "Suspend:\n>-\nUnusual Market Activity (UMA):\n>-\n"
        "By PHINTRACO SEKURITAS | Research\n-Disclaimer On -\n"
    )

    status = parse_stock_information(35377, text)

    assert status.uma == ()
    assert status.suspend_in == ()
    assert status.suspend_out == ("WAPO",)
    assert status.fca_in == ()
    assert status.fca_out == ("UNSP",)


@pytest.mark.parametrize("empty_body", [">-\n", "\n\n"])
def test_present_section_with_empty_marker_or_blank_body_is_empty(empty_body):
    text = (
        "Stock Information\nEffective date : 23 September 2026\n"
        f"Unusual Market Activity (UMA):\n{empty_body}"
        "Suspend:\n>-\nUnsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n"
    )

    assert parse_stock_information(35377, text).uma == ()


def test_duplicate_tickers_are_removed_only_within_their_section():
    text = (
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>WAPO\n>WAPO\n>NASI\n"
        "Suspend:\n>WAPO\nUnsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n"
    )

    status = parse_stock_information(35377, text)

    assert status.uma == ("WAPO", "NASI")
    assert status.suspend_in == ("WAPO",)


@pytest.mark.parametrize(
    "body",
    [
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n"
        "New Status:\n>ABCD\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Effective date : 24 September 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 31 February 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 Septembre 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>ABC\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>abcd\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\nWAPO\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA):\n>-\nSuspend:\n>-\n"
        "Unsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\nUnknown field\n",
    ],
)
def test_incomplete_or_malformed_status_posts_are_rejected(body):
    with pytest.raises(StockStatusError):
        parse_stock_information(35377, body)


def test_message_35377_renders_the_approved_discord_message(load_fixture):
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )
    base_url = "https://t.me/phintasprofits/35377"
    now = datetime.fromisoformat("2026-10-05T08:30:00+07:00")
    base_content = format_stock_status(status, base_url, now)
    exact_length_url = base_url + ("x" * (2000 - len(base_content)))

    assert len(format_stock_status(status, exact_length_url, now)) == 2000
    with pytest.raises(StockStatusError):
        format_stock_status(status, exact_length_url + "x", now)

    assert format_stock_status(status, base_url, now) == (
        "### <:phintraco:1531272488645038091> Stock Status: Mon, 05 Oct 2026\n\n"
        "**UMA:**\n(None)\n\n"
        "**Suspend In:**\n(None)\n\n"
        "**Suspend Out:**\n- WAPO\n- NASI\n\n"
        "**FCA In:**\n(None)\n\n"
        "**FCA Out:**\n- UNSP\n\n"
        "[View in Telegram](<https://t.me/phintasprofits/35377>)"
    )


@pytest.mark.parametrize("observed_at, expected_heading", [
    ("2026-10-04T16:59:59+00:00", "Sun, 04 Oct 2026"),
    ("2026-10-04T17:00:00+00:00", "Mon, 05 Oct 2026"),
    ("2026-10-05T17:00:00+00:00", "Tue, 06 Oct 2026"),
])
def test_header_uses_jakarta_observation_date_instead_of_future_source_date(observed_at, expected_heading):
    source = (
        "Stock Information\nEffective date : 10 October 2026\n"
        "Unusual Market Activity (UMA):\n>BLTZ\n"
        "Suspend:\n>BSWD\n>PTPP\nUnsuspend:\n>-\nFCA In:\n>-\nFCA Out:\n>-\n"
    )
    status = parse_stock_information(35594, source)
    content = format_stock_status(status, "https://t.me/phintasprofits/35594", datetime.fromisoformat(observed_at))
    assert content.splitlines()[0] == f"### <:phintraco:1531272488645038091> Stock Status: {expected_heading}"
    assert "**UMA:**\n- BLTZ" in content
    assert "**Suspend In:**\n- BSWD\n- PTPP" in content
    assert "Web" not in content
    assert "Sat, 10 Oct" not in content


def test_heading_requires_an_explicit_timezone(load_fixture):
    status = parse_stock_information(35377, load_fixture("phintraco-stock-status-35377.txt"))
    with pytest.raises(ValueError, match="timezone"):
        format_stock_status(status, "https://t.me/phintasprofits/35377", datetime(2026, 10, 5))
