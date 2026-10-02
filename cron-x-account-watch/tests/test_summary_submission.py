import json

import pytest

import scan
import state
from models import PostKind, SourcePost
from datetime import UTC, datetime


def test_submit_title_only_preserves_raw_post_and_quote(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["show_quoted_post"] = True
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


def test_submit_irrelevant_analysis_removes_its_private_vision_cache(tmp_path, monkeypatch, config_path, profile_payload):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Non-market post", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    cache = storage.parent / "x-post-watch-vision" / profile.id / post.post_id
    cache.mkdir(parents=True)
    (cache / "0.jpg").write_bytes(b"image")
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))

    result = scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": False})

    assert result == {"submitted": True, "ignored": True, "delivered": 0}
    assert not cache.exists()


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
        ("id_stocks_news", "1525102508714889257", "MYOR: Uji Rute Saham Indonesia"),
        ("id_stocks_swing", "1525102458253217803", "BBNI: Uji Rute Swing Indonesia"),
        ("us_stocks_news", "1532266331737686199", "META: Uji Rute Saham AS"),
    ],
)
def test_submit_summary_routes_stock_analysis_to_its_configured_channel(tmp_path, monkeypatch, config_path, profile_payload, route, channel, title):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    profile_payload["enable_llm_routing"] = True
    profile_payload["discord_channels"] = [
        {"key": "macro_news", "channel_id": "1531655369884045382", "description": "Macro"},
        {"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"},
        {"key": "id_stocks_swing", "channel_id": "1525102458253217803", "description": "IDX swing"},
        {"key": "us_stocks_news", "channel_id": "1532266331737686199", "description": "US listed"},
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


def test_submit_summary_overrides_clear_txth_route_with_deterministic_route(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload.update({
        "id": "txthariansaham",
        "profile_url": "https://x.com/txthariansaham",
        "handle": "txthariansaham",
        "display_name": "Ga Cuan Ga tidur",
        "enable_llm_title": True,
        "enable_llm_summary": True,
        "enable_llm_routing": True,
        "discord_channels": [
            {"key": "macro_news", "channel_id": "1531655369884045382", "description": "Macro"},
            {"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"},
            {"key": "id_stocks_swing", "channel_id": "1525102458253217803", "description": "IDX swing"},
        ],
    })
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "2091763719059747023", "https://x.com/txthariansaham/status/2091763719059747023", datetime.now(UTC), "BBRI breakout resistance pada chart harian, dengan entry dan stop-loss.", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "2091763719059747022"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, channel, dry_run, nonce: sent.append((content, channel)) or "test")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)

    result = scan.submit_analysis_payload({
        "event_key": f"{profile.id}:{post.post_id}",
        "is_relevant": True,
        "title": "BBRI: Chart Harian Menunjukkan Breakout",
        "summary": "*(Ringkasan)* Breakout resistance dengan entry dan stop-loss.",
        "route": "id_stocks_news",
    })

    assert result == {"submitted": True, "delivered": 1}
    assert sent[0][1] == "1525102458253217803"


def test_submit_summary_accepts_profile_specific_noise_when_llm_marks_it_relevant(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload.update({
        "id": "aldotjahjadi8",
        "profile_url": "https://x.com/aldotjahjadi8",
        "handle": "aldotjahjadi8",
        "display_name": "IHSG Journal",
        "enable_llm_title": True,
        "enable_llm_summary": True,
        "enable_llm_routing": True,
        "discord_channels": [
            {"key": "macro_news", "channel_id": "1531655369884045382", "description": "Macro"},
            {"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"},
        ],
    })
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "2092189697150005608", "https://x.com/aldotjahjadi8/status/2092189697150005608", datetime.now(UTC), "Pelajaran dari rekam jejak investasi Stanley Druckenmiller: 30% annual returns selama 30 tahun dan no losing years.", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "2092189062409195602"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args) or "test")

    result = scan.submit_analysis_payload({
        "event_key": f"{profile.id}:{post.post_id}",
        "is_relevant": True,
        "title": "Druckenmiller: Rekam Jejak Investasi",
        "summary": "*(Ringkasan)* Rekam jejak investasi.",
        "route": "macro_news",
    })

    assert result == {"submitted": True, "delivered": 1}
    assert sent
    assert state.load_state(storage)["outbox"] == []


@pytest.mark.parametrize(
    "text",
    [
        "AI memangkas pekerjaan tiga hari menjadi setengah hari dan mengembalikan waktu untuk berpikir, belajar, dan berefleksi.",
        "Persentase menjadi bahasa universal dalam trading untuk membandingkan perubahan harga dan kinerja.",
    ],
)
def test_submit_accepts_generic_non_stock_or_trading_education_when_agent_marks_relevant(tmp_path, monkeypatch, config_path, profile_payload, text):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), text, PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC))
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args) or "test")

    result = scan.submit_analysis_payload({
        "event_key": "kutekians:102",
        "is_relevant": True,
        "title": "Tidak boleh diteruskan",
    })

    assert result == {"submitted": True, "delivered": 1}
    assert sent
    assert state.load_state(storage)["outbox"] == []


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

    monkeypatch.setattr(scan.discord, "post_text", lambda *args: pytest.fail("irrelevant content was forwarded"))
    result = scan.submit_analysis_payload({"event_key": "kutekians:102", "is_relevant": False})
    assert result["ignored"] is True
    assert state.load_state(storage)["outbox"] == []


def test_submit_ignores_kobeissi_publication_notice_without_posting(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload.update({
        "id": "kobeissiletter",
        "profile_url": "https://x.com/KobeissiLetter",
        "handle": "KobeissiLetter",
        "relevance_scope": "financial_market",
        "enable_llm_title": True,
    })
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    storage = tmp_path / "state.json"
    post = SourcePost(
        profile.id,
        "2094130531256390123",
        "https://x.com/KobeissiLetter/status/2094130531256390123",
        datetime.now(UTC),
        "The Kobeissi Letter for the week of August 31st has been published and may be viewed through the link below. "
        "https://tinyurl.com/TheKobeissiLetter The Chart of the Week for the week of August 31st has been published. "
        "View or sign up for FREE through the link below. https://tinyurl.com/TKLChartofWeek",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "2094130531256390122"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args))

    result = scan.submit_analysis_payload({
        "event_key": "kobeissiletter:2094130531256390123",
        "is_relevant": False,
    })

    assert result == {"submitted": True, "ignored": True, "delivered": 0}
    assert sent == []
    assert state.load_state(storage)["outbox"] == []


def test_submit_accepts_promotional_post_when_agent_marks_it_relevant(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    profile_payload["enable_llm_routing"] = True
    profile_payload["discord_channels"].append({"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"})
    storage = tmp_path / "state.json"
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "102",
        "https://x.com/Kutekians/status/102",
        datetime.now(UTC),
        "Product is live. CA: 0xfc861e02605addab95d8e6b8e662100e987cb9aa. Hold $INSIDER and unlock benefits. 80% of revenue will be used to buy back $INSIDER.",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.observe_posts(value, profile, [post], lambda candidate: True)
    assert state.claim_oldest_agent(value, {profile.id: profile}, datetime.now(UTC)) is not None
    state.save_state(storage, value)
    monkeypatch.setenv("X_POST_WATCH_STATE_PATH", str(storage))
    monkeypatch.setenv("X_POST_WATCH_CONFIG_PATH", str(config_path))
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: sent.append(args) or "test")

    result = scan.submit_analysis_payload({
        "event_key": "kutekians:102",
        "is_relevant": True,
        "title": "Produk Crypto Insider Tracker",
        "summary": "*(Ringkasan)* Produk promosi.",
        "route": "macro_news",
    })

    assert result == {"submitted": True, "delivered": 1}
    assert sent
    assert state.load_state(storage)["outbox"] == []
    assert state.load_state(storage)["filtered_since_last_heartbeat"] == 0


def test_independent_news_cards_freeze_quote_and_resume_after_second_card_pending(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload.update(enable_llm_title=True, enable_llm_summary=True, enable_llm_routing=True)
    profile_payload['discord_channels'] = [
        {'key':'id_stocks_news','channel_id':'1525102508714889257','description':'IDX news'},
        {'key':'macro_news','channel_id':'1531655369884045382','description':'Macro'},
        {'key':'us_stocks_news','channel_id':'1525102508714889258','description':'US news'},
    ]
    config_path.write_text(json.dumps({'version':1,'profiles':[profile_payload]}))
    profile=__import__('config').load_watch_config(config_path).profiles[0]
    storage=tmp_path/'state.json'
    post=SourcePost(profile.id,'102','https://x.com/Kutekians/status/102',datetime.now(UTC),'GIAA rights issue. UNTR buyback.',PostKind.NORMAL,None,None,(),())
    value=state.new_state()
    value['profiles'][profile.id]={'cursor':'101'}
    state.observe_posts(value,profile,[post],lambda _:True)
    state.claim_oldest_agent(value,{profile.id:profile},datetime.now(UTC))
    state.save_state(storage,value)
    monkeypatch.setenv('X_POST_WATCH_STATE_PATH',str(storage))
    monkeypatch.setenv('X_POST_WATCH_CONFIG_PATH',str(config_path))
    quotes=[]
    monkeypatch.setattr(scan.render.news_format,'get_market_snapshot',lambda ticker,route:quotes.append(ticker))
    attempts=[]
    def send(content,channel,dry_run,nonce):
        saved=state.load_state(storage)['outbox'][0]
        assert len(saved['news_cards']) == 2
        attempts.append((content,channel,nonce))
        if len(attempts)==2:
            raise scan.discord.DeliveryOwnerPending('pending')
        return str(7000+len(attempts))
    monkeypatch.setattr(scan.discord,'post_text',send)
    result=scan.submit_analysis_payload({'event_key':'kutekians:102','is_relevant':True,'items':[
        {'title':'GIAA: Rencana rights issue','summary':'GIAA akan melakukan rights issue.','route':'id_stocks_news'},
        {'title':'UNTR: Rencana buyback saham','summary':'UNTR akan membeli kembali hingga 20% modalnya.','route':'id_stocks_news'},
    ]})
    assert result['delivered']==0 and quotes==['GIAA','UNTR']
    saved=state.load_state(storage)
    frozen=saved['outbox'][0]['news_cards']
    assert saved['outbox'][0]['text_index']==1
    monkeypatch.setattr(scan.render.news_format,'get_market_snapshot',lambda *args:pytest.fail('retry fetched quotes'))
    assert scan._deliver(saved,{profile.id:profile},0,False,storage,scan.RunStats(),datetime.now(UTC))
    assert len(attempts)==3 and attempts[1]==attempts[2]
    assert all(card['messages'][0].count('Harga terakhir')==1 for card in frozen)
    assert all('https://x.com/Kutekians/status/102' in card['messages'][0] for card in frozen)
    assert state.load_state(storage)['outbox']==[]


def test_education_with_earnings_and_dividend_terms_can_be_rejected(tmp_path,monkeypatch,config_path,profile_payload):
    profile=__import__('config').load_watch_config(config_path).profiles[0]
    post=SourcePost(profile.id,'102','https://x.com/Kutekians/status/102',datetime.now(UTC),
                    'Cara analisis fundamental saham: belajar membaca earnings, laba bersih dan dividen dibandingkan chart.',PostKind.NORMAL,None,None,(),())
    assert scan.requires_relevance(post,profile=profile)
    storage=tmp_path/'state.json'
    value=state.new_state();value['profiles'][profile.id]={'cursor':'101'}
    state.observe_posts(value,profile,[post],lambda _:True)
    state.claim_oldest_agent(value,{profile.id:profile},datetime.now(UTC));state.save_state(storage,value)
    monkeypatch.setenv('X_POST_WATCH_STATE_PATH',str(storage));monkeypatch.setenv('X_POST_WATCH_CONFIG_PATH',str(config_path))
    monkeypatch.setattr(scan.discord,'post_text',lambda *args:pytest.fail('education forwarded'))
    assert scan.submit_analysis_payload({'event_key':'kutekians:102','is_relevant':False})['ignored']
    assert state.load_state(storage)['outbox']==[]
