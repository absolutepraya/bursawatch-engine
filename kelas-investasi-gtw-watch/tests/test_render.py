from __future__ import annotations

from render import render_event


def event(
    ticker: str = "CTRA",
    buy_area: str = "605 sampai 630",
    targets: str = "655, 675, 700",
    stoploss: str = "<573",
    *,
    title: str = "CTRA: Akumulasi kuat di area breakout",
    summary: str = "*(Ringkasan)* Ringkasan tervalidasi.",
    header_message_id: int = 101,
) -> dict[str, object]:
    return {
        "event_key": f"{header_message_id}:{ticker}",
        "ticker": ticker,
        "header_message_id": header_message_id,
        "source_text": "Akumulasi kuat di area breakout.",
        "plan": {"buy_area": buy_area, "targets": targets, "stoploss": stoploss},
        "title": title,
        "summary": summary,
    }


def test_render_matches_approved_stock_news_layout() -> None:
    text = render_event(event())[0]

    assert text == (
        "### <:telegram:1531657996432576618> CTRA: Akumulasi kuat di area breakout\n"
        "-# <:kelasinvestasi:1536570114772574218> Kelas Investasi\n\n"
        "*(Ringkasan)* Ringkasan tervalidasi.\n\n"
        "*Plan sumber*\n- Buy area: 605 sampai 630\n- Target: 655, 675, 700\n- Stoploss: <573\n\n"
        "[View on Telegram](<https://t.me/kelasinvestasiid/101>)"
    )


def test_render_uses_dash_for_missing_plan_fields_and_header_deep_link() -> None:
    text = render_event(event(buy_area="-", targets="-", stoploss="-", header_message_id=777))[0]

    assert "- Buy area: -\n- Target: -\n- Stoploss: -" in text
    assert text.endswith("[View on Telegram](<https://t.me/kelasinvestasiid/777>)")


def test_render_does_not_leak_source_label_or_generic_formatting() -> None:
    text = render_event(event(title="CTRA: *Aman* _terbatas_", summary="*(Ringkasan)* *Bersih* _dari markup_."))[0]

    assert "Good to Watch" not in text
    assert "·" not in text
    assert "🚨" not in text
    assert "\\*Aman\\*" in text
    assert "\\_dari markup\\_" in text


def test_long_summary_splits_before_plan_block_and_keeps_link_with_plan() -> None:
    summary = "*(Ringkasan)* " + "akumulasi " * 300
    messages = render_event(event(summary=summary))

    assert len(messages) == 2
    assert len(messages[0]) <= 2_000
    assert "*Plan sumber*" not in messages[0]
    assert "*Plan sumber*" in messages[1]
    assert messages[1].endswith("[View on Telegram](<https://t.me/kelasinvestasiid/101>)")


def test_renderer_allows_exactly_two_thousand_characters() -> None:
    baseline_summary = "*(Ringkasan)* x"
    base = render_event(event(summary=baseline_summary))[0]
    summary = "*(Ringkasan)* " + "x" * (1 + 2_000 - len(base))
    messages = render_event(event(summary=summary))
    assert len(messages) == 1
    assert len(messages[0]) == 2_000
