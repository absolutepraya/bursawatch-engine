from datetime import datetime, timedelta
import json

import pytest

import config
from models import PostKind, SourcePost
import scan
import state
import subject_context
import agent_protocol
import news_identity


@pytest.mark.parametrize("name,ticker,market,home,text,expected_ticker", [
    ("Snapchat", "SNAP", "US", "US", "Snapchat stock, $SNAP, falls over -10% after earnings.", "SNAP"),
    ("ASSA", "ASSA", "ID", "ID", "ASSA akan membagikan dividen interim Rp 20/saham.", None),
    ("ASSA", "ASSA", "ID", "ID", "ASSA: akan membagikan dividen interim Rp 20/saham.", None),
])
def test_source_company_identity_survives_submission(name, ticker, market, home, text, expected_ticker, monkeypatch, config_path, profile_payload):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [{"key":key,"channel_id":str(100000000000000001 + i),"description":key} for i,key in enumerate(("id_stocks_news","us_stocks_news","global_company_news"))]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    monkeypatch.setattr(news_identity, "lookup_company", lambda query, selected: {"status":"verified", "ticker":ticker} if query == ticker and selected == market else {"status":"unresolved"})
    route = "us_stocks_news" if home == "US" else "id_stocks_news"
    payload = {"event_key":"source:1", "is_relevant":True, "items":[{"title":ticker + ": Company update", "summary":text, "route":route, "ticker":ticker,
        "subject":{"kind":"company", "name":name, "evidence":text, "company":{"business_home":home, "listing_status":"listed", "security_market":market}}}]}
    result = agent_protocol.validate_submission(profile, payload, subject_required=True, company_required=True, source_text=text)
    assert result["news_items"][0]["route"] == route
    assert result["news_items"][0]["ticker"] == expected_ticker


@pytest.mark.parametrize("ticker,company,text,evidence", [
    ("ROTI", "PT Nippon Indosari Corpindo Tbk", "$ROTI AKAN MUSNAHKAN SAHAM\nSari Roti berencana menarik saham.", "Sari Roti berencana menarik saham."),
])
def test_explicit_stock_reference_without_issuer_stays_text_only(ticker, company, text, evidence, monkeypatch, config_path, profile_payload):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [{"key":key, "channel_id":str(100000000000000001 + i), "description":key} for i,key in enumerate(("id_stocks_news", "us_stocks_news", "global_company_news"))]
    config_path.write_text(json.dumps({"version":1, "profiles":[profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    monkeypatch.setattr(news_identity, "_search", lambda _: [{"symbol":ticker + ".JK", "exchange":"JKT", "quoteType":"EQUITY", "longname":company}])
    payload = {"event_key":"source:1", "is_relevant":True, "items":[{"title":ticker + ": Kabar perusahaan", "summary":evidence,
        "route":"id_stocks_news", "ticker":ticker, "subject":{"kind":"company", "name":ticker, "evidence":evidence,
        "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}]}
    item, = agent_protocol.validate_submission(profile, payload, subject_required=True, company_required=True, source_text=text)["news_items"]
    assert item["ticker"] is None and not item["title"].startswith(ticker + ":")


@pytest.mark.parametrize("industry_region", [None, "US", "GLOBAL"])
def test_missing_global_destination_is_terminal_without_macro_or_backlog(tmp_path, monkeypatch, config_path, profile_payload, industry_region):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True,
                           enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [
        {"key": key, "channel_id": str(100000000000000001 + index), "description": key}
        for index, key in enumerate(("id_stocks_news", "macro_news"))
    ]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    now = datetime.now(scan.WIB)
    text = "Example Business plans an IPO to expand production."
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", now - timedelta(hours=2),
                      text, PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [post], lambda _: True, now=now - timedelta(hours=2))
    storage = tmp_path / "state.json"
    state.save_state(storage, value)
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")
    def no_post(content, channel, dry_run, *_args):
        assert channel == scan.HEARTBEAT_CHANNEL_ID and dry_run is True
        return "synthetic-heartbeat"
    monkeypatch.setattr(scan.discord, "post_text", no_post)
    monkeypatch.setattr(scan.render, "freeze_news", lambda *_args, **_kwargs: pytest.fail("must not prepare undeliverable news"))
    wake = scan.run(now=now, dry_run=True)
    payload = {"event_key": wake["item"]["event_key"], "is_relevant": True, "items": [{
        "title": "Example Business plans an IPO", "summary": text, "route": "global_company_news", "ticker": "",
        "subject": {"kind": "company", "name": "Example Business", "evidence": "Example Business plans an IPO",
                    "company": {"business_home": "GLOBAL", "listing_status": "pre_ipo", "security_market": ""}},
    }]}
    if industry_region:
        payload["items"][0].update(route="us_industry_news" if industry_region == "US" else "global_industry_news",
            subject={"kind":"industry","name":"Production","evidence":text,"industry":{"region":industry_region}})
    result = scan.submit_analysis_payload(payload, dry_run=True)
    assert result["outcome"] == "destination_missing" and result["delivered"] == 0
    saved = state.load_state(storage)
    assert not any(event.get("agent_phase") in {"pending", "awaiting_agent", "ready"} for event in saved["outbox"])


def test_outstanding_v1_subject_context_still_reads(tmp_path):
    event = {"profile_id": "example", "post_id": "101", "agent_lease_until": "2026-11-04T00:00:00+00:00"}
    storage = tmp_path / "state.json"
    subject_context.freeze(storage, event, {"post_text": "Legacy source"})
    event["news_subject_contract"] = "subject-v1"
    assert subject_context.read(storage, event).strip() == "Legacy source"


@pytest.mark.parametrize("source,subject,route,ticker,title", [
    ("US semiconductor sector index fell 5%.",
     {"kind":"industry","name":"Semiconductors","evidence":"US semiconductor sector index fell", "industry":{"region":"US"}},
     "us_industry_news", "", "Volatilitas semikonduktor AS meningkat"),
    ("Malaysian palm oil futures rose 1%.",
     {"kind":"industry","name":"Palm oil","evidence":"Malaysian palm oil futures rose", "industry":{"region":"GLOBAL"}},
     "global_industry_news", "", "Harga CPO Malaysia meningkat"),
    ("ACME memperoleh kontrak baru meski IHSG melemah.",
     {"kind": "company", "name": "ACME", "evidence": "ACME memperoleh kontrak baru", "company": {"business_home": "ID", "listing_status": "private", "security_market": ""}},
     "id_stocks_news", "", "ACME: Memperoleh kontrak baru"),
    ("Biaya pakan industri unggas turun, CPIN dan JPFA menjadi contoh penerima manfaat.",
     {"kind": "industry", "name": "Unggas", "evidence": "Biaya pakan industri unggas turun"},
     "id_industry_news", "", "Biaya pakan unggas menurun"),
    ("Inflasi nasional melandai; BBRI disebut sebagai contoh penerima manfaat.",
     {"kind": "macro", "name": "Inflasi", "evidence": "Inflasi nasional melandai"},
     "macro_news", "", "Inflasi nasional melandai"),
])
def test_claim_validates_subject_and_preserves_route_without_lexical_override(
    tmp_path, monkeypatch, config_path, profile_payload, source, subject, route, ticker, title,
):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True,
                           enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [
        {"key": key, "channel_id": str(100000000000000001 + index), "description": key}
        for index, key in enumerate(("id_stocks_news", "id_industry_news", "macro_news", "us_industry_news", "global_industry_news"))
    ]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    now = datetime(2026, 10, 28, 10, tzinfo=scan.WIB)
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", now - timedelta(hours=2),
                      source, PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [post], lambda _: True, now=now - timedelta(hours=2))
    storage = tmp_path / "state.json"
    state.save_state(storage, value)
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args) or "test")
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")
    monkeypatch.setattr(scan.render.news_format, "get_market_snapshot", lambda *_: pytest.fail("no ticker must not fetch prices"))
    wake = scan.run(now=now, dry_run=True)
    assert wake["wakeAgent"] is True
    assert "lookup-company" in wake["item"]["instruction"]
    claimed = state.load_state(storage)["outbox"][0]
    assert subject_context.read(storage, claimed) is not None
    payload = {"event_key": wake["item"]["event_key"], "is_relevant": True,
               "items": [{"subject": subject, "ticker": ticker, "title": title, "summary": source, "route": route}]}
    wrong = {**payload, "items": [{**payload["items"][0], "route": "id_stocks_news" if route != "id_stocks_news" else "macro_news"}]}
    with pytest.raises(ValueError, match="subject"):
        scan.submit_analysis_payload(wrong, dry_run=True)
    assert state.load_state(storage)["outbox"][0]["agent_phase"] == "awaiting_agent"
    scan.submit_analysis_payload(payload, dry_run=True)
    assert state.load_state(storage)["outbox"] == []
    expected_channel = profile.channel_for(route).channel_id
    assert sent[-1][1] == expected_channel
    assert "Harga terakhir" not in sent[-1][0]
    assert title in sent[-1][0]
    assert not list((tmp_path / "subject-context").glob("*.txt"))


def test_subject_context_rejects_changed_evidence_and_cleans_replaced_lease(tmp_path):
    storage = tmp_path / "state.json"
    event = {"profile_id": "source", "post_id": "1", "agent_lease_until": "lease-1"}
    subject_context.freeze(storage, event, {"post_text": "Original source"})
    path = next((tmp_path / "subject-context").glob("*.txt"))
    path.write_text("Changed source")
    with pytest.raises(ValueError, match="changed"):
        subject_context.read(storage, event)
    event["agent_lease_until"] = "lease-2"
    subject_context.freeze(storage, event, {"post_text": "Fresh source"})
    assert not path.exists()
    assert subject_context.read(storage, event).strip() == "Fresh source"


def test_company_security_cannot_be_submitted_without_source_evidence(config_path):
    from dataclasses import replace
    from agent_protocol import validate_submission
    profile = replace(config.load_watch_config(config_path).profiles[0], enable_llm_title=True,
        enable_llm_summary=True, enable_llm_routing=True)
    payload = {'event_key': profile.id+':102', 'is_relevant': True, 'title': 'Example expands',
        'summary': 'Example expands its business.', 'route': 'global_company_news', 'ticker': 'EXAMPLE',
        'subject': {'kind': 'company', 'name': 'Example', 'evidence': 'Example expands',
                    'company': {'business_home': 'GLOBAL', 'listing_status': 'listed', 'security_market': 'US'}}}
    with pytest.raises(ValueError, match='source evidence'):
        validate_submission(profile, payload)


def test_symbol_named_in_focus_evidence_keeps_its_ticker(monkeypatch, config_path, profile_payload):
    """Forwarder policy: AMMN is named in the focus evidence and Yahoo verifies it, so it keeps its ticker."""
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [{"key":key, "channel_id":str(100000000000000001 + i), "description":key} for i,key in enumerate(("id_stocks_news", "us_stocks_news", "global_company_news"))]
    config_path.write_text(json.dumps({"version":1, "profiles":[profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    text = "PENDAPATAN AMMN TURUN\nForeign net outflow saham AMMN Rp4,75 triliun."
    evidence = "saham AMMN"
    monkeypatch.setattr(news_identity, "_search", lambda _: [{"symbol":"AMMN.JK", "exchange":"JKT", "quoteType":"EQUITY", "longname":"PT Amman Mineral Internasional Tbk"}])
    payload = {"event_key":"source:1", "is_relevant":True, "items":[{"title":"AMMN: Kabar perusahaan", "summary":evidence,
        "route":"id_stocks_news", "ticker":"AMMN", "subject":{"kind":"company", "name":"AMMN", "evidence":evidence,
        "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}]}
    item, = agent_protocol.validate_submission(profile, payload, subject_required=True, company_required=True, source_text=text)["news_items"]
    assert item["ticker"] == "AMMN" and item["title"].startswith("AMMN:")


def _single_market_scan(tmp_path, monkeypatch, config_path, profile_payload, keys):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [{"key": key, "channel_id": str(100000000000000001 + index), "description": key} for index, key in enumerate(keys)]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    now = datetime.now(scan.WIB)
    text = "BNI Mobile Banking beralih ke Wondr by BNI secara bertahap."
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", now - timedelta(hours=2), text, PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [post], lambda _: True, now=now - timedelta(hours=2))
    storage = tmp_path / "state.json"
    state.save_state(storage, value)
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel, dry_run, *_a: "synthetic-heartbeat")
    wake = scan.run(now=now, dry_run=True)
    return profile, wake, text


@pytest.mark.parametrize("home,outcome_is_missing", [("UNKNOWN", False), ("GLOBAL", True)])
def test_single_market_account_receives_uncertain_company_news_but_not_a_truthful_foreign_call(tmp_path, monkeypatch, config_path, profile_payload, home, outcome_is_missing):
    profile, wake, text = _single_market_scan(tmp_path, monkeypatch, config_path, profile_payload, ("id_stocks_news", "id_industry_news", "macro_news"))
    seen = []
    real = scan.render.freeze_news
    monkeypatch.setattr(scan.render, "freeze_news", lambda prof, post, items, **kw: seen.append([(i["route"], i["subject"]["company"]["business_home"]) for i in items]) or real(prof, post, items, **kw))
    payload = {"event_key": wake["item"]["event_key"], "is_relevant": True, "items": [{
        "title": "BNI Mobile Banking beralih ke Wondr", "summary": text, "route": "global_company_news", "ticker": "",
        "subject": {"kind": "company", "name": "BNI", "evidence": "BNI Mobile Banking beralih ke Wondr by BNI",
                    "company": {"business_home": home, "listing_status": "listed", "security_market": ""}}}]}
    result = scan.submit_analysis_payload(payload, dry_run=True)
    if outcome_is_missing:
        assert result["outcome"] == "destination_missing" and not seen
    else:
        assert result.get("outcome") != "destination_missing" and seen == [[("id_stocks_news", "ID")]]


@pytest.mark.parametrize("name,ticker,text,evidence,lookup,title", [
    # Live 11 Nov: an uncertain IDX symbol Yahoo does not know was posted bare, with no `META:` and no tracker.
    ("META", "", "Hari ini cum date dividen interim IFII (Rp 5), MIDI (Rp 3,8) dan META (Rp 3,5).", "META (Rp 3,5)",
     {"status": "unresolved", "reason": "no_match"}, "Cum date dividen interim berlangsung hari ini"),
    # Live 11 Nov: Yahoo verified ITMG.JK, yet the uncertain call left no ticker and no price block.
    ("Indo Tambangraya Megah", "ITMG", "Indo Tambangraya Megah (ITMG) Raup Rp 28 Triliun", "Indo Tambangraya Megah (ITMG) Raup Rp 28 Triliun",
     {"status": "verified", "ticker": "ITMG"}, "Raup Rp28 triliun"),
])
def test_uncertain_company_snapped_to_the_only_market_is_treated_as_a_native_one(monkeypatch, config_path, profile_payload, name, ticker, text, evidence, lookup, title):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True, enable_llm_relevance_filter=True)
    profile_payload["discord_channels"] = [{"key": key, "channel_id": str(100000000000000001 + i), "description": key} for i, key in enumerate(("macro_news", "id_stocks_news", "id_industry_news"))]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}))
    profile = config.load_watch_config(config_path).profiles[0]
    monkeypatch.setattr(news_identity, "lookup_company", lambda query, market: {**lookup, "company": query, "market": market})
    payload = {"event_key": "source:1", "is_relevant": True, "items": [{"title": title, "summary": evidence, "route": "global_company_news", "ticker": ticker,
        "subject": {"kind": "company", "name": name, "evidence": evidence,
                    "company": {"business_home": "UNKNOWN", "listing_status": "listed", "security_market": ""}}}]}
    item, = agent_protocol.validate_submission(profile, payload, subject_required=True, company_required=True, source_text=text)["news_items"]
    assert item["route"] == "id_stocks_news" and item["subject"]["company"]["business_home"] == "ID"
    assert item["subject"]["company"]["security_market"] == "ID"
    assert item["ticker"] == (ticker or name) and item["title"] == title


def _rejected_payload(wake, text):
    """A relevant macro item whose evidence is a paraphrase, so the quote check rejects it."""
    return {"event_key": wake["item"]["event_key"], "is_relevant": True, "items": [{
        "title": "BNI beralih ke Wondr", "summary": text, "route": "macro_news", "ticker": "",
        "subject": {"kind": "macro", "name": "Perbankan", "evidence": "BNI Mobile Banking is moving to Wondr"}}]}


def test_rejections_are_counted_explained_to_the_next_agent_and_capped(tmp_path, monkeypatch, config_path, profile_payload):
    import agent_feedback
    profile, wake, text = _single_market_scan(tmp_path, monkeypatch, config_path, profile_payload, ("id_stocks_news", "id_industry_news", "macro_news"))
    payload = _rejected_payload(wake, text)
    storage = tmp_path / "state.json"

    with pytest.raises(agent_feedback.AgentRejection) as first:
        scan.submit_analysis_payload(payload, dry_run=True)
    assert first.value.attempts == 1 and first.value.final is False and "character for character" in first.value.guidance
    report = scan.cli_error_report(first.value)
    assert report["error"].startswith("subject evidence must be quoted") and report["attempt"] == 1
    assert report["attempts_allowed"] == 3 and report["final"] is False and "Bursa Efek Indonesia (BEI)" in report["fix"]

    event, = state.load_state(storage)["outbox"]
    assert event["agent_rejections"] == 1 and event["agent_last_rejection"] == first.value.guidance

    # The lease ends, the item is claimed again, and the next agent is told what to fix.
    value = state.load_state(storage)
    value["outbox"][0]["agent_lease_until"] = "2000-01-01T00:00:00+00:00"
    state.save_state(storage, value)
    again = scan.run(now=datetime.now(scan.WIB), dry_run=True)
    assert again["item"]["event_key"] == wake["item"]["event_key"]
    assert "Scanner note: your previous submission for this item was rejected (1 of 3 allowed)" in again["item"]["instruction"]
    assert first.value.guidance in again["item"]["instruction"]

    with pytest.raises(agent_feedback.AgentRejection) as second:
        scan.submit_analysis_payload(payload, dry_run=True)
    assert second.value.attempts == 2 and second.value.final is False
    with pytest.raises(agent_feedback.AgentRejection) as third:
        scan.submit_analysis_payload(payload, dry_run=True)
    assert third.value.attempts == 3 and third.value.final is True
    assert scan.cli_error_report(third.value)["fix"].endswith("This item has now been skipped. Stop.")
    assert state.load_state(storage)["outbox"] == []              # skipped for good, not re-claimed forever


def test_cli_error_report_adds_a_fix_only_for_rejections():
    assert scan.cli_error_report(ValueError("title must be a plain headline without a link or ending punctuation"))["fix"].startswith("Remove any link")
    assert "fix" not in scan.cli_error_report(RuntimeError("delivery failed"))
    assert len(scan.cli_error_report(ValueError("x " * 400))["error"]) <= 180
