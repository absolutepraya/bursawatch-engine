from __future__ import annotations

import hashlib
import pytest

import pipeline_owner
from state import load_state


def test_agent_news_cannot_be_acknowledged_without_classifier_handoff():
    with pytest.raises(ValueError, match="bounded Hermes classifier handoff"):
        pipeline_owner.submit({"pipeline_id": "company_news"})


def test_stock_status_uses_existing_parser_renderer_and_owner_ledger(tmp_path, monkeypatch, load_fixture):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    source = load_fixture("phintraco-stock-status-35377.txt")
    key = "b" * 64
    effect = hashlib.sha256(f"{key}:1:stock_status".encode()).hexdigest()
    work = {"pipeline_id": "stock_status", "capability_id": "stock_status", "version": 1, "event_key": key, "effect_key": effect, "work_key": effect, "envelope": {"endpoint_id": "telegram:phintasprofits", "publisher_id": "phintraco", "provider_event_id": "35377", "source_url": "https://t.me/phintasprofits/35377", "payload": {"text": source}, "media_required": False, "media_refs": []}}
    work["envelope"]["media_required"] = True
    work["envelope"]["media_refs"] = [{"ref": "00000000-0000-4000-8000-000000000053", "sha256": hashlib.sha256(b"source chart").hexdigest(), "kind": "image", "content_type": "image/jpeg", "size_bytes": 12, "filename": "chart.jpg", "durable": True}]
    assert pipeline_owner.submit_stock_status(work, no_post=True) == "accepted"
    record = load_state()["stats"]["stock_status_events"]["phintraco-stock-status:35377"]
    assert record["phase"] == "delivered"
    assert record["content"] == (
        "### <:phintraco:1531272488645038091> Stock Status: Web, Wed, 23 Sep 2026\n\n"
        "**UMA:**\n(None)\n\n"
        "**Suspend In:**\n(None)\n\n"
        "**Suspend Out:**\n- WAPO\n- NASI\n\n"
        "**FCA In:**\n(None)\n\n"
        "**FCA Out:**\n- UNSP\n\n"
        "[View in Telegram](<https://t.me/phintasprofits/35377>)"
    )
    assert pipeline_owner.submit_stock_status(work, no_post=True) == "accepted"
