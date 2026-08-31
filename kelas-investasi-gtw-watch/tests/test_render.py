from __future__ import annotations

from render import _split, render_event


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
        "*Plan sumber*\n- **Buy area:** 605 sampai 630\n- **Target:** 655, 675, 700\n- **Stoploss:** <573\n\n"
        "[View on Telegram](<https://t.me/kelasinvestasiid/101>)"
    )


def test_render_uses_dash_for_missing_plan_fields_and_header_deep_link() -> None:
    text = render_event(event(buy_area="-", targets="-", stoploss="-", header_message_id=777))[0]

    assert "- **Buy area:** -\n- **Target:** -\n- **Stoploss:** -" in text
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


def test_summary_that_fills_first_chunk_keeps_plan_in_following_chunk() -> None:
    baseline = render_event(event(summary="*(Ringkasan)* x"))[0]
    header_length = baseline.index("*(Ringkasan)* ")
    summary_prefix = "*(Ringkasan)* "
    summary = summary_prefix + "x " * 925

    messages = render_event(event(summary=summary))

    assert len(messages) == 2
    assert header_length + len(summary) <= 2_000
    assert len(messages[0]) <= 2_000
    assert "*(Ringkasan)*" in messages[0]
    assert "*(Ringkasan)*" not in messages[1]
    assert "*Plan sumber*" in messages[1]
    assert messages[1].endswith("[View on Telegram](<https://t.me/kelasinvestasiid/101>)")
    assert "*(Ringkasan)*" not in "\n".join(messages[1:])


def test_split_boundary_renders_summary_once_before_suffix() -> None:
    header = "H" * 100
    summary = "*(Ringkasan)* " + "x " * 693
    plan = "P" * 500

    messages = _split(header, summary, plan)

    assert len(messages) == 2
    assert all(len(message) <= 2_000 for message in messages)
    assert messages[0] == header + summary
    assert messages[1] == "\n\n" + plan
    assert "".join(message.removeprefix(header).removesuffix("\n\n" + plan) for message in messages) == summary
    assert "".join(messages).count(summary) == 1
    assert "".join(messages).count(plan) == 1


def test_render_summary_with_boundary_delimiter_never_exceeds_discord_limit() -> None:
    messages = render_event(
        event(
            title="tt",
            summary="*(Ringkasan)* " + "x " * 1_000,
        )
    )

    assert all(len(message) <= 2_000 for message in messages)
    assert "".join(messages).count("*(Ringkasan)*") == 1
    assert "".join(messages).count("*Plan sumber*") == 1
