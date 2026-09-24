from __future__ import annotations

import hashlib
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
