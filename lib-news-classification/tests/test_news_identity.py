from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import news_identity


@pytest.mark.parametrize("ticker,issuer,source,evidence", [
    ("BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk",
     "Muncul Lapkeu BBRI\nPT Bank Rakyat Indonesia Tbk (BBRI) mengumumkan laba meningkat.",
     "mengumumkan laba meningkat"),
    ("RAJA", "PT Rukun Raharja Tbk",
     "RAJA Ekspansi Bisnis\nPT Rukun Raharja Tbk. (RAJA) mengakuisisi KNJ.",
     "RAJA Ekspansi Bisnis"),
])
def test_issuer_pair_elsewhere_does_not_bind_focus(ticker, issuer, source, evidence, monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row(ticker + ".JK", issuer)])
    item = {"title": ticker + ": Berita", "ticker": ticker, "route": "id_stocks_news",
            "subject": {"kind": "company", "name": ticker, "evidence": evidence,
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


@pytest.mark.parametrize("ticker,issuer,evidence", [
    ("BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk", "PT Bank Rakyat Indonesia Tbk (BBRI) mengumumkan laba meningkat"),
    ("BBRI", "PT Bank Rakyat Indonesia (Persero) Tbk", "Bank Rakyat Indonesia Tbk (BBRI) mengumumkan laba meningkat"),
    ("RAJA", "PT Rukun Raharja Tbk", "PT Rukun Raharja Tbk. (RAJA) mengakuisisi KNJ"),
])
def test_focus_evidence_can_bind_normalized_issuer_pair(ticker, issuer, evidence, monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row(ticker + ".JK", issuer)])
    item = {"title": ticker + ": Berita", "ticker": ticker, "route": "id_stocks_news",
            "subject": {"kind": "company", "name": ticker, "evidence": evidence,
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, evidence + ".")[1] == ticker


def test_short_focus_name_with_direct_verified_pair_retains_ticker(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row("BBCA.JK", "PT Bank Central Asia Tbk")])
    evidence = "BCA (BBCA) reports earnings"
    item = {"title": "BBCA: Earnings", "ticker": "BBCA", "route": "id_stocks_news",
            "subject": {"kind": "company", "name": "BCA", "evidence": evidence,
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, evidence + ".")[1] == "BBCA"
    item["subject"]["evidence"] = "BCA reports earnings"
    assert news_identity.prepare_item(item, "BCA reports earnings; other firm $BBCA falls.")[1] is None


def test_issuer_pair_does_not_accept_related_or_different_company(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row("BBRI.JK", "PT Bank Rakyat Indonesia (Persero) Tbk")])
    source = "BBRI expands. PT Bank Rakyat Indonesia Syariah Tbk. (BBRI) reports results."
    item = {"title": "BBRI: Berita", "ticker": "BBRI", "route": "id_stocks_news",
            "subject": {"kind": "company", "name": "BBRI", "evidence": "BBRI expands",
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_explicit_symbol_does_not_override_wrong_market_issuer(monkeypatch):
    def search(query):
        return {"BULL.JK": [row("BULL.JK", "PT Buana Lintas Lautan Tbk")],
                "BULL": [row("BULL", "Webull Corporation", "NCM")]}.get(query, [])
    monkeypatch.setattr(news_identity, "_search", search)
    source = "$BULL Webull Corporation reports earnings."
    item = {"title": "BULL: Earnings", "ticker": "BULL", "route": "us_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": source,
                        "company": {"business_home": "US", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_wrong_named_issuer_is_not_accepted_when_other_market_is_unavailable(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda query: [row("BULL.JK", "PT Buana Lintas Lautan Tbk")] if query == "BULL.JK" else [])
    source = "$BULL Webull Corporation reports earnings."
    item = {"title": "BULL: Earnings", "ticker": "BULL", "route": "us_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": source,
                        "company": {"business_home": "US", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_unknown_other_market_does_not_validate_different_focus_name(monkeypatch):
    def search(query):
        if query == "BULL.JK":
            return [row("BULL.JK", "PT Buana Lintas Lautan Tbk")]
        raise TimeoutError("provider unavailable")
    monkeypatch.setattr(news_identity, "_search", search)
    source = "$BULL Webull reports earnings."
    item = {"title": "BULL: Earnings", "ticker": "BULL", "route": "us_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": source,
                        "company": {"business_home": "US", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_shared_symbol_without_focus_issuer_does_not_choose_a_market(monkeypatch):
    def search(query):
        return {"BULL.JK": [row("BULL.JK", "PT Buana Lintas Lautan Tbk")],
                "BULL": [row("BULL", "Webull Corporation", "NCM")]}.get(query, [])
    monkeypatch.setattr(news_identity, "_search", search)
    source = "$BULL reports earnings."
    item = {"title": "BULL: Earnings", "ticker": "BULL", "route": "us_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": source,
                        "company": {"business_home": "US", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_source_pair_for_other_company_cannot_override_focus_issuer(monkeypatch):
    def search(query):
        return {"BULL.JK": [row("BULL.JK", "PT Buana Lintas Lautan Tbk")],
                "BULL": [row("BULL", "Webull Corporation", "NCM")]}.get(query, [])
    monkeypatch.setattr(news_identity, "_search", search)
    evidence = "$BULL Webull reports earnings."
    source = evidence + " PT Buana Lintas Lautan Tbk (BULL) is a different company."
    item = {"title": "BULL: Earnings", "ticker": "BULL", "route": "us_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": evidence,
                        "company": {"business_home": "US", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_issuer_pair_elsewhere_is_not_proof_of_private_focus(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda query: [row("BULL.JK", "PT Buana Lintas Lautan Tbk")] if query == "BULL.JK" else [])
    evidence = "BULL startup launches a product"
    source = evidence + ". Separately, PT Buana Lintas Lautan Tbk (BULL) reported its earnings."
    item = {"title": "BULL: New product", "ticker": "BULL", "route": "id_stocks_news",
            "subject": {"kind": "company", "name": "BULL", "evidence": evidence,
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None
    item["subject"]["evidence"] = source.rstrip(".")
    assert news_identity.prepare_item(item, source)[1] is None


def test_named_counterparty_is_not_focus_evidence(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row("BULL.JK", "PT Buana Lintas Lautan Tbk")])
    evidence = "Private startup announces a new product"
    source = evidence + ". PT Buana Lintas Lautan Tbk (BULL) is also mentioned."
    item = {"title": "BULL: New product", "ticker": "BULL", "route": "id_stocks_news",
            "subject": {"kind": "company", "name": "Buana Lintas Lautan", "evidence": evidence,
                        "company": {"business_home": "ID", "listing_status": "listed", "security_market": "ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None
    long_evidence = source.rstrip(".")
    item["subject"]["evidence"] = long_evidence
    assert news_identity.prepare_item(item, source)[1] is None


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
    assert news_identity.prepare_item(item, "BULL: Company update\nBULL opens a factory")[1] is None
    assert news_identity.prepare_item(item, "Other company $BULL.B rises. BULL opens a factory")[1] is None


def test_ticker_like_name_can_use_source_pair_with_verified_issuer(monkeypatch):
    issuer = row("CASA.JK", "PT Capital Financial Indonesia Tbk", "JKT")
    monkeypatch.setattr(news_identity, "_search", lambda _: [issuer])
    item = {"title":"CASA: BEI memeriksa saham", "route":"id_stocks_news", "ticker":"CASA",
            "subject":{"kind":"company", "name":"CASA", "evidence":"CASA",
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    paired = "BEI memeriksa saham PT Capital Financial Indonesia Tbk (CASA)."
    assert news_identity.prepare_item(item, paired)[1] is None
    bound = {**item, "subject": {**item["subject"], "evidence": "PT Capital Financial Indonesia Tbk (CASA)"}}
    assert news_identity.prepare_item(bound, paired)[1] == "CASA"
    unrelated = "CASA expands while PT Other Company Tbk (CASA) falls."
    assert news_identity.prepare_item(item, unrelated)[1] is None
    other_symbol = "CASA expands while PT Capital Financial Indonesia Tbk (CASA.B) falls."
    assert news_identity.prepare_item(item, other_symbol)[1] is None


@pytest.mark.parametrize("ticker,name,source,evidence", [
    ("ROTI", "PT Nippon Indosari Corpindo Tbk", "$ROTI AKAN MUSNAHKAN SAHAM\nSari Roti berencana menarik saham.", "Sari Roti berencana menarik saham."),
    ("AMMN", "PT Amman Mineral Internasional Tbk", "PENDAPATAN AMMN TURUN\nForeign net outflow saham AMMN Rp4,75 triliun.", "saham AMMN"),
])
def test_explicit_source_stock_symbol_alone_does_not_identify_issuer(ticker, name, source, evidence, monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row(ticker + ".JK", name, "JKT")])
    item = {"title": ticker + ": Kabar perusahaan", "route":"id_stocks_news", "ticker":ticker,
            "subject":{"kind":"company", "name":ticker, "evidence":evidence,
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None


def test_unrelated_or_partial_source_symbol_is_not_accepted(monkeypatch):
    monkeypatch.setattr(news_identity, "_search", lambda _: [row("ROTI.JK", "PT Nippon Indosari Corpindo Tbk", "JKT")])
    item = {"title":"ROTI: Kabar perusahaan", "route":"id_stocks_news", "ticker":"ROTI",
            "subject":{"kind":"company", "name":"ROTI", "evidence":"ROTI expands",
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    for source in ("ROTI expands while $ROTI.B falls.", "ROTI expands while saham ROTIX falls.",
                   "ROTI expands while another firm $ROTI falls."):
        assert news_identity.prepare_item(item, source)[1] is None


@pytest.mark.parametrize("source,evidence,expected", [
    ("$ROTI_BARU grows", "ROTI_BARU grows", False),
    ("ROTI grows. saham ROTI_BARU rises", "ROTI grows. saham ROTI_BARU rises", False),
    ("ROTI grows. saham\n\nROTI rises", "ROTI grows. saham\n\nROTI rises", False),
    ("ROTI grows. Another firm holds saham ROTI", "ROTI grows", False),
    ("$ROTI announces a deal with OTHER", "OTHER announces a deal", False),
    ("$ROTI. Company update", "ROTI", True),
    ("saham ROTI.", "saham ROTI.", True),
    ("saham $ROTI.", "saham $ROTI.", True),
    ("$ROTI.B falls", "ROTI.B falls", False),
])
def test_explicit_symbol_boundaries_and_focus_evidence(source, evidence, expected):
    assert news_identity._source_explicit_symbol(source, evidence, "ROTI") is expected


def test_mixed_case_ticker_subject_uses_explicit_symbol_lookup(monkeypatch):
    def search(query):
        return [row("ROTI.JK", "PT Nippon Indosari Corpindo Tbk", "JKT")] if query == "ROTI.JK" else []
    monkeypatch.setattr(news_identity, "_search", search)
    source = "$ROTI earns revenue. Roti grows."
    item = {"title":"ROTI: Kabar perusahaan", "route":"id_stocks_news", "ticker":"ROTI",
            "subject":{"kind":"company", "name":"Roti", "evidence":"Roti grows",
                       "company":{"business_home":"ID", "listing_status":"listed", "security_market":"ID"}}}
    assert news_identity.prepare_item(item, source)[1] is None

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
    assert ticker is None and result["route"] == "global_company_news"
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
