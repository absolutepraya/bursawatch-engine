import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

import scan

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def now() -> dt.datetime:
    return dt.datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB)

def test_daily_runtime_identifiers_are_provider_specific():
    assert scan.WATCHER_NAME == "idx-swing-watch-phintraco-daily"
    assert scan.WATCHER_HEARTBEAT_NAME == "idx-swing-phintraco-daily"
    assert "idx-swing-watch-phintraco-daily" in str(scan.DEFAULT_STATE_FILE)




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
        "**Board:** <https://discord.com/channels/940285152335110204/1548273399069933720>\n\n"
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
        "**Board:** <https://discord.com/channels/940285152335110204/1548273399069933720>\n\n"
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
        "### <:phintraco:1531272488645038091> INCO: Reminder\n"
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
        "### <:phintraco:1531272488645038091> BRMS: Hold\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Entry:** >=540\n"
        "**Stop-loss:** <520\n"
        "**Target 1:** 590 to 600\n"
        "**Target 2:** 640\n"
        "\n**Source status:** On support <:hold:1531284248235868333>\n"
        "**Last updated:** 17 Jul 2026 10:11 WIB\n"
        "**Board:** <https://discord.com/channels/940285152335110204/1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/33801>)"
    )


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
        "### <:phintraco:1531272488645038091> ESSA: Hold\n"
        "-# Phintraco Sekuritas\n\n"
        "**Source status:** On track <:hold:1531284248235868333>\n"
        "**Last updated:** 15 Jul 2026 10:55 WIB\n"
        "**Board:** <https://discord.com/channels/940285152335110204/1548273399069933720>\n\n"
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
    assert state["version"] == 2
    assert state["observed_message_id"] == 0
    assert state["outbox"] == {}
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
    def __init__(self, message_id, text, photo=False, *, reply_to_msg_id=None, date=None):
        self.id = message_id
        self.message = text
        self.photo = object() if photo else None
        self.reply_to_msg_id = reply_to_msg_id
        self.date = date or dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc)


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
        return b"\xff\xd8\xffsource-chart"


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
    assert payload["plan"] is None
    assert chart is None


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"accepted":true}', True),
        ('{"accepted":1}', False),
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


def test_discord_429_is_exposed_without_sleeping_or_truncation(monkeypatch):
    import requests

    class Response:
        status_code = 429
        headers = {}

        @staticmethod
        def json():
            return {"retry_after": 125.5}

    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        scan.time,
        "sleep",
        lambda seconds: pytest.fail(f"must not sleep under process lock: {seconds}"),
    )

    with pytest.raises(scan.DiscordRetryAfter) as raised:
        scan._discord_request("POST", "https://discord.invalid", headers={})
    assert raised.value.retry_after == 125.5


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


def test_discord_text_and_chart_use_stable_distinct_enforced_nonces(
    tmp_path, monkeypatch
):
    requests_seen = []

    class Response:
        status_code = 201

        @staticmethod
        def json():
            return {"id": "discord-id"}

    def capture_request(method, url, **kwargs):
        requests_seen.append(kwargs)
        return Response()

    chart = tmp_path / "chart.jpg"
    chart.write_bytes(b"chart")
    monkeypatch.setattr(scan, "_discord_token", lambda: "token")
    monkeypatch.setattr(scan, "_discord_request", capture_request)

    assert scan.post_discord_text("alert", scan.ALERT_CHANNEL_ID, False, "33655")
    assert scan.post_discord_text("alert", scan.ALERT_CHANNEL_ID, False, "33655")
    assert scan.post_discord_file(str(chart), scan.ALERT_CHANNEL_ID, False, "33655")
    assert scan.post_discord_file(str(chart), scan.ALERT_CHANNEL_ID, False, "33655")

    text_payloads = [request["json"] for request in requests_seen[:2]]
    chart_payloads = [
        json.loads(request["data"]["payload_json"]) for request in requests_seen[2:]
    ]
    assert text_payloads[0]["nonce"] == text_payloads[1]["nonce"]
    assert chart_payloads[0]["nonce"] == chart_payloads[1]["nonce"]
    assert text_payloads[0]["nonce"] != chart_payloads[0]["nonce"]
    assert all(payload["enforce_nonce"] is True for payload in text_payloads)
    assert all(payload["enforce_nonce"] is True for payload in chart_payloads)

def test_oversized_alert_is_rejected_without_splitting(monkeypatch):
    monkeypatch.setattr(scan, "_discord_token", lambda: "token")
    with pytest.raises(ValueError, match="Discord message limit"):
        scan.post_discord_text("x" * 2001, scan.ALERT_CHANNEL_ID, False, "1")


# Heartbeat and orchestration

def test_format_heartbeat_healthy_and_degraded():
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    healthy = scan.format_heartbeat(now, scan.RunStats(42, 3, 3, 0, False))
    assert healthy == "🫀 idx-swing-phintraco-daily · 08:00 WIB · 42 messages · 3 calls · 3 delivered · 0 pending"
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
        "affected=idx-swing-watch-phintraco-daily"
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
