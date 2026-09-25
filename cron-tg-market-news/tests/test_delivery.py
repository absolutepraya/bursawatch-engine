import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import delivery
from market_data import MarketSnapshot
from bursawatch_discord_delivery import OperationReceipt
import state as state_module
from domain import CompanyCandidate, Destination, EventClass, Provider, SourceKind
from selection import SelectionCandidate
from sources import PhintracoNewsAdapter
from state import (
    StateBlockedError,
    empty_state,
    enqueue_candidate,
    enqueue_stock_status,
    load_state,
)
from stock_status import format_stock_status, parse_stock_information


class Response:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class DeliveredOwner:
    def __init__(self):
        self.operations = {}
        self.submissions = []

    def status(self, operation_key):
        return self.operations.get(operation_key)

    def submit(self, operation):
        self.submissions.append(operation)
        receipt = OperationReceipt(
            id=f"owner-{len(self.submissions)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={
                "channel_id": operation.target["channel_id"],
                "message_id": str(5000 + len(self.submissions)),
            },
        )
        self.operations[operation.key] = receipt
        return receipt

    def wait(self, operation_key, timeout_seconds):
        assert timeout_seconds == 0
        return self.operations[operation_key]


def _item(
    provider,
    message_id,
    ticker,
    event_class,
    published_at,
    facts=("contract value",),
    source_text="source text is not reposted",
    title="",
):
    if provider is Provider.TUNTUN and not title:
        title = f"{ticker}: Test news"
    return SelectionCandidate(
        candidate=CompanyCandidate(
            provider=provider,
            source_message_id=message_id,
            ticker=ticker,
            source_kind=SourceKind.CORPORATE_ENTRY,
            published_at=published_at,
            source_text=source_text,
            direct_image=False,
        ),
        event_class=event_class,
        ranking_band=1,
        material_facts=facts,
        dedupe_facts=("counterparty", "term"),
        title=title,
    )


@pytest.fixture
def dewa_tier_one():
    return _item(
        Provider.TUNTUN,
        13597,
        "DEWA",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 18, tzinfo=timezone.utc),
    )


@pytest.fixture
def cbre_tier_two():
    return _item(
        Provider.TUNTUN,
        13598,
        "CBRE",
        EventClass.QUANTIFIED_OPERATIONAL_EXECUTION,
        datetime(2026, 7, 14, 6, 20, tzinfo=timezone.utc),
    )


@pytest.fixture
def anm_tier_two():
    return _item(
        Provider.PHINTRACO,
        13599,
        "ANTM",
        EventClass.OTHER_COMPANY_OPERATION,
        datetime(2026, 7, 14, 6, 21, tzinfo=timezone.utc),
    )


def test_news_item_has_no_delivery_window_heading(dewa_tier_one):
    alert = delivery.format_news_item(dewa_tier_one)

    assert alert.startswith(
        "### <:tuntun:1531272430985937086> DEWA: Test news"
    )
    assert all(label not in alert for label in ("PRE-MARKET", "POST-MARKET", "INTRA-DAY"))
    assert "┈" * 13 not in alert
    assert "Sumber:" not in alert
    assert "[View on Telegram](<https://t.me/tuntunsekuritas/13597>)" in alert
    assert "BUY" not in alert
    assert (
        "Harga terakhir (IDR): **-**\n"
        "<:grey:1531279158913536182> 1D: **-**, "
        "<:grey:1531279158913536182> 1W: **-**,\n"
        "<:grey:1531279158913536182> 1M: **-**, "
        "<:grey:1531279158913536182> 3M: **-**"
    ) in alert
    assert "*(Ringkasan)*" in alert
    assert len(alert) <= 2000


def test_news_item_preserves_material_fact_capitalization():
    alert = delivery.format_news_item(
        _item(
            Provider.TUNTUN,
            14039,
            "SINI",
            EventClass.MNA_OR_ASSET_TRANSACTION,
            datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
            facts=("SINI acquired KMS.", "KMS revenue is projected at US$159 million in 2027."),
            title="SINI: Akuisisi KMS memperkuat ekspansi",
        )
    )

    assert "SINI acquired KMS. KMS revenue is projected at US$159 million in 2027." in alert
    assert "•" not in alert


def test_entry_uses_yahoo_snapshot_for_canonical_name_and_rupiah_changes(monkeypatch, dewa_tier_one):
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot("PT Darma Henwa Tbk", 472, 32, 7.27, -18, -3.67),
    )

    alert = delivery.format_news_item(dewa_tier_one)

    assert "DEWA: Test news" in alert
    assert (
        "Harga terakhir (IDR): **472**\n"
        "<:green:1531274822221434911> 1D: **+32 (+7.27%)**, "
        "<:red:1531274756853202974> 1W: **-18 (-3.67%)**,\n"
        "<:grey:1531279158913536182> 1M: **-**, "
        "<:grey:1531279158913536182> 3M: **-**"
    ) in alert


def test_tuntun_entry_uses_generated_title_and_four_horizons(monkeypatch):
    item = _item(
        Provider.TUNTUN,
        14040,
        "RAJA",
        EventClass.MNA_OR_ASSET_TRANSACTION,
        datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
        facts=("RAJA acquired a 5% stake.",),
        source_text="RAJA: Akuisisi Layar Nusantara Gas\nRAJA mengakuisisi 5% saham.",
        title="RAJA: Akuisisi Layar Nusantara Gas",
    )
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot(
            "PT Rukun Raharja Tbk", 820, 5, 0.61, 10, 1.23, 5, 0.61, 10, 1.23
        ),
    )

    alert = delivery.format_news_item(item)

    assert alert == (
        "### <:tuntun:1531272430985937086> RAJA: Akuisisi Layar Nusantara Gas\n\n"
        "*(Ringkasan)* RAJA acquired a 5% stake.\n\n"
        "Harga terakhir (IDR): **820**\n"
        "<:green:1531274822221434911> 1D: **+5 (+0.61%)**, "
        "<:green:1531274822221434911> 1W: **+10 (+1.23%)**,\n"
        "<:green:1531274822221434911> 1M: **+5 (+0.61%)**, "
        "<:green:1531274822221434911> 3M: **+10 (+1.23%)**\n\n"
        "[View on Telegram](<https://t.me/tuntunsekuritas/14040>)"
    )
    assert "(PT Rukun Raharja Tbk)" not in alert
    assert "*Harga terakhir" not in alert


def test_phintraco_entry_uses_shared_issuer_layout_and_four_horizons(monkeypatch):
    item = _item(
        Provider.PHINTRACO,
        35235,
        "FORU",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 9, 15, 6, 41, tzinfo=timezone.utc),
        facts=(
            "FORU akan melakukan rights issue hingga Rp27,1 triliun.",
            "Pemegang saham yang tidak mengeksekusi HMETD berpotensi terdilusi.",
        ),
        source_text="FORU (PT Fortune Indonesia Tbk): rights issue hingga Rp27,1 triliun.",
    )
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot(
            "PT Fortune Indonesia Tbk", 4310, -340, -7.31, 610, 16.49, 2500, 116.28, 1580, 51.47
        ),
    )

    alert = delivery.format_news_item(item)

    assert alert == (
        "### <:phintraco:1531272488645038091> FORU (PT Fortune Indonesia Tbk)\n\n"
        "*(Ringkasan)* FORU akan melakukan rights issue hingga Rp27,1 triliun. "
        "Pemegang saham yang tidak mengeksekusi HMETD berpotensi terdilusi.\n\n"
        "Harga terakhir (IDR): **4.310**\n"
        "<:red:1531274756853202974> 1D: **-340 (-7.31%)**, "
        "<:green:1531274822221434911> 1W: **+610 (+16.49%)**,\n"
        "<:green:1531274822221434911> 1M: **+2.500 (+116.28%)**, "
        "<:green:1531274822221434911> 3M: **+1.580 (+51.47%)**\n\n"
        "[View on Telegram](<https://t.me/phintasprofits/35235>)"
    )
    assert "┈" * 13 not in alert
    assert "*Harga terakhir" not in alert


def test_phintraco_anak_usaha_quick_note_uses_the_issuer_market_card(monkeypatch):
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
    candidate = candidates[0]
    assert candidate.ticker == "ARKO"
    item = SelectionCandidate(
        candidate=candidate,
        event_class=EventClass.FINANCING_OR_OWNERSHIP,
        ranking_band=1,
        material_facts=("ARKO's subsidiary received a US$9.8 million facility.",),
        dedupe_facts=("US$9.8 million", "subsidiary", "solar project"),
        summary="Anak usaha ARKO memperoleh fasilitas pembiayaan US$9,8 juta untuk proyek PLTS.",
        route=Destination.ID_STOCKS_NEWS,
    )
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot(
            "PT Arkora Hydro Tbk", 1234, 24, 1.98, -18, -1.44, 55, 4.66, 118, 10.58
        ),
    )

    alert = delivery.format_news_item(item)

    assert alert == (
        "### <:phintraco:1531272488645038091> ARKO (PT Arkora Hydro Tbk)\n\n"
        "*(Ringkasan)* Anak usaha ARKO memperoleh fasilitas pembiayaan US$9,8 juta untuk proyek PLTS.\n\n"
        "Harga terakhir (IDR): **1.234**\n"
        "<:green:1531274822221434911> 1D: **+24 (+1.98%)**, "
        "<:red:1531274756853202974> 1W: **-18 (-1.44%)**,\n"
        "<:green:1531274822221434911> 1M: **+55 (+4.66%)**, "
        "<:green:1531274822221434911> 3M: **+118 (+10.58%)**\n\n"
        "[View on Telegram](<https://t.me/phintasprofits/35412>)"
    )


def test_phintraco_macro_entry_uses_brand_summary_and_link_without_issuer_data():
    item = SelectionCandidate(
        candidate=CompanyCandidate(
            provider=Provider.PHINTRACO,
            source_message_id=35378,
            ticker="BSDE",
            source_kind=SourceKind.PHINTRACO_NOTE,
            published_at=datetime(2026, 9, 23, 2, 40, tzinfo=timezone.utc),
            source_text="Landbank Implications from Agrarian Reform; impact across property developers.",
            direct_image=False,
        ),
        event_class=EventClass.LISTING_LEGAL_REGULATORY_OR_CREDIT,
        ranking_band=1,
        material_facts=("The policy may affect several developers.",),
        dedupe_facts=("agrarian reform policy",),
        summary="Perubahan kebijakan agraria dapat memengaruhi sejumlah pengembang properti.",
        route=Destination.MACRO_NEWS,
    )

    alert = delivery.format_news_item(item)

    assert alert == (
        "### <:phintraco:1531272488645038091> Phintraco Sekuritas\n\n"
        "*(Ringkasan)* Perubahan kebijakan agraria dapat memengaruhi sejumlah pengembang properti.\n\n"
        "[View on Telegram](<https://t.me/phintasprofits/35378>)"
    )
    assert "BSDE" not in alert
    assert "Harga terakhir" not in alert


def test_tuntun_macro_card_uses_the_telegram_link_without_market_data():
    item = SelectionCandidate(
        candidate=CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=14786,
            ticker=None,
            candidate_id="macro-1",
            source_kind=SourceKind.TUNTUN_UPDATE_SECTION,
            published_at=datetime(2026, 9, 11, 5, 35, 30, tzinfo=timezone.utc),
            source_text="ECB menaikkan suku bunga deposit.",
            direct_image=False,
        ),
        event_class=EventClass.OTHER_COMPANY_OPERATION,
        ranking_band=1,
        material_facts=("ECB menaikkan suku bunga deposit.",),
        dedupe_facts=("ECB deposit rate",),
        summary="ECB menaikkan suku bunga deposit sebesar 25 basis poin.",
        title="ECB naikkan suku bunga deposit 25 bps",
        route=Destination.MACRO_NEWS,
    )

    alert = delivery.format_news_item(item)

    assert alert == (
        "### <:tuntun:1531272430985937086> ECB naikkan suku bunga deposit 25 bps\n\n"
        "*(Ringkasan)* ECB menaikkan suku bunga deposit sebesar 25 basis poin.\n\n"
        "[View on Telegram](<https://t.me/tuntunsekuritas/14786>)"
    )
    assert "Harga terakhir" not in alert


def test_tickered_tuntun_macro_card_has_no_issuer_price_block():
    item = SelectionCandidate(
        candidate=CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=14793,
            ticker="BUMI",
            candidate_id="macro-1",
            source_kind=SourceKind.TUNTUN_UPDATE_SECTION,
            published_at=datetime(2026, 9, 11, 10, 49, 20, tzinfo=timezone.utc),
            source_text="Harga minyak meningkat.",
            direct_image=False,
        ),
        event_class=EventClass.OTHER_COMPANY_OPERATION,
        ranking_band=1,
        material_facts=("Harga minyak meningkat.",),
        dedupe_facts=("harga minyak",),
        summary="Harga minyak meningkat karena risiko pasokan.",
        title="Harga minyak meningkat karena risiko pasokan",
        route=Destination.MACRO_NEWS,
    )

    alert = delivery.format_news_item(item)

    assert "Harga terakhir" not in alert
    assert "BUMI:" not in alert


def test_tuntun_entry_always_marks_the_llm_summary():
    short = _item(
        Provider.TUNTUN,
        14041,
        "RAJA",
        EventClass.OTHER_COMPANY_OPERATION,
        datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
        source_text="RAJA: headline\n" + "x" * 500,
        title="RAJA: Headline singkat",
    )
    long = _item(
        Provider.TUNTUN,
        14042,
        "RAJA",
        EventClass.OTHER_COMPANY_OPERATION,
        datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
        source_text="RAJA: headline\n" + "x" * 501,
        title="RAJA: Headline panjang",
    )

    short_alert = delivery.format_news_item(short)
    long_alert = delivery.format_news_item(long)

    assert "*(Ringkasan)*" in short_alert
    assert "*(Ringkasan)*" in long_alert


def test_tuntun_entry_uses_bold_grey_placeholders_when_market_data_is_unavailable():
    item = _item(
        Provider.TUNTUN,
        14043,
        "RAJA",
        EventClass.OTHER_COMPANY_OPERATION,
        datetime(2026, 7, 23, 5, 51, tzinfo=timezone.utc),
        title="RAJA: Pembaruan operasional",
    )

    alert = delivery.format_news_item(item)

    assert "Harga terakhir (IDR): **-**" in alert
    assert (
        "<:grey:1531279158913536182> 1D: **-**, "
        "<:grey:1531279158913536182> 1W: **-**,\n"
        "<:grey:1531279158913536182> 1M: **-**, "
        "<:grey:1531279158913536182> 3M: **-**"
    ) in alert


def test_pending_delivery_reuses_existing_payload_instead_of_reformatting(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"
    legacy_content = "legacy payload retained"
    state["stats"]["delivery_payloads"] = {}
    state["stats"]["delivery_payloads"][dewa_tier_one.key] = {
        "content": legacy_content,
        "nonce": "legacy-nonce",
        "enforce_nonce": True,
        "text_discord_id": None,
        "image_discord_id": None,
        "image_error": None,
    }
    owner = DeliveredOwner()

    assert asyncio.run(delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner))
    assert [operation.payload["content"] for operation in owner.submissions] == [legacy_content]


def test_entry_uses_complete_legal_name_when_quote_is_unavailable():
    item = _item(
        Provider.TUNTUN,
        1542081138334503023,
        "BTEL",
        EventClass.FINANCING_OR_OWNERSHIP,
        datetime(2026, 8, 20, 6, 18, tzinfo=timezone.utc),
        facts=("ownership clarification",),
        source_text=(
            "📰 BTEL (Mengklarifikasi Kepemilikan 4,85 Miliar Saham PT Bakrie Telecom Tbk)\n\n"
            "Protelindo mengklarifikasi kepemilikan saham BTEL."
        ),
        title="BTEL: Klarifikasi kepemilikan saham",
    )

    alert = delivery.format_news_item(item)

    assert "BTEL: Klarifikasi kepemilikan saham" in alert
    assert "BTEL (Mengklarifikasi Kepemilikan" not in alert


def test_flat_market_change_uses_grey_emoji(monkeypatch, dewa_tier_one):
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda ticker, source_text: MarketSnapshot("PT Darma Henwa Tbk", 472, 0, 0, 0, 0),
    )

    alert = delivery.format_news_item(dewa_tier_one)

    assert alert.count("<:grey:1531279158913536182>") == 4


def test_investment_language_guard_does_not_reject_the_factual_word_holds():
    assert not delivery._contains_investment_language("DSSA holds more than 99% of BMT.")
    assert delivery._contains_investment_language("The source recommends BUY.")


def test_each_news_item_is_a_standalone_message_without_a_shared_heading(monkeypatch, tmp_path, dewa_tier_one):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    second = _item(
        Provider.TUNTUN,
        13601,
        "ADRO",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 20, tzinfo=timezone.utc),
    )
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    for item in (dewa_tier_one, second):
        enqueue_candidate(state, item.candidate, now)
        state["candidates"][item.key]["phase"] = "pending_delivery"
    owner = DeliveredOwner()

    assert asyncio.run(delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner))
    assert asyncio.run(delivery.deliver_event(state, second, "123", now, delivery_client=owner))

    contents = [operation.payload["content"] for operation in owner.submissions]
    assert contents[0].startswith("### <:tuntun:1531272430985937086> DEWA")
    assert contents[1].startswith("### <:tuntun:1531272430985937086> ADRO: Test news")
    assert all("INTRA-DAY" not in message for message in contents)


def test_tier_two_uses_the_same_standalone_format_and_oversize_is_rejected(cbre_tier_two):
    assert delivery.format_news_item(cbre_tier_two).startswith("### <:tuntun:1531272430985937086> CBRE: Test news")
    oversized = _item(
        Provider.TUNTUN,
        13600,
        "ADRO",
        EventClass.CORPORATE_ACTION,
        datetime(2026, 7, 14, 6, 18, tzinfo=timezone.utc),
        facts=("x" * 2_000,),
    )
    with pytest.raises(ValueError, match="2,000"):
        delivery.format_news_item(oversized)


def test_post_text_uses_stable_owner_operation_and_reuses_its_receipt():
    owner = DeliveredOwner()

    assert delivery.post_discord_text("message", "123", "event-key", client=owner) == "5001"
    assert delivery.post_discord_text("message", "123", "event-key", client=owner) == "5001"

    assert len(owner.submissions) == 1
    operation = owner.submissions[0]
    assert operation.kind == "channel_message_create"
    assert operation.key == "bursawatch-market-news:event-key:text"
    assert operation.ordering_key == "channel:123"
    assert operation.target == {"channel_id": "123"}
    assert operation.payload == {"content": "message", "allowed_mentions": {"parse": []}}


def test_post_text_rejects_oversize_before_owner_call():
    owner = DeliveredOwner()

    with pytest.raises(ValueError, match="2,000"):
        delivery.post_discord_text("x" * 2_001, "123", "event-key", client=owner)

    assert owner.submissions == []


def test_post_text_reports_service_errors_without_reading_discord_credentials():
    class RejectedOwner:
        def status(self, operation_key):
            raise delivery.DeliveryClientError("forbidden")

        def submit(self, operation):
            pytest.fail("must not submit after owner rejection")

    with pytest.raises(delivery.DeliveryClientError) as error:
        delivery.post_discord_text("message", "123", "event-key", client=RejectedOwner())
    assert error.value.category == "forbidden"


def test_post_text_leaves_owner_retry_and_rate_limit_state_remote():
    class RetryingOwner(DeliveredOwner):
        def submit(self, operation):
            self.submissions.append(operation)
            receipt = OperationReceipt(
                id="owner-retrying",
                key=operation.key,
                digest=operation.digest,
                status="retrying",
                receipt=None,
            )
            self.operations[operation.key] = receipt
            return receipt

    owner = RetryingOwner()

    assert delivery.post_discord_text("message", "123", "event-key", client=owner) is None

    assert len(owner.submissions) == 1
    assert owner.operations[owner.submissions[0].key].status == "retrying"


def test_post_image_uploads_cached_bytes_and_accepts_200(monkeypatch, tmp_path):
    image = tmp_path / "source.jpg"
    image.write_bytes(b"jpeg bytes")
    owner = DeliveredOwner()

    assert delivery.post_discord_image(image, "123", "event-key", client=owner) == "5001"

    operation = owner.submissions[0]
    assert operation.kind == "channel_message_create"
    assert operation.key == "bursawatch-market-news:event-key:image"
    assert operation.payload["content"] == ""
    assert len(operation.attachments) == 1
    assert operation.attachments[0].filename == "source.jpg"
    assert operation.attachments[0].data == b"jpeg bytes"


def test_capture_direct_image_requires_the_exact_source_message_photo(tmp_path, dewa_tier_one):
    candidate = dewa_tier_one.candidate
    client = SimpleNamespace()
    requested = []

    async def get_messages(entity, ids):
        requested.append((entity, ids))
        return SimpleNamespace(id=ids, photo=object())

    async def download_media(message, file):
        assert file is bytes
        return b"jpeg bytes"

    client.get_messages = get_messages
    client.download_media = download_media

    cached = asyncio.run(delivery.capture_direct_image(client, "source", candidate, tmp_path / "media"))

    assert requested == [("source", candidate.source_message_id)]
    assert cached is not None
    assert cached.read_bytes() == b"jpeg bytes"
    assert cached.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "media").stat().st_mode & 0o777 == 0o700


def test_capture_direct_image_ignores_missing_or_mismatched_photo(tmp_path, dewa_tier_one):
    candidate = dewa_tier_one.candidate

    class Client:
        async def get_messages(self, entity, ids):
            return SimpleNamespace(id=ids + 1, photo=object())

        async def download_media(self, message, file):
            pytest.fail("must not download a mismatched message")

    assert asyncio.run(delivery.capture_direct_image(Client(), "source", candidate, tmp_path)) is None


def test_tier_one_persists_text_before_post_and_marks_delivered_only_after_success(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"
    observed_phase = []

    class Owner(DeliveredOwner):
        def submit(self, operation):
            observed_phase.append(state["candidates"][dewa_tier_one.key]["phase"])
            assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == operation.payload["content"]
            return super().submit(operation)

    owner = Owner()

    assert asyncio.run(
        delivery.deliver_event(
            state,
            dewa_tier_one,
            "123",
            now,
            delivery_client=owner,
            media_directory=tmp_path / "media",
        )
    )
    assert observed_phase == ["pending_delivery"]
    assert state["candidates"][dewa_tier_one.key]["phase"] == "delivered"
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["text_discord_id"] == "5001"
    assert state["last_delivery_success"] == now.isoformat()


def test_unaccepted_owner_request_preserves_payload_and_uses_state_retry(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"

    class UnavailableOwner:
        def status(self, operation_key):
            raise delivery.DeliveryClientError("timeout")

        def submit(self, operation):
            pytest.fail("must not submit after a failed status lookup")


    assert not asyncio.run(
        delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=UnavailableOwner())
    )
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == delivery.format_news_item(
        dewa_tier_one
    )
    assert state["candidates"][dewa_tier_one.key]["phase"] == "pending_delivery"
    assert state["candidates"][dewa_tier_one.key]["retry"]["last_error"] == "Delivery Owner request failed (timeout)"
    retry_due_at = datetime.fromisoformat(
        state["candidates"][dewa_tier_one.key]["retry"]["next_attempt_at"]
    )
    assert retry_due_at >= now + timedelta(minutes=1)
    restored = load_state()
    assert restored["candidates"][dewa_tier_one.key]["phase"] == "pending_delivery"
    assert restored["stats"]["delivery_payloads"][dewa_tier_one.key]["content"] == delivery.format_news_item(
        dewa_tier_one
    )
    assert datetime.fromisoformat(
        restored["candidates"][dewa_tier_one.key]["retry"]["next_attempt_at"]
    ) >= now + timedelta(minutes=1)


def test_text_only_immediate_delivery_never_attempts_source_image(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"
    owner = DeliveredOwner()

    async def broken_capture(*args, **kwargs):
        raise OSError("download failed")

    monkeypatch.setattr(delivery, "capture_direct_image", broken_capture)
    client = SimpleNamespace()

    assert asyncio.run(
        delivery.deliver_event(
            state,
            dewa_tier_one,
            "123",
            now,
            client=client,
            delivery_client=owner,
            entity="source",
            media_directory=tmp_path / "media",
        )
    )
    assert state["candidates"][dewa_tier_one.key]["phase"] == "delivered"
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["image_error"] is None


def test_tier_two_standalone_delivery_never_enters_media_capture(
    monkeypatch, tmp_path, cbre_tier_two
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, cbre_tier_two.candidate, now)
    state["candidates"][cbre_tier_two.key]["phase"] = "pending_delivery"
    owner = DeliveredOwner()

    async def fail_capture(*args, **kwargs):
        pytest.fail("Standalone news delivery must not capture media")

    monkeypatch.setattr(delivery, "capture_direct_image", fail_capture)

    assert asyncio.run(
        delivery.deliver_event(
            state,
            cbre_tier_two,
            "123",
            now,
            client=SimpleNamespace(),
            entity="source",
            delivery_client=owner,
        )
    )
    assert state["candidates"][cbre_tier_two.key]["phase"] == "delivered"


def test_delivery_recovers_lost_acceptance_ack_with_same_operation_key_without_duplicate_create(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"

    class Owner:
        def __init__(self):
            self.operations = {}
            self.submits = []
            self.discord_creates = 0
            self.hide_first_status_after_acceptance = False

        def status(self, operation_key):
            if self.hide_first_status_after_acceptance:
                self.hide_first_status_after_acceptance = False
                return None
            return self.operations.get(operation_key)

        def submit(self, operation):
            self.submits.append(operation)
            previous = self.operations.get(operation.key)
            if previous is None:
                self.discord_creates += 1
                previous = OperationReceipt(
                    id="owner-operation-1",
                    key=operation.key,
                    digest=operation.digest,
                    status="delivered",
                    receipt={"channel_id": "123", "message_id": "456"},
                )
                self.operations[operation.key] = previous
                self.hide_first_status_after_acceptance = True
                raise RuntimeError("accepted but response was lost")
            assert previous.digest == operation.digest
            return previous

        def wait(self, operation_key, timeout_seconds):
            assert timeout_seconds == 0
            return self.operations[operation_key]

    owner = Owner()

    assert not asyncio.run(
        delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner)
    )
    saved = load_state()["stats"]["delivery_payloads"][dewa_tier_one.key]
    assert saved["content"] == delivery.format_news_item(dewa_tier_one)
    assert saved["delivery_handoff"]["state"] == "unknown"
    assert state["candidates"][dewa_tier_one.key]["phase"] == "pending_delivery"

    assert asyncio.run(
        delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner)
    )

    assert state["candidates"][dewa_tier_one.key]["phase"] == "delivered"
    assert state["stats"]["delivery_payloads"][dewa_tier_one.key]["text_discord_id"] == "456"
    assert len(owner.submits) == 2
    assert owner.submits[0].key == owner.submits[1].key
    assert owner.submits[0].digest == owner.submits[1].digest
    assert owner.discord_creates == 1


def test_accepted_service_retry_stays_with_owner_without_local_delivery_backoff(
    monkeypatch, tmp_path, dewa_tier_one
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    state = empty_state()
    now = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    enqueue_candidate(state, dewa_tier_one.candidate, now)
    state["candidates"][dewa_tier_one.key]["phase"] = "pending_delivery"

    class Owner:
        def __init__(self):
            self.operations = {}
            self.submits = 0
            self.status_calls = 0

        def status(self, operation_key):
            self.status_calls += 1
            return self.operations.get(operation_key)

        def submit(self, operation):
            self.submits += 1
            receipt = OperationReceipt(
                id="owner-operation-2",
                key=operation.key,
                digest=operation.digest,
                status="retrying",
                receipt=None,
            )
            self.operations[operation.key] = receipt
            return receipt

        def wait(self, operation_key, timeout_seconds):
            assert timeout_seconds == 0
            return self.operations[operation_key]

    owner = Owner()

    assert not asyncio.run(
        delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner)
    )
    accepted = state["stats"]["delivery_payloads"][dewa_tier_one.key]["delivery_handoff"]
    assert accepted["state"] == "accepted"
    assert accepted["receipt"]["status"] == "retrying"
    assert state["candidates"][dewa_tier_one.key]["retry"]["attempts"] == 0

    assert not asyncio.run(
        delivery.deliver_event(state, dewa_tier_one, "123", now, delivery_client=owner)
    )

    assert owner.submits == 1
    assert owner.status_calls >= 2
    assert state["candidates"][dewa_tier_one.key]["retry"]["attempts"] == 0
@pytest.fixture
def status_event(load_fixture, tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    state = empty_state()
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")
    source_url = "https://t.me/phintasprofits/35377"
    content = format_stock_status(status, source_url)
    event_key = "phintraco-stock-status:35377"
    enqueue_stock_status(state, status, source_url, "123", content, now)
    return SimpleNamespace(
        state=state, event_key=event_key, now=now, content=content
    )


def test_status_delivery_posts_frozen_payload_to_frozen_channel(status_event):
    owner = DeliveredOwner()
    delivered = asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state,
            status_event.event_key,
            status_event.now,
            delivery_client=owner,
        )
    )

    assert delivered is True
    assert len(owner.submissions) == 1
    operation = owner.submissions[0]
    assert operation.target == {"channel_id": "123"}
    assert operation.payload["content"] == status_event.content
    record = status_event.state["stats"]["stock_status_events"][status_event.event_key]
    assert record["phase"] == "delivered"
    assert record["delivery_handoff"]["state"] == "accepted"


def test_status_delivery_transient_failure_keeps_same_owner_operation_for_retry(status_event):
    class Owner:
        def __init__(self):
            self.operations = {}
            self.submissions = []

        def status(self, operation_key):
            return self.operations.get(operation_key)

        def submit(self, operation):
            self.submissions.append(operation)
            if len(self.submissions) == 1:
                raise RuntimeError("temporary")
            receipt = OperationReceipt(
                id="owner-status-1",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": "123", "message_id": "456"},
            )
            self.operations[operation.key] = receipt
            return receipt

        def wait(self, operation_key, timeout_seconds):
            assert timeout_seconds == 0
            return self.operations[operation_key]

    owner = Owner()
    assert not asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state,
            status_event.event_key,
            status_event.now,
            delivery_client=owner,
        )
    )
    event = status_event.state["stats"]["stock_status_events"][status_event.event_key]
    assert event["phase"] == "pending_delivery"
    assert event["retry"]["attempts"] == 1
    assert event["retry"]["last_error"]

    later = status_event.now + timedelta(minutes=1)
    assert asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state,
            status_event.event_key,
            later,
            delivery_client=owner,
        )
    )
    assert len(owner.submissions) == 2
    assert owner.submissions[0].key == owner.submissions[1].key
    assert owner.submissions[0].digest == owner.submissions[1].digest


def test_accepted_status_retry_stays_with_owner_without_local_backoff(status_event):
    class Owner:
        def __init__(self):
            self.operations = {}
            self.submissions = []
            self.status_calls = 0

        def status(self, operation_key):
            self.status_calls += 1
            return self.operations.get(operation_key)

        def submit(self, operation):
            self.submissions.append(operation)
            receipt = OperationReceipt(
                id="owner-status-pending",
                key=operation.key,
                digest=operation.digest,
                status="retrying",
                receipt=None,
            )
            self.operations[operation.key] = receipt
            return receipt

        def wait(self, operation_key, timeout_seconds):
            assert timeout_seconds == 0
            return self.operations[operation_key]

    owner = Owner()
    assert not asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state,
            status_event.event_key,
            status_event.now,
            delivery_client=owner,
        )
    )
    event = status_event.state["stats"]["stock_status_events"][status_event.event_key]
    assert event["delivery_handoff"]["state"] == "accepted"
    assert event["retry"]["attempts"] == 0
    later = status_event.now + timedelta(minutes=1)
    assert not asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state,
            status_event.event_key,
            later,
            delivery_client=owner,
        )
    )
    assert len(owner.submissions) == 1
    assert owner.status_calls >= 2
    assert event["retry"]["attempts"] == 0


def test_oversized_status_payload_never_reaches_discord(monkeypatch, status_event):
    event = status_event.state["stats"]["stock_status_events"][status_event.event_key]
    event["content"] += "x" * (2001 - len(event["content"]))
    monkeypatch.setattr(
        delivery,
        "post_discord_text",
        lambda *_args, **_kwargs: pytest.fail("oversized status reached Discord sender"),
    )

    with pytest.raises(StateBlockedError):
        asyncio.run(
            delivery.deliver_stock_status_event(
                status_event.state, status_event.event_key, status_event.now
            )
        )
