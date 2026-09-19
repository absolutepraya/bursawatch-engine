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
    source_published_at: str | None = None,
) -> dict[str, object]:
    value = {
        "event_key": f"{header_message_id}:{ticker}",
        "ticker": ticker,
        "header_message_id": header_message_id,
        "source_text": "Akumulasi kuat di area breakout.",
        "plan": {"buy_area": buy_area, "targets": targets, "stoploss": stoploss},
        "title": title,
        "summary": summary,
    }
    if source_published_at is not None:
        value["source_published_at"] = source_published_at
    return value


def test_render_matches_approved_all_swing_layout() -> None:
    text = render_event(event())[0]

    assert text == (
        "### <:kelasinvestasi:1536570114772574218> CTRA: Akumulasi kuat di area breakout\n"
        "-# Kelas Investasi GTW\n\n"
        "*(Ringkasan)* Ringkasan tervalidasi.\n\n"
        "**Buy area:** 605 sampai 630\n"
        "**Target:** 655, 675, 700\n"
        "**Stoploss:** <573\n"
        "**Chart:** Unavailable from source\n\n"
        "[View on Telegram](<https://t.me/kelasinvestasiid/101>)"
    )


def test_render_includes_neutral_gtw_status_and_board_link_for_all_copy() -> None:
    text = render_event(event(source_published_at="2026-09-19T06:50:00+07:00"))[0]

    assert "**Source status:** Good to watch <:grey:1531279158913536182>" in text
    assert "**Last updated:** 19 Sep 2026 06:50 WIB" in text
    assert "**Board:** <#1548273399069933720>" in text


def test_render_omits_board_link_for_board_copy() -> None:
    text = render_event(event(source_published_at="2026-09-19T06:50:00+07:00"), include_board=False)[0]

    assert "**Source status:** Good to watch <:grey:1531279158913536182>" in text
    assert "**Board:**" not in text


def test_render_uses_dash_for_missing_plan_fields_and_header_deep_link() -> None:
    text = render_event(event(buy_area="-", targets="-", stoploss="-", header_message_id=777))[0]

    assert "**Buy area:** -\n**Target:** -\n**Stoploss:** -" in text
    assert text.endswith("[View on Telegram](<https://t.me/kelasinvestasiid/777>)")


def test_render_uses_the_active_configured_source_username() -> None:
    import config

    configured = config.WatchConfig(
        telegram_channel_id=2142109999,
        telegram_username="kelasinvestasibar",
        alert_discord_channel_id="1525102458253217804",
        heartbeat_discord_channel_id="1505162000420835389",
        additional_prompt_instruction="",
    )

    with config.activate_watch_config(configured):
        text = render_event(event(header_message_id=777))[0]

    assert text.endswith("[View on Telegram](<https://t.me/kelasinvestasibar/777>)")


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
    assert "**Buy area:**" not in messages[0]
    assert any("**Buy area:**" in message for message in messages)
    assert any("**Target:**" in message for message in messages)
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
    assert any("**Buy area:**" in message for message in messages)
    assert any("**Target:**" in message for message in messages)
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
    assert "".join(messages).count("**Buy area:**") == 1
