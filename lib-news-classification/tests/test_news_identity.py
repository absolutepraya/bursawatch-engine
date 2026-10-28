from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import news_identity


def row(symbol="BACH.JK", name="Bach Multi Global Tbk.", exchange="JKT"):
    return {"symbol": symbol, "longname": name, "exchange": exchange, "quoteType": "EQUITY"}


def test_lookup_requires_unique_company_name_and_correct_exchange():
    query = "PT Bach Multi Global Tbk"
    verified = news_identity.lookup_company(query, search=lambda _: [row()])
    assert verified["ticker"] == "BACH"
    assert verified["symbol"] == "BACH.JK"
    assert verified["source_url"] == "https://finance.yahoo.com/quote/BACH.JK/"
    for results in [[], [row(name="Another Company Tbk")], [row(exchange="NYQ")],
                    [row(), row(symbol="ABCD.JK")]]:
        assert news_identity.lookup_company(query, search=lambda _: results)["status"] == "unresolved"


def test_lookup_preserves_us_listing_and_never_uses_an_idx_symbol_for_us():
    result = news_identity.lookup_company("Microsoft", "US", search=lambda _: [row("MSFT", "Microsoft Corporation", "NMS")])
    assert result["ticker"] == "MSFT"
    assert news_identity.lookup_company("Bach Multi Global", "US", search=lambda _: [row()])["status"] == "unresolved"


def test_lookup_failure_is_unresolved_instead_of_a_guessed_security():
    def broken(_):
        raise OSError("provider unavailable")
    assert news_identity.lookup_company("Bach Multi Global", search=broken)["status"] == "unresolved"


def test_lookup_does_not_fuzzy_match_short_names_or_subsidiaries():
    assert news_identity.lookup_company("Bach", search=lambda _: [row()])["status"] == "unresolved"
    assert news_identity.lookup_company("Bach Multi Global Logistics", search=lambda _: [row()])["status"] == "unresolved"


def company_item():
    return {"title": "BACH: Laba meningkat", "ticker": "BACH", "route": "id_stocks_news",
            "subject": {"kind": "company", "name": "Bach Multi Global", "evidence": "Bach Multi Global mencatat laba meningkat"}}


def test_external_ticker_is_independently_verified_without_adding_news_facts(monkeypatch):
    item = company_item()
    monkeypatch.setattr(news_identity, "lookup_company", lambda *args: {"status": "verified", "ticker": "BACH"})
    normalized, verified = news_identity.prepare_item(item, "Bach Multi Global mencatat laba meningkat.")
    assert normalized == item
    assert verified == "BACH"


def test_failed_external_ticker_becomes_name_only_stock_news(monkeypatch):
    monkeypatch.setattr(news_identity, "lookup_company", lambda *args: {"status": "unresolved"})
    normalized, verified = news_identity.prepare_item(company_item(), "Bach Multi Global mencatat laba meningkat.")
    assert normalized["route"] == "id_stocks_news"
    assert normalized["ticker"] == ""
    assert normalized["title"] == "Bach Multi Global: Laba meningkat"
    assert verified is None


def test_missing_ticker_and_source_ticker_do_not_trigger_lookup(monkeypatch):
    monkeypatch.setattr(news_identity, "lookup_company", lambda *args: pytest.fail("unnecessary lookup"))
    item = company_item()
    assert news_identity.prepare_item(item, "Bach Multi Global mencatat laba meningkat (BACH).")[0] == item
    item["ticker"] = ""
    assert news_identity.prepare_item(item, "Bach Multi Global mencatat laba meningkat.")[1] is None


def test_lookup_has_closed_input_schema():
    for payload in [{"company": "Bach", "market": "ID", "url": "https://example.test"},
                    {"company": "", "market": "ID"}, {"company": "Bach", "market": "unknown"}]:
        with pytest.raises(ValueError):
            news_identity.lookup_payload(payload)
