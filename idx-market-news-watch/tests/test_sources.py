import asyncio
from datetime import datetime, timezone


from domain import Provider
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
