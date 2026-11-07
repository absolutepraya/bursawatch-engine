from pathlib import Path
import sys
import time

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


def test_lookup_exact_source_symbol_requires_matching_market_and_equity():
    issuer = row("ASSA.JK", "PT Adi Sarana Armada Tbk", "JKT")
    assert news_identity.lookup_company("ASSA", "ID", search=lambda _: [issuer])["ticker"] == "ASSA"
    assert news_identity.lookup_company("ASSA", "US", search=lambda _: [issuer])["status"] == "unresolved"
    assert news_identity.lookup_company("ASSA", "ID", search=lambda _: [row("ASSA-B.ST", "ASSA ABLOY", "STO")])["status"] == "unresolved"


def test_idx_ticker_qualifies_search_before_unrelated_us_results():
    searches = []
    def search(query):
        searches.append(query)
        return [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")] if query == "BULL.JK" else [row("BULL", "Webull Corporation", "NCM")]
    result = news_identity.lookup_company("BULL", "ID", search=search)
    assert (result["ticker"], result["symbol"], result["exchange"]) == ("BULL", "BULL.JK", "JKT")
    assert searches == ["BULL.JK"]
    assert "business_home" not in result


def test_idx_already_qualified_symbol_and_us_collision_stay_distinct():
    def search(query):
        return {"BULL.JK": [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")],
                "BULL": [row("BULL", "Webull Corporation", "NCM")]}.get(query, [])
    assert news_identity.lookup_company("BULL.JK", "ID", search=search)["ticker"] == "BULL"
    assert news_identity.lookup_company("BULL", "US", search=search)["name"] == "Webull Corporation"


def test_idx_symbol_fallback_never_accepts_another_security_or_wrong_exchange():
    calls = []
    def search(query):
        calls.append(query)
        if query == "BULL.JK":
            return [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "NYQ")]
        return [row("BUIL.JK", "BULL", "JKT"), row("BULL", "Webull Corporation", "NCM")]
    assert news_identity.lookup_company("BULL", "ID", search=search)["status"] == "unresolved"
    assert calls == ["BULL.JK", "BULL"]


def test_idx_unqualified_fallback_runs_when_qualified_search_fails():
    def search(query):
        if query == "BULL.JK":
            raise OSError("temporary provider failure")
        return [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")]
    assert news_identity.lookup_company("BULL", "ID", search=search)["ticker"] == "BULL"



def test_idx_fallback_gets_time_after_a_slow_qualified_search():
    def search(query):
        if query == "BULL.JK":
            time.sleep(3.0)
            return []
        time.sleep(0.7)
        return [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")]
    assert news_identity.lookup_company("BULL", "ID", search=search)["ticker"] == "BULL"


def test_ticker_like_company_name_requires_source_evidence_for_symbol(monkeypatch):
    issuer = row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")
    monkeypatch.setattr(news_identity, "_search", lambda _: [issuer])
    item = {"title":"BULL: Opens a factory", "route":"id_stocks_news", "ticker":"BULL",
            "subject":{"kind":"company", "name":"BULL", "evidence":"BULL opens a factory",
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    assert news_identity.prepare_item(item, "BULL opens a factory")[1] is None
    assert news_identity.prepare_item(item, "BULL: Company update\nBULL opens a factory")[1] == "BULL"
    assert news_identity.prepare_item(item, "Other company $BULL.B rises. BULL opens a factory")[1] is None


def test_ticker_like_name_can_use_source_pair_with_verified_issuer(monkeypatch):
    issuer = row("CASA.JK", "PT Capital Financial Indonesia Tbk", "JKT")
    monkeypatch.setattr(news_identity, "_search", lambda _: [issuer])
    item = {"title":"CASA: BEI memeriksa saham", "route":"id_stocks_news", "ticker":"CASA",
            "subject":{"kind":"company", "name":"CASA", "evidence":"CASA",
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    paired = "BEI memeriksa saham PT Capital Financial Indonesia Tbk (CASA)."
    assert news_identity.prepare_item(item, paired)[1] == "CASA"
    unrelated = "CASA expands while PT Other Company Tbk (CASA) falls."
    assert news_identity.prepare_item(item, unrelated)[1] is None
    other_symbol = "CASA expands while PT Capital Financial Indonesia Tbk (CASA.B) falls."
    assert news_identity.prepare_item(item, other_symbol)[1] is None

def test_idx_conflicting_company_names_for_same_symbol_are_unresolved():
    rows = [row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT"),
            row("BULL.JK", "Other Issuer Tbk", "JKT")]
    assert news_identity.lookup_company("BULL", "ID", search=lambda _: rows)["status"] == "unresolved"


def test_idx_security_lookup_does_not_rewrite_business_home(monkeypatch):
    issuer = row("BULL.JK", "PT Buana Lintas Lautan Tbk", "JKT")
    monkeypatch.setattr(news_identity, "_search", lambda query: [issuer] if query == "BULL.JK" else [])
    text = "BULL: New shipping contracts\nBULL announced new shipping contracts."
    item = {"title":"BULL: New shipping contracts", "route":"global_company_news", "ticker":"BULL",
            "subject":{"kind":"company", "name":"BULL", "evidence":text,
                       "company":{"business_home":"GLOBAL", "listing_status":"listed", "security_market":"ID"}}}
    result, ticker = news_identity.prepare_item(item, text)
    assert ticker == "BULL" and result["route"] == "global_company_news"
    assert result["subject"]["company"]["business_home"] == "GLOBAL"


def test_lookup_may_supply_matching_headquarters_as_a_hint():
    issuer = row("ASSA.JK", "PT Adi Sarana Armada Tbk", "JKT")
    match = lambda _: {"symbol":"ASSA.JK", "country":"Indonesia"}
    assert news_identity.lookup_company("ASSA", "ID", search=lambda _: [issuer], details=match)["headquarters_country"] == "Indonesia"
    other = lambda _: {"symbol":"OTHER.JK", "country":"Indonesia"}
    assert "headquarters_country" not in news_identity.lookup_company("ASSA", "ID", search=lambda _: [issuer], details=other)


def test_busy_optional_country_lookup_does_not_block_security_lookup():
    issuer = row("ASSA.JK", "PT Adi Sarana Armada Tbk", "JKT")
    assert news_identity._DETAIL_SLOTS.acquire(blocking=False)
    assert news_identity._DETAIL_SLOTS.acquire(blocking=False)
    try:
        result = news_identity.lookup_company("ASSA", "ID", search=lambda _: [issuer], details=lambda _: pytest.fail("no slot"))
        assert result["ticker"] == "ASSA" and "headquarters_country" not in result
    finally:
        news_identity._DETAIL_SLOTS.release()
        news_identity._DETAIL_SLOTS.release()


def test_source_ticker_and_product_alias_are_accepted_only_when_directly_linked(monkeypatch):
    source = "BREAKING: Snapchat stock, $SNAP, falls over -10% after posting weaker than expected earnings."
    subject = {"kind":"company", "name":"Snapchat", "evidence":"Snapchat stock, $SNAP, falls over -10% after posting weaker than expected earnings.", "company":{"business_home":"US", "listing_status":"listed", "security_market":"US"}}
    item = {"title":"SNAP: Snapchat falls after earnings", "ticker":"SNAP", "route":"us_stocks_news", "subject":subject}
    monkeypatch.setattr(news_identity, "lookup_company", lambda name, market: {"status":"verified", "ticker":"SNAP"} if name == "SNAP" else {"status":"unresolved"})
    result, ticker = news_identity.prepare_item(item, source)
    assert ticker == "SNAP" and result["route"] == "us_stocks_news"
    unrelated = "Snapchat expands while another company $SNAP declines."
    other = {**item, "subject":{**subject,"evidence":unrelated}}
    assert news_identity.prepare_item(other, unrelated)[1] is None
    different_security = "Snapchat stock, $SNAP.B, falls after earnings."
    other = {**item, "subject":{**subject,"evidence":different_security}}
    assert news_identity.prepare_item(other, different_security)[1] is None


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
