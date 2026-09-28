from __future__ import annotations

import hashlib
from types import SimpleNamespace
from pathlib import Path
from datetime import date

import pytest

import pipeline_owner
import scan


def _configured_owner(monkeypatch):
    configured = scan.config.WatchConfig(
        1444713822,
        "phintraprofits",
        "123456789012345678",
        "1505162000420835388",
    )
    monkeypatch.setattr(
        scan.config,
        "load_watch_config_for_run",
        lambda: scan.config.LoadedWatchConfig(configured, 17),
    )


def _source_work(message_id, payload, *, media_refs=(), key_char="d", published_at="2026-09-28T06:05:33+00:00"):
    event_key = key_char * 64
    effect_key = hashlib.sha256(f"{event_key}:1:trading_plans".encode()).hexdigest()
    return {
        "pipeline_id": "swing_plan",
        "capability_id": "trading_plans",
        "event_key": event_key,
        "version": 1,
        "effect_key": effect_key,
        "work_key": effect_key,
        "envelope": {
            "endpoint_id": "telegram:phintraprofits",
            "publisher_id": "phintraco",
            "provider_event_id": str(message_id),
            "published_at": published_at,
            "payload": payload,
            "media_required": bool(media_refs),
            "media_refs": list(media_refs),
        },
    }


def _weekly_setup():
    return SimpleNamespace(
        ticker="KETR",
        descriptor="On support",
        trend="Uptrend",
        ma_indicator="Below, Bull tendency",
        potential_upside="6%-11%",
        potential_downside="-4%",
        entry=">=940",
        stop_loss="<900",
        targets=(scan.PriceTarget(1, "1000"), scan.PriceTarget(2, "1050")),
        page_number=1,
        section_number=1,
        chart_bytes=b"\xff\xd8\xffketr-chart",
    )


def test_text_plan_uses_existing_owner_and_exact_render(tmp_state, monkeypatch):
    text = (Path(__file__).parent / "fixtures" / "trading_buy.txt").read_text()
    key = "a" * 64
    effect = hashlib.sha256(f"{key}:1:trading_plans".encode()).hexdigest()
    work = {"pipeline_id": "swing_plan", "capability_id": "trading_plans", "event_key": key, "version": 1, "effect_key": effect, "work_key": effect, "envelope": {"endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "provider_event_id": "40001", "published_at": "2026-07-10T00:00:00+00:00", "payload": {"text": text}, "media_required": False, "media_refs": []}}
    route = "123456789012345678"
    configured = scan.config.WatchConfig(1444713822, "phintraprofits", route, "1505162000420835388")
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda: scan.config.LoadedWatchConfig(configured, 17))
    sent = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, *args: sent.append((content, channel_id)) or "dry-text-40001")
    assert pipeline_owner.submit(work, no_post=True) == "accepted"
    assert len(sent) == 1
    assert sent[0] == (
        "### <:phintraco:1531272488645038091> SCMA: Buy\n"
        "-# Alrich Paskalis T, Phintraco Sekuritas\n\n"
        "**Type:** Trading Buy <:up:1531285100346740766>\n"
        "**Entry:** 208 to 212\n"
        "**Stop-loss:** <200\n"
        "**Target:** 230\n"
        "**Signal date:** 10 Jul 2026 07:00 WIB\n\n"
        "**Reasons:** Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. MACD yang konsisten membentuk histogram positif sejalan dengan peluang tersebut.\n"
        "**Chart:** Unavailable from source\n\n"
        "**Source status:** New setup <:grey:1531279158913536182>\n"
        "**Last updated:** 10 Jul 2026 07:00 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View in Telegram](<https://t.me/phintraprofits/40001>)",
        route,
    )
    assert pipeline_owner.submit(work, no_post=True) == "accepted"
    assert len(sent) == 1


def test_chart_plan_downloads_durable_ref_into_existing_owner_path(tmp_state, monkeypatch):
    text = (Path(__file__).parent / "fixtures" / "trading_buy.txt").read_text()
    key = "c" * 64
    effect = hashlib.sha256(f"{key}:1:trading_plans".encode()).hexdigest()
    chart = b"\xff\xd8\xffdurable-chart"
    ref = {"ref": "00000000-0000-4000-8000-000000000041", "sha256": hashlib.sha256(chart).hexdigest(), "kind": "image", "content_type": "image/jpeg", "size_bytes": len(chart), "filename": "chart.jpg", "durable": True}
    work = {"pipeline_id": "swing_plan", "capability_id": "trading_plans", "event_key": key, "version": 1, "effect_key": effect, "work_key": effect, "envelope": {"endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "provider_event_id": "40002", "published_at": "2026-07-10T00:00:00+00:00", "payload": {"text": text, "media_ref_ids": [ref["ref"]]}, "media_required": True, "media_refs": [ref]}}
    configured = scan.config.WatchConfig(1444713822, "phintraprofits", "123456789012345678", "1505162000420835388")
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda: scan.config.LoadedWatchConfig(configured, 17))

    class MediaStore:
        def download(self, stored_ref):
            assert stored_ref == ref["ref"]
            return SimpleNamespace(data=chart, content_type="image/jpeg", filename="chart.jpg")

    delivered_files = []
    board_events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *args: "dry-text-40002")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, *args: delivered_files.append(Path(path).read_bytes()) or "dry-chart-40002")
    monkeypatch.setattr(scan, "submit_board_event", lambda payload, path, dry_run: board_events.append((payload.copy(), Path(path).read_bytes() if path else None, dry_run)) or True)

    assert pipeline_owner.submit(work, no_post=True, media_store=MediaStore()) == "accepted"
    assert delivered_files == [chart]
    assert len(board_events) == 1
    assert board_events[0][1:] == (chart, True)
    assert board_events[0][0]["media_path"].endswith("phintraco-40002.jpg")


def test_active_owner_ingests_pdf_then_links_updates_without_reading_caption(tmp_state, monkeypatch):
    _configured_owner(monkeypatch)
    content = b"%PDF-1.7 synthetic weekly report"
    filename = "PHINTAS Weekly Swing Trading Ideas_20260928.pdf"
    reference = {
        "ref": "00000000-0000-4000-8000-000000000048",
        "sha256": hashlib.sha256(content).hexdigest(),
        "kind": "document",
        "content_type": "application/pdf",
        "size_bytes": len(content),
        "filename": filename,
        "durable": True,
    }

    class MediaStore:
        def __init__(self):
            self.downloaded = []

        def download(self, stored_ref):
            self.downloaded.append(stored_ref)
            return SimpleNamespace(
                data=content,
                content_type="application/pdf",
                filename=filename,
            )

    media_store = MediaStore()
    parsed = []

    def parse_pdf(received_filename, received_content):
        parsed.append((received_filename, received_content))
        return SimpleNamespace(
            report_date=date(2026, 9, 28),
            setups=(_weekly_setup(),),
            quarantined_pages=(),
        )

    monkeypatch.setattr(scan, "parse_weekly_pdf", parse_pdf, raising=False)
    delivered = []

    def drain(state, now, *, dry_run):
        for key, event in list(state["outbox"].items()):
            call = scan.deserialize_call(event["call"])
            payload, _ = scan.board_event_payload(event, call)
            delivered.append(payload)
            state["outbox"].pop(key)
        scan.save_state(state)

    monkeypatch.setattr(scan, "drain_outbox", drain)
    caption = (Path(__file__).parent / "fixtures" / "trading_buy.txt").read_text()
    pdf_work = _source_work(
        35448,
        {"text": caption, "media_ref_ids": [], "reply_to_message_id": None},
        media_refs=[reference],
    )

    assert pipeline_owner.submit(pdf_work, no_post=True, media_store=media_store) == "accepted"
    assert media_store.downloaded == [reference["ref"]]
    assert parsed == [(filename, content)]
    assert [item["ticker"] for item in delivered] == ["KETR"]
    assert delivered[0]["event_key"] == "phintraco:1444713822:weekly:35448:KETR"
    state = scan.load_state()
    assert list(state["source_plans"]) == ["pdf:35448:KETR"]
    assert state["pdf_batches"]["35448"]["event_keys"] == ["pdf:35448:KETR"]

    # The owner effect receipt makes a repeated source claim idempotent.
    assert pipeline_owner.submit(pdf_work, no_post=True, media_store=media_store) == "accepted"
    assert media_store.downloaded == [reference["ref"]]
    assert len(parsed) == 1

    reply_parent = {
        "message_id": 35447,
        "text": "weekly companion text is not plan data",
        "published_at": "2026-09-27T23:05:29+00:00",
        "has_photo": False,
    }
    reminder_text = (
        "KETR - First target 1000 achieved\n"
        "Target 3: 1100\n\n"
        "By PHINTRACO SEKURITAS"
    )
    reminder_work = _source_work(
        35461,
        {
            "text": reminder_text,
            "media_ref_ids": [],
            "reply_to_message_id": 35447,
            "reply_parent": reply_parent,
        },
        key_char="e",
        published_at="2026-09-28T06:20:00+00:00",
    )
    assert pipeline_owner.submit(reminder_work, no_post=True) == "accepted"
    reminder = next(item for item in delivered if item["event_key"] == "phintraco:1444713822:35461")
    assert reminder["kind"] == "reminder"
    assert reminder["matched_setup_event_key"] == "phintraco:1444713822:weekly:35448:KETR"

    reply_text = "KETR on track"
    status_work = _source_work(
        35462,
        {
            "text": reply_text,
            "media_ref_ids": [],
            "reply_to_message_id": 35448,
            "reply_parent": {
                "message_id": 35448,
                "text": "",
                "published_at": "2026-09-27T23:05:33+00:00",
                "has_photo": False,
            },
        },
        key_char="f",
        published_at="2026-09-28T06:25:00+00:00",
    )
    assert pipeline_owner.submit(status_work, no_post=True) == "accepted"
    linked_status = next(item for item in delivered if item["event_key"] == "phintraco:1444713822:35462")
    assert linked_status["kind"] == "status"
    assert linked_status["matched_setup_event_key"] == "phintraco:1444713822:weekly:35448:KETR"

    unmatched_work = _source_work(
        35463,
        {
            "text": reminder_text.replace("1000", "999").replace("1100", "1110"),
            "media_ref_ids": [],
            "reply_to_message_id": 35447,
            "reply_parent": reply_parent,
        },
        key_char="a",
        published_at="2026-09-28T06:30:00+00:00",
    )
    assert pipeline_owner.submit(unmatched_work, no_post=True) == "accepted"
    unmatched = next(item for item in delivered if item["event_key"] == "phintraco:1444713822:35463")
    assert unmatched["kind"] == "context"
    assert "matched_setup_event_key" not in unmatched
    assert unmatched["plan"] is None


def test_active_owner_keeps_quarantined_pdf_work_degraded(tmp_state, monkeypatch):
    _configured_owner(monkeypatch)
    content = b"%PDF-1.7 synthetic weekly report"
    filename = "PHINTAS Weekly Swing Trading Ideas_20260928.pdf"
    reference = {
        "ref": "00000000-0000-4000-8000-000000000049",
        "sha256": hashlib.sha256(content).hexdigest(),
        "kind": "document",
        "content_type": "application/pdf",
        "size_bytes": len(content),
        "filename": filename,
        "durable": True,
    }

    class MediaStore:
        def download(self, stored_ref):
            return SimpleNamespace(
                data=content,
                content_type="application/pdf",
                filename=filename,
            )

    monkeypatch.setattr(
        scan,
        "parse_weekly_pdf",
        lambda *_: SimpleNamespace(
            report_date=date(2026, 9, 28),
            setups=(_weekly_setup(),),
            quarantined_pages=(
                SimpleNamespace(page_number=2, reason="chart association is ambiguous"),
            ),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        scan,
        "drain_outbox",
        lambda state, now, *, dry_run: [state["outbox"].pop(key) for key in list(state["outbox"])],
    )
    work = _source_work(
        35448,
        {"text": "ignored caption", "media_ref_ids": [], "reply_to_message_id": None},
        media_refs=[reference],
    )

    with pytest.raises(pipeline_owner.OwnerPending, match="held or pending"):
        pipeline_owner.submit(work, no_post=True, media_store=MediaStore())
    assert scan.load_state()["pdf_batches"]["35448"]["status"] == "degraded"
    assert not pipeline_owner._receipt_path(work["effect_key"]).exists()


def test_owner_rejects_missing_effective_live_config_before_state_or_delivery(tmp_state, monkeypatch):
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda: scan.config.LoadedWatchConfig(scan.config.default_watch_config(), None))
    monkeypatch.setattr(scan, "load_state", lambda: (_ for _ in ()).throw(AssertionError("state opened")))
    import pytest
    with pytest.raises(ValueError, match="effective live watch config"):
        pipeline_owner.submit({}, no_post=True)


def test_owner_rejects_source_mismatch_before_state_or_delivery(tmp_state, monkeypatch):
    configured = scan.config.WatchConfig(1444713823, "phintraprofits", "123456789012345678", "1505162000420835388")
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda: scan.config.LoadedWatchConfig(configured, 17))
    monkeypatch.setattr(scan, "load_state", lambda: (_ for _ in ()).throw(AssertionError("state opened")))
    import pytest
    with pytest.raises(ValueError, match="canonical endpoint"):
        pipeline_owner.submit({}, no_post=True)
