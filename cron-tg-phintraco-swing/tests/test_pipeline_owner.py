from __future__ import annotations

import hashlib
from types import SimpleNamespace
from pathlib import Path

import pipeline_owner
import scan


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
