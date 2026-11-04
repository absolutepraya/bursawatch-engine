from datetime import datetime, timedelta
import json

import pytest

import config
from models import PostKind, SourcePost
import scan
import state
import subject_context


def test_missing_global_destination_is_terminal_without_macro_or_backlog(tmp_path, monkeypatch, config_path, profile_payload):
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
                    "company": {"business_home": "UNKNOWN", "listing_status": "pre_ipo", "security_market": ""}},
    }]}
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
        for index, key in enumerate(("id_stocks_news", "id_industry_news", "macro_news"))
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
