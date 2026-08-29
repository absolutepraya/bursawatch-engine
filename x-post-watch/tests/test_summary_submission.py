import json

import pytest

import scan
import state
from models import PostKind, SourcePost
from datetime import UTC, datetime


def test_submit_title_only_preserves_raw_post_and_quote(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.QUOTE, "https://x.com/a/status/101", "Quoted author: Quoted raw", (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel, dry_run, nonce: sent.append((content, channel)) or "test")

    result = scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": True, "title": "BI: Tiga Indikator untuk Pasar"})

    assert result == {"submitted": True, "delivered": 1}
    assert sent == [("### <:twitter:1531672630602498129> BI: Tiga Indikator untuk Pasar\n-# <:kutekians:1531673483459821729> Almer Sad, CFA\n\nRaw original [View on X](<https://x.com/Kutekians/status/102>)\n> **Quoted author**\n> Quoted raw\n> [View quoted on X](<https://x.com/a/status/101>)", "1531655369884045382")]


def test_submit_summary_validates_then_drains_only_summary_event(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    claimed = state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC))
    assert claimed is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel, dry_run, nonce: sent.append((content, channel)) or "test")

    result = scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": True, "title": "Pasar: Ringkasan Tervalidasi", "summary": "*(Ringkasan)* Ringkasan yang tervalidasi."})

    assert result == {"submitted": True, "delivered": 1}
    assert sent == [("### <:twitter:1531672630602498129> Pasar: Ringkasan Tervalidasi\n-# <:kutekians:1531673483459821729> Almer Sad, CFA\n\n*(Ringkasan)* Ringkasan yang tervalidasi.\n\n[View on X](<https://x.com/Kutekians/status/102>)", "1531655369884045382")]
    assert state.load_state(storage)["outbox"] == []


@pytest.mark.parametrize(
    ("route", "channel", "title"),
    [
        ("id_stock", "1525102508714889257", "MYOR: Uji Rute Saham Indonesia"),
        ("us_stock", "1532266331737686199", "META: Uji Rute Saham AS"),
    ],
)
def test_submit_summary_routes_stock_analysis_to_its_configured_channel(tmp_path, monkeypatch, config_path, profile_payload, route, channel, title):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    profile_payload["enable_llm_routing"] = True
    profile_payload["discord_channels"] = [
        {"key": "macro", "channel_id": "1531655369884045382", "description": "Macro"},
        {"key": "id_stock", "channel_id": "1525102508714889257", "description": "IDX"},
        {"key": "us_stock", "channel_id": "1532266331737686199", "description": "US listed"},
    ]
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel, dry_run, nonce: sent.append((content, channel)) or "test")

    scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": True, "title": title, "summary": "*(Ringkasan)* Ringkasan saham.", "route": route})

    assert sent[0][1] == channel


def test_submit_summary_rejects_invalid_value_without_mutating_state(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC))
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))

    with pytest.raises(ValueError, match="missing"):
        scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": True, "title": "Judul valid yang hilang ringkasan"})

    event = state.load_state(storage)["outbox"][0]
    assert event["agent_phase"] == "awaiting_agent"
    assert event["summary"] is None


def test_submit_irrelevant_analysis_removes_event_without_posting(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    storage = tmp_path / "state.json"
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Pengen survei", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC))
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args))

    assert scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": False}) == {"submitted": True, "ignored": True, "delivered": 0}
    assert sent == []
    assert state.load_state(storage)["outbox"] == []
    assert state.load_state(storage)["filtered_since_last_heartbeat"] == 1


def test_submit_irrelevant_disclosure_is_rejected_and_keeps_agent_event(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    storage = tmp_path / "state.json"
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "$RATU private placement dengan dilusi 9,09%", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC))
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))

    with pytest.raises(ValueError, match="must be relevant"):
        scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": False})

    event = state.load_state(storage)["outbox"][0]
    assert event["agent_phase"] == "awaiting_agent"
