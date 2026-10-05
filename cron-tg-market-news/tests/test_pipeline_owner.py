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


def _news_work(
    capability,
    *,
    enabled=("company_news", "macro_news"),
    endpoint_id="telegram:phintasprofits",
    publisher_id="phintraco",
    source_handle="phintasprofits",
    message_id="35390",
    text="Notes: DEWA secures a Rp22 trillion contract.",
    topic_id=None,
):
    event_key = "a" * 64
    payload = {"text": text}
    if topic_id is not None:
        payload["topic_id"] = topic_id
    envelope = {
        "endpoint_id": endpoint_id,
        "publisher_id": publisher_id,
        "provider_event_id": message_id,
        "published_at": "2026-09-24T03:00:00+00:00",
        "source_url": f"https://t.me/{source_handle}/{message_id}",
        "content_hash": "c" * 64,
        "payload": payload,
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
        "### <:phintraco:1531272488645038091> Phintraco Sekuritas\n-# Phintraco\n\n"
        "*(Ringkasan)* DEWA mendapat kontrak bernilai Rp22 triliun.\n\n"
        "[View on Telegram](<https://t.me/phintasprofits/35390>)"
    )
    assert delivered["channel_id"] == "1531655369884045382"
    assert pipeline_owner.agent_status()["candidates"]["pending_analysis"] == 0


def test_tuntun_corporate_source_work_accepts_all_ticker_candidates_once(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    corporate = (
        "Corporate 🏢\n\n"
        "DEWA (PT Darma Henwa Tbk): DEWA mendapat kontrak baru.\n\n"
        "PTBA (PT Bukit Asam Tbk): PTBA meningkatkan volume produksi."
    )
    company, company_inspection = _news_work(
        "company_news", endpoint_id="telegram:tuntunsekuritas", publisher_id="tuntun",
        source_handle="tuntunsekuritas", message_id="14980", text=corporate, topic_id=3743,
    )
    macro, macro_inspection = _news_work(
        "macro_news", endpoint_id="telegram:tuntunsekuritas", publisher_id="tuntun",
        source_handle="tuntunsekuritas", message_id="14980", text=corporate, topic_id=3743,
    )

    assert pipeline_owner.submit(company, no_post=True, inbox=_Inbox(company_inspection)) == "accepted"
    assert pipeline_owner.submit(macro, no_post=True, inbox=_Inbox(macro_inspection)) == "accepted"

    state = load_state()
    assert set(state["candidates"]) == {"tuntun:14980:DEWA", "tuntun:14980:PTBA"}
    for candidate_key in state["candidates"]:
        origin = state["stats"]["news_source_work"][candidate_key]
        assert origin["event_key"] == company["event_key"]
        assert origin["source_url"] == "https://t.me/tuntunsekuritas/14980"
        assert origin["enabled_capabilities"] == ["company_news", "macro_news"]
        assert origin["watch_config"]["providers"]["tuntun"]["telegram_username"] == "tuntunsekuritas"


def test_tuntun_news_owner_ignores_posts_outside_configured_forum_topic(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    work, inspection = _news_work(
        "company_news", endpoint_id="telegram:tuntunsekuritas", publisher_id="tuntun",
        source_handle="tuntunsekuritas", message_id="14981",
        text="Corporate 🏢\n\nDEWA: eligible-looking source entry.", topic_id=1234,
    )

    assert pipeline_owner.submit(work, no_post=True, inbox=_Inbox(inspection)) == "irrelevant"
    assert not (tmp_path / "news.json").exists()


def test_dead_lettered_news_sibling_keeps_enabled_route_and_stable_replay_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    company, first_inspection = _news_work("company_news")
    macro_row = next(row for row in first_inspection["work"] if row["capability_id"] == "macro_news")
    macro_row["status"] = "dead_letter"

    assert pipeline_owner.submit(company, no_post=True, inbox=_Inbox(first_inspection)) == "accepted"
    candidate_key = "phintraco:35390:DEWA"
    initial_state = load_state()
    initial_origin = initial_state["stats"]["news_source_work"][candidate_key]
    assert initial_origin["enabled_capabilities"] == ["company_news", "macro_news"]
    assert scan.route_enabled(initial_state, candidate_key, scan.Destination.MACRO_NEWS)

    replay_inspection = {"event": first_inspection["event"], "work": []}
    for row in first_inspection["work"]:
        replayed = dict(row)
        if replayed["capability_id"] == "company_news":
            replayed.update(status="done", lease_token=None)
        else:
            replayed.update(status="executing", lease_token="lease-replay")
        replay_inspection["work"].append(replayed)
    macro_work = {
        **next(row for row in replay_inspection["work"] if row["capability_id"] == "macro_news"),
        "event_kind": "original",
        "envelope": company["envelope"],
    }
    assert pipeline_owner.submit(macro_work, no_post=True, inbox=_Inbox(replay_inspection)) == "accepted"

    replayed_state = load_state()
    replayed_origin = replayed_state["stats"]["news_source_work"][candidate_key]
    assert replayed_origin["work_keys"] == initial_origin["work_keys"]
    assert replayed_origin["enabled_capabilities"] == initial_origin["enabled_capabilities"]


def test_expired_news_agent_lease_is_visible_then_reclaimed_after_backoff(tmp_path, monkeypatch):
    state_path = tmp_path / "news.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(state_path))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    work, inspection = _news_work("company_news")
    assert pipeline_owner.submit(work, no_post=True, inbox=_Inbox(inspection)) == "accepted"

    now = datetime.now(scan.WIB) + timedelta(seconds=1)
    first = pipeline_owner.claim_agent(now)
    assert first["wakeAgent"] is True
    candidate_key = first["items"][0]["candidate_key"]
    lease_end = datetime.fromisoformat(load_state()["candidates"][candidate_key]["agent_lease_until"])
    assert pipeline_owner.agent_status(lease_end - timedelta(microseconds=1))["ready"] is False

    before = state_path.read_bytes()
    expired = pipeline_owner.agent_status(lease_end)
    assert expired["ready"] is True
    assert expired["event_key"] == work["event_key"]
    assert state_path.read_bytes() == before

    assert pipeline_owner.claim_agent(lease_end) == {"wakeAgent": False, "items": []}
    pending = load_state()["candidates"][candidate_key]
    assert pending["phase"] == "pending_analysis"
    assert pending["retry"]["attempts"] == 1
    retry_at = datetime.fromisoformat(pending["retry"]["next_attempt_at"])
    assert pipeline_owner.agent_status(retry_at - timedelta(microseconds=1))["ready"] is False
    assert pipeline_owner.agent_status(retry_at)["ready"] is True
    reclaimed = pipeline_owner.claim_agent(retry_at)
    assert reclaimed["wakeAgent"] is True
    assert reclaimed["items"][0]["candidate_key"] == candidate_key


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


@pytest.mark.parametrize("source_kind,ticker,category", [
    (scan.SourceKind.CORPORATE_ENTRY, "DEWA", "issuer"),
    (scan.SourceKind.TUNTUN_UPDATE_INDUSTRY, None, "industry"),
    (scan.SourceKind.TUNTUN_UPDATE_SECTION, None, "macro"),
])
def test_native_category_claim_accepts_bound_image_instruction(tmp_path, monkeypatch, source_kind, ticker, category):
    import news_source_work
    from state import empty_state, enqueue_candidate, save_state
    from domain import CompanyCandidate, Provider
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    current = datetime.now(scan.WIB)
    candidate = CompanyCandidate(Provider.TUNTUN, 14980, ticker, source_kind, current, "Kapasitas produksi bertambah.", False, candidate_id="story")
    value = empty_state()
    enqueue_candidate(value, candidate, current)
    news_source_work.put_provenance(value, candidate.key, event_key="a"*64, version=1, content_hash="b"*64,
        source_url="https://t.me/tuntunsekuritas/14980", work_keys={"company_news":"c"*64,"macro_news":"d"*64},
        loaded_config=config.LoadedWatchConfig(config.default_watch_config(), 9),
        summary_media_refs=[{"kind":"image","durable":True,"ref":"opaque","sha256":"e"*64,"size_bytes":1,"content_type":"image/png"}])
    save_state(value)
    wake = pipeline_owner.claim_agent(current + timedelta(seconds=1))
    assert wake["wakeAgent"] is True
    item = wake["items"][0]
    assert item["candidate_key"] == candidate.key
    assert "prepare-summary-images" in item["instruction"]
    if category != "issuer":
        assert f"Selected presentation category: {category}." in item["instruction"]


def test_split_tuntun_image_context_remains_candidate_bound(tmp_path, monkeypatch, load_fixture):
    import base64
    import summary_context
    from bursawatch_source_media import MediaDownload, claim_id
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")
    work, inspection = _news_work("company_news", endpoint_id="telegram:tuntunsekuritas", publisher_id="tuntun",
        source_handle="tuntunsekuritas", message_id="14980", text=load_fixture("tuntun-split-image-context.txt"), topic_id=3743)
    work["envelope"]["media_refs"] = [{"kind":"image","durable":True,"ref":"publication-image",
        "sha256":hashlib.sha256(data).hexdigest(),"size_bytes":len(data),"content_type":"image/png"}]
    assert pipeline_owner.submit(work, no_post=True, inbox=_Inbox(inspection)) == "accepted"
    current = datetime.now(scan.WIB) + timedelta(seconds=1)
    items = [pipeline_owner.claim_agent(current)["items"][0] for _ in range(2)]
    assert {item["ticker"] for item in items} == {"DEWA", "PTBA"}
    claims = [summary_context._load_claim(item["candidate_key"], current, True) for item in items]
    assert claims[0].source_event_key == claims[1].source_event_key
    assert claims[0].refs == claims[1].refs
    assert claim_id(claims[0]) != claim_id(claims[1])
    for item, claim in zip(items, claims):
        other_ticker = "PTBA" if item["ticker"] == "DEWA" else "DEWA"
        assert other_ticker not in item["source_text"]
        assert claim.source_text == item["source_text"]
        assert "do not lift an unrelated company/story from a publication image" in item["instruction"]
        assert "Only after eligible text establishes this story" in item["instruction"]
    calls = []
    class Reader:
        def download(self, key, **kwargs):
            calls.append(key)
            return MediaDownload(data, "image/png", "publication.png", "image", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(summary_context, "_client", Reader)
    request = {"protocol":"summary-images-v1","owner_event_key":claims[1].owner_event_key,
               "claim_id":claim_id(claims[0]),"text_eligible":True,"asset_indexes":[0]}
    assert summary_context.prepare_summary_context(request, now=current, no_post=True)["assets"] == []
    assert calls == []
    request["claim_id"] = claim_id(claims[1])
    request["text_eligible"] = False
    assert summary_context.prepare_summary_context(request, now=current, no_post=True)["assets"] == []
    assert calls == []
    request["text_eligible"] = True
    response = summary_context.prepare_summary_context(request, now=current, no_post=True)
    assert response["status"] == "ready" and calls == ["publication-image"]
    assert response["assets"][0]["association"] == "source publication; only this candidate's supplied story"
