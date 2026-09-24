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
    sent = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, *args: sent.append(content) or "dry-text-40001")
    assert pipeline_owner.submit(work, no_post=True) == "accepted"
    assert len(sent) == 1
    assert "SCMA" in sent[0]
    assert "[View in Telegram]" in sent[0]
    assert pipeline_owner.submit(work, no_post=True) == "accepted"
    assert len(sent) == 1
