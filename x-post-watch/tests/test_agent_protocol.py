from datetime import UTC, datetime

import pytest

import agent_protocol
import config as config_module
from models import PostKind, SourcePost


def test_agent_item_supplies_only_bounded_post_context(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Author text", PostKind.QUOTE, "https://x.com/a/status/101", "Quoted text", (), ())

    payload = agent_protocol.build_wake_payload(agent_protocol.agent_item(profile, post))

    assert payload["wakeAgent"] is True
    assert payload["item"]["event_key"] == "kutekians:102"
    assert payload["item"]["post_text"] == "Author text"
    assert payload["item"]["quoted_post_text"] == "Quoted text"
    assert payload["item"]["title_required"] is True
    assert payload["item"]["summary_required"] is True
    assert payload["item"]["route_required"] is False
    assert payload["item"]["relevance_required"] is True


def test_agent_item_uses_combined_thread_context_and_thread_relevance(config_path, profile_payload):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC), "$RATU umumkan private placement", PostKind.NORMAL, None, None, (), ())
    child = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Detail tambahan", PostKind.QUOTE, None, None, (), ())
    item = agent_protocol.agent_item(profile, child, (root, child))
    assert item["thread_post_count"] == "2"
    assert "Thread post 1/2" in item["post_text"]
    assert item["relevance_guard_required"] is True
    assert "combined thread" in item["instruction"]


def test_agent_item_passes_compact_article_quote_context(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Author text", PostKind.NORMAL, None, None, (), (), quoted_article_url="https://x.com/i/article/123", quoted_article_label="Ricky Ho")
    assert agent_protocol.agent_item(profile, post)["quoted_post_text"] == "Ricky Ho: https://x.com/i/article/123"


@pytest.mark.parametrize(
    "summary",
    [
        "No prefix.",
        "*(Ringkasan)* One\nline break.",
        "*(Ringkasan)* One.\n\nTwo.\n\nThree.",
    ],
)
def test_summary_validation_rejects_wrong_shape(summary):
    with pytest.raises(ValueError):
        agent_protocol.validate_summary(summary)


def test_summary_validation_normalizes_one_or_two_paragraphs():
    assert agent_protocol.validate_summary(" *(Ringkasan)* Satu.\n\nDua. ") == "*(Ringkasan)* Satu.\n\nDua."


def test_summary_validation_normalizes_repeated_label_on_second_paragraph():
    assert agent_protocol.validate_summary(
        "*(Ringkasan)* Satu.\n\n*(Ringkasan)* Dua."
    ) == "*(Ringkasan)* Satu.\n\nDua."


def test_summary_validation_rejects_repeated_label_inside_paragraph():
    with pytest.raises(ValueError, match="exactly once"):
        agent_protocol.validate_summary(
            "*(Ringkasan)* Satu dengan *(Ringkasan)* label tambahan."
        )


@pytest.mark.parametrize("title", ["A", "Judul dengan akhir titik.", "Lihat https://x.com/post"])
def test_title_validation_rejects_invalid_headlines(title):
    with pytest.raises(ValueError):
        agent_protocol.validate_title(title)


def test_title_validation_normalizes_one_line_headline():
    assert agent_protocol.validate_title("  BI:  Tiga Indikator\nuntuk Membaca Pasar  ") == "BI: Tiga Indikator untuk Membaca Pasar"


def test_submission_requires_exact_fields_for_title_only_profile(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    assert agent_protocol.validate_submission(profile, {"event_key": "kutekians:102", "is_relevant": True, "title": "BI: Tiga Indikator untuk Pasar"}) == {"event_key": "kutekians:102", "is_relevant": True, "title": "BI: Tiga Indikator untuk Pasar"}
    with pytest.raises(ValueError, match="unexpected"):
        agent_protocol.validate_submission(profile, {"event_key": "kutekians:102", "is_relevant": True, "title": "BI: Tiga Indikator untuk Pasar", "summary": "*(Ringkasan)* Tidak diminta"})


def test_relevance_filter_accepts_a_closed_irrelevant_decision(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    assert agent_protocol.validate_submission(profile, {"event_key": "kutekians:102", "is_relevant": False}) == {"event_key": "kutekians:102", "is_relevant": False}
    with pytest.raises(ValueError, match="unexpected"):
        agent_protocol.validate_submission(profile, {"event_key": "kutekians:102", "is_relevant": False, "title": "Tidak boleh ada judul"})


def test_direct_market_disclosure_requires_a_relevant_decision(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "$RATU umumkan private placement dengan potensi dilusi 9,09% #RangkumKeterbukaanInformasi", PostKind.NORMAL, None, None, (), ())

    item = agent_protocol.agent_item(profile, post)

    assert agent_protocol.requires_relevance(post) is True
    assert item["relevance_guard_required"] is True
    assert "must be relevant" in item["instruction"].lower()


def test_promotional_thread_is_not_forced_relevant_by_financial_language(config_path, profile_payload):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "102",
        "https://x.com/Kutekians/status/102",
        datetime.now(UTC),
        "Insider Crypto Tracker is live. CA: 0xfc861e02605addab95d8e6b8e662100e987cb9aa. Hold $INSIDER and unlock benefits. 80% of revenue will be used to buy back $INSIDER.",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )

    item = agent_protocol.agent_item(profile, post)

    assert agent_protocol.is_promotional(post) is True
    assert agent_protocol.requires_relevance(post) is False
    assert item["relevance_guard_required"] is False
    assert "advertisements and product promotions" in item["instruction"]


def test_insider_tracker_token_promotion_is_deterministically_discarded(config_path, profile_payload):
    post = SourcePost(
        "insidertracker",
        "2090891308827054155",
        "https://x.com/InsiderTrackX/status/2090891308827054155",
        datetime.now(UTC),
        "4% of $INSIDER supply was burned. Users are staking $INSIDER in the flywheel and 80% of revenue funds buybacks.",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )

    assert agent_protocol.is_promotional(post) is True
    assert agent_protocol.requires_relevance(post) is False


def test_member_only_stock_promotion_is_deterministically_discarded(config_path, profile_payload):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "2089649063310569955",
        "https://x.com/doktermarket/status/2089649063310569955",
        datetime.now(UTC),
        "Member Only: Saham Properti Ini Berpeluang Beri Cuan 20-140% https://www.doktermarket.com/2026/08/member-only-saham-properti-ini_04974221.html",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )

    assert agent_protocol.is_promotional(post) is True
    assert agent_protocol.requires_relevance(post) is False


def test_doktermarket_analysis_link_is_not_by_itself_promotional(config_path, profile_payload):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id,
        "2090372937425780921",
        "https://x.com/doktermarket/status/2090372937425780921",
        datetime.now(UTC),
        "ARCI Capai Target Kenaikan Pertama https://www.doktermarket.com/2026/08/arci-capai-target-kenaikan-pertama.html",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )

    assert agent_protocol.is_promotional(post) is False


def _canonical_profile(profile_id: str):
    canonical_config = __import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "watches.json"
    return {item.id: item for item in config_module.load_watch_config(canonical_config).profiles}[profile_id]


def _source_post(profile_id: str, post_id: str, text: str) -> SourcePost:
    return SourcePost(
        profile_id,
        post_id,
        f"https://x.com/example/status/{post_id}",
        datetime.now(UTC),
        text,
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )


def test_aldotjahjadi_generic_investor_track_record_is_deterministically_irrelevant():
    profile = _canonical_profile("aldotjahjadi8")
    generic = _source_post(
        profile.id,
        "2092189697150005608",
        "Pelajaran dari rekam jejak investasi Stanley Druckenmiller: 30% annual returns selama 30 tahun dan no losing years.",
    )
    macro = _source_post(
        profile.id,
        "2092189062409195602",
        "Peringatan Druckenmiller soal disiplin fiskal dan inflasi, dengan risiko yield obligasi yang lebih tinggi.",
    )

    assert agent_protocol.is_deterministically_irrelevant(profile, generic) is True
    assert agent_protocol.is_deterministically_irrelevant(profile, macro) is False


def test_clear_idx_chart_setup_is_deterministically_routed_to_swing():
    profile = _canonical_profile("doktermarket")
    post = _source_post(profile.id, "2092071113228787737", "ADRO: Menembus Resisten, pola inverted head and shoulders, target pertama 2750.")

    assert agent_protocol.deterministic_route(profile, post) == "id_stocks_swing"


def test_txth_news_boundaries_are_deterministically_routed():
    profile = _canonical_profile("txthariansaham")
    dividend = _source_post(profile.id, "2091750335014691145", "Jadwal pembagian dividen tunai dari Panin Sekuritas.")
    foreign_flow = _source_post(profile.id, "2091763719059747022", "Asing net sell Rp391,96 miliar pada midday. Asing membeli TINS dan menjual BBRI.")
    technical = _source_post(profile.id, "2091763719059747023", "BBRI breakout resistance pada chart harian, dengan entry dan stop-loss.")

    assert agent_protocol.deterministic_route(profile, dividend) == "id_stocks_news"
    assert agent_protocol.deterministic_route(profile, foreign_flow) == "macro_news"
    assert agent_protocol.deterministic_route(profile, technical) == "id_stocks_swing"


def test_submission_accepts_only_configured_routes(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    profile_payload["enable_llm_routing"] = True
    profile_payload["discord_channels"] = [
        {"key": "macro_news", "channel_id": "1531655369884045382", "description": "Macro"},
        {"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"},
        {"key": "id_stocks_swing", "channel_id": "1525102458253217803", "description": "IDX swing"},
        {"key": "us_stocks_news", "channel_id": "1532266331737686199", "description": "US listed"},
    ]
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    payload = {"event_key": "kutekians:102", "is_relevant": True, "title": "MYOR: Uji Rute Saham Indonesia", "summary": "*(Ringkasan)* Uji rute.", "route": "id_stocks_news"}

    assert agent_protocol.validate_submission(profile, payload)["route"] == "id_stocks_news"
    payload["route"] = "id_stocks_swing"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "id_stocks_swing"
    payload["route"] = "us_stocks_news"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "us_stocks_news"
    payload["route"] = "macro"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "macro_news"
    payload["route"] = "id_stock"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "id_stocks_news"
    payload["route"] = "id_stock_swing"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "id_stocks_swing"
    payload["route"] = "us_stock"
    assert agent_protocol.validate_submission(profile, payload)["route"] == "us_stocks_news"
    payload["route"] = "other"
    with pytest.raises(ValueError, match="configured channel key"):
        agent_protocol.validate_submission(profile, payload)


def test_agent_routing_instruction_prioritizes_market_thesis_over_company_examples(config_path, profile_payload):
    profile_payload["enable_llm_routing"] = True
    profile_payload["discord_channels"].append({"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX"})
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    instruction = agent_protocol.instruction_for(profile).lower()
    assert "central thesis, not named entities" in instruction
    assert "leverage, derivatives, liquidity" in instruction
    assert "companies or etfs are examples" in instruction
    assert "issuer, exchange, or listing country is unknown or ambiguous" in instruction
    assert "yahoo finance tool first, then serper, then brave search" in instruction
    assert "do not add any other lookup fact to the title or summary" in instruction
    assert "lookup remains inconclusive" in instruction
    assert "choose macro_news" in instruction
    assert "id_stocks_swing" in instruction
    assert "a target derived from earnings, dcf, or valuation remains id_stocks_news" in instruction
    assert "there is no separate us swing route" in instruction
    assert "ticker, number, target price, company name, or chart image alone" in instruction
    assert "spcx" not in instruction


def test_agent_instruction_requires_ticker_first_stock_titles_and_direct_summary_voice(config_path, profile_payload):
    instruction = agent_protocol.instruction_for(__import__("config").load_watch_config(config_path).profiles[0]).lower()
    assert "id_stocks_news, id_stocks_swing, or us_stocks_news" in instruction
    assert "first word of the title" in instruction
    assert "never repeat that label in the second paragraph" in instruction
    assert "do not describe ricky or the writer" in instruction


def test_agent_instruction_includes_profile_specific_instruction(config_path, profile_payload):
    profile_payload["additional_prompt_instruction"] = "Keep only data-backed market analysis."
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    assert "Profile-specific instruction: Keep only data-backed market analysis." in agent_protocol.instruction_for(profile)
