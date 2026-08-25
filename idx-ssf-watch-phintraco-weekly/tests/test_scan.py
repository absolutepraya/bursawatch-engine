from __future__ import annotations

import json
import os
from pathlib import Path
import asyncio
from datetime import datetime, timedelta

import pytest

import scan
from scan import InvalidSsfReport, format_ssf_alert, parse_weekly_ssf_pdf, ssf_alert_direction


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ssf"


def test_default_state_path_is_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(scan.STATE_ENV, raising=False)

    assert scan._state_path() == (
        Path.home() / ".hermes" / "state" / "idx-ssf-watch-phintraco-weekly.json"
    )


@pytest.mark.parametrize(
    ("source_message_id", "filename"),
    ((33681, "33681.pdf"), (33568, "33568.pdf"), (33327, "33327.pdf")),
)
def test_real_source_reports_have_complete_ssf_reviews(
    source_message_id: int, filename: str, tmp_state: Path
) -> None:
    review = parse_weekly_ssf_pdf(source_message_id, FIXTURE_DIR / filename)

    assert review.source_message_id == source_message_id
    assert review.provider == "Phintraco"
    assert len(review.underlyings) == 5
    assert all(len(underlying.contracts) == 3 for underlying in review.underlyings)
    assert all(underlying.chart_path is None for underlying in review.underlyings)


def test_33681_preserves_indf_short_contract_values(tmp_state: Path) -> None:
    review = parse_weekly_ssf_pdf(33681, FIXTURE_DIR / "33681.pdf")
    indf = review.underlyings[0]

    assert indf.ticker == "INDF"
    assert [contract.strategy for contract in indf.contracts] == ["Short", "Short", "Short"]
    assert [contract.purchase_price for contract in indf.contracts] == ["6825", "6825", "6825"]
    assert indf.share_price == "6750"
    alert = format_ssf_alert(indf, review.report_date, review.source_message_id)
    assert alert.startswith("### <:phintraco:1531272488645038091> [SSF] SHORT: INDF\n")
    assert "[SSF] SHORT<:down:" not in alert


def test_33568_mixed_indf_heading_and_source_faithful_contracts(tmp_state: Path) -> None:
    review = parse_weekly_ssf_pdf(33568, FIXTURE_DIR / "33568.pdf")
    indf = review.underlyings[0]

    assert [contract.strategy for contract in indf.contracts] == ["Short", "Long", "Long"]
    assert ssf_alert_direction(indf.contracts) == "MIXED"

    alert = format_ssf_alert(indf, review.report_date, review.source_message_id)
    assert alert.startswith("### <:phintraco:1531272488645038091> [SSF] MIXED: INDF\n")
    assert "Report date: Mon, Jul 6 2026" in alert
    assert "Underlying price: 6925" in alert
    for contract in indf.contracts:
        assert f"**{contract.horizon_months}-month contract**" in alert
        marker = "<:up:1531285100346740766>" if contract.strategy == "Long" else "<:down:1531285063986053200>"
        assert f"Strategy: {contract.strategy}{marker}" in alert
        assert f"Purchase price: {contract.purchase_price}" in alert
        assert f"Target price: {contract.target_price}" in alert
        assert f"Support / resistance: {contract.support_resistance}" in alert
    assert alert.endswith("Source: [Phintraco Sekuritas](<https://t.me/phintraprofits/33568>) | Weekly SSF Review")
    assert len(alert) < 2000


def test_malformed_fifth_page_is_rejected(tmp_state: Path) -> None:
    with pytest.raises(InvalidSsfReport, match="exactly four pages"):
        parse_weekly_ssf_pdf(33681, FIXTURE_DIR / "malformed-five-pages.pdf")


def test_unexpected_technical_chart_distribution_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_state: Path
) -> None:
    real_runner = scan.run_poppler
    mismatched_inventory = """page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image    1722  1000  rgb     3   8  jpeg   no        79  0   350   350  255K 5.0%
   1     1 image    1722  1000  rgb     3   8  jpeg   no        80  0   356   356  264K 5.2%
   1     2 image    1722  1000  rgb     3   8  jpeg   no        81  0   356   356  264K 5.2%
   2     3 image    1722  1000  rgb     3   8  jpeg   no        82  0   356   356  264K 5.2%
   2     4 image    1722  1000  rgb     3   8  jpeg   no        83  0   356   356  264K 5.2%
"""

    def fake_runner(*args: str) -> str:
        if args[0] == "pdfimages":
            return mismatched_inventory
        return real_runner(*args)

    monkeypatch.setattr(scan, "run_poppler", fake_runner)

    with pytest.raises(InvalidSsfReport, match="chart distribution"):
        parse_weekly_ssf_pdf(33681, FIXTURE_DIR / "33681.pdf")


def prepare_events(tmp_state: Path) -> tuple[dict[str, object], scan.WeeklySsfReview]:
    review = parse_weekly_ssf_pdf(33681, FIXTURE_DIR / "33681.pdf")
    chart_dir = tmp_state.parent / "media"
    chart_dir.mkdir()
    chart_paths = []
    for underlying in review.underlyings:
        chart_path = chart_dir / f"{review.source_message_id}-{underlying.ticker}.png"
        chart_path.write_bytes(b"durable chart")
        chart_paths.append(chart_path)

    state = scan.empty_state()
    scan.enqueue_review(state, review, chart_paths)
    scan.save_state(state)
    return state, review


def test_enqueue_review_creates_source_ordered_pending_text_events(
    tmp_state: Path,
) -> None:
    state, review = prepare_events(tmp_state)

    assert list(state["outbox"]) == [
        f"{review.source_message_id}:INDF",
        f"{review.source_message_id}:BBCA",
        f"{review.source_message_id}:BMRI",
        f"{review.source_message_id}:ASII",
        f"{review.source_message_id}:MDKA",
    ]
    assert [event["phase"] for event in state["outbox"].values()] == [
        "pending_text"
    ] * 5


def test_text_success_then_chart_failure_retries_only_cached_chart(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = prepare_events(tmp_state)
    delivery_now = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    calls: list[tuple[str, str]] = []

    def post_text(
        channel_id: str, bot_token: str, content: str, nonce: str
    ) -> str:
        calls.append(("text", nonce))
        return "discord-text-id"

    def fail_chart(
        channel_id: str, bot_token: str, chart_path: Path, nonce: str
    ) -> str:
        calls.append(("chart", nonce))
        raise OSError("Discord unavailable")

    monkeypatch.setattr(scan, "post_discord_text", post_text)
    monkeypatch.setattr(scan, "post_discord_file", fail_chart)

    assert scan.drain_outbox(state, "channel", "token", now=delivery_now) == 1
    event = state["outbox"][f"{review.source_message_id}:INDF"]
    assert event["text_discord_id"] == "discord-text-id"
    assert event["phase"] == "pending_chart"
    assert state["outbox"][f"{review.source_message_id}:BBCA"]["phase"] == "pending_text"
    assert state["last_delivery_success"] is None
    assert calls == [
        ("text", scan.discord_nonce(f"{review.source_message_id}:INDF", "text")),
        ("chart", scan.discord_nonce(f"{review.source_message_id}:INDF", "chart")),
    ]

    def post_chart(
        channel_id: str, bot_token: str, chart_path: Path, nonce: str
    ) -> str:
        calls.append(("chart-retry", nonce))
        return "discord-chart-id"

    monkeypatch.setattr(scan, "post_discord_file", post_chart)

    assert (
        scan.drain_outbox(
            state, "channel", "token", now=delivery_now + timedelta(minutes=1)
        )
        == 9
    )
    assert calls[2] == (
        "chart-retry",
        scan.discord_nonce(f"{review.source_message_id}:INDF", "chart"),
    )
    assert all(event["phase"] == "delivered" for event in state["outbox"].values())


def test_drain_outbox_defers_retrying_head_with_capped_backoff_and_fifo(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = prepare_events(tmp_state)
    started = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    attempts: list[str] = []
    first_event_key = f"{review.source_message_id}:INDF"
    first_event = state["outbox"][first_event_key]

    def fail_text(
        channel_id: str, bot_token: str, content: str, nonce: str
    ) -> str:
        attempts.append(content)
        raise OSError("Discord unavailable")

    monkeypatch.setattr(scan, "post_discord_text", fail_text)

    assert scan.drain_outbox(state, "channel", "token", now=started) == 0
    assert first_event["delivery_attempts"] == 1
    assert first_event["next_attempt_at"] == "2026-07-14T06:01:00+07:00"
    assert scan.load_state()["outbox"][first_event_key]["next_attempt_at"] == (
        "2026-07-14T06:01:00+07:00"
    )
    assert (
        scan.drain_outbox(
            state, "channel", "token", now=started + timedelta(seconds=59)
        )
        == 0
    )
    assert attempts == [first_event["text"]]
    assert state["outbox"][f"{review.source_message_id}:BBCA"]["phase"] == (
        "pending_text"
    )

    for expected_delay in (2, 4, 8, 16, 32, 60, 60):
        due = datetime.fromisoformat(first_event["next_attempt_at"])
        assert scan.drain_outbox(state, "channel", "token", now=due) == 0
        assert datetime.fromisoformat(first_event["next_attempt_at"]) == due + timedelta(
            minutes=expected_delay
        )

    assert attempts == [first_event["text"]] * 8
    assert state["outbox"][f"{review.source_message_id}:BBCA"]["phase"] == (
        "pending_text"
    )


def test_state_save_is_atomic_and_corrupt_state_fails_closed(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = scan.empty_state()
    scan.save_state(state)
    original = tmp_state.read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("interrupted replacement")

    monkeypatch.setattr(scan.os, "replace", fail_replace)
    state["observed_message_id"] = 33681
    with pytest.raises(OSError, match="interrupted replacement"):
        scan.save_state(state)

    assert tmp_state.read_bytes() == original
    assert not list(tmp_state.parent.glob(f".{tmp_state.name}.*.tmp"))
    assert os.stat(tmp_state).st_mode & 0o777 == 0o600

    tmp_state.write_text("{not valid JSON", encoding="utf-8")
    with pytest.raises(scan.StateBlockedError):
        scan.load_state()
    tmp_state.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(scan.StateBlockedError):
        scan.load_state()


def test_invalid_report_is_terminal_and_never_enqueues_events(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = scan.empty_state()

    def fake_parse(source_message_id: int, pdf_path: Path) -> scan.WeeklySsfReview:
        raise InvalidSsfReport("wrong provider")

    monkeypatch.setattr(scan, "parse_weekly_ssf_pdf", fake_parse)

    assert (
        scan.capture_report(
            state,
            33681,
            lambda temporary_pdf_path: temporary_pdf_path.write_bytes(b"invalid"),
        )
        is None
    )
    assert state["invalid_reports"] == {"33681": {"reason": "wrong provider"}}
    assert state["report_jobs"] == {}
    assert state["outbox"] == {}
    assert not (tmp_state.parent / "reports" / "33681.pdf").exists()


def test_capture_report_retries_ordinary_downloader_failures(
    tmp_state: Path,
) -> None:
    state = scan.empty_state()

    def interrupted_download(temporary_pdf_path: Path) -> None:
        temporary_pdf_path.write_bytes(b"partial download")
        raise RuntimeError("temporary network failure")

    retry_at = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    assert scan.capture_report(state, 33681, interrupted_download, now=retry_at) is None

    job = state["report_jobs"]["33681"]
    assert job["phase"] == "pending_download"
    assert job["retry"] == {
        "attempts": 1,
        "last_error": "temporary network failure",
        "next_attempt_at": "2026-07-14T06:01:00+07:00",
    }
    assert not (tmp_state.parent / "reports" / "33681.pdf.tmp").exists()
    assert not (tmp_state.parent / "reports" / "33681.pdf").exists()
    assert scan.load_state()["report_jobs"]["33681"]["retry"] == job["retry"]


def test_drain_outbox_removes_cached_charts_and_pdf_only_after_all_events(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = prepare_events(tmp_state)
    delivery_now = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    report_dir = tmp_state.parent / "reports"
    report_dir.mkdir()
    pdf_path = report_dir / f"{review.source_message_id}.pdf"
    pdf_path.write_bytes(b"source report")
    state["report_jobs"][str(review.source_message_id)]["pdf_path"] = str(pdf_path)
    chart_paths = [Path(event["chart_path"]) for event in state["outbox"].values()]

    legs: list[str] = []

    def post_text(channel_id: str, bot_token: str, content: str, nonce: str) -> str:
        legs.append(f"text:{nonce}")
        return "text-id"

    def post_chart(
        channel_id: str, bot_token: str, chart_path: Path, nonce: str
    ) -> str:
        legs.append(f"chart:{nonce}")
        return "chart-id"

    monkeypatch.setattr(scan, "post_discord_text", post_text)
    monkeypatch.setattr(scan, "post_discord_file", post_chart)

    assert scan.drain_outbox(state, "channel", "token", now=delivery_now) == 10
    assert legs == [
        f"{leg}:{scan.discord_nonce(f'{review.source_message_id}:{ticker}', leg)}"
        for ticker in ("INDF", "BBCA", "BMRI", "ASII", "MDKA")
        for leg in ("text", "chart")
    ]
    assert all(event["phase"] == "delivered" for event in state["outbox"].values())
    assert state["last_delivery_success"] == delivery_now.isoformat()
    persisted_delivery = datetime.fromisoformat(
        scan.load_state()["last_delivery_success"]
    )
    assert persisted_delivery.tzinfo is not None
    assert persisted_delivery.utcoffset() == timedelta(hours=7)
    assert all(not chart_path.exists() for chart_path in chart_paths)
    assert not pdf_path.exists()
    assert state["report_jobs"][str(review.source_message_id)]["phase"] == "completed"
    assert scan.discord_nonce("33681:INDF", "text") == (
        "8fb65722dc7c4d7aa8a7de17"
    )


def test_chart_cleanup_failure_retries_without_reposting_or_pdf_cleanup(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, review = prepare_events(tmp_state)
    delivery_now = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    report_dir = tmp_state.parent / "reports"
    report_dir.mkdir()
    pdf_path = report_dir / f"{review.source_message_id}.pdf"
    pdf_path.write_bytes(b"source report")
    state["report_jobs"][str(review.source_message_id)]["pdf_path"] = str(pdf_path)
    chart_paths = [Path(event["chart_path"]) for event in state["outbox"].values()]
    chart_nonces: list[str] = []

    def post_text(channel_id: str, bot_token: str, content: str, nonce: str) -> str:
        return "text-id"

    def post_chart(
        channel_id: str, bot_token: str, chart_path: Path, nonce: str
    ) -> str:
        chart_nonces.append(nonce)
        return "chart-id"

    original_unlink = Path.unlink
    unlink_failed = False

    def fail_first_chart_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal unlink_failed
        if path == chart_paths[0] and not unlink_failed:
            unlink_failed = True
            raise OSError("cached chart remains")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(scan, "post_discord_text", post_text)
    monkeypatch.setattr(scan, "post_discord_file", post_chart)
    monkeypatch.setattr(Path, "unlink", fail_first_chart_cleanup)

    assert scan.drain_outbox(state, "channel", "token", now=delivery_now) == 2
    first_event = state["outbox"][f"{review.source_message_id}:INDF"]
    assert first_event["phase"] == "pending_chart_cleanup"
    assert first_event["chart_discord_id"] == "chart-id"
    assert first_event["chart_path"] == str(chart_paths[0])
    assert chart_paths[0].exists()
    assert pdf_path.exists()
    assert state["last_delivery_success"] is None

    assert (
        scan.drain_outbox(
            state, "channel", "token", now=delivery_now + timedelta(minutes=1)
        )
        == 8
    )
    assert chart_nonces == [
        scan.discord_nonce(f"{review.source_message_id}:{ticker}", "chart")
        for ticker in ("INDF", "BBCA", "BMRI", "ASII", "MDKA")
    ]
    assert all(event["phase"] == "delivered" for event in state["outbox"].values())
    assert all(not chart_path.exists() for chart_path in chart_paths)
    assert not pdf_path.exists()


def test_capture_report_caches_validated_charts_before_enqueuing(
    tmp_state: Path,
) -> None:
    state = scan.empty_state()

    review = scan.capture_report(
        state,
        33681,
        lambda temporary_pdf_path: temporary_pdf_path.write_bytes(
            (FIXTURE_DIR / "33681.pdf").read_bytes()
        ),
    )

    assert review is not None
    job = state["report_jobs"]["33681"]
    assert job["phase"] == "queued"
    assert Path(job["pdf_path"]).is_file()
    assert len(job["event_keys"]) == 5
    assert all(
        Path(event["chart_path"]).is_file() for event in state["outbox"].values()
    )



def test_select_newest_valid_candidate_uses_highest_source_id(tmp_state: Path) -> None:
    older = scan.SsfCandidate(33327, "Weekly SSF Review 2026-06-29.pdf", object())
    newest = scan.SsfCandidate(33681, "weekly ssf review 2026-07-13.PDF", object())

    assert scan.select_newest_valid_candidate((older, newest)) == newest


def test_record_invalid_report_is_terminal_without_outbox_events(tmp_state: Path) -> None:
    state = scan.empty_state()
    state["outbox"]["999:TEST"] = {
        "source_message_id": 999,
        "ticker": "TEST",
        "phase": "pending_text",
        "text": "stale event",
        "chart_path": None,
        "text_discord_id": None,
        "chart_discord_id": None,
        "delivery_attempts": 0,
        "last_error": None,
    }

    scan.record_invalid_report(state, 999, "wrong provider")
    heartbeat = scan.format_heartbeat(
        datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB),
        scan.RunStats(source_status="invalid", reports=0, alerts=0, degraded=False),
    )

    assert state["invalid_reports"]["999"]["reason"] == "wrong provider"
    assert state["outbox"] == {}
    assert heartbeat.startswith("🫀 idx-ssf · 06:00 WIB · source=invalid")


def test_fatal_format_redacts_secrets_paths_and_raw_bytes(tmp_state: Path) -> None:
    fatal = scan.format_fatal(
        datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB),
        "POLYCOP_SESSION_STRING=top-secret /private/reports/source.pdf b'raw bytes'",
    )

    assert fatal.startswith("❌ idx-ssf · 06:00 WIB · failed: ")
    assert "top-secret" not in fatal
    assert "/private" not in fatal
    assert ".pdf" not in fatal
    assert "b'raw bytes'" not in fatal


def test_successful_runs_post_heartbeat_every_thirty_minutes(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    posted: list[str] = []

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return 0

    async def fetch_unseen_messages(
        _client: Client, _entity: object, _minimum_id: int
    ) -> list[object]:
        return []

    monkeypatch.setattr(scan, "make_client", lambda: Client())
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(scan, "fetch_unseen_messages", fetch_unseen_messages)
    monkeypatch.setattr(
        scan,
        "post_operational_text",
        lambda content, nonce, dry_run: posted.append(content) or "message-id",
    )

    first = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    asyncio.run(scan.run(now=first, dry_run=False))
    asyncio.run(scan.run(now=first + timedelta(minutes=30), dry_run=False))

    assert len(posted) == 2
    assert posted[0].startswith("🫀 idx-ssf · 06:00 WIB")
    assert posted[1].startswith("🫀 idx-ssf · 06:30 WIB")


def test_run_preserves_watcher_state_when_shared_telegram_probe_times_out(
    tmp_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from telegram_resilience import PolyCopResilience

    class UnavailableClient:
        async def connect(self) -> None:
            raise TimeoutError("network unavailable")

        async def disconnect(self) -> None:
            pass

    resilience = PolyCopResilience.for_paths(
        tmp_path / "resilience.json", tmp_path / "resilience.jsonl"
    )
    posted: list[str] = []
    monkeypatch.setattr(scan, "resilience", lambda: resilience)
    monkeypatch.setattr(scan, "make_client", UnavailableClient)
    monkeypatch.setattr(
        scan,
        "post_operational_text",
        lambda content, *_args: posted.append(content) or "discord-id",
    )

    assert asyncio.run(
        scan.run(now=datetime(2026, 8, 10, 15, 15, tzinfo=scan.WIB), dry_run=False)
    ) == {"wakeAgent": False}
    assert not tmp_state.exists()
    assert posted == [
        "❌ telegram-polycop · 15:15 WIB · transport unavailable; "
        "affected=idx-ssf-watch-phintraco-weekly"
    ]


def test_heartbeat_ignores_delivered_history_but_warns_for_pending_work(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    posted: list[str] = []

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return 0

    async def fetch_unseen_messages(
        _client: Client, _entity: object, _minimum_id: int
    ) -> list[object]:
        return []

    monkeypatch.setattr(scan, "make_client", lambda: Client())
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(scan, "fetch_unseen_messages", fetch_unseen_messages)
    monkeypatch.setattr(
        scan,
        "post_operational_text",
        lambda content, nonce, dry_run: posted.append(content) or "message-id",
    )

    state = scan.empty_state()
    state["bootstrap_complete"] = True
    state["outbox"]["33681:INDF"] = {
        "source_message_id": 33681,
        "ticker": "INDF",
        "phase": "delivered",
        "text": "historical alert",
        "chart_path": None,
        "text_discord_id": "text-id",
        "chart_discord_id": "chart-id",
        "delivery_attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
    }
    scan.save_state(state)

    first = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    asyncio.run(scan.run(now=first, dry_run=True))
    assert not posted[-1].endswith("⚠️")

    state = scan.load_state()
    state["outbox"]["33681:INDF"]["phase"] = "pending_text"
    state["outbox"]["33681:INDF"]["chart_path"] = "cached-chart.png"
    scan.save_state(state)
    asyncio.run(scan.run(now=first + timedelta(minutes=30), dry_run=True))
    assert posted[-1].endswith("⚠️")

    state = scan.load_state()
    state["outbox"]["33681:INDF"]["phase"] = "delivered"
    state["outbox"]["33681:INDF"]["chart_path"] = None
    state["report_jobs"]["33681"] = {
        "source_message_id": 33681,
        "phase": "pending_download",
        "pdf_path": None,
        "retry": {
            "attempts": 1,
            "last_error": "temporary network failure",
            "next_attempt_at": "2026-07-14T07:01:00+07:00",
        },
        "event_keys": [],
    }
    scan.save_state(state)
    asyncio.run(scan.run(now=first + timedelta(hours=1), dry_run=True))
    assert posted[-1].endswith("⚠️")


def test_main_force_heartbeat_uses_forced_post_nonce_during_no_post_dry_run(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    posted: list[tuple[str, str]] = []

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return 0

    async def fetch_unseen_messages(
        _client: Client, _entity: object, _minimum_id: int
    ) -> list[object]:
        return []

    monkeypatch.setenv("IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST", "1")
    monkeypatch.delenv("IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT", raising=False)
    monkeypatch.setattr(scan, "make_client", lambda: Client())
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(scan, "fetch_unseen_messages", fetch_unseen_messages)
    monkeypatch.setattr(
        scan,
        "post_operational_text",
        lambda content, nonce, _dry_run: posted.append((content, nonce)) or "message-id",
    )

    assert scan.main() == 0
    assert len(posted) == 1
    assert posted[0][1].startswith("heartbeat-")

    monkeypatch.setenv("IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT", "1")

    assert scan.main() == 0
    assert len(posted) == 2
    assert posted[1][0].startswith("🫀 idx-ssf · ")
    assert posted[1][1].startswith("force-heartbeat-")


def test_bootstrap_streams_newest_first_and_stops_after_newest_valid_report(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Message:
        def __init__(self, message_id: int, filename: str | None) -> None:
            self.id = message_id
            self.document = (
                type(
                    "Document",
                    (),
                    {
                        "mime_type": "application/pdf",
                        "attributes": [
                            type("Filename", (), {"file_name": filename})()
                        ],
                    },
                )()
                if filename is not None
                else None
            )

    newest_noncandidate = Message(33700, None)
    newer_invalid = Message(33690, "Weekly SSF Review 2026-07-14.pdf")
    newest_valid = Message(33681, "Weekly SSF Review 2026-07-13.pdf")

    class Client:
        def __init__(self) -> None:
            self.iter_message_calls: list[dict[str, int]] = []
            self.yielded_message_ids: list[int] = []

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def iter_messages(self, _entity: object, **kwargs: int) -> object:
            self.iter_message_calls.append(kwargs)
            for message in (newest_noncandidate, newer_invalid, newest_valid):
                self.yielded_message_ids.append(message.id)
                yield message
            raise AssertionError("bootstrap enumerated historical channel messages")

        async def download_media(self, message: Message, file: str) -> str:
            fixture = (
                FIXTURE_DIR / "malformed-five-pages.pdf"
                if message.id == newer_invalid.id
                else FIXTURE_DIR / "33681.pdf"
            )
            Path(file).write_bytes(fixture.read_bytes())
            return file

    client = Client()

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return 33700

    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(
        scan, "post_operational_text", lambda _content, _nonce, _dry_run: "message-id"
    )

    asyncio.run(scan.run(now=datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB), dry_run=True))
    state = scan.load_state()

    assert client.iter_message_calls == [{"max_id": 33701}]
    assert client.yielded_message_ids == [33700, 33690, 33681]
    assert state["bootstrap_complete"] is True
    assert state["observed_message_id"] == 33700
    assert set(state["report_jobs"]) == {"33681"}
    assert set(state["invalid_reports"]) == {"33690"}
    assert set(state["outbox"]) == {
        "33681:INDF",
        "33681:BBCA",
        "33681:BMRI",
        "33681:ASII",
        "33681:MDKA",
    }


def test_current_invalid_candidate_reports_invalid_source_status(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Message:
        id = 999
        document = type(
            "Document",
            (),
            {
                "mime_type": "application/pdf",
                "attributes": [
                    type("Filename", (), {"file_name": "Weekly SSF Review bad.pdf"})()
                ],
            },
        )()

    class Client:
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def download_media(self, _message: Message, file: str) -> str:
            Path(file).write_bytes((FIXTURE_DIR / "malformed-five-pages.pdf").read_bytes())
            return file

    state = scan.empty_state()
    state["bootstrap_complete"] = True
    scan.save_state(state)
    posted: list[str] = []

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return 999

    async def fetch_unseen_messages(
        _client: Client, _entity: object, _minimum_id: int
    ) -> list[Message]:
        return [Message()]

    monkeypatch.setattr(scan, "make_client", lambda: Client())
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(scan, "fetch_unseen_messages", fetch_unseen_messages)
    monkeypatch.setattr(
        scan,
        "post_operational_text",
        lambda content, nonce, dry_run: posted.append(content) or "message-id",
    )

    asyncio.run(scan.run(now=datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB), dry_run=True))

    assert scan.load_state()["invalid_reports"]["999"]["reason"] == "expected exactly four pages"
    assert posted == ["🫀 idx-ssf · 06:00 WIB · source=invalid · reports=0 · alerts=0"]


@pytest.mark.parametrize(
    ("reason", "secret", "sanitised"),
    (
        (
            "POLYCOP_SESSION_STRING: top-secret",
            "top-secret",
            "POLYCOP_SESSION_STRING=<redacted>",
        ),
        (
            'DISCORD_BOT_TOKEN = "quoted bot token"',
            "quoted bot token",
            "DISCORD_BOT_TOKEN=<redacted>",
        ),
        (
            "TELEGRAM_API_HASH : 'quoted api hash'",
            "quoted api hash",
            "TELEGRAM_API_HASH=<redacted>",
        ),
        (
            "database_password = super-secret",
            "super-secret",
            "database_password=<redacted>",
        ),
    ),
)
def test_fatal_reason_redacts_delimited_and_quoted_secrets_before_fingerprinting(
    tmp_state: Path, reason: str, secret: str, sanitised: str
) -> None:
    now = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)

    assert secret not in scan.format_fatal(now, reason)
    assert scan.error_fingerprint(reason) == scan.error_fingerprint(sanitised)


def test_capture_retry_uses_bounded_exponential_wib_schedule(tmp_state: Path) -> None:
    state = scan.empty_state()
    started = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    attempt_times = (
        started,
        started + timedelta(minutes=1),
        started + timedelta(minutes=3),
        started + timedelta(minutes=7),
        started + timedelta(minutes=15),
    )

    def fail_download(_temporary_pdf_path: Path) -> None:
        raise RuntimeError("temporary network failure")

    next_attempts = []
    for attempt_time in attempt_times:
        assert (
            scan.capture_report(state, 33681, fail_download, now=attempt_time) is None
        )
        next_attempts.append(state["report_jobs"]["33681"]["retry"]["next_attempt_at"])

    assert next_attempts == [
        "2026-07-14T06:01:00+07:00",
        "2026-07-14T06:03:00+07:00",
        "2026-07-14T06:07:00+07:00",
        "2026-07-14T06:15:00+07:00",
        None,
    ]


def test_pending_capture_retry_skips_until_due_and_stops_at_cap(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Message:
        id = 33681
        document = type(
            "Document",
            (),
            {
                "mime_type": "application/pdf",
                "attributes": [
                    type(
                        "Filename",
                        (),
                        {"file_name": "Weekly SSF Review 2026-07-13.pdf"},
                    )()
                ],
            },
        )()

    class Client:
        def __init__(self) -> None:
            self.requested_ids: list[int] = []

        async def get_messages(self, _entity: object, ids: int) -> Message:
            self.requested_ids.append(ids)
            return Message()

    state = scan.empty_state()
    now = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    state["report_jobs"]["33681"] = {
        "source_message_id": 33681,
        "phase": "pending_download",
        "pdf_path": None,
        "retry": {
            "attempts": 1,
            "last_error": "temporary network failure",
            "next_attempt_at": (now + timedelta(minutes=1)).isoformat(),
        },
        "event_keys": [],
    }
    captured: list[int] = []

    async def fake_capture(
        _client: Client,
        _state: dict[str, object],
        candidate: scan.SsfCandidate,
        _now: datetime,
    ) -> None:
        captured.append(candidate.source_message_id)
        return None

    monkeypatch.setattr(scan, "_capture_candidate", fake_capture)
    client = Client()

    assert asyncio.run(scan._retry_pending_reports(client, object(), state, now)) == (
        0,
        True,
    )
    assert client.requested_ids == []
    assert captured == []

    assert asyncio.run(
        scan._retry_pending_reports(client, object(), state, now + timedelta(minutes=1))
    ) == (0, True)
    assert client.requested_ids == [33681]
    assert captured == [33681]

    state["report_jobs"]["33681"]["retry"] = {
        "attempts": scan.CAPTURE_RETRY_MAX_ATTEMPTS,
        "last_error": "temporary network failure",
        "next_attempt_at": None,
    }
    assert asyncio.run(
        scan._retry_pending_reports(client, object(), state, now + timedelta(days=1))
    ) == (0, True)
    assert client.requested_ids == [33681]
    assert captured == [33681]


def test_bootstrap_completes_after_retry_then_ingests_newer_candidate(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Message:
        def __init__(self, message_id: int) -> None:
            self.id = message_id
            self.document = type(
                "Document",
                (),
                {
                    "mime_type": "application/pdf",
                    "attributes": [
                        type(
                            "Filename",
                            (),
                            {
                                "file_name": (
                                    f"Weekly SSF Review 2026-07-{message_id}.pdf"
                                )
                            },
                        )()
                    ],
                },
            )()

    bootstrap_message = Message(33681)
    newer_message = Message(33700)

    class Client:
        def __init__(self) -> None:
            self.fail_first_download = True
            self.download_calls = 0

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass
        async def iter_messages(self, _entity: object, **kwargs: int) -> object:
            assert kwargs == {"max_id": 33682}
            yield bootstrap_message


        async def download_media(self, _message: Message, file: str) -> str:
            self.download_calls += 1
            if self.fail_first_download:
                self.fail_first_download = False
                raise RuntimeError("temporary download failure")
            Path(file).write_bytes((FIXTURE_DIR / "33681.pdf").read_bytes())
            return file

        async def get_messages(self, _entity: object, ids: int) -> Message | None:
            return bootstrap_message if ids == bootstrap_message.id else None

    client = Client()
    latest_ids = iter((33681, 33681, 33681, 33700))

    async def resolve_source(_client: Client) -> object:
        return object()

    async def latest_source_message_id(_client: Client, _entity: object) -> int:
        return next(latest_ids)

    async def fetch_unseen_messages(
        _client: Client, _entity: object, minimum_id: int
    ) -> list[Message]:
        assert minimum_id == 33681
        return [newer_message]

    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "resolve_source", resolve_source)
    monkeypatch.setattr(scan, "latest_source_message_id", latest_source_message_id)
    monkeypatch.setattr(scan, "fetch_unseen_messages", fetch_unseen_messages)
    monkeypatch.setattr(
        scan, "post_operational_text", lambda _content, _nonce, _dry_run: "message-id"
    )

    started = datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB)
    asyncio.run(scan.run(now=started, dry_run=True))
    assert scan.load_state()["bootstrap_complete"] is False

    asyncio.run(scan.run(now=started + timedelta(seconds=30), dry_run=True))
    assert scan.load_state()["bootstrap_complete"] is False
    assert client.download_calls == 1

    asyncio.run(scan.run(now=started + timedelta(minutes=1), dry_run=True))
    retried_state = scan.load_state()
    assert retried_state["bootstrap_complete"] is True
    assert retried_state["observed_message_id"] == 33681

    asyncio.run(scan.run(now=started + timedelta(minutes=2), dry_run=True))
    state = scan.load_state()
    assert state["observed_message_id"] == 33700
    assert set(state["report_jobs"]) == {"33681", "33700"}
