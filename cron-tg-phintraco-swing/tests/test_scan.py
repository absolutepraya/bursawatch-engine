import asyncio
import datetime as dt
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import scan

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def now() -> dt.datetime:
    return dt.datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB)

def test_daily_runtime_identifiers_are_provider_specific():
    assert scan.WATCHER_NAME == "bursawatch-tg-phintraco-swing"
    assert scan.WATCHER_HEARTBEAT_NAME == "bursawatch-tg-phintraco-swing"
    assert "cron-tg-phintraco-swing" in str(scan.DEFAULT_STATE_FILE)




@pytest.mark.parametrize(
    ("filename", "message_id", "ticker", "subtype", "entry", "stop_loss"),
    [
        ("trading_buy.txt", 33655, "SCMA", "Trading Buy", "208 to 212", "<200"),
        ("buy_on_support.txt", 33654, "BBRI", "Buy on Support", "2710 to 2780", "<2670"),
        ("speculative_buy.txt", 33656, "BUKA", "Speculative Buy", "96 to 97", "<95"),
    ],
)
def test_parse_verified_subtypes(filename, message_id, ticker, subtype, entry, stop_loss):
    call = scan.parse_swing_call(message_id, fixture(filename), has_photo=True)
    assert call is not None
    assert call.source_message_id == message_id
    assert call.provider == "Phintraco"
    assert call.ticker == ticker
    assert call.call_subtype == subtype
    assert call.entry == entry
    assert call.stop_loss == stop_loss
    assert call.has_source_chart is True
    assert call.signal_datetime == dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB)
    assert call.advisor_name == "Alrich Paskalis T"
    assert call.advisor_role == "Investment Advisor"


def test_parse_hold_trading_buy_as_a_buy_subtype():
    text = (
        "AMMN - Hold/Trading Buy : Koreksi cenderung tertahan di atas support area 4300 "
        "menjadi indikasi awal rebound hingga bullish continuation. Konfirmasi jika breakout resistance 4520.\n\n"
        "Entry : 4360\n"
        "Stop-loss : <4200\n"
        "Target 2: 5000\n"
        "Target 1: 4700\n\n"
        "By PHINTRACO SEKURITAS\n"
        "2/09/2026 6.00 WIB\n"
        "Alrich Paskalis T| Investment Advisor\n"
        "- Disclaimer On -"
    )
    published_at = dt.datetime(2026, 9, 2, 6, 0, tzinfo=scan.WIB)

    call = scan.parse_swing_call(34908, text, has_photo=True, source_posted_at=published_at)

    assert call is not None
    assert call.event_kind == "BUY"
    assert call.call_subtype == "Hold/Trading Buy"
    assert call.ticker == "AMMN"
    assert call.entry == "4360"
    assert call.stop_loss == "<4200"
    assert [(target.number, target.value) for target in call.targets] == [(1, "4700"), (2, "5000")]
    assert call.signal_datetime == published_at
    assert "AMMN: Buy" in scan.format_swing_alert(call, include_board=False)
    assert "**Type:** Hold/Trading Buy <:up:1531285100346740766>" in scan.format_swing_alert(
        call, include_board=False
    )


def test_targets_are_sorted_by_number():
    call = scan.parse_swing_call(33654, fixture("buy_on_support.txt"), has_photo=True)
    assert [(target.number, target.value) for target in call.targets] == [(1, "2900"), (2, "3000")]


def test_unnumbered_target_is_preserved():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert call.targets == (scan.PriceTarget(None, "230"),)


def test_header_spacing_variants_parse():
    text = fixture("trading_buy.txt").replace("SCMA - Trading Buy", "SCMA- Trading Buy")
    assert scan.parse_swing_call(1, text, has_photo=False).ticker == "SCMA"
    text = fixture("trading_buy.txt").replace("SCMA - Trading Buy", "SCMA -Trading Buy")
    assert scan.parse_swing_call(2, text, has_photo=False).ticker == "SCMA"


def test_hyphen_delimited_entry_and_stop_loss_remain_a_buy_call():
    text = fixture("buy_on_support.txt")
    text = text.replace("Entry : 2710-2780", "Entry - 2710-2780")
    text = text.replace("Stop-loss : <2670", "Stop-loss - <2670")

    call = scan.parse_swing_call(33912, text, has_photo=True)

    assert call is not None
    assert call.event_kind == "BUY"
    assert call.ticker == "BBRI"
    assert call.entry == "2710 to 2780"
    assert call.stop_loss == "<2670"


def test_multiple_qualifying_stock_headers_are_rejected():
    text = f"{fixture('trading_buy.txt')}\n{fixture('buy_on_support.txt')}"
    assert scan.parse_swing_call(99, text, has_photo=True) is None


@pytest.mark.parametrize(
    "invalid_datetime",
    [
        "31/02/2026 7.00 WIB",
        "10/13/2026 7.00 WIB",
        "10/07/2026 24.00 WIB",
        "10/07/2026 7.60 WIB",
    ],
)
def test_impossible_signal_datetimes_are_rejected(invalid_datetime):
    text = fixture("trading_buy.txt").replace("10/07/2026 7.00 WIB", invalid_datetime)
    assert scan.parse_swing_call(99, text, has_photo=True) is None


@pytest.mark.parametrize(
    "text",
    [
        "Reminder\n\nMARK - Second target 1100 achieved\n\nBy PHINTRACO SEKURITAS",
        "JPFA - Sell on Strength : consider selling\nResistance : 2050\nBy PHINTRACO SEKURITAS",
        "PHINTAS Weekly Swing Trading Ideas_20260706\nASII - Breakout MA20 : Buy\nEntry : >=4710\nTarget : 5100\nStoploss : <4520\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nStop-loss : <200\nTarget : 230\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nEntry : 208-212\nTarget : 230\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nEntry : 208-212\nStop-loss : <200\nBy PHINTRACO SEKURITAS",
    ],
)
def test_non_calls_and_malformed_calls_are_rejected(text):
    assert scan.parse_swing_call(99, text, has_photo=True) is None


def test_malformed_buy_candidate_is_detectable():
    text = (
        "SCMA - Trading Buy : rationale\n"
        "Stop-loss : <200\n"
        "Target : 230\n"
        "By PHINTRACO SEKURITAS\n"
        "10/07/2026 7.00 WIB"
    )
    assert scan.looks_like_swing_call(text) is True
    assert scan.parse_swing_call(99, text, has_photo=True) is None


def test_format_chart_backed_alert_exact():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert scan.format_swing_alert(call) == (
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Type:** Trading Buy <:up:1531285100346740766>\n"
        "**Entry:** 208 to 212\n"
        "**Stop-loss:** <200\n"
        "**Target:** 230\n"
        "**Signal date:** 10 Jul 2026 07:00 WIB\n\n"
        "**Reasons:** Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. "
        "MACD yang konsisten membentuk histogram positif sejalan dengan peluang tersebut.\n\n"
        "**Source status:** New setup <:grey:1531279158913536182>\n"
        "**Last updated:** 10 Jul 2026 07:00 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/33655>)"
    )


def test_buy_alert_is_ticker_first_with_byline_and_telegram_footer() -> None:
    output = scan.format_swing_alert(sample_call())
    assert output.startswith(
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
    )
    assert "**Signal date:** 10 Jul 2026 07:00 WIB" in output
    assert output.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_format_multi_target_alert_exact():
    call = scan.parse_swing_call(33654, fixture("buy_on_support.txt"), has_photo=True)
    output = scan.format_swing_alert(call)
    assert "**Target 1:** 2900\n**Target 2:** 3000\n**Signal date:**" in output
    assert "`" not in output


def test_future_sell_alert_uses_down_marker():
    buy_call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    sell_call = scan.SwingCall(**{**buy_call.__dict__, "event_kind": "SELL"})
    assert scan.format_swing_alert(sell_call).startswith(
        "### <:phintraco:1531272488645038091> SCMA: Sell\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Type:** Trading Buy <:down:1531285063986053200>"
    )


def test_format_chartless_alert_exact_suffix():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=False)
    output = scan.format_swing_alert(call)
    assert "**Chart:** Unavailable from source" in output
    assert output.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_missing_advisor_falls_back_to_source_only():
    text = fixture("trading_buy.txt").replace("Alrich Paskalis T| Investment Advisor\n", "")
    call = scan.parse_swing_call(33655, text, has_photo=True)
    assert "-# Phintraco Sekuritas" in scan.format_swing_alert(call)


def test_dynamic_source_markdown_is_escaped_without_changing_labels():
    call = sample_call()
    call = scan.SwingCall(
        **{
            **call.__dict__,
            "rationale": r"back\slash *star* _under_ ~tilde~ `tick`",
            "advisor_name": r"Al\rich*_*~*`*",
        }
    )

    output = scan.format_swing_alert(call)

    assert (
        r"**Reasons:** back\\slash \*star\* \_under\_ \~tilde\~ \`tick\`"
        in output
    )
    assert r"-# Al\\rich\*\_\*\~\*\`\*, Phintraco Sekuritas" in output
    assert "**Reasons:**" in output
    assert "[View in Telegram](<https://t.me/phintraprofits/33655>)" in output


@pytest.mark.parametrize(
    ("source", "escaped"),
    [
        ("literal ||spoiler||", r"literal \|\|spoiler\|\|"),
        (
            "masked [label](https://example.com)",
            r"masked \[label](https://example.com)",
        ),
    ],
)
def test_dynamic_spoiler_and_masked_link_markdown_is_escaped(source, escaped):
    call = sample_call()
    call = scan.SwingCall(**{**call.__dict__, "rationale": source})
    assert f"**Reasons:** {escaped}" in scan.format_swing_alert(call).splitlines()


def test_canonical_fixture_output_is_unchanged_when_no_escape_is_needed():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert scan.format_swing_alert(call) == (
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Type:** Trading Buy <:up:1531285100346740766>\n"
        "**Entry:** 208 to 212\n"
        "**Stop-loss:** <200\n"
        "**Target:** 230\n"
        "**Signal date:** 10 Jul 2026 07:00 WIB\n\n"
        "**Reasons:** Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. MACD yang konsisten membentuk histogram positif sejalan dengan peluang tersebut.\n\n"
        "**Source status:** New setup <:grey:1531279158913536182>\n"
        "**Last updated:** 10 Jul 2026 07:00 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/33655>)"
    )


def test_call_serialization_roundtrip():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert scan.deserialize_call(scan.serialize_call(call)) == call


def test_parse_target_reminder_and_format_source_link():
    text = (
        "Reminder\n\nINCO - First target 5000 achieved\n\nTarget 2 : 5400\n\n"
        "By PHINTRACO SEKURITAS\n14/07/2026 13.35 WIB\n"
        "Nauval Maulana| Investment Advisor"
    )
    event = scan.parse_swing_reminder(33711, text, has_photo=True)
    assert event is not None
    assert event.event_kind == "REMINDER"
    assert event.outcomes == ("First target 5000 achieved",)
    assert scan.format_swing_alert(event).startswith(
        "### <:phintraco:1531272488645038091> INCO: First target 5000 achieved\n"
        "-# Nauval Maulana, Phintraco Sekuritas\n\n"
    )
    assert scan.format_swing_alert(event).endswith(
        "[View in Telegram](<https://t.me/phintraprofits/33711>)"
    )


def test_photo_reminder_posts_chart_from_exact_source_message(tmp_state, monkeypatch):
    text = (
        "Reminder\n\nASII - First target 5150 achieved\n\nTarget 2: 5300\n\n"
        "By PHINTRACO SEKURITAS\n30/07/2026 10.06 WIB\n"
        "Nauval Maulana| Investment Advisor"
    )
    reminder = scan.parse_swing_reminder(34093, text, has_photo=True)
    assert reminder is not None
    assert reminder.has_source_chart is True

    state = scan.empty_state()
    event = scan.enqueue_call(state, reminder, dt.datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB))
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["chart_status"] == "expected"

    client = FakeTelegramClient([FakeMessage(34093, text, photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    assert asyncio.run(
        scan.capture_oldest_media(client, entity, state, dt.datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB))
    ) is True
    assert client.download_calls == [34093]

    posted = []
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, channel_id, dry_run, event_key: posted.append(("text", event_key)) or "text-34093",
    )
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda path, channel_id, dry_run, event_key: posted.append(("chart", Path(path).name, event_key)) or "chart-34093",
    )
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)

    assert scan.drain_outbox(state, dt.datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB)) == 1
    assert posted == [("text", "34093"), ("chart", "phintraco-34093.jpg", "34093")]


def test_parse_unnumbered_target_achievement_reminder():
    text = (
        "Reminder\n\nHRTA -Target 1940 achieved.\n\n"
        "By PHINTRACO SEKURITAS\n16/07/2026 10.10 WIB\n"
        "Alrich Paskalis T| Investment Advisor"
    )
    event = scan.parse_swing_reminder(33767, text, has_photo=True)
    assert event is not None
    assert event.event_kind == "REMINDER"
    assert event.outcomes == ("Target 1940 achieved",)


def test_parse_chartless_status_reminder_with_typo():
    text = (
        "TLKM - on track. Still inilne with trading plan before (4/2). Hold\n\n"
        "By PHINTRACO SEKURITAS\n7/2/2025 15.59 WIB\n"
        "Alrich Paskalis T| Investment Advisor"
    )
    event = scan.parse_swing_reminder(22711, text, has_photo=False)
    assert event is not None
    assert event.event_kind == "STATUS"
    output = scan.format_swing_alert(event)
    assert "Still inline with trading plan before" in output
    assert "**Chart:** Unavailable from source" not in output


def test_source_timestamp_overrides_embedded_phintraco_date():
    source_posted_at = dt.datetime(2026, 7, 17, 3, 11, tzinfo=dt.timezone.utc)

    event = scan.parse_swing_call(
        33655,
        fixture("trading_buy.txt"),
        has_photo=True,
        source_posted_at=source_posted_at,
    )

    assert event is not None
    assert event.signal_datetime == dt.datetime(2026, 7, 17, 10, 11, tzinfo=scan.WIB)


def test_on_support_update_uses_common_status_format_and_source_timestamp():
    text = (
        "BRMS - On support\n\n"
        "Re-test support area 530-540 dengan penipisan volume menjadi indikasi pembentukan base.\n\n"
        "Entry : >=540\n"
        "Target 2: 640\n"
        "Target 1: 590-600\n"
        "Stoploss :<520\n\n"
        "By PHINTRACO SEKURITAS\n"
        "7/07/2026 10.11 WIB\n"
        "Alrich Paskalis T| Investment Advisor"
    )

    event = scan.parse_source_event(
        FakeMessage(
            33801,
            text,
            photo=True,
            date=dt.datetime(2026, 7, 17, 3, 11, tzinfo=dt.timezone.utc),
        )
    )

    assert event is not None
    assert event.event_kind == "STATUS"
    assert event.has_source_chart is True
    assert event.status == "On support"
    assert event.entry == ">=540"
    assert event.stop_loss == "<520"
    assert [(target.number, target.value) for target in event.targets] == [
        (1, "590 to 600"),
        (2, "640"),
    ]
    assert scan.format_swing_alert(event) == (
        "### <:phintraco:1531272488645038091> BRMS: On support\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Entry:** >=540\n"
        "**Stop-loss:** <520\n"
        "**Target 1:** 590 to 600\n"
        "**Target 2:** 640\n"
        "\n**Source status:** On support <:hold:1531284248235868333>\n"
        "**Last updated:** 17 Jul 2026 10:11 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/33801>)"
    )


def test_complete_on_support_status_becomes_a_primary_board_setup():
    text = (
        "BMRI - On support\n\n"
        "Memasuki support area 4000-4050 menjadi indikasi awal rebound.\n\n"
        "Entry : 4020-4060\n"
        "Target : 4230\n"
        "Stoploss :<3940\n\n"
        "By PHINTRACO SEKURITAS\n"
        "28/09/2026 9.33 WIB\n"
        "Alrich Paskalis T| Investment Advisor"
    )
    call = scan.parse_swing_reminder(
        35459,
        text,
        has_photo=True,
        source_posted_at=dt.datetime(2026, 9, 28, 2, 34, tzinfo=dt.timezone.utc),
    )

    assert call is not None
    assert call.event_kind == "STATUS"
    assert call.status == "On support"
    payload, chart = scan.board_event_payload({"board_kind_override": None}, call)

    assert payload["kind"] == "buy"
    assert payload["source_status"] == "New setup"
    assert payload["source_title"] == "BMRI: On support"
    assert payload["plan"] == {
        "entry": "4020 to 4060",
        "stop_loss": "<3940",
        "targets": ["4230"],
    }
    assert chart is None


def test_incomplete_on_support_status_remains_status_only():
    call = scan.parse_swing_reminder(
        35460,
        "BRMS - On support\n\n"
        "Entry : >=540\n"
        "Target : 590\n\n"
        "By PHINTRACO SEKURITAS\n"
        "28/09/2026 9.33 WIB\n"
        "Alrich Paskalis T| Investment Advisor",
        has_photo=False,
        source_posted_at=dt.datetime(2026, 9, 28, 2, 41, tzinfo=dt.timezone.utc),
    )
    assert call is not None
    payload, _ = scan.board_event_payload({"board_kind_override": None}, call)
    assert payload["kind"] == "status"
    assert payload["plan"] is None


def test_reply_status_requires_matching_parent_swing_plan():
    parent = scan.parse_swing_call(
        33722,
        fixture("trading_buy.txt").replace("SCMA", "ESSA"),
        has_photo=True,
    )
    assert parent is not None
    source_posted_at = dt.datetime(2026, 7, 15, 3, 55, 48, tzinfo=dt.timezone.utc)

    event = scan.parse_reply_status(
        33735,
        "ESSA on track",
        has_photo=False,
        source_posted_at=source_posted_at,
        parent=parent,
    )

    assert event is not None
    assert event.event_kind == "STATUS"
    assert event.ticker == "ESSA"
    assert event.status == "On track"
    assert event.signal_datetime == dt.datetime(2026, 7, 15, 10, 55, 48, tzinfo=scan.WIB)
    assert scan.format_swing_alert(event) == (
        "### <:phintraco:1531272488645038091> ESSA: On track\n"
        "-# Phintraco Sekuritas\n\n"
        "**Source status:** On track <:hold:1531284248235868333>\n"
        "**Last updated:** 15 Jul 2026 10:55 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/33735>)"
    )
    assert (
        scan.parse_reply_status(
            33735,
            "BBNI on track",
            has_photo=False,
            source_posted_at=source_posted_at,
            parent=parent,
        )
        is None
    )


def test_reply_status_tolerates_known_on_trac_source_typo():
    parent = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert parent is not None

    event = scan.parse_reply_status(
        33763,
        "SCMA on trac",
        has_photo=False,
        source_posted_at=dt.datetime(2026, 7, 16, 2, 12, 29, tzinfo=dt.timezone.utc),
        parent=parent,
    )

    assert event is not None
    assert event.status == "On track"

# State and outbox

def sample_call(has_photo=True):
    return scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=has_photo)


def test_missing_state_returns_empty_state(tmp_state):
    state = scan.load_state()
    assert state["version"] == 4
    assert state["observed_message_id"] == 0
    assert state["outbox"] == {}
    assert state["pdf_batches"] == {}
    assert state["source_plans"] == {}
    assert state["quarantined_documents"] == {}
    assert state["blocked"] is False


def test_state_roundtrip_is_atomic(tmp_state):
    state = scan.empty_state()
    state["observed_message_id"] = 123
    scan.save_state(state)
    assert scan.load_state()["observed_message_id"] == 123
    assert not tmp_state.with_suffix(".tmp").exists()


def test_version_one_state_migrates_completed_all_delivery_to_pending_board(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=False), now())
    event["phase"] = scan.PHASE_DELIVERED
    state["version"] = 1
    for field in (
        "board_submitted",
        "board_attempts",
        "board_next_attempt_at",
        "board_last_error",
    ):
        del event[field]
    tmp_state.write_text(json.dumps(state))

    migrated = scan.load_state()

    assert migrated["version"] == scan.STATE_VERSION
    assert migrated["outbox"]["33655"]["phase"] == scan.PHASE_PENDING_BOARD
    assert migrated["outbox"]["33655"]["board_submitted"] is False


def test_state_v2_migration_preserves_delivery_progress_and_adds_pdf_indexes(tmp_state):
    state = scan.empty_state()
    state.update(pdf_batches={}, source_plans={}, quarantined_documents={})
    event = scan.enqueue_call(state, sample_call(), now())
    event.update(
        phase=scan.PHASE_PENDING_CHART,
        text_discord_id="all-message-1",
        attempts=3,
        media_path="/private/state/chart.jpg",
    )
    state["version"] = 2
    for field in ("pdf_batches", "source_plans", "quarantined_documents"):
        state.pop(field)
    for field in (
        "delivery_order",
        "pdf_batch_id",
        "source_page",
        "source_section",
        "pdf_sha256",
        "pdf_path",
        "chart_path",
    ):
        event.pop(field)
    tmp_state.write_text(json.dumps(state))

    migrated = scan.load_state()

    assert migrated["version"] == 4
    migrated_event = migrated["outbox"]["33655"]
    assert migrated_event["phase"] == scan.PHASE_PENDING_CHART
    assert migrated_event["text_discord_id"] == "all-message-1"
    assert migrated_event["attempts"] == 3
    assert migrated_event["media_path"] == "/private/state/chart.jpg"
    assert migrated["pdf_batches"] == {}
    assert migrated["source_plans"] == {}
    assert migrated["quarantined_documents"] == {}


def test_enqueue_call_uses_source_id_and_media_phase(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    assert event["event_key"] == "33655"
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["chart_status"] == "expected"
    assert event["text_discord_id"] is None
    assert list(state["outbox"]) == ["33655"]


def test_enqueue_chartless_call_starts_pending_text(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=False), dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["chart_status"] == "absent"


def test_same_source_message_is_not_enqueued_twice(tmp_state):
    state = scan.empty_state()
    first = scan.enqueue_call(state, sample_call(), dt.datetime.now(scan.WIB))
    second = scan.enqueue_call(state, sample_call(), dt.datetime.now(scan.WIB))
    assert first is second
    assert len(state["outbox"]) == 1


def test_retry_backoff_is_bounded(tmp_state):
    event = scan.enqueue_call(scan.empty_state(), sample_call(), dt.datetime.now(scan.WIB))
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    for _ in range(20):
        scan.schedule_retry(event, now, "network failed")
    due = dt.datetime.fromisoformat(event["next_attempt_at"])
    assert due - now == dt.timedelta(minutes=15)
    assert event["last_error"] == "network failed"


def test_corrupt_state_creates_backup_and_blocked_sentinel(tmp_state):
    tmp_state.write_text("{bad json")
    with pytest.raises(scan.StateBlockedError) as raised:
        scan.load_state()
    assert raised.value.state["blocked"] is True
    assert scan.state_path().exists()
    assert len(list(tmp_state.parent.glob("state.corrupt-*.json"))) == 1
    with pytest.raises(scan.StateBlockedError):
        scan.load_state()


def test_fatal_notice_state_roundtrips_and_suppresses_repeat(tmp_state, monkeypatch):
    state = scan.empty_state()
    posts = []
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, channel_id, dry_run, event_key: posts.append(content) or "fatal-id",
    )
    now = dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB)

    assert scan.report_fatal(state, now, "Telegram unavailable", False) is True
    loaded = scan.load_state()
    assert scan.report_fatal(loaded, now, "Telegram unavailable", False) is False
    assert len(posts) == 1


def test_best_effort_fatal_reloads_state_under_lock_before_saving(
    tmp_state, monkeypatch
):
    stale = scan.empty_state()
    stale["observed_message_id"] = 41
    live = scan.empty_state()
    live["observed_message_id"] = 99
    scan.enqueue_call(
        live,
        sample_call(has_photo=False),
        dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB),
    )
    scan.save_state(live)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *args, **kwargs: "fatal-id",
    )

    assert scan._report_fatal_best_effort(
        stale,
        dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB),
        "Telegram unavailable",
        False,
    ) is True
    persisted = scan.load_state()
    assert persisted["observed_message_id"] == 99
    assert list(persisted["outbox"]) == ["33655"]


def test_deployed_version_one_null_fatal_metadata_still_loads(tmp_state):
    state = scan.empty_state()
    state["last_error_notice"] = None
    scan.save_state(state)
    assert scan.load_state()["last_error_notice"] is None


@pytest.mark.parametrize(
    "last_error_notice",
    [
        {"hour": "", "fingerprints": ["a" * 16]},
        {"hour": "2026-07-10T08+07:00", "fingerprints": []},
        {"hour": "2026-07-10T08+07:00", "fingerprints": "not-a-list"},
        {"hour": "2026-07-10T08+07:00", "fingerprints": [123]},
        {"hour": "2026-07-10T08+07:00", "fingerprints": ["not-hex"]},
        {
            "hour": "2026-07-10T08+07:00",
            "fingerprints": ["a" * 16, "a" * 16],
        },
    ],
)
def test_invalid_fatal_notice_collection_blocks_state(
    tmp_state, last_error_notice
):
    state = scan.empty_state()
    state["last_error_notice"] = last_error_notice
    tmp_state.write_text(json.dumps(state))

    with pytest.raises(scan.StateBlockedError):
        scan.load_state()


def test_run_lock_is_nonblocking(tmp_state):
    with scan.run_lock() as acquired:
        assert acquired is True
        with scan.run_lock() as second:
            assert second is False


# Task 2 review regressions

def test_saved_state_file_is_private(tmp_state):
    scan.save_state(scan.empty_state())
    assert tmp_state.stat().st_mode & 0o777 == 0o600


def test_failed_state_replacement_preserves_prior_destination(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 123
    scan.save_state(state)

    replacement = scan.empty_state()
    replacement["observed_message_id"] = 456

    def fail_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(scan.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        scan.save_state(replacement)

    assert json.loads(tmp_state.read_text())["observed_message_id"] == 123


@pytest.mark.parametrize(
    "case",
    [
        "wrong_root",
        "boolean_version",
        "missing_required_field",
        "wrong_root_field_type",
        "outbox_list",
        "wrong_event_field_type",
    ],
)
def test_structurally_invalid_state_is_backed_up_and_stays_blocked(tmp_state, case):
    state = scan.empty_state()
    if case == "wrong_root":
        state = []
    elif case == "boolean_version":
        state["version"] = True
    elif case == "missing_required_field":
        del state["last_poll_success"]
    elif case == "wrong_root_field_type":
        state["observed_message_id"] = "0"
    elif case == "outbox_list":
        state["outbox"] = []
    elif case == "wrong_event_field_type":
        event = scan.enqueue_call(
            state,
            sample_call(),
            dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB),
        )
        event["attempts"] = "zero"

    tmp_state.write_text(json.dumps(state))
    with pytest.raises(scan.StateBlockedError) as raised:
        scan.load_state()
    assert raised.value.state["blocked"] is True
    assert len(list(tmp_state.parent.glob("state.corrupt-*.json"))) == 1

    with pytest.raises(scan.StateBlockedError):
        scan.load_state()
    assert len(list(tmp_state.parent.glob("state.corrupt-*.json"))) == 1


def test_schedule_retry_rejects_naive_now(tmp_state):
    event = scan.enqueue_call(
        scan.empty_state(),
        sample_call(),
        dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        scan.schedule_retry(event, dt.datetime(2026, 7, 10, 8, 0), "failed")


def test_retry_due_rejects_naive_now():
    with pytest.raises(ValueError, match="timezone-aware"):
        scan.retry_due({"next_attempt_at": None}, dt.datetime(2026, 7, 10, 8, 0))


def test_retry_due_rejects_naive_persisted_timestamp():
    event = {"next_attempt_at": "2026-07-10T08:00:00"}
    with pytest.raises(ValueError, match="timezone-aware"):
        scan.retry_due(event, dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))


def test_retry_due_boundary_is_timezone_offset_safe():
    event = {"next_attempt_at": "2026-07-10T08:00:00+07:00"}
    assert scan.retry_due(
        event,
        dt.datetime(2026, 7, 10, 0, 59, 59, tzinfo=dt.timezone.utc),
    ) is False
    assert scan.retry_due(
        event,
        dt.datetime(2026, 7, 10, 1, 0, tzinfo=dt.timezone.utc),
    ) is True


@pytest.mark.parametrize(
    "next_attempt_at",
    ["not-a-datetime", "2026-07-10T08:01:00"],
)
def test_invalid_persisted_retry_timestamp_blocks_state(tmp_state, next_attempt_at):
    state = scan.empty_state()
    event = scan.enqueue_call(
        state,
        sample_call(),
        dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB),
    )
    event["next_attempt_at"] = next_attempt_at
    tmp_state.write_text(json.dumps(state))

    with pytest.raises(scan.StateBlockedError):
        scan.load_state()
    assert len(list(tmp_state.parent.glob("state.corrupt-*.json"))) == 1


# Telegram observation and media capture

class FakeMessage:
    def __init__(
        self,
        message_id,
        text,
        photo=False,
        *,
        reply_to_msg_id=None,
        date=None,
        document_filename=None,
        document_mime_type=None,
        document_bytes=b"weekly-pdf-bytes",
    ):
        self.id = message_id
        self.message = text
        self.photo = object() if photo else None
        self.reply_to_msg_id = reply_to_msg_id
        self.date = date or dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc)
        self.document = (
            SimpleNamespace(mime_type=document_mime_type)
            if document_filename is not None
            else None
        )
        self.file = SimpleNamespace(name=document_filename) if document_filename else None
        self.document_bytes = document_bytes


class FakeDialog:
    def __init__(self, entity_id, name="Phintraco Sekuritas Official"):
        self.entity = type("Entity", (), {"id": entity_id})()
        self.name = name


class FakeTelegramClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.dialog_calls = 0
        self.download_calls = []

    async def get_dialogs(self):
        self.dialog_calls += 1
        return [FakeDialog(scan.SOURCE_CHANNEL_ID)]

    def iter_messages(self, entity, min_id=0, reverse=False):
        assert reverse is True
        async def generate():
            for message in self.messages:
                if message.id > min_id:
                    yield message
        return generate()

    async def get_messages(self, entity, ids=None, limit=None):
        if ids is not None:
            return next((message for message in self.messages if message.id == ids), None)
        if limit == 1:
            return self.messages[-1:] if self.messages else []
        return self.messages

    async def download_media(self, message, target_type):
        assert target_type is bytes
        self.download_calls.append(message.id)
        if message.document is not None:
            return message.document_bytes
        return b"\xff\xd8\xffsource-chart"


def weekly_pdf_result(*, with_quarantine=False):
    setups = (
        SimpleNamespace(
            ticker="AADI",
            descriptor="Base Formation Indication",
            trend="Uptrend",
            ma_indicator="Above, Bear tendency",
            potential_upside="5%-11%",
            potential_downside="-3%",
            entry=">=11000",
            stop_loss="<10600",
            targets=(scan.PriceTarget(1, "11600"), scan.PriceTarget(2, "12200")),
            page_number=1,
            section_number=1,
            chart_bytes=b"\xff\xd8\xffaadi-chart",
        ),
        SimpleNamespace(
            ticker="ITMG",
            descriptor="On support",
            trend="Bullish",
            ma_indicator="Above, Bear Tendency",
            potential_upside="4%",
            potential_downside="-2%",
            entry=">=25000",
            stop_loss="<24400",
            targets=(scan.PriceTarget(None, "26050"),),
            page_number=1,
            section_number=2,
            chart_bytes=b"\xff\xd8\xffitmg-chart",
        ),
    )
    quarantined_pages = (
        (SimpleNamespace(page_number=2, reason="weekly plan page has an ambiguous chart association"),)
        if with_quarantine
        else ()
    )
    return SimpleNamespace(
        report_date=dt.date(2026, 9, 28),
        setups=setups[:1] if with_quarantine else setups,
        quarantined_pages=quarantined_pages,
    )


def _ingest_test_weekly_pdf(monkeypatch, state, *, with_quarantine=False):
    attachment = FakeMessage(
        35448,
        "caption must not replace PDF content",
        date=dt.datetime(2026, 9, 27, 23, 5, 33, tzinfo=dt.timezone.utc),
        document_filename="PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        document_mime_type="application/pdf",
    )
    client = FakeTelegramClient([attachment])
    state["observed_message_id"] = 35447
    monkeypatch.setattr(
        scan,
        "parse_weekly_pdf",
        lambda filename, payload: weekly_pdf_result(with_quarantine=with_quarantine),
        raising=False,
    )
    entity = asyncio.run(scan.resolve_source(client))
    result = asyncio.run(scan.ingest_unseen_messages(client, entity, state, now()))
    assert result[1] == len(state["outbox"])
    return client


def _source_plan(
    event_key="pdf:35448:KETR",
    *,
    ticker="KETR",
    document_message_id=35448,
    signal_datetime="2026-09-28T06:05:33+07:00",
    entry=">=940",
    stop_loss="<900",
    targets=None,
):
    return {
        "event_key": event_key,
        "ticker": ticker,
        "descriptor": "On support",
        "trend": "Uptrend",
        "ma_indicator": "Below, Bull tendency",
        "potential_upside": "6%-11%",
        "potential_downside": "-4%",
        "entry": entry,
        "stop_loss": stop_loss,
        "targets": targets or [
            {"number": 1, "value": "1000"},
            {"number": 2, "value": "1050"},
        ],
        "signal_datetime": signal_datetime,
        "document_message_id": document_message_id,
        "page_number": 1,
        "section_number": 5,
        "pdf_sha256": "a" * 64,
        "pdf_path": "/tmp/weekly.pdf",
        "chart_path": "/tmp/ketr.jpg",
        "report_date": "2026-09-28",
    }


def _source_update(
    *,
    ticker="KETR",
    signal_datetime=dt.datetime(2026, 9, 28, 11, 1, tzinfo=scan.WIB),
    entry="",
    stop_loss="",
    targets=(scan.PriceTarget(2, "1050"), scan.PriceTarget(3, "1100")),
    outcomes=("First target 1000 achieved",),
):
    call = sample_call(has_photo=False)
    return scan.SwingCall(
        **{
            **call.__dict__,
            "source_message_id": 35461,
            "ticker": ticker,
            "call_subtype": "",
            "entry": entry,
            "stop_loss": stop_loss,
            "targets": targets,
            "signal_datetime": signal_datetime,
            "event_kind": "REMINDER",
            "status": None,
            "outcomes": outcomes,
        }
    )


def test_source_media_pdf_uploads_are_durable_before_adjacent_all_and_board_delivery(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    _ingest_test_weekly_pdf(monkeypatch, state)
    operations = []
    upload_refs = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )

    class FakeSourceMediaClient:
        def upload(self, key, data, *, kind, content_type, filename):
            operations.append(("upload", key, data, kind, content_type, filename))
            reference = upload_refs[len([item for item in operations if item[0] == "upload"]) - 1]
            return {
                "ref": reference,
                "sha256": scan.hashlib.sha256(data).hexdigest(),
                "kind": kind,
                "content_type": content_type,
                "size_bytes": len(data),
                "filename": filename,
                "durable": True,
            }

    monkeypatch.setattr(scan, "source_media_client", FakeSourceMediaClient, raising=False)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, channel_id, dry_run, event_key: operations.append(
            ("text", event_key, content)
        ) or f"text-{event_key}",
    )
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda path, channel_id, dry_run, event_key: operations.append(
            ("chart", event_key, Path(path).read_bytes())
        ) or f"chart-{event_key}",
    )
    monkeypatch.setattr(
        scan,
        "submit_board_event",
        lambda payload, chart, dry_run: operations.append(
            ("board", payload["event_key"], payload)
        ) or True,
    )

    assert scan.drain_outbox(state, dt.datetime(2026, 9, 28, 12, tzinfo=scan.WIB)) == 2

    uploads = [item for item in operations if item[0] == "upload"]
    assert [item[1] for item in uploads] == [
        "telegram:channel:1444713822:message:35448:weekly-pdf",
        "telegram:channel:1444713822:message:35448:weekly-chart:AADI",
        "telegram:channel:1444713822:message:35448:weekly-chart:ITMG",
    ]
    assert [item[2] for item in uploads] == [
        b"weekly-pdf-bytes",
        b"\xff\xd8\xffaadi-chart",
        b"\xff\xd8\xffitmg-chart",
    ]
    assert [(item[0], item[1]) for item in operations if item[0] in {"text", "chart"}] == [
        ("text", "pdf:35448:AADI"),
        ("chart", "pdf:35448:AADI"),
        ("text", "pdf:35448:ITMG"),
        ("chart", "pdf:35448:ITMG"),
    ]
    positions = {
        (item[0], item[1]): index for index, item in enumerate(operations)
        if item[0] in {"upload", "text", "chart"}
    }
    assert positions[("upload", uploads[0][1])] < positions[("text", "pdf:35448:AADI")]
    assert positions[("upload", uploads[1][1])] < positions[("text", "pdf:35448:AADI")]
    assert positions[("upload", uploads[2][1])] < positions[("text", "pdf:35448:ITMG")]
    assert "Report date: 28 Sep 2026" in next(
        item[2] for item in operations if item[:2] == ("text", "pdf:35448:AADI")
    )
    assert [(item[0], item[1]) for item in operations if item[0] == "board"] == [
        ("board", "phintraco:1444713822:weekly:35448:AADI"),
        ("board", "phintraco:1444713822:weekly:35448:ITMG"),
    ]
    batch = state["pdf_batches"]["35448"]
    assert batch["source_media"]["ref"] == upload_refs[0]
    assert state["source_plans"]["pdf:35448:AADI"]["source_media"]["ref"] == upload_refs[1]
    assert state["source_plans"]["pdf:35448:ITMG"]["source_media"]["ref"] == upload_refs[2]
    assert state["source_plans"]["pdf:35448:AADI"]["chart_sha256"] == scan.hashlib.sha256(
        b"\xff\xd8\xffaadi-chart"
    ).hexdigest()


def test_source_media_pdf_ambiguous_retry_reuses_same_key_and_bytes(tmp_state, monkeypatch):
    state = scan.empty_state()
    _ingest_test_weekly_pdf(monkeypatch, state, with_quarantine=True)
    uploads = []

    class FakeSourceMediaClient:
        def upload(self, key, data, *, kind, content_type, filename):
            uploads.append((key, data, kind, content_type, filename))
            if len(uploads) == 1:
                raise RuntimeError("connection dropped after durable upload")
            return {
                "ref": "11111111-1111-4111-8111-111111111111" if kind == "document" else "22222222-2222-4222-8222-222222222222",
                "sha256": scan.hashlib.sha256(data).hexdigest(),
                "kind": kind,
                "content_type": content_type,
                "size_bytes": len(data),
                "filename": filename,
                "durable": True,
            }

    monkeypatch.setattr(scan, "source_media_client", FakeSourceMediaClient, raising=False)
    sent = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *args: sent.append("text") or "text")
    monkeypatch.setattr(scan, "post_discord_file", lambda *args: sent.append("chart") or "chart")
    monkeypatch.setattr(scan, "submit_board_event", lambda *args: True)

    assert scan.drain_outbox(state, dt.datetime(2026, 9, 28, 12, tzinfo=scan.WIB)) == 0
    event = state["outbox"]["pdf:35448:AADI"]
    assert event["phase"] == scan.PHASE_PENDING_SOURCE_MEDIA
    assert sent == []

    event["next_attempt_at"] = None
    assert scan.drain_outbox(state, dt.datetime(2026, 9, 28, 12, 2, tzinfo=scan.WIB)) == 1
    assert uploads[0] == uploads[1]
    assert uploads[0][0] == "telegram:channel:1444713822:message:35448:weekly-pdf"
    assert uploads[2][0] == "telegram:channel:1444713822:message:35448:weekly-chart:AADI"
    assert sent == ["text", "chart"]


def test_strict_range_match_accepts_only_explicit_source_ranges():
    state = scan.empty_state()
    key = "pdf:35448:KETR"
    board_key = "phintraco:1444713822:weekly:35448:KETR"
    state["source_plans"][key] = _source_plan(
        targets=[{"number": 1, "value": "1000 to 1050"}]
    )

    in_range = _source_update(
        targets=(scan.PriceTarget(1, "1040"),),
        outcomes=("First target 1040 achieved",),
    )
    outside_range = _source_update(
        targets=(scan.PriceTarget(1, "1051"),),
        outcomes=("First target 1051 achieved",),
    )

    assert scan.match_source_plan(in_range, state, None) == board_key
    state["source_plans"][key] = _source_plan(
        targets=[{"number": 1, "value": "1000"}]
    )
    exact_single = _source_update(
        targets=(scan.PriceTarget(1, "1000"),),
        outcomes=("First target 1000 achieved",),
    )
    assert scan.match_source_plan(exact_single, state, None) == board_key
    assert scan.match_source_plan(outside_range, state, None) is None


@pytest.mark.parametrize(
    "call",
    [
        _source_update(ticker="INDF"),
        _source_update(outcomes=("Second target 1000 achieved",)),
        _source_update(outcomes=("First target 999 achieved",)),
        _source_update(entry="970"),
        _source_update(stop_loss="<880"),
        _source_update(signal_datetime=dt.datetime(2026, 9, 27, 12, tzinfo=scan.WIB)),
    ],
    ids=("wrong-ticker", "wrong-target-ordinal", "wrong-target-value", "entry-mismatch", "stop-mismatch", "stale-chronology"),
)
def test_matched_setup_rejects_conflicting_or_stale_plan_updates(call):
    state = scan.empty_state()
    state["source_plans"]["pdf:35448:KETR"] = _source_plan()
    assert scan.match_source_plan(call, state, None) is None


def test_matched_setup_uses_direct_pdf_reply_then_requires_unique_fallback():
    state = scan.empty_state()
    first_key = "pdf:35448:KETR"
    second_key = "pdf:35449:KETR"
    first_board_key = "phintraco:1444713822:weekly:35448:KETR"
    state["source_plans"][first_key] = _source_plan()
    state["source_plans"][second_key] = _source_plan(
        event_key=second_key,
        document_message_id=35449,
        signal_datetime="2026-09-28T07:05:33+07:00",
    )
    call = _source_update(signal_datetime=dt.datetime(2026, 9, 28, 11, 1, tzinfo=scan.WIB))

    assert scan.match_source_plan(call, state, 35448) == first_board_key
    assert scan.match_source_plan(call, state, None) is None


def test_matched_setup_allows_only_the_next_target_as_an_amendment():
    state = scan.empty_state()
    key = "pdf:35448:KETR"
    board_key = "phintraco:1444713822:weekly:35448:KETR"
    state["source_plans"][key] = _source_plan()
    call = _source_update(
        targets=(scan.PriceTarget(2, "1050"), scan.PriceTarget(3, "1100")),
        outcomes=("First target 1000 achieved",),
    )

    assert scan.match_source_plan(call, state, None) == board_key


def test_unmatched_pdf_update_is_source_context_without_plan_mutation(tmp_state, monkeypatch):
    state = scan.empty_state()
    key = "pdf:35448:KETR"
    state["source_plans"][key] = _source_plan()
    state["observed_message_id"] = 35460
    source_text = (
        "Reminder\n\nKETR - First target 999 achieved\n\nTarget 2: 1051\n"
        "Target 3: 1100\n\nBy PHINTRACO SEKURITAS\n"
        "28/09/2026 11.01 WIB\nNauval Maulana| Investment Advisor"
    )
    companion = FakeMessage(
        35447,
        "Phintraco Sekuritas | Weekly Swing Trading Ideas",
        date=dt.datetime(2026, 9, 27, 23, 5, tzinfo=dt.timezone.utc),
    )
    reminder = FakeMessage(
        35461,
        source_text,
        reply_to_msg_id=35447,
        date=dt.datetime(2026, 9, 28, 4, 1, tzinfo=dt.timezone.utc),
    )
    client = FakeTelegramClient([companion, reminder])
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (1, 1, 0)
    event = state["outbox"]["35461"]
    call = scan.deserialize_call(event["call"])
    payload, chart = scan.board_event_payload(event, call)

    assert event["matched_setup_event_key"] is None
    assert event["board_kind_override"] == "context"
    assert payload["kind"] == "context"
    assert "matched_setup_event_key" not in payload
    assert payload["plan"] is None
    assert "KETR - First target 999 achieved" in payload["all_content"]
    assert "Nauval Maulana" in payload["all_content"]
    assert chart is None


def test_matched_setup_event_key_links_companion_reply_to_ketr_pdf_plan(tmp_state, monkeypatch):
    state = scan.empty_state()
    setup_key = "pdf:35448:KETR"
    board_setup_key = "phintraco:1444713822:weekly:35448:KETR"
    state["source_plans"][setup_key] = _source_plan()
    state["observed_message_id"] = 35460
    source_text = (
        "Reminder\n\nKETR - First target 1000 achieved\n\nTarget 2: 1050\n"
        "Target 3: 1100\n\nBy PHINTRACO SEKURITAS\n"
        "28/09/2026 11.01 WIB\nNauval Maulana| Investment Advisor"
    )
    companion = FakeMessage(
        35447,
        "Phintraco Sekuritas | Weekly Swing Trading Ideas",
        date=dt.datetime(2026, 9, 27, 23, 5, tzinfo=dt.timezone.utc),
    )
    reminder = FakeMessage(
        35461,
        source_text,
        reply_to_msg_id=35447,
        date=dt.datetime(2026, 9, 28, 4, 1, tzinfo=dt.timezone.utc),
    )
    client = FakeTelegramClient([companion, reminder])
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (1, 1, 0)
    event = state["outbox"]["35461"]
    payload, _ = scan.board_event_payload(event, scan.deserialize_call(event["call"]))

    assert event["matched_setup_event_key"] == board_setup_key
    assert event["board_kind_override"] is None
    assert payload["kind"] == "reminder"
    assert payload["matched_setup_event_key"] == board_setup_key
    assert payload["plan"] is None


def test_state_v3_pdf_pending_event_migrates_to_durable_media_contract(tmp_state, monkeypatch):
    state = scan.empty_state()
    _ingest_test_weekly_pdf(monkeypatch, state, with_quarantine=True)
    state["version"] = 3
    for event in state["outbox"].values():
        event.pop("matched_setup_event_key")
        event.pop("board_kind_override")
        event["call"].pop("source_text")
        event["phase"] = scan.PHASE_PENDING_TEXT
    for batch in state["pdf_batches"].values():
        batch.pop("source_media")
    for plan in state["source_plans"].values():
        plan.pop("source_media")
    tmp_state.write_text(json.dumps(state))

    migrated = scan.load_state()

    assert migrated["version"] == 4
    assert migrated["outbox"]["pdf:35448:AADI"]["phase"] == scan.PHASE_PENDING_TEXT
    assert migrated["outbox"]["pdf:35448:AADI"]["call"]["source_text"] == ""
    assert migrated["pdf_batches"]["35448"]["source_media"] is None
    assert migrated["source_plans"]["pdf:35448:AADI"]["source_media"] is None


def test_weekly_pdf_batch_persists_all_children_before_advancing_cursor(tmp_state, monkeypatch):
    published = dt.datetime(2026, 9, 27, 23, 5, 33, tzinfo=dt.timezone.utc)
    companion = FakeMessage(
        35447,
        "Phintraco Sekuritas | Weekly Swing Trading Ideas: source text companion, excluded from PDF intake",
        date=published - dt.timedelta(seconds=4),
    )
    attachment = FakeMessage(
        35448,
        "caption must not replace PDF content",
        date=published,
        document_filename="PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        document_mime_type="application/pdf",
    )
    client = FakeTelegramClient([companion, attachment])
    state = scan.empty_state()
    state["observed_message_id"] = 35446
    parsed_inputs = []

    def parse_pdf(filename, payload):
        parsed_inputs.append((filename, payload))
        return weekly_pdf_result()

    monkeypatch.setattr(scan, "parse_weekly_pdf", parse_pdf, raising=False)
    parsed_text_ids = []
    original_parse_source_event = scan.parse_source_event

    def track_source_text(message):
        parsed_text_ids.append(message.id)
        return original_parse_source_event(message)

    monkeypatch.setattr(scan, "parse_source_event", track_source_text)
    original_save_state = scan.save_state
    saved_after_cursor_advance = []

    def save_with_durability_assertion(candidate):
        if candidate["observed_message_id"] == 35448:
            batch = candidate["pdf_batches"]["35448"]
            assert Path(batch["pdf_path"]).is_file()
            assert batch["event_keys"] == ["pdf:35448:AADI", "pdf:35448:ITMG"]
            assert all(Path(candidate["outbox"][key]["chart_path"]).is_file() for key in batch["event_keys"])
            assert all(key in candidate["source_plans"] for key in batch["event_keys"])
            saved_after_cursor_advance.append(True)
        original_save_state(candidate)

    monkeypatch.setattr(scan, "save_state", save_with_durability_assertion)
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (2, 2, 0)
    assert parsed_inputs == [
        ("PHINTAS Weekly Swing Trading Ideas_20260928.pdf", b"weekly-pdf-bytes")
    ]
    assert saved_after_cursor_advance and all(saved_after_cursor_advance)
    assert parsed_text_ids == []
    assert client.download_calls == [35448]
    assert state["observed_message_id"] == 35448
    assert list(state["outbox"]) == ["pdf:35448:AADI", "pdf:35448:ITMG"]
    assert [state["outbox"][key]["delivery_order"] for key in state["outbox"]] == [1, 2]
    assert [
        state["source_plans"][key]["signal_datetime"] for key in state["source_plans"]
    ] == ["2026-09-28T06:05:33+07:00", "2026-09-28T06:05:33+07:00"]
    assert all(state["outbox"][key]["phase"] == scan.PHASE_PENDING_SOURCE_MEDIA for key in state["outbox"])
    state["outbox"] = dict(reversed(list(state["outbox"].items())))
    assert scan.oldest_outbox_event(state)["event_key"] == "pdf:35448:AADI"
    assert len(scan.load_state()["source_plans"]) == 2


def test_weekly_pdf_page_quarantine_is_durable_and_retries_do_not_duplicate_children(
    tmp_state, monkeypatch
):
    attachment = FakeMessage(
        35448,
        "",
        date=dt.datetime(2026, 9, 27, 23, 5, 33, tzinfo=dt.timezone.utc),
        document_filename="PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        document_mime_type="application/pdf",
    )
    client = FakeTelegramClient([attachment])
    state = scan.empty_state()
    state["observed_message_id"] = 35447
    parser_calls = []
    monkeypatch.setattr(
        scan,
        "parse_weekly_pdf",
        lambda filename, payload: parser_calls.append((filename, payload)) or weekly_pdf_result(with_quarantine=True),
        raising=False,
    )
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (1, 1, 1)
    assert state["pdf_batches"]["35448"]["status"] == "degraded"
    assert state["pdf_batches"]["35448"]["quarantined_pages"] == [
        {"page_number": 2, "reason": "weekly plan page has an ambiguous chart association"}
    ]
    assert list(state["outbox"]) == ["pdf:35448:AADI"]

    state["observed_message_id"] = 35447
    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (1, 0, 0)
    assert len(state["outbox"]) == 1
    assert len(state["source_plans"]) == 1
    assert len(parser_calls) == 1


def test_weekly_pdf_named_non_pdf_attachment_is_quarantined_without_download_or_cursor_loss(
    tmp_state,
):
    attachment = FakeMessage(
        35448,
        "",
        document_filename="PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        document_mime_type="image/jpeg",
    )
    client = FakeTelegramClient([attachment])
    state = scan.empty_state()
    state["observed_message_id"] = 35447
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(scan.ingest_unseen_messages(client, entity, state, now())) == (1, 0, 1)
    assert client.download_calls == []
    assert state["observed_message_id"] == 35448
    assert state["quarantined_documents"]["35448"]["reason"] == (
        "weekly attachment is not an application/pdf document"
    )
    assert scan.load_state()["quarantined_documents"]["35448"]


def test_ingest_accepts_verified_reply_status_with_source_timestamp(tmp_state):
    state = scan.empty_state()
    state["observed_message_id"] = 33722
    source_posted_at = dt.datetime(2026, 7, 15, 3, 55, 48, tzinfo=dt.timezone.utc)
    client = FakeTelegramClient(
        [
            FakeMessage(
                33722,
                fixture("trading_buy.txt").replace("SCMA", "ESSA"),
                photo=True,
            ),
            FakeMessage(
                33735,
                "ESSA on track",
                reply_to_msg_id=33722,
                date=source_posted_at,
            ),
        ]
    )
    entity = asyncio.run(scan.resolve_source(client))

    assert asyncio.run(
        scan.ingest_unseen_messages(
            client,
            entity,
            state,
            dt.datetime(2026, 7, 15, 11, 0, tzinfo=scan.WIB),
        )
    ) == (1, 1, 0)

    queued = scan.deserialize_call(state["outbox"]["33735"]["call"])
    assert queued.event_kind == "STATUS"
    assert queued.ticker == "ESSA"
    assert queued.signal_datetime == dt.datetime(2026, 7, 15, 10, 55, 48, tzinfo=scan.WIB)


def test_resolve_source_uses_verified_channel_id():
    client = FakeTelegramClient([])
    entity = asyncio.run(scan.resolve_source(client))
    assert entity.id == scan.SOURCE_CHANNEL_ID
    assert client.dialog_calls == 1


def test_fetch_unseen_messages_is_chronological_and_unbounded():
    client = FakeTelegramClient([
        FakeMessage(10, "irrelevant"),
        FakeMessage(11, fixture("trading_buy.txt"), photo=True),
        FakeMessage(12, fixture("buy_on_support.txt"), photo=True),
    ])
    entity = asyncio.run(scan.resolve_source(client))
    messages = asyncio.run(scan.fetch_unseen_messages(client, entity, min_id=10))
    assert [message.id for message in messages] == [11, 12]


def test_first_run_bootstrap_uses_latest_without_outbox(tmp_state):
    state = scan.empty_state()
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    bootstrapped = asyncio.run(scan.bootstrap_source(client, entity, state, dt.datetime.now(scan.WIB)))
    assert bootstrapped is True
    assert state["observed_message_id"] == 33655
    assert state["outbox"] == {}


def test_bootstrap_records_poll_completion_time(tmp_state, monkeypatch):
    state = scan.empty_state()
    client = FakeTelegramClient(
        [FakeMessage(33655, fixture("trading_buy.txt"), photo=True)]
    )
    entity = asyncio.run(scan.resolve_source(client))
    run_entry = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    completed = run_entry + dt.timedelta(minutes=11)
    monkeypatch.setattr(scan, "current_time", lambda: completed)

    assert asyncio.run(
        scan.bootstrap_source(client, entity, state, run_entry)
    ) is True
    assert state["last_poll_success"] == completed.isoformat()
    assert json.loads(tmp_state.read_text())["last_poll_success"] == completed.isoformat()


def test_ingest_captures_calls_before_cursor_advance(tmp_state):
    state = scan.empty_state()
    state["observed_message_id"] = 33653
    client = FakeTelegramClient([
        FakeMessage(33654, fixture("buy_on_support.txt"), photo=True),
        FakeMessage(33655, fixture("trading_buy.txt"), photo=True),
        FakeMessage(33656, "unrelated research", photo=True),
        FakeMessage(
            33657,
            "SCMA - Trading Buy : rationale\nStop-loss : <200\nTarget : 230\n"
            "By PHINTRACO SEKURITAS\n10/07/2026 7.00 WIB",
            photo=True,
        ),
    ])
    entity = asyncio.run(scan.resolve_source(client))
    messages, calls, malformed = asyncio.run(
        scan.ingest_unseen_messages(client, entity, state, dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    )
    assert (messages, calls, malformed) == (4, 2, 1)
    assert state["observed_message_id"] == 33657
    assert list(state["outbox"]) == ["33654", "33655"]
    persisted = json.loads(tmp_state.read_text())
    assert list(persisted["outbox"]) == ["33654", "33655"]


def test_ingest_records_poll_completion_time(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33655
    client = FakeTelegramClient([FakeMessage(33656, "unrelated research")])
    entity = asyncio.run(scan.resolve_source(client))
    run_entry = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    completed = run_entry + dt.timedelta(minutes=11)
    monkeypatch.setattr(scan, "current_time", lambda: completed)

    assert asyncio.run(
        scan.ingest_unseen_messages(client, entity, state, run_entry)
    ) == (1, 0, 0)
    assert state["last_poll_success"] == completed.isoformat()
    assert json.loads(tmp_state.read_text())["last_poll_success"] == completed.isoformat()


def test_capture_oldest_media_writes_durable_file(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is True
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["chart_status"] == "captured"
    assert Path(event["media_path"]).read_bytes() == b"\xff\xd8\xffsource-chart"
    assert client.download_calls == [33655]


def test_media_capture_fsyncs_file_and_directory_before_state(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    client = FakeTelegramClient(
        [FakeMessage(33655, fixture("trading_buy.txt"), photo=True)]
    )
    entity = asyncio.run(scan.resolve_source(client))
    scan.media_dir().mkdir(parents=True)
    operations = []
    real_replace = scan.os.replace

    monkeypatch.setattr(scan.os, "fsync", lambda descriptor: operations.append("fsync"))

    def record_replace(source, destination):
        operations.append("replace")
        return real_replace(source, destination)

    monkeypatch.setattr(scan.os, "replace", record_replace)
    monkeypatch.setattr(scan, "save_state", lambda persisted: operations.append("save"))

    assert asyncio.run(
        scan.capture_oldest_media(
            client,
            entity,
            state,
            dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB),
        )
    ) is True
    assert operations == ["fsync", "replace", "fsync", "save"]


def test_media_retry_delay_starts_when_failure_is_observed(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    event = scan.enqueue_call(
        state,
        sample_call(has_photo=True),
        dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB),
    )
    client = FakeTelegramClient(
        [FakeMessage(33655, fixture("trading_buy.txt"), photo=True)]
    )

    async def fail_download(message, target_type):
        raise TimeoutError("telegram media timeout")

    client.download_media = fail_download
    entity = asyncio.run(scan.resolve_source(client))
    run_start = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    observed = run_start + dt.timedelta(seconds=35)
    monkeypatch.setattr(scan, "current_time", lambda: observed)

    assert asyncio.run(
        scan.capture_oldest_media(client, entity, state, run_start)
    ) is False
    assert dt.datetime.fromisoformat(event["next_attempt_at"]) - observed == dt.timedelta(
        seconds=60
    )


def test_media_recapture_after_text_returns_to_pending_chart(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    event["text_discord_id"] = "text-33655"
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is True
    assert event["phase"] == scan.PHASE_PENDING_CHART


def test_media_download_failure_stays_pending_capture(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    async def fail_download(message, target_type):
        raise TimeoutError("telegram media timeout")
    client.download_media = fail_download
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is False
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["last_error"] == "telegram media timeout"


# Discord delivery and strict FIFO

def enqueue_ready(state, call, tmp_path, chart=True):
    event = scan.enqueue_call(state, call, dt.datetime.now(scan.WIB))
    if chart:
        path = tmp_path / f"{call.source_message_id}.jpg"
        path.write_bytes(b"chart")
        event["phase"] = scan.PHASE_PENDING_TEXT
        event["chart_status"] = "captured"
        event["media_path"] = str(path)
    return event


def enqueue_ready_chart_call(tmp_state, tmp_path):
    assert scan.state_path() == tmp_state
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), now())
    media = tmp_path / "media"
    media.mkdir()
    chart = media / "phintraco-33655.jpg"
    chart.write_bytes(b"source chart")
    event["phase"] = scan.PHASE_PENDING_TEXT
    event["chart_status"] = "captured"
    event["media_path"] = str(chart)
    scan.save_state(state)
    return state


def test_text_then_chart_order_per_call(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    first = sample_call(has_photo=True)
    second = scan.SwingCall(**{**first.__dict__, "source_message_id": 33656, "ticker": "BUKA"})
    enqueue_ready(state, first, tmp_path)
    enqueue_ready(state, second, tmp_path)
    scan.save_state(state)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append(("text", event_key)) or f"text-{event_key}")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or f"chart-{event_key}")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    delivered = scan.drain_outbox(state, dt.datetime.now(scan.WIB))
    assert delivered == 2
    assert events == [("text", "33655"), ("chart", "33655"), ("text", "33656"), ("chart", "33656")]
    assert state["outbox"] == {}


def test_board_handoff_waits_for_all_text_and_chart(tmp_state, tmp_path, monkeypatch) -> None:
    state = enqueue_ready_chart_call(tmp_state, tmp_path)
    submitted = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *_: "all-text")
    monkeypatch.setattr(scan, "post_discord_file", lambda *_: "all-chart")
    monkeypatch.setattr(
        scan,
        "submit_board_event",
        lambda payload, chart, dry_run: submitted.append((payload, chart)) or True,
    )

    scan.drain_outbox(state, now())

    assert submitted[0][0]["kind"] == "buy"
    assert submitted[0][0]["plan"] == {
        "entry": "208 to 212",
        "stop_loss": "<200",
        "targets": ["230"],
    }
    assert submitted[0][0]["source_status"] == "New setup"
    assert submitted[0][1].name == "phintraco-33655.jpg"
    assert state["outbox"] == {}


def test_chartless_buy_hands_off_without_media(tmp_state, monkeypatch):
    state = scan.empty_state()
    scan.enqueue_call(state, sample_call(has_photo=False), now())
    submitted = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *_: "all-text")
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda *_: pytest.fail("chartless call must not upload"),
    )
    monkeypatch.setattr(
        scan,
        "submit_board_event",
        lambda payload, chart, dry_run: submitted.append((payload, chart)) or True,
    )

    assert scan.drain_outbox(state, now()) == 1
    assert submitted[0][0]["kind"] == "buy"
    assert submitted[0][1] is None
    assert state["outbox"] == {}


def test_status_handoff_is_accepted_without_a_primary_plan(tmp_state, monkeypatch):
    state = scan.empty_state()
    status = scan.SwingCall(
        **{
            **sample_call(has_photo=False).__dict__,
            "event_kind": "STATUS",
            "status": "On track",
            "targets": (),
        }
    )
    scan.enqueue_call(state, status, now())
    submitted = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *_: "all-text")
    monkeypatch.setattr(
        scan,
        "submit_board_event",
        lambda payload, chart, dry_run: submitted.append(payload) or True,
    )

    assert scan.drain_outbox(state, now()) == 1
    assert submitted[0]["kind"] == "status"
    assert submitted[0]["source_status"] == "On track"
    assert submitted[0]["source_title"] == "SCMA: On track"
    assert submitted[0]["plan"] is None
    assert state["outbox"] == {}


def test_reminder_board_payload_preserves_explicit_outcomes(tmp_state):
    reminder = scan.SwingCall(
        **{
            **sample_call(has_photo=False).__dict__,
            "event_kind": "REMINDER",
            "outcomes": ("First target 230 achieved", "Second target 250 achieved"),
            "targets": (),
        }
    )
    state = scan.empty_state()
    event = scan.enqueue_call(state, reminder, now())

    payload, chart = scan.board_event_payload(event, reminder)

    assert payload["kind"] == "reminder"
    assert payload["source_status"] == "First target 230 achieved; Second target 250 achieved"
    assert payload["source_title"] == "SCMA: First target 230 achieved; Second target 250 achieved"
    assert payload["plan"] is None
    assert chart is None


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"accepted":true}', True),
        ('{"accepted":1}', False),
        ('{"accepted":true,"board_url":"https://discord.com/channels/940285152335110204/123"}', True),
        ('{"accepted":true,"extra":false}', False),
        ('{"accepted":false}', False),
        ("not-json", False),
    ],
)
def test_board_submission_accepts_only_the_owner_acknowledgement(
    monkeypatch, stdout, expected
):
    completed = type("Completed", (), {"returncode": 0, "stdout": stdout})()
    monkeypatch.setattr(scan.subprocess, "run", lambda *args, **kwargs: completed)
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_WRAPPER", "/tmp/board-wrapper")

    assert scan.submit_board_event({"event_key": "phintraco:1444713822:33655"}, None, False) is expected


def test_board_retry_preserves_all_ids_and_cached_chart_until_acknowledged(
    tmp_state, tmp_path, monkeypatch
):
    state = enqueue_ready_chart_call(tmp_state, tmp_path)
    event = state["outbox"]["33655"]
    all_posts = []
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *_: all_posts.append("text") or "all-text",
    )
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda *_: all_posts.append("chart") or "all-chart",
    )
    monkeypatch.setattr(scan, "current_time", now)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)

    assert scan.drain_outbox(state, now()) == 0
    assert event["phase"] == scan.PHASE_PENDING_BOARD
    assert event["text_discord_id"] == "all-text"
    assert event["board_attempts"] == 1
    assert Path(event["media_path"]).is_file()
    assert all_posts == ["text", "chart"]

    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    assert scan.drain_outbox(state, now() + dt.timedelta(minutes=1)) == 1
    assert all_posts == ["text", "chart"]
    assert state["outbox"] == {}


def test_pending_board_never_blocks_later_all_text_and_chart(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    first = sample_call()
    for offset in range(2):
        call = scan.SwingCall(**{**first.__dict__, "source_message_id": 33655 + offset})
        enqueue_ready(state, call, tmp_path)
    posts = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *args: posts.append(("text", args[-1])) or "text-id")
    monkeypatch.setattr(scan, "post_discord_file", lambda *args: posts.append(("chart", args[-1])) or "chart-id")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)
    monkeypatch.setattr(scan, "current_time", now)
    scan.drain_outbox(state, now())
    assert posts == [("text", "33655"), ("chart", "33655"), ("text", "33656"), ("chart", "33656")]
    third = scan.SwingCall(**{**first.__dict__, "source_message_id": 33657})
    enqueue_ready(state, third, tmp_path)
    scan.drain_outbox(state, now() + dt.timedelta(seconds=10))
    assert posts[-2:] == [("text", "33657"), ("chart", "33657")]
    assert all(event["phase"] == scan.PHASE_PENDING_BOARD for event in state["outbox"].values())
    assert all(Path(event["media_path"]).is_file() for event in state["outbox"].values())


@pytest.mark.parametrize("health,healthy", [
    ('{"drained":0,"pending":0,"failed":0}', True),
    ('{"drained":0,"pending":2,"failed":1}', False),
    ('{"drained":0}', False),
    ('{"drained":0,"pending":false,"failed":0}', False),
])
def test_owner_drain_requires_explicit_healthy_queue(monkeypatch, health, healthy):
    completed = type("Completed", (), {"returncode": 0, "stdout": health})()
    monkeypatch.setattr(scan.subprocess, "run", lambda *args, **kwargs: completed)
    assert scan.drain_board(False) is healthy


def test_degraded_poll_still_drains_board_and_later_all(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33654
    scan.save_state(state)
    client = ConnectedFakeTelegramClient([
        FakeMessage(33655, fixture("trading_buy.txt"), photo=True),
        FakeMessage(33656, fixture("trading_buy.txt"), photo=True),
    ])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args: True)
    posts, drains = [], []
    monkeypatch.setattr(scan, "post_discord_text", lambda *args: posts.append(("text", args[-1])) or "text-id")
    monkeypatch.setattr(scan, "post_discord_file", lambda *args: posts.append(("chart", args[-1])) or "chart-id")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)
    monkeypatch.setattr(scan, "drain_board", lambda *_: drains.append(True) or False)
    asyncio.run(scan.run(now=now()))
    assert posts == [("text", "33655"), ("chart", "33655"), ("text", "33656"), ("chart", "33656")]
    assert drains == [True]


def test_text_failure_does_not_attempt_chart(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    scan.save_state(state)
    monkeypatch.setattr(scan, "post_discord_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("chart must not be attempted"))
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 0
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["text_discord_id"] is None


def test_chart_failure_retries_chart_only_and_blocks_newer_call(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    first = sample_call(has_photo=True)
    second = scan.SwingCall(**{**first.__dict__, "source_message_id": 33656, "ticker": "BUKA"})
    first_event = enqueue_ready(state, first, tmp_path)
    enqueue_ready(state, second, tmp_path)
    scan.save_state(state)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append(("text", event_key)) or f"text-{event_key}")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or None)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    assert scan.drain_outbox(state, now) == 0
    assert events == [("text", "33655"), ("chart", "33655")]
    assert first_event["phase"] == scan.PHASE_PENDING_CHART
    assert first_event["text_discord_id"] == "text-33655"
    scan.clear_retry(first_event)
    events.clear()
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or f"chart-{event_key}")
    assert scan.drain_outbox(state, now) == 2
    assert events == [("chart", "33655"), ("text", "33656"), ("chart", "33656")]


def test_chartless_call_delivers_text_only(tmp_state, monkeypatch):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=False), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    captured = {}
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: captured.update(content=content) or "text-33655")
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("chartless call must not upload"))
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 1
    assert "**Chart:** Unavailable from source" in captured["content"]
    assert event["event_key"] not in state["outbox"]


def test_missing_cached_chart_returns_to_media_capture(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    Path(event["media_path"]).unlink()
    event["phase"] = scan.PHASE_PENDING_CHART
    event["text_discord_id"] = "text-33655"
    scan.save_state(state)
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("missing file must not upload"))
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 0
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE



def test_zero_length_cached_chart_is_recaptured_before_text(
    tmp_state, tmp_path, monkeypatch
):
    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    Path(event["media_path"]).write_bytes(b"")
    scan.save_state(state)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *args, **kwargs: pytest.fail("empty chart must be recaptured before text"),
    )

    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 0
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["chart_status"] == "expected"


def test_delivered_phase_is_finalized_without_network_or_spin(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    event = scan.enqueue_call(
        state,
        sample_call(has_photo=False),
        dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB),
    )
    event["phase"] = "delivered"
    scan.save_state(state)
    original_oldest = scan.oldest_outbox_event
    calls = 0

    def bounded_oldest(current):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise AssertionError("delivered event spun without progress")
        return original_oldest(current)

    monkeypatch.setattr(scan, "oldest_outbox_event", bounded_oldest)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *args, **kwargs: pytest.fail("delivered text must not be reposted"),
    )
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda *args, **kwargs: pytest.fail("delivered chart must not be reposted"),
    )

    assert scan.drain_outbox(
        state, dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    ) == 0
    assert state["outbox"] == {}


@pytest.mark.parametrize("leg", ["text", "chart"])
def test_delivery_retry_delay_starts_when_failure_is_observed(
    tmp_state, tmp_path, monkeypatch, leg
):
    state = scan.empty_state()
    if leg == "text":
        event = scan.enqueue_call(
            state,
            sample_call(has_photo=False),
            dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB),
        )
        monkeypatch.setattr(scan, "post_discord_text", lambda *args, **kwargs: None)
    else:
        event = enqueue_ready(state, sample_call(), tmp_path)
        event["phase"] = scan.PHASE_PENDING_CHART
        event["text_discord_id"] = "text-33655"
        monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: None)
    scan.save_state(state)
    run_start = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    observed = run_start + dt.timedelta(seconds=35)
    monkeypatch.setattr(scan, "current_time", lambda: observed)

    assert scan.drain_outbox(state, run_start) == 0
    assert dt.datetime.fromisoformat(event["next_attempt_at"]) - observed == dt.timedelta(
        seconds=60
    )


def test_delivery_owner_rate_limit_is_exposed_without_sleeping(monkeypatch):
    class FakeOwner:
        def status(self, _key):
            return None

        def submit(self, _operation):
            raise scan.DeliveryClientError("rate_limited")

    monkeypatch.setattr(
        scan.time,
        "sleep",
        lambda seconds: pytest.fail(f"must not sleep under process lock: {seconds}"),
    )

    with pytest.raises(scan.DiscordRetryAfter) as raised:
        scan.post_discord_text("alert", scan.ALERT_CHANNEL_ID, False, "33655", client=FakeOwner())
    assert raised.value.retry_after == 60.0


def test_full_discord_retry_after_is_persisted_from_failure_time(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    event = scan.enqueue_call(
        state,
        sample_call(has_photo=False),
        dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB),
    )
    scan.save_state(state)
    run_start = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    observed = run_start + dt.timedelta(seconds=35)
    monkeypatch.setattr(scan, "current_time", lambda: observed)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            scan.DiscordRetryAfter(125.5)
        ),
    )

    assert scan.drain_outbox(state, run_start) == 0
    retry_at = dt.datetime.fromisoformat(event["next_attempt_at"])
    assert retry_at - observed == dt.timedelta(seconds=125.5)
    assert json.loads(tmp_state.read_text())["outbox"]["33655"][
        "next_attempt_at"
    ] == event["next_attempt_at"]


def test_discord_text_and_chart_use_stable_distinct_delivery_keys(tmp_path):
    class FakeOwner:
        def __init__(self):
            self.operations = []

        def status(self, _key):
            return None

        def submit(self, operation):
            self.operations.append(operation)
            return scan.OperationReceipt(
                id=f"receipt-{len(self.operations)}",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": operation.target["channel_id"], "message_id": str(90000 + len(self.operations))},
            )

    chart = tmp_path / "chart.jpg"
    chart.write_bytes(b"chart")
    owner = FakeOwner()

    assert scan.post_discord_text("alert", scan.ALERT_CHANNEL_ID, False, "33655", client=owner)
    assert scan.post_discord_text("alert", scan.ALERT_CHANNEL_ID, False, "33655", client=owner)
    assert scan.post_discord_file(str(chart), scan.ALERT_CHANNEL_ID, False, "33655", client=owner)
    assert scan.post_discord_file(str(chart), scan.ALERT_CHANNEL_ID, False, "33655", client=owner)

    keys = [operation.key for operation in owner.operations]
    assert keys == [
        "bursawatch-tg-phintraco-swing:33655:text",
        "bursawatch-tg-phintraco-swing:33655:text",
        "bursawatch-tg-phintraco-swing:33655:chart",
        "bursawatch-tg-phintraco-swing:33655:chart",
    ]
    assert keys[0] != keys[2]
    assert owner.operations[2].attachments[0].data == b"chart"


def test_imported_pending_receipt_waits_without_resubmitting():
    operation = scan._channel_message_operation(
        "alert", scan.ALERT_CHANNEL_ID, "33655", leg="text"
    )
    imported = replace(
        operation,
        reconcile_before_first_create=True,
        legacy_nonce=scan.discord_nonce("33655", "text"),
    )

    class FakeOwner:
        def __init__(self):
            self.submits = []
            self.waits = []

        def status(self, key):
            assert key == operation.key
            return scan.OperationReceipt(
                id="imported",
                key=key,
                digest=imported.digest,
                status="pending_reconciliation",
                receipt=None,
            )

        def submit(self, value):
            self.submits.append(value)
            pytest.fail("an imported operation must not be submitted again")

        def wait(self, key, timeout):
            self.waits.append((key, timeout))
            return scan.OperationReceipt(
                id="imported",
                key=key,
                digest=imported.digest,
                status="delivered",
                receipt={"channel_id": scan.ALERT_CHANNEL_ID, "message_id": "90001"},
            )

    owner = FakeOwner()

    assert scan.post_discord_text(
        "alert", scan.ALERT_CHANNEL_ID, False, "33655", client=owner
    ) == "90001"
    assert owner.submits == []
    assert owner.waits == [(operation.key, 0)]


def test_unrecognized_existing_digest_is_rejected_without_resubmitting():
    operation = scan._channel_message_operation(
        "alert", scan.ALERT_CHANNEL_ID, "33655", leg="text"
    )

    class FakeOwner:
        def status(self, key):
            assert key == operation.key
            return scan.OperationReceipt(
                id="existing",
                key=key,
                digest="a" * 64,
                status="delivered",
                receipt={"channel_id": scan.ALERT_CHANNEL_ID, "message_id": "90001"},
            )

        def submit(self, _operation):
            pytest.fail("a mismatched existing receipt must never trigger a create")

    with pytest.raises(scan.DeliveryClientError, match="invalid response"):
        scan.post_discord_text(
            "alert", scan.ALERT_CHANNEL_ID, False, "33655", client=FakeOwner()
        )


def test_submit_response_cannot_use_legacy_import_digest():
    operation = scan._channel_message_operation(
        "alert", scan.ALERT_CHANNEL_ID, "33655", leg="text"
    )
    imported = replace(
        operation,
        reconcile_before_first_create=True,
        legacy_nonce=scan.discord_nonce("33655", "text"),
    )

    class FakeOwner:
        def status(self, key):
            assert key == operation.key
            return None

        def submit(self, value):
            assert value.digest == operation.digest
            assert value.reconcile_before_first_create is False
            return scan.OperationReceipt(
                id="unexpected-import",
                key=value.key,
                digest=imported.digest,
                status="delivered",
                receipt={"channel_id": scan.ALERT_CHANNEL_ID, "message_id": "90001"},
            )

    with pytest.raises(scan.DeliveryClientError, match="invalid response"):
        scan._submit_or_lookup(
            operation,
            FakeOwner(),
            legacy_import_nonce=scan.discord_nonce("33655", "text"),
        )


def test_oversized_alert_is_rejected_without_splitting(monkeypatch):
    with pytest.raises(ValueError, match="Discord message limit"):
        scan.post_discord_text("x" * 2001, scan.ALERT_CHANNEL_ID, False, "1")


def test_delivery_owner_receipts_persist_text_before_chart_and_keep_source_keys(
    tmp_state, tmp_path, monkeypatch
):
    class FakeOwner:
        def __init__(self):
            self.operations = []
            self.chart_saw_saved_text = False

        def status(self, key):
            return None

        def submit(self, operation):
            self.operations.append(operation)
            if operation.key.endswith(":chart"):
                stored = json.loads(tmp_state.read_text())["outbox"]["33655"]
                self.chart_saw_saved_text = (
                    stored["text_discord_id"] == "90001"
                    and stored["phase"] == scan.PHASE_PENDING_CHART
                )
            message_id = "90001" if operation.key.endswith(":text") else "90002"
            return scan.OperationReceipt(
                id=f"receipt-{message_id}",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": operation.target["channel_id"], "message_id": message_id},
            )

    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    owner = FakeOwner()
    monkeypatch.setattr(scan, "delivery_client_from_environment", lambda **_kwargs: owner)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_args: True)

    scan.save_state(state)
    assert scan.drain_outbox(state, now()) == 1

    assert [operation.key for operation in owner.operations] == [
        "bursawatch-tg-phintraco-swing:33655:text",
        "bursawatch-tg-phintraco-swing:33655:chart",
    ]
    assert owner.operations[0].payload["content"] == scan.format_swing_alert(
        sample_call(), include_board=True
    )
    assert owner.operations[1].attachments[0].data == b"chart"
    assert owner.chart_saw_saved_text is True
    assert event["phase"] == scan.PHASE_DELIVERED


def test_delivery_owner_unavailable_keeps_only_unfinished_chart_leg(
    tmp_state, tmp_path, monkeypatch
):
    class FakeOwner:
        operations = []

        def status(self, key):
            return None

        def submit(self, operation):
            self.operations.append(operation)
            if operation.key.endswith(":chart"):
                raise scan.DeliveryClientError("network_error")
            return scan.OperationReceipt(
                id="receipt-text",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": operation.target["channel_id"], "message_id": "90001"},
            )

    state = scan.empty_state()
    scan_event = enqueue_ready(state, sample_call(), tmp_path)
    owner = FakeOwner()
    monkeypatch.setattr(scan, "delivery_client_from_environment", lambda **_kwargs: owner)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_args: pytest.fail("Board handoff must wait"))
    scan.save_state(state)

    assert scan.drain_outbox(state, now()) == 0

    persisted = json.loads(tmp_state.read_text())["outbox"]["33655"]
    assert [operation.key for operation in owner.operations] == [
        "bursawatch-tg-phintraco-swing:33655:text",
        "bursawatch-tg-phintraco-swing:33655:chart",
    ]
    assert persisted["text_discord_id"] == "90001"
    assert persisted["phase"] == scan.PHASE_PENDING_CHART
    assert persisted["last_error"] == "delivery service could not be reached"
    assert scan_event["phase"] == scan.PHASE_PENDING_CHART


def test_board_link_edit_reads_and_edits_the_original_message_without_reposting():
    class FakeOwner:
        def __init__(self):
            self.queries = []
            self.operations = []

        def query(self, query):
            self.queries.append(query)
            return [{
                "id": "876543210123456789",
                "content": "Alert\n\n**Board:** <#1548273399069933720>",
            }]

        def status(self, _key):
            return None

        def submit(self, operation):
            self.operations.append(operation)
            return scan.OperationReceipt(
                id="edit-receipt",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": operation.target["channel_id"], "message_id": operation.target["message_id"]},
            )

    owner = FakeOwner()
    board_url = "https://discord.com/channels/940285152335110204/777777777777777777"

    assert scan.edit_discord_board_link(
        "876543210123456789", board_url, False, "33655", client=owner
    ) is True

    assert owner.queries == [scan.DiscordQuery(
        kind="channel_messages",
        channel_id=scan.ALERT_CHANNEL_ID,
        before="876543210123456790",
        limit=100,
    )]
    assert len(owner.operations) == 1
    operation = owner.operations[0]
    assert operation.kind == "channel_message_edit"
    assert operation.key == "bursawatch-tg-phintraco-swing:33655:board-link"
    assert operation.target == {
        "channel_id": scan.ALERT_CHANNEL_ID,
        "message_id": "876543210123456789",
    }
    assert board_url in operation.payload["content"]


# Heartbeat and orchestration

def test_format_heartbeat_healthy_and_degraded():
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    healthy = scan.format_heartbeat(now, scan.RunStats(42, 3, 3, 0, False))
    assert healthy == "🫀 bursawatch-tg-phintraco-swing · 08:00 WIB · 42 messages · 3 calls · 3 delivered · 0 pending"
    degraded = scan.format_heartbeat(now, scan.RunStats(42, 3, 2, 1, True))
    assert degraded.endswith(" · 1 pending ⚠️")


def test_delayed_new_hour_posts_heartbeat(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["last_heartbeat_hour"] = "2026-07-10T07+07:00"
    scan.save_state(state)
    posts = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: posts.append(content) or "heartbeat-id")
    now = dt.datetime(2026, 7, 10, 8, 7, tzinfo=scan.WIB)
    assert scan.post_heartbeat_if_due(state, now, scan.RunStats(0, 0, 0, 0, False), False) is True
    assert len(posts) == 1
    assert state["last_heartbeat_hour"] == "2026-07-10T08+07:00"


def test_failed_heartbeat_does_not_persist_hour(tmp_state, monkeypatch):
    state = scan.empty_state()
    monkeypatch.setattr(scan, "post_discord_text", lambda *args, **kwargs: None)
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    assert scan.post_heartbeat_if_due(state, now, scan.RunStats(0, 0, 0, 0, False), False) is False
    assert state["last_heartbeat_hour"] is None


def test_fatal_notice_is_rate_limited_per_fingerprint_and_hour(tmp_state, monkeypatch):
    state = scan.empty_state()
    posts = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: posts.append(content) or "fatal-id")
    now = dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB)
    assert scan.report_fatal(state, now, "Telegram unavailable", False) is True
    assert scan.report_fatal(state, now, "Telegram unavailable", False) is False
    assert len(posts) == 1


def test_fatal_rate_limit_remembers_alternating_fingerprints(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    posts = []
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, channel_id, dry_run, event_key: posts.append(content) or "fatal-id",
    )
    now = dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB)

    assert scan.report_fatal(state, now, "Telegram unavailable", False) is True
    state = scan.load_state()
    assert scan.report_fatal(state, now, "Discord unavailable", False) is True
    state = scan.load_state()
    assert scan.report_fatal(state, now, "Telegram unavailable", False) is False
    assert len(posts) == 2


def test_fatal_fingerprint_collection_is_bounded_and_resets_each_hour(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda *args, **kwargs: "fatal-id",
    )
    first_hour = dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB)
    for index in range(scan.MAX_FATAL_FINGERPRINTS_PER_HOUR + 1):
        assert scan.report_fatal(state, first_hour, f"failure {index}", False) is True
    notice = state["last_error_notice"]
    assert len(notice["fingerprints"]) == scan.MAX_FATAL_FINGERPRINTS_PER_HOUR
    assert scan.error_fingerprint("failure 0") not in notice["fingerprints"]

    next_hour = first_hour + dt.timedelta(hours=1)
    assert scan.report_fatal(state, next_hour, "failure 0", False) is True
    assert state["last_error_notice"] == {
        "hour": scan.heartbeat_hour_key(next_hour),
        "fingerprints": [scan.error_fingerprint("failure 0")],
    }


class ConnectedFakeTelegramClient(FakeTelegramClient):
    async def connect(self):
        return None

    async def disconnect(self):
        return None


def test_run_does_not_touch_watcher_state_when_telegram_transport_is_unavailable(
    tmp_state, tmp_path, monkeypatch
):
    from telegram_resilience import PolyCopResilience

    class UnavailableClient:
        async def connect(self):
            raise TimeoutError("network unavailable")

        async def disconnect(self):
            return None

    resilience = PolyCopResilience.for_paths(
        tmp_path / "resilience.json", tmp_path / "resilience.jsonl"
    )
    posted = []
    monkeypatch.setattr(scan, "resilience", lambda: resilience)
    monkeypatch.setattr(scan, "make_client", UnavailableClient)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, *_args: posted.append(content) or "discord-id",
    )

    assert asyncio.run(scan.run(now=dt.datetime(2026, 8, 10, 15, 15, tzinfo=scan.WIB))) == {
        "wakeAgent": False
    }
    assert not tmp_state.exists()
    assert posted == [
        "❌ telegram-polycop · 15:15 WIB · transport unavailable; "
        "affected=bursawatch-tg-phintraco-swing"
    ]


def test_run_enters_auth_hold_without_touching_watcher_state(tmp_state, tmp_path, monkeypatch):
    from telegram_resilience import PolyCopResilience

    class UnauthorizedClient:
        async def connect(self):
            return None

        async def is_user_authorized(self):
            return False

        async def get_me(self):
            raise AssertionError("unauthorized client must not fetch identity")

        async def disconnect(self):
            return None

    resilience = PolyCopResilience.for_paths(
        tmp_path / "resilience.json", tmp_path / "resilience.jsonl"
    )
    posted = []
    monkeypatch.setattr(scan, "resilience", lambda: resilience)
    monkeypatch.setattr(scan, "make_client", UnauthorizedClient)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda content, *_args: posted.append(content) or "discord-id",
    )

    assert asyncio.run(scan.run(now=dt.datetime(2026, 8, 10, 15, 16, tzinfo=scan.WIB))) == {
        "wakeAgent": False
    }
    assert not tmp_state.exists()
    assert posted == [
        "❌ telegram-polycop · 15:16 WIB · authorization required; "
        "manual PolyCop session login needed"
    ]


def test_run_bootstraps_without_replay(tmp_state, monkeypatch):
    client = ConnectedFakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    result = asyncio.run(scan.run(now=dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB), dry_run=True))
    assert result == {"wakeAgent": False}
    state = scan.load_state()
    assert state["observed_message_id"] == 33655
    assert state["outbox"] == {}


def test_run_ingests_and_delivers_text_then_chart(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33654
    scan.save_state(state)
    client = ConnectedFakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append("text") or "text-id")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append("chart") or "chart-id")
    monkeypatch.setattr(scan, "drain_board", lambda *_: True)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    result = asyncio.run(scan.run(now=dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)))
    assert result == {"wakeAgent": False}
    assert events == ["text", "chart"]
    assert scan.load_state()["outbox"] == {}


def test_live_run_uses_one_config_revision_and_reports_structured_lifecycle(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33654
    scan.save_state(state)
    loaded = scan.config.LoadedWatchConfig(
        config=scan.config.load_watch_config_data(
            {
                "version": 1,
                "source": {"telegram_channel_id": scan.SOURCE_CHANNEL_ID, "telegram_username": "phintraprofits"},
                "destinations": {
                    "alert_discord_channel_id": "1525102458253217804",
                    "heartbeat_discord_channel_id": "1505162000420835388",
                },
            }
        ),
        revision=7,
    )
    reporter_events = []
    finished = []

    class FakeControlRun:
        @classmethod
        def begin(cls, prefix, revision, **kwargs):
            assert prefix == "IDX_SWING_WATCH_PHINTRACO_DAILY"
            assert revision == 7
            assert kwargs == {"scheduler_job_id": "bursawatch-tg-phintraco-swing"}
            return cls()

        def event(self, event_id, **kwargs):
            reporter_events.append((event_id, kwargs))

        def finish(self, status, error=None):
            finished.append((status, error))

    client = ConnectedFakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    destinations = []
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda: loaded)
    monkeypatch.setattr(scan, "ControlPlaneRun", FakeControlRun)
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        scan,
        "post_discord_text",
        lambda _content, channel_id, _dry_run, _event_key: destinations.append(channel_id) or "text-id",
    )
    monkeypatch.setattr(scan, "post_discord_file", lambda *_args: "chart-id")
    monkeypatch.setattr(scan, "drain_board", lambda *_args: True)
    monkeypatch.setattr(scan, "submit_board_event", lambda *_args: True)

    assert asyncio.run(scan.run(now=dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))) == {"wakeAgent": False}
    assert destinations == ["1525102458253217804"]
    assert [event_id for event_id, _event in reporter_events] == [
        "run-started",
        "source-poll-completed",
        "delivery-drain-completed",
        "run-completed",
    ]
    assert reporter_events[-1][1]["attributes"]["config_revision"] == 7
    assert finished == [("ok", None)]


def test_live_config_failure_stops_before_opening_telegram(monkeypatch):
    monkeypatch.setattr(
        scan.config,
        "load_watch_config_for_run",
        lambda: (_ for _ in ()).throw(ValueError("live config unavailable")),
    )
    monkeypatch.setattr(scan, "make_client", lambda: pytest.fail("Telegram client must not be created"))

    with pytest.raises(ValueError, match="live config unavailable"):
        asyncio.run(scan.run(now=now()))


def test_board_drain_failure_degrades_heartbeat_without_blocking_poll(
    tmp_state, monkeypatch
):
    state = scan.empty_state()
    state["observed_message_id"] = 33655
    scan.save_state(state)
    client = ConnectedFakeTelegramClient([])
    heartbeat_stats = []
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "drain_board", lambda *_: False)
    monkeypatch.setattr(
        scan,
        "post_heartbeat_if_due",
        lambda _state, _now, stats, _dry_run: heartbeat_stats.append(stats) or True,
    )

    assert asyncio.run(scan.run(now=now())) == {"wakeAgent": False}
    assert scan.load_state()["observed_message_id"] == 33655
    assert heartbeat_stats[0].degraded is True


def test_run_records_poll_completion_time(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33655
    scan.save_state(state)
    client = ConnectedFakeTelegramClient([])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    run_entry = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    ingest_completed = run_entry + dt.timedelta(minutes=10)
    run_completed = run_entry + dt.timedelta(minutes=11)
    completion_times = iter((ingest_completed, run_completed))
    monkeypatch.setattr(scan, "current_time", lambda: next(completion_times))

    assert asyncio.run(scan.run(now=run_entry)) == {"wakeAgent": False}
    assert scan.load_state()["last_poll_success"] == run_completed.isoformat()


def test_main_prints_no_agent_json_on_fatal(tmp_state, monkeypatch, capsys):
    async def fail_run(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(scan, "run", fail_run)
    monkeypatch.setattr(scan, "load_state", lambda: scan.empty_state())
    monkeypatch.setattr(scan, "report_fatal", lambda *args, **kwargs: True)
    assert scan.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"wakeAgent": False, "error": "boom"}


def test_run_lock_contention_is_clean_noop(monkeypatch):
    class HeldLock:
        def __enter__(self):
            return False

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(scan, "run_lock", HeldLock)
    monkeypatch.setattr(scan, "make_client", lambda: pytest.fail("contended run must not create a client"))
    assert asyncio.run(scan.run()) == {"wakeAgent": False}


def test_main_prints_original_error_when_fatal_notice_fails(
    tmp_state, monkeypatch, capsys
):
    async def fail_run(*args, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(scan, "run", fail_run)
    monkeypatch.setattr(scan, "load_state", lambda: scan.empty_state())
    monkeypatch.setattr(
        scan,
        "report_fatal",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("discord down")),
    )
    assert scan.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"wakeAgent": False, "error": "telegram down"}
