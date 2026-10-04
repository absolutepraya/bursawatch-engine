from dataclasses import replace
from datetime import datetime, timezone

import pytest

import delivery
from agent_protocol import submit_classification
from domain import CompanyCandidate, Destination, EventClass, Provider, SourceKind
from market_data import MarketSnapshot
from selection import SelectionCandidate, pending_selection_candidates
from state import claim_oldest_pending_analysis, empty_state, enqueue_candidate, load_state


SUMMARY = "DEWA memperoleh kontrak baru.\n\nPendanaan disiapkan melalui fasilitas pinjaman."
FULL_QUOTE = MarketSnapshot("PT Darma Henwa Tbk", 472, 32, 7.27, -18, -3.67, 10, 2.16, 100, 26.88)


def _item(provider, summary, route=Destination.ID_STOCKS_NEWS):
    return SelectionCandidate(
        candidate=CompanyCandidate(
            provider=provider,
            source_message_id=42,
            ticker="DEWA",
            source_kind=SourceKind.CORPORATE_ENTRY if provider is Provider.TUNTUN else SourceKind.PHINTRACO_NOTE,
            published_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_text="DEWA (PT Darma Henwa Tbk): kontrak baru dengan fasilitas pinjaman.",
            direct_image=False,
        ),
        event_class=EventClass.MATERIAL_CONTRACT,
        ranking_band=1,
        material_facts=("Kontrak baru", "Fasilitas pinjaman"),
        dedupe_facts=("kontrak", "pinjaman"),
        summary=summary,
        title="DEWA: Kontrak baru" if route is Destination.ID_STOCKS_NEWS else "Pendanaan kegiatan usaha",
        route=route,
    )


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize("route", [Destination.ID_STOCKS_NEWS, Destination.MACRO_NEWS])
@pytest.mark.parametrize("quote", [FULL_QUOTE, None, replace(FULL_QUOTE, one_month_change=None, one_month_percent=None)])
def test_paragraphs_survive_submission_reload_and_shared_card(provider, route, quote, monkeypatch, tmp_path):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    item = _item(provider, SUMMARY, route)
    now = item.published_at
    state = empty_state()
    enqueue_candidate(state, item.candidate, now)
    assert claim_oldest_pending_analysis(state, now) == item.candidate
    payload = {
        "candidate_key": item.key,
        "ticker": item.ticker,
        "event_class": item.event_class.value,
        "summary": SUMMARY,
        "material_facts": list(item.material_facts),
        "dedupe_facts": list(item.dedupe_facts),
        "ranking_band": 1,
        "eligible": True,
        "route": route.value,
        "source_evidence": item.candidate.source_text,
    }
    if provider is Provider.TUNTUN:
        payload["title"] = item.title
    submit_classification(state, item.candidate, payload, now)

    restored = load_state()
    assert restored["candidates"][item.key]["selection"]["summary"] == SUMMARY
    selected, = pending_selection_candidates(restored)
    assert selected.summary == SUMMARY
    quote_calls = []

    def market_snapshot(ticker, source_text):
        quote_calls.append(ticker)
        return quote

    monkeypatch.setattr(delivery, "get_market_snapshot", market_snapshot)
    content = delivery.format_news_item(selected)
    assert f"*(Ringkasan)* {SUMMARY}\n\n" in content
    assert content.count("*(Ringkasan)*") == 1
    username = "tuntunsekuritas" if provider is Provider.TUNTUN else "phintasprofits"
    assert content.count(f"[View on Telegram](<https://t.me/{username}/42>)") == 1
    if route is Destination.MACRO_NEWS:
        assert "Harga terakhir" not in content
        assert quote_calls == []
    else:
        assert quote_calls == ["DEWA"]
        assert content.count("Harga terakhir (IDR):") == 1
        for horizon in ("1D", "1W", "1M", "3M"):
            assert content.count(f"{horizon}:") == 1
        if quote is None:
            assert "Harga terakhir (IDR): **-**" in content
            assert content.count("<:grey:1531279158913536182>") == 4
        else:
            assert "Harga terakhir (IDR): **472**" in content
            assert "<:green:1531274822221434911> 1D: **+32 (+7.27%)**" in content
            assert "<:red:1531274756853202974> 1W: **-18 (-3.67%)**" in content
            expected_month = "**-**" if quote.one_month_change is None else "**+10 (+2.16%)**"
            assert f"1M: {expected_month}" in content
            assert "3M: **+100 (+26.88%)**" in content


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize(
    "summary",
    [
        "Phintraco melaporkan kontrak baru untuk DEWA.",
        "DEWA memperoleh kontrak baru.\n\nPendanaan disiapkan.\n\nPelaksanaan dimulai bulan depan.",
    ],
)
def test_style_preferences_do_not_block_otherwise_valid_submissions(provider, summary, monkeypatch, tmp_path):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    item = _item(provider, summary)
    now = item.published_at
    state = empty_state()
    enqueue_candidate(state, item.candidate, now)
    claim_oldest_pending_analysis(state, now)
    payload = {
        "candidate_key": item.key, "ticker": item.ticker, "event_class": item.event_class.value,
        "summary": summary, "material_facts": list(item.material_facts),
        "dedupe_facts": list(item.dedupe_facts), "ranking_band": 1, "eligible": True,
        "route": item.route.value, "source_evidence": item.candidate.source_text,
    }
    if provider is Provider.TUNTUN:
        payload["title"] = item.title
    submit_classification(state, item.candidate, payload, now)
    selected, = pending_selection_candidates(load_state())
    assert f"*(Ringkasan)* {summary}\n\n" in delivery.format_news_item(selected)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  DEWA  memperoleh\nkontrak baru. \r\n \t\r\n\r\n Pendanaan\tdisiapkan.  ",
         "DEWA memperoleh kontrak baru.\n\nPendanaan disiapkan."),
        ("DEWA\r\nmemperoleh kontrak baru.", "DEWA memperoleh kontrak baru."),
        (" \n\t ", "Kontrak baru Fasilitas pinjaman"),
    ],
)
def test_summary_whitespace_normalization_preserves_only_paragraph_boundaries(raw, expected):
    item = _item(Provider.TUNTUN, raw)
    assert item.summary == expected
    assert item.material_facts == ("Kontrak baru", "Fasilitas pinjaman")
    assert item.dedupe_facts == ("kontrak", "pinjaman")
    assert item.title == "DEWA: Kontrak baru"


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize("route", [Destination.ID_STOCKS_NEWS, Destination.MACRO_NEWS])
@pytest.mark.parametrize("flat_length", [1999, 2000, 2001])
def test_paragraph_spacing_cannot_break_a_card_that_previously_fit(provider, route, flat_length, monkeypatch):
    seed = _item(provider, "DEWA.\n\nPendanaan disiapkan.", route)
    flat_seed = replace(seed, summary="DEWA. Pendanaan disiapkan.")
    flat_content = delivery.format_news_item(flat_seed)
    padding = "x" * (flat_length - len(flat_content))
    item = replace(seed, summary=f"DEWA{padding}.\n\nPendanaan disiapkan.")
    assert "\n\n" in item.summary
    quote_calls = []
    monkeypatch.setattr(delivery, "get_market_snapshot", lambda *args: quote_calls.append(args) or None)
    if flat_length > 2000:
        with pytest.raises(ValueError, match="2,000-character"):
            delivery.format_news_item(item)
    else:
        content = delivery.format_news_item(item)
        assert len(content) == 2000
        expected_summary = item.summary if flat_length == 1999 else " ".join(item.summary.split())
        assert f"*(Ringkasan)* {expected_summary}\n\n" in content
        assert item.summary.endswith("\n\nPendanaan disiapkan.")
        assert content.count("*(Ringkasan)*") == 1
        assert content.endswith(flat_content.split("\n\n")[-1])
        if route is Destination.ID_STOCKS_NEWS:
            assert content.split("Harga terakhir")[1] == flat_content.split("Harga terakhir")[1]
    assert len(quote_calls) == (1 if route is Destination.ID_STOCKS_NEWS else 0)
