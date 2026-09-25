from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

import pipeline_owner
import scan
import config
from state import load_state


def _news_work(capability, *, enabled=("company_news", "macro_news")):
    event_key = "a" * 64
    envelope = {
        "endpoint_id": "telegram:phintasprofits",
        "publisher_id": "phintraco",
        "provider_event_id": "35390",
        "published_at": "2026-09-24T03:00:00+00:00",
        "source_url": "https://t.me/phintasprofits/35390",
        "content_hash": "c" * 64,
        "payload": {"text": "Notes: DEWA secures a Rp22 trillion contract."},
        "media_required": False,
        "media_refs": [],
    }
    rows = []
    for item in enabled:
        key = hashlib.sha256(f"{event_key}:1:{item}".encode()).hexdigest()
        rows.append({
            "work_key": key, "effect_key": key, "event_key": event_key,
            "version": 1, "capability_id": item, "pipeline_id": item,
            "catalog_revision": 7, "settings": {},
            "status": "executing" if item == capability else "pending",
            "lease_token": "lease-1" if item == capability else None,
        })
    chosen = next(row for row in rows if row["capability_id"] == capability)
    work = {**chosen, "event_kind": "original", "envelope": envelope}
    return work, {"event": {"event_key": event_key, "versions": [{"version": 1, "envelope": envelope}]}, "work": rows}


class _Inbox:
    def __init__(self, inspection):
        self.inspection = inspection

    def inspect(self, key):
        assert key == self.inspection["event"]["event_key"]
        return self.inspection


def test_phintraco_news_sibling_work_claims_one_frozen_agent_item_and_renders_golden(tmp_path, monkeypatch):
    state_path = tmp_path / "news.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(state_path))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    frozen = replace(config.default_watch_config(), additional_prompt_instruction="Preserve exact source periods.")
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: config.LoadedWatchConfig(frozen, 9))
    company, first_inspection = _news_work("company_news")
    macro, second_inspection = _news_work("macro_news")
    assert pipeline_owner.submit(company, no_post=True, inbox=_Inbox(first_inspection)) == "accepted"
    assert pipeline_owner.submit(macro, no_post=True, inbox=_Inbox(second_inspection)) == "accepted"
    state = load_state()
    assert list(state["candidates"]) == ["phintraco:35390:DEWA"]
    origin = state["stats"]["news_source_work"]["phintraco:35390:DEWA"]
    assert origin["enabled_capabilities"] == ["company_news", "macro_news"]
    before = state_path.read_bytes()
    now = datetime.now(scan.WIB) + timedelta(seconds=1)
    status = pipeline_owner.agent_status(now)
    assert status["ready"] is True
    assert status["event_key"] == company["event_key"]
    assert status["published_at"] == company["envelope"]["published_at"]
    assert status["candidates"]["pending_analysis"] == 1
    assert state_path.read_bytes() == before
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: (_ for _ in ()).throw(AssertionError("config was refetched")))
    wake = pipeline_owner.claim_agent(now)
    assert wake["wakeAgent"] is True and len(wake["items"]) == 1
    item = wake["items"][0]
    assert item["candidate_key"] == "phintraco:35390:DEWA"
    assert item["source_text"] == company["envelope"]["payload"]["text"]
    assert "Preserve exact source periods." in item["instruction"]
    assert pipeline_owner.claim_agent(now) == {"wakeAgent": False, "items": []}
    claimed_status = pipeline_owner.agent_status(now)
    assert claimed_status["ready"] is False and claimed_status["event_key"] is None
    payload = {
        "candidate_key": item["candidate_key"], "ticker": item["ticker"],
        "event_class": "material_contract", "summary": "DEWA mendapat kontrak bernilai Rp22 triliun.",
        "material_facts": ["Kontrak DEWA bernilai Rp22 triliun."],
        "ranking_band": 1, "dedupe_facts": ["DEWA kontrak Rp22 triliun"],
        "eligible": True, "route": "macro_news",
        "source_evidence": "Pesan Phintraco menyebut kontrak DEWA bernilai Rp22 triliun.",
    }
    result = asyncio.run(scan.submit_classification_payload(payload, now + timedelta(seconds=30)))
    assert result["news_delivered"] == 1
    delivered = load_state()["stats"]["delivery_payloads"][item["candidate_key"]]
    assert delivered["content"] == (
        "### <:phintraco:1531272488645038091> Phintraco Sekuritas\n\n"
        "*(Ringkasan)* DEWA mendapat kontrak bernilai Rp22 triliun.\n\n"
        "[View on Telegram](<https://t.me/phintasprofits/35390>)"
    )
    assert delivered["channel_id"] == "1531655369884045382"
    assert pipeline_owner.agent_status()["candidates"]["pending_analysis"] == 0


def test_company_only_subscription_suppresses_a_macro_route(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    work, inspection = _news_work("company_news", enabled=("company_news",))
    assert pipeline_owner.submit(work, no_post=True, inbox=_Inbox(inspection)) == "accepted"
    now = datetime.now(scan.WIB) + timedelta(seconds=1)
    item = pipeline_owner.claim_agent(now)["items"][0]
    payload = {
        "candidate_key": item["candidate_key"], "ticker": item["ticker"],
        "event_class": "material_contract", "summary": "DEWA mendapat kontrak bernilai Rp22 triliun.",
        "material_facts": ["Kontrak DEWA bernilai Rp22 triliun."],
        "ranking_band": 1, "dedupe_facts": ["DEWA kontrak Rp22 triliun"],
        "eligible": True, "route": "macro_news",
        "source_evidence": "Pesan Phintraco menyebut kontrak DEWA bernilai Rp22 triliun.",
    }
    assert asyncio.run(scan.submit_classification_payload(payload, now + timedelta(seconds=30)))["news_delivered"] == 0
    state = load_state()
    assert state["candidates"][item["candidate_key"]]["phase"] == "suppressed_ineligible"
    assert item["candidate_key"] not in state["stats"].get("delivery_payloads", {})


def test_news_source_work_requires_begun_same_version_sibling_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    work, inspection = _news_work("company_news")
    inspection["work"][0]["status"] = "leased"
    with pytest.raises(ValueError, match="has not begun"):
        pipeline_owner.submit(work, no_post=True, inbox=_Inbox(inspection))
    assert not (tmp_path / "news.json").exists()


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
