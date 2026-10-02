import asyncio
from datetime import datetime, timezone

import pytest

from domain import Provider, SourceKind
from sources import (
    PhintracoNewsAdapter,
    TuntunNewsAdapter,
    bootstrap_provider,
    fetch_unseen_messages,
)
from state import empty_state, provider_bootstrap_complete, provider_cursor


def test_tuntun_corporate_post_splits_only_its_company_entries(load_fixture):
    adapter = TuntunNewsAdapter()
    candidates = adapter.extract_candidates(
        message_id=13597,
        text=load_fixture("tuntun-corporate.txt"),
        published_at=datetime(2026, 7, 1, 6, 18, 54, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["DEWA", "PTBA"]
    assert all(candidate.source_message_id == 13597 for candidate in candidates)



def test_tuntun_corporate_post_with_emoji_header_splits_company_entries():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14018,
        text=(
            "Corporate 🏢\n\n"
            "TBIG (Tower Bersama Infrastructure): Offers bonds and sukuk.\n\n"
            "AGAR (Asia Sejahtera Mina): Planned controlling-shareholder acquisition."
        ),
        published_at=datetime(2026, 7, 22, 5, 27, 23, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["TBIG", "AGAR"]


def test_tuntun_uppercase_multiline_corporate_preserves_each_issuer_evidence(load_fixture):
    candidates = TuntunNewsAdapter().extract_candidates(
        15079, load_fixture("tuntun-20261002-15079.txt"),
        datetime(2026, 10, 2, 10, 45, 43, tzinfo=timezone.utc), 3743, False,
    )
    assert [item.ticker for item in candidates] == [
        "BRNA", "GOTO", "AMMN", "WIKA", "DOOH", "BBRI", "NAYZ", "GIAA", "AADI", "BACH",
    ]
    assert all(item.source_kind is SourceKind.CORPORATE_ENTRY for item in candidates)
    assert all(item.key == f"tuntun:15079:{item.ticker}" for item in candidates)
    by_ticker = {item.ticker: item.source_text for item in candidates}
    assert "Rp373 miliar" in by_ticker["BRNA"]
    assert "14-21 Oktober" in by_ticker["BRNA"]
    assert "Rp5,5 triliun" in by_ticker["WIKA"]
    assert "Rp4,17 triliun" in by_ticker["WIKA"]
    assert "AMMN: perkara" in by_ticker["AMMN"]
    assert "BRNA" not in by_ticker["WIKA"]
    assert all("Sumber:" not in item.source_text for item in candidates)


@pytest.mark.parametrize("embedded_corporate", [False, True])
def test_tuntun_actual_evening_update_bounds_industry_before_corporate(load_fixture, embedded_corporate):
    text = load_fixture("tuntun-20261002-15078.txt")
    if embedded_corporate:
        text += "\n\n" + load_fixture("tuntun-20261002-15079.txt")
    candidates = TuntunNewsAdapter().extract_candidates(
        15078, text, datetime(2026, 10, 2, 10, 45, 42, tzinfo=timezone.utc), 3743, False,
    )
    lead = candidates[0]
    assert lead.source_text.startswith("AS Pertimbangkan Kapal Induk Ketiga")
    assert lead.ticker is None
    assert "PNM" not in lead.source_text
    industry = [item for item in candidates if item.source_kind is SourceKind.TUNTUN_UPDATE_INDUSTRY]
    assert len(industry) == 3
    assert all("CORPORATE" not in item.source_text and "BRNA" not in item.source_text for item in industry)
    corporate = [item for item in candidates if item.source_kind is SourceKind.CORPORATE_ENTRY]
    assert len(corporate) == (10 if embedded_corporate else 0)
    if embedded_corporate:
        assert {item.ticker for item in corporate}.issuperset({"BRNA", "WIKA"})
    assert len([item for item in candidates if item.source_kind is SourceKind.TUNTUN_UPDATE_SECTION]) == 4
    assert all("Gainers" not in item.source_text and "Top Volume" not in item.source_text for item in candidates)


@pytest.mark.parametrize("header", ["CORPORATE", "> Corporate", "**Corporate 🏢**"])
def test_tuntun_corporate_heading_variants_accept_bullet_entries(header):
    candidates = TuntunNewsAdapter().extract_candidates(
        15074, f"{header}\n\n- AADI: Divestasi rampung.\n- WIFI: Kontrak baru.",
        datetime(2026, 10, 2, tzinfo=timezone.utc), 3743, False,
    )
    assert [item.ticker for item in candidates] == ["AADI", "WIFI"]


def test_tuntun_quoted_update_sections_do_not_absorb_corporate_or_tables():
    candidates = TuntunNewsAdapter().extract_candidates(
        15074,
        "Midday Update_Tuntun Sekuritas_20261002\nMixed PTPP title\n\n"
        "> Headline\nOil supplies tighten\n- Prices increased.\n\n"
        "> Overview\nIHSG: 6,000\n\n> Sector\nEnergy +2%\n\n"
        "> Macro & Global\nInflation slows\n- Inflation was 2%.\n\n"
        "> Industry\nIndustry demand expands\n- Demand rose 5%.\n\n"
        "> Corporate\n- AADI: Divestasi rampung.\n- WIFI: Kontrak baru.\n\n"
        "> Top Movers\nGOTO +5%",
        datetime(2026, 10, 2, tzinfo=timezone.utc), 3743, False,
    )
    assert [(item.source_kind, item.ticker) for item in candidates] == [
        (SourceKind.TUNTUN_UPDATE_LEAD, None),
        (SourceKind.TUNTUN_UPDATE_SECTION, None),
        (SourceKind.TUNTUN_UPDATE_INDUSTRY, None),
        (SourceKind.CORPORATE_ENTRY, "AADI"),
        (SourceKind.CORPORATE_ENTRY, "WIFI"),
    ]
    assert "Industry demand expands" in candidates[2].source_text
    assert all("GOTO" not in item.source_text for item in candidates)


def test_tuntun_truncated_or_repeated_multiline_header_does_not_mix_issuers():
    candidates = TuntunNewsAdapter().extract_candidates(
        15078, "CORPORATE\n\nDOOH (PT Era Media)\n- Akuisisi Rp2 triliun.\n\n"
        "BBRI (PT\n\nBRNA (PT Berlina Tbk)\n- Rights issue Rp373 miliar.\n\n"
        "BRNA (PT Berlina Tbk)\n- Repeated entry.",
        datetime(2026, 10, 2, tzinfo=timezone.utc), 3743, False,
    )
    assert [item.ticker for item in candidates] == ["DOOH", "BRNA"]
    assert "BBRI" not in candidates[0].source_text
    assert candidates[1].source_text == "BRNA (PT Berlina Tbk)\n- Rights issue Rp373 miliar."


def test_tuntun_corporate_entry_with_nested_parentheses_is_retained():
    source_entry = (
        "BRIS (PT Bank Syariah Indonesia (Persero) Tbk): "
        "PMHMETD II direncanakan menerbitkan maksimal 6,8 miliar saham Seri B."
    )

    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=15054,
        text=f"Corporate 🏢\n\n{source_entry}",
        published_at=datetime(2026, 9, 30, 11, 26, 16, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["BRIS"]
    assert candidates[0].source_text == source_entry


def test_tuntun_corporate_repeated_ticker_entries_keep_one_stable_candidate():
    first_plas = (
        "PLAS (PT Polaris Investama Tbk): PLAS menyiapkan sekitar Rp60,39 miliar "
        "untuk membeli kembali 1,184 miliar saham publik pada harga Rp51 per saham menjelang delisting. "
        "Periode buyback berlangsung 24 September-6 November dan delisting dijadwalkan efektif 10 November 2026."
    )
    second_plas = (
        "PLAS (PT Polaris Investama Tbk): Menjelang delisting, PLAS menawarkan buyback seluruh "
        "1,184 miliar saham publik di harga Rp51 per saham dengan dana sekitar Rp60,39 miliar. "
        "Periode buyback berlangsung 24 September-6 November dan delisting dijadwalkan efektif 10 November 2026."
    )
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14978,
        text=(
            "Corporate 🏢\n\n"
            f"{first_plas}\n\n"
            "SILO (PT Siloam International Hospitals Tbk): Acquires 14 hospitals.\n\n"
            f"{second_plas}"
        ),
        published_at=datetime(2026, 9, 23, 10, 48, 2, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["PLAS", "SILO"]
    assert candidates[0].key == "tuntun:14978:PLAS"
    assert candidates[0].source_text == first_plas
    assert second_plas not in candidates[0].source_text


def test_tuntun_issuer_headline_with_decorative_prefix_is_ticker_led():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14021,
        text=(
            "📰 SINI Sebut Akuisisi KMS Rp1,73 Triliun Jadi Langkah Strategis\n\n"
            "PT Singaraja Putra Tbk (SINI) menyatakan akuisisi KMS dilakukan untuk memperkuat ekspansi."
        ),
        published_at=datetime(2026, 7, 22, 8, 22, 33, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["SINI"]


def test_tuntun_long_news_with_topic_led_headline_extracts_issuer_ticker(load_fixture):
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14784,
        text=load_fixture("tuntun-long-news.txt"),
        published_at=datetime(2026, 9, 11, 4, 18, 44, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["KLBF"]
    assert candidates[0].source_kind.value == "tuntun_standalone"


def test_tuntun_decorated_news_strips_the_source_footer_and_detects_the_headline_issuer():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14760,
        text=(
            "📰 Rata Kanan Capital Borong 30,75 Juta Saham MMIX Senilai Rp20 Miliar\n\n"
            "Rata Kanan Capital resmi masuk sebagai pemegang saham PT Multi Medika Internasional Tbk (MMIX) "
            "setelah membeli 30,75 juta saham senilai sekitar Rp20 miliar.\n\n"
            "Sumber: IDXChannel"
        ),
        published_at=datetime(2026, 9, 10, 4, 1, 30, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["MMIX"]
    assert "Sumber:" not in candidates[0].source_text


def test_tuntun_decorated_macro_news_is_a_routeable_tickerless_candidate():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14761,
        text="📰 Pemerintah Pertahankan Harga BBM untuk Redam Inflasi\n\nSumber: Bisnis",
        published_at=datetime(2026, 9, 10, 4, 2, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [(candidate.candidate_id, candidate.ticker) for candidate in candidates] == [("news", None)]
    assert "Sumber:" not in candidates[0].source_text


@pytest.mark.parametrize(
    "abbreviation",
    (
        "APBD",
        "APBN",
        "APEC",
        "BKPM",
        "BMKG",
        "BPJS",
        "BRIN",
        "BUMD",
        "BUMN",
        "CAGR",
        "CCUS",
        "EBIT",
        "ESDM",
        "FCFE",
        "FCFF",
        "FLNG",
        "FOMC",
        "HGBT",
        "ISPO",
        "IUPK",
        "KPEI",
        "KPPU",
        "KSEI",
        "LCGC",
        "OECD",
        "OPEC",
        "PLTA",
        "PLTU",
        "POJK",
        "PUPR",
        "REER",
        "RKAB",
        "ROIC",
        "RSPO",
        "RUPS",
        "SOFR",
        "SPBU",
        "TKDN",
        "WACC",
        "WIPO",
    ),
)
def test_tuntun_decorated_reserved_abbreviation_is_a_routeable_tickerless_candidate(abbreviation):
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14878,
        text=(
            f"📰 {abbreviation}: Kebijakan terkini berdampak pada perekonomian nasional\n\n"
            "Rincian kebijakan akan diumumkan oleh otoritas terkait."
        ),
        published_at=datetime(2026, 9, 16, 4, 26, 40, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [(candidate.candidate_id, candidate.ticker) for candidate in candidates] == [("news", None)]


def test_tuntun_decorated_headline_skips_reserved_abbreviation_before_real_issuer():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14880,
        text=(
            "📰 APBN Dorong BMRI Perluas Penyaluran Kredit\n\n"
            "PT Bank Mandiri (Persero) Tbk (BMRI) memperluas penyaluran kredit."
        ),
        published_at=datetime(2026, 9, 16, 4, 30, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [(candidate.candidate_id, candidate.ticker) for candidate in candidates] == [("BMRI", "BMRI")]


def test_tuntun_midday_update_extracts_its_lead_and_each_macro_or_industry_paragraph():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14786,
        text=(
            "Midday Update_Tuntun Sekuritas_20260911\n\n"
            "BUMI Tuntaskan Akuisisi Loyal Metals\n\n"
            "BUMI menyelesaikan akuisisi untuk memperluas eksposur tembaga dan emas.\n\n"
            "Overview 🧭\n\nIHSG: 6,490.91 (-1.49%)\n\n"
            "Macro & Global🌐\n\n"
            "ECB Naikkan Suku Bunga Deposit 25 bps ke 2,5%\n\n"
            "Kenaikan memperkuat tren kebijakan moneter global yang lebih hawkish.\n\n"
            "Rupiah Kembali Tertekan ke Area Rp17.600 per Dolar AS\n\n"
            "Harga minyak tinggi menjadi tekanan utama rupiah.\n\n"
            "Industry 🏭\n\n"
            "Harga Minyak Mendekati US$110 per Barel\n\n"
            "Brent naik sekitar 6,3% ke US$107,6.\n\n"
            "Ekspor Batu Bara Indonesia Agustus Turun 23,3% YoY\n\n"
            "Kekeringan membatasi pengangkutan batu bara menuju terminal."
        ),
        published_at=datetime(2026, 9, 11, 5, 35, 30, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [(candidate.candidate_id, candidate.source_kind.value, candidate.ticker) for candidate in candidates] == [
        ("lead", "tuntun_update_lead", "BUMI"),
        ("macro-1", "tuntun_update_section", None),
        ("macro-2", "tuntun_update_section", None),
        ("industry-1", "tuntun_update_industry", None),
        ("industry-2", "tuntun_update_industry", None),
    ]


def test_tuntun_decorated_brand_headline_prefers_parenthesized_idx_ticker():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14281,
        text=(
            "📰 SIG (SMGR) Hidupkan Kembali Semen Kujang untuk Perkuat Pangsa Pasar Jawa Barat\n\n"
            "PT Semen Indonesia (Persero) Tbk (SMGR) kembali menghadirkan Semen Kujang."
        ),
        published_at=datetime(2026, 8, 6, 3, 44, 26, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["SMGR"]


def test_tuntun_decorated_headline_ignores_non_ticker_parenthetical_label():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14359,
        text=(
            "📰 BAJA Masuk Daftar Saham dengan Konsentrasi Kepemilikan Tinggi (HSC)\n\n"
            "BEI memasukkan PT Saranacentral Bajatama Tbk (BAJA) ke dalam daftar saham dengan "
            "High Shareholding Concentration (HSC)."
        ),
        published_at=datetime(2026, 8, 12, 6, 43, 16, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["BAJA"]


def test_tuntun_foreign_partner_headline_uses_the_listed_issuer_after_the_hyphen():
    candidates = TuntunNewsAdapter().extract_candidates(
        message_id=14132,
        text=(
            "📰 NFC China-BRMS Siap Kebut Tambang Timah Hitam di Sumut\n\n"
            "NFC China dan PT Bumi Resources Minerals Tbk (BRMS) melalui PT Dairi Prima Mineral "
            "melanjutkan proyek tambang bawah tanah."
        ),
        published_at=datetime(2026, 7, 29, 1, 51, 33, tzinfo=timezone.utc),
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["BRMS"]
    assert candidates[0].source_kind.value == "tuntun_standalone"


def test_tuntun_subsidiary_subject_headlines_extract_the_named_issuers():
    adapter = TuntunNewsAdapter()
    at = datetime(2026, 7, 28, 1, 46, 20, tzinfo=timezone.utc)

    wifi = adapter.extract_candidates(
        message_id=14091,
        text="📰 Anak Usaha WIFI Terbitkan Samurai Bonds Senilai JPY21,4 Miliar di Jepang",
        published_at=at,
        topic_id=3743,
        direct_image=False,
    )
    brpt_cdia = adapter.extract_candidates(
        message_id=14098,
        text="Anak usaha BRPT, CDIA, mendapat kontrak pengembangan terminal energi",
        published_at=at,
        topic_id=3743,
        direct_image=False,
    )

    assert [candidate.ticker for candidate in wifi] == ["WIFI"]
    assert [candidate.ticker for candidate in brpt_cdia] == ["BRPT", "CDIA"]
    assert all(candidate.source_kind.value == "tuntun_standalone" for candidate in wifi + brpt_cdia)


def test_phintraco_company_notes_extracts_ticker_from_issuer_line():
    candidates = PhintracoNewsAdapter().extract_candidates(
        message_id=33896,
        text=(
            "Company Notes – Juli 22nd 2026\n"
            "PT Adhi Karya (Persero) Tbk – ADHI.IJ\n"
            "ADHI: Margin Expansion Softens the Blow from Topline Contraction"
        ),
        published_at=datetime(2026, 7, 22, 2, 27, 9, tzinfo=timezone.utc),
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["ADHI"]
    assert candidates[0].source_kind.value == "phintraco_note"


def test_phintraco_branded_notes_extracts_ticker_from_the_headline_line():
    candidates = PhintracoNewsAdapter().extract_candidates(
        message_id=33916,
        text=(
            "Phintraco Sekuritas Notes | 23 Juli 2026\n"
            "ELSA Terapkan Teknologi Dual Completion di Adera Field Milik Pertamina\n"
            "PT Elnusa Tbk menerapkan teknologi Dual Completion pada sumur BNG-D14."
        ),
        published_at=datetime(2026, 7, 23, 0, 41, 26, tzinfo=timezone.utc),
        direct_image=False,
    )

    assert [candidate.ticker for candidate in candidates] == ["ELSA"]
    assert candidates[0].source_kind.value == "phintraco_note"


def test_phintraco_quick_notes_extracts_issuer_from_the_headline():
    content = (
        "PHINTAS Quick Notes | 23 September 2026\n\n"
        "POWR Berpotensi Catat Pertumbuhan Kinerja pada 2026\n"
        "Phintraco estimates FY26 revenue growth, subject to execution."
    )

    candidates = PhintracoNewsAdapter().extract_candidates(
        35376,
        content,
        datetime(2026, 9, 23, 3, 0, tzinfo=timezone.utc),
        False,
    )

    assert len(candidates) == 1
    assert candidates[0].ticker == "POWR"
    assert candidates[0].source_kind is SourceKind.PHINTRACO_QUICK_NOTE
    assert candidates[0].source_text == content


def test_phintraco_quick_notes_extracts_issuer_from_anak_usaha_headline():
    content = (
        "PHINTAS Quick Notes | 24 September 2026\n\n"
        "Anak Usaha ARKO Peroleh Pembiayaan US$9.8 Juta untuk Proyek PLTS\n\n"
        "ARKO melalui anak usaha tidak langsung memperoleh fasilitas pembiayaan."
    )

    candidates = PhintracoNewsAdapter().extract_candidates(
        35412,
        content,
        datetime(2026, 9, 24, 1, 15, 42, tzinfo=timezone.utc),
        False,
    )

    assert len(candidates) == 1
    assert candidates[0].ticker == "ARKO"
    assert candidates[0].candidate_id == "ARKO"
    assert candidates[0].source_kind is SourceKind.PHINTRACO_QUICK_NOTE


def test_phintraco_multi_issuer_anak_usaha_quick_note_stays_tickerless():
    content = (
        "PHINTAS Quick Notes | 24 September 2026\n\n"
        "Anak Usaha ARKO dan BRPT Peroleh Pembiayaan untuk Proyek Energi"
    )

    candidates = PhintracoNewsAdapter().extract_candidates(
        35413,
        content,
        datetime(2026, 9, 24, 1, 15, 42, tzinfo=timezone.utc),
        False,
    )

    assert len(candidates) == 1
    assert candidates[0].ticker is None
    assert candidates[0].candidate_id == "news"


def test_phintraco_branded_macro_notes_create_one_tickerless_candidate():
    content = (
        "Phintraco Sekuritas Notes | 23 September 2026\n\n"
        "Landbank Implications from Agrarian Reform\n"
        "The policy may affect several listed property developers."
    )

    candidates = PhintracoNewsAdapter().extract_candidates(
        35378,
        content,
        datetime(2026, 9, 23, 2, 40, tzinfo=timezone.utc),
        False,
    )

    assert len(candidates) == 1
    assert candidates[0].ticker is None
    assert candidates[0].source_kind is SourceKind.PHINTRACO_NOTE
    assert candidates[0].candidate_id == "news"


def test_phintraco_company_update_extracts_the_single_headline_issuer():
    content = (
        "Phintraco Sekuritas Company Update\n"
        "MEDC: Positive Momentum with Strengthening Production and Strategic Assets\n"
        "Phintraco estimates FY26 revenue at US$2.63 billion."
    )

    candidates = PhintracoNewsAdapter().extract_candidates(
        35381,
        content,
        datetime(2026, 9, 23, 2, 39, 12, tzinfo=timezone.utc),
        False,
    )

    assert len(candidates) == 1
    assert candidates[0].ticker == "MEDC"
    assert candidates[0].source_kind is SourceKind.PHINTRACO_COMPANY_UPDATE


def test_tuntun_wrong_topic_and_market_update_are_excluded(load_fixture):
    adapter = TuntunNewsAdapter()

    assert adapter.extract_candidates(1, load_fixture("tuntun-standalone.txt"), datetime.now(timezone.utc), 999, False) == []
    assert adapter.extract_candidates(2, load_fixture("tuntun-macro-update.txt"), datetime.now(timezone.utc), 3743, False) == []


def test_tuntun_accepts_issuer_specific_special_topics_and_rejects_nonissuer_categories():
    adapter = TuntunNewsAdapter()
    at = datetime.now(timezone.utc)

    candidates = adapter.extract_candidates(
        3,
        "Special Topic: DEWA (Darma Henwa): contract execution update.\nDetails follow.",
        at,
        3743,
        False,
    )

    assert [candidate.source_kind.value for candidate in candidates] == ["tuntun_special_topic"]
    for nonissuer_text in (
        "Daily: DEWA is a top pick.",
        "Midday: DEWA is a top pick.",
        "Evening: DEWA is a top pick.",
        "Macro: DEWA is a top pick.",
        "Sector: DEWA is a top pick.",
        "Market: DEWA is a top pick.",
        "Promotion: DEWA is a top pick.",
        "Customer Service: DEWA is a top pick.",
    ):
        assert adapter.extract_candidates(3, nonissuer_text, at, 3743, False) == []


def test_ticker_led_tuntun_categories_and_known_market_symbols_are_excluded():
    adapter = TuntunNewsAdapter()
    at = datetime.now(timezone.utc)

    for excluded_text in (
        "DEWA: Daily market update.",
        "DEWA: Macro outlook.",
        "DEWA: Promotional program.",
        "DEWA: Customer Service announcement.",
        "JCI: market update.",
        "IHSG: market update.",
        "LQ45: market update.",
    ):
        assert adapter.extract_candidates(3, excluded_text, at, 3743, False) == []


def test_phintraco_rejects_known_market_symbols_under_allowed_headers():
    adapter = PhintracoNewsAdapter()
    at = datetime.now(timezone.utc)

    for excluded_text in (
        "Notes: JCI market outlook.",
        "Company Flash: IHSG market update.",
        "Stock Information\nJCI: status update.\nLQ45: status update.",
    ):
        assert adapter.extract_candidates(3, excluded_text, at, False) == []


def test_phintraco_allows_notes_flash_and_stock_information_but_not_market_review(load_fixture):
    adapter = PhintracoNewsAdapter()
    at = datetime.now(timezone.utc)

    assert [item.source_kind.value for item in adapter.extract_candidates(1, load_fixture("phintraco-note.txt"), at, False)] == ["phintraco_note"]
    assert [item.source_kind.value for item in adapter.extract_candidates(2, load_fixture("phintraco-company-flash.txt"), at, False)] == ["phintraco_company_flash"]
    assert [item.source_kind.value for item in adapter.extract_candidates(3, load_fixture("phintraco-stock-information.txt"), at, False)] == ["phintraco_stock_information", "phintraco_stock_information"]
    assert adapter.extract_candidates(4, load_fixture("phintraco-market-review.txt"), at, False) == []


def test_fetch_unseen_messages_uses_a_read_only_ascending_iteration():
    messages = [object(), object()]

    class Client:
        def __init__(self):
            self.calls = []

        async def iter_messages(self, entity, min_id, reverse):
            self.calls.append((entity, min_id, reverse))
            for message in messages:
                yield message

    client = Client()

    assert asyncio.run(fetch_unseen_messages(client, "channel", 9)) == messages
    assert client.calls == [("channel", 9, True)]


def test_bootstrap_records_the_latest_message_without_creating_candidates(monkeypatch, tmp_path):
    class Message:
        id = 13597

    class Client:
        async def iter_messages(self, entity, limit):
            assert entity == "channel"
            assert limit == 1
            yield Message()

    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    assert asyncio.run(bootstrap_provider(Client(), "channel", state, Provider.TUNTUN)) is True
    assert provider_bootstrap_complete(state, Provider.TUNTUN) is True
    assert provider_cursor(state, Provider.TUNTUN) == 13597
    assert state["candidates"] == {}
    assert asyncio.run(bootstrap_provider(Client(), "channel", state, Provider.TUNTUN)) is False



def test_empty_channel_bootstrap_keeps_the_first_later_message_unseen(monkeypatch, tmp_path):
    class EmptyClient:
        async def iter_messages(self, entity, limit):
            assert entity == "channel"
            assert limit == 1
            if False:
                yield None

    class FirstLaterMessage:
        id = 1

    class LaterClient:
        async def iter_messages(self, entity, min_id, reverse):
            assert entity == "channel"
            assert min_id == 0
            assert reverse is True
            yield FirstLaterMessage()

    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()

    assert asyncio.run(bootstrap_provider(EmptyClient(), "channel", state, Provider.TUNTUN)) is True
    assert provider_bootstrap_complete(state, Provider.TUNTUN) is True
    assert provider_cursor(state, Provider.TUNTUN) == 0
    later_messages = asyncio.run(fetch_unseen_messages(LaterClient(), "channel", provider_cursor(state, Provider.TUNTUN)))
    assert [message.id for message in later_messages] == [1]
    assert asyncio.run(bootstrap_provider(EmptyClient(), "channel", state, Provider.TUNTUN)) is False
