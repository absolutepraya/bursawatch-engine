from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import news_identity
import news_subject


def subject(home="UNKNOWN", status="private", market=""):
    return {"kind": "company", "name": "Example Business", "evidence": "Example Business plans an IPO",
            "company": {"business_home": home, "listing_status": status, "security_market": market}}


@pytest.mark.parametrize("home,route", [("ID", "id_stocks_news"), ("US", "us_stocks_news"),
                                         ("GLOBAL", "global_company_news"), ("UNKNOWN", "global_company_news")])
def test_business_home_controls_company_route_independently_of_listing(home, route):
    value = news_subject.validate_subject(subject(home), "Example Business plans an IPO")
    assert news_subject.route_for(value) == route
    assert news_subject.quote_route(value, route) is None
    for wrong in news_subject.COMPANY_ROUTES | {"macro_news"} - {route}:
        if wrong != route:
            with pytest.raises(ValueError, match="subject"):
                news_subject.validate_route(value, wrong)


def test_foreign_business_can_have_a_verified_us_security():
    value = news_subject.validate_subject(subject("GLOBAL", "listed", "US"))
    assert news_subject.route_for(value) == "global_company_news"
    assert news_subject.quote_route(value, "global_company_news") == "us_stocks_news"


@pytest.mark.parametrize("status", ["private", "pre_ipo", "formerly_listed", "unknown"])
@pytest.mark.parametrize("prefix", ["PARENT:", "PARENT :"])
def test_nonlisted_focus_company_never_inherits_a_source_ticker(monkeypatch, status, prefix):
    monkeypatch.setattr(news_identity, "lookup_company", lambda *_: pytest.fail("nonlisted company must not look up a ticker"))
    item = {"subject": subject("US", status), "route": "us_stocks_news", "ticker": "PARENT",
            "title": prefix + " Plans an IPO"}
    normalized, verified = news_identity.prepare_item(item, "Example Business plans an IPO; PARENT is mentioned")
    assert normalized["ticker"] == "" and verified is None
    assert normalized["title"] == "Example Business: Plans an IPO" and "PARENT" not in normalized["title"]


def test_even_source_mentioned_security_requires_focus_company_verification(monkeypatch):
    monkeypatch.setattr(news_identity, "lookup_company", lambda *_: {"status": "verified", "ticker": "OTHER"})
    item = {"subject": subject("GLOBAL", "listed", "US"), "route": "global_company_news", "ticker": "PARENT"}
    normalized, verified = news_identity.prepare_item(item, "Example Business plans an IPO; PARENT is mentioned")
    assert normalized["ticker"] == "" and verified is None


def test_verified_current_security_can_be_used_without_a_ticker_headline(monkeypatch):
    calls = []
    def lookup(company, market):
        calls.append((company, market))
        return {"status": "verified", "ticker": "EXAMPLE"}
    monkeypatch.setattr(news_identity, "lookup_company", lookup)
    item = {"subject": subject("GLOBAL", "listed", "US"), "route": "global_company_news", "ticker": "EXAMPLE",
            "title": "Example Business expands production"}
    normalized, verified = news_identity.prepare_item(item, "Example Business plans an IPO; EXAMPLE is mentioned")
    assert calls == [("Example Business", "US")]
    assert verified == normalized["ticker"] == "EXAMPLE"
    assert normalized["title"] == item["title"]


@pytest.mark.parametrize("change", [{"business_home": "CN"}, {"security_market": "CN"},
                                  {"listing_status": "private", "security_market": "US"}, {"extra": "ignored"}])
def test_company_details_remain_closed_and_consistent(change):
    value = subject()
    value["company"].update(change)
    with pytest.raises(ValueError, match="company|listed"):
        news_subject.validate_subject(value)


def test_legacy_subject_remains_readable_but_new_claim_requires_details():
    legacy = {"kind": "company", "name": "Example", "evidence": "Example expands"}
    assert news_subject.validate_subject(legacy) == legacy
    assert news_subject.validate_route(legacy, "us_stocks_news") == "us_stocks_news"
    with pytest.raises(ValueError, match="details"):
        news_subject.require_company_details(legacy)


@pytest.mark.parametrize("title", ["PARENT: Laporan kaitkan CEO dengan pengiriman chip", "PARENT : Laporan kaitkan CEO dengan pengiriman chip"])
def test_dropped_ticker_prefix_becomes_a_colon_separated_company_name(monkeypatch, title):
    """A ticker that fails verification must not leave `<Name> <predicate>` (live bug: `Nvidia Laporan kaitkan...`)."""
    monkeypatch.setattr(news_identity, "lookup_company", lambda *_: {"status": "unresolved"})
    item = {"subject": subject("US", "listed", "US"), "route": "us_stocks_news", "ticker": "PARENT", "title": title}
    normalized, verified = news_identity.prepare_item(item, "Example Business plans an IPO; PARENT is mentioned")
    assert verified is None and normalized["ticker"] == ""
    assert normalized["title"] == "Example Business: Laporan kaitkan CEO dengan pengiriman chip"


def test_dropped_ticker_prefix_keeps_a_body_that_already_names_the_company(monkeypatch):
    monkeypatch.setattr(news_identity, "lookup_company", lambda *_: {"status": "unresolved"})
    item = {"subject": subject("US", "listed", "US"), "route": "us_stocks_news", "ticker": "PARENT",
            "title": "PARENT: Saham Example Business turun"}
    assert news_identity.prepare_item(item, "Example Business plans an IPO; PARENT is mentioned")[0]["title"] == "Saham Example Business turun"


def test_dropped_symbol_only_name_never_renders_as_a_verified_ticker_prefix(monkeypatch):
    """A `SYMBOL:` prefix would claim a verified security; the symbol-like name keeps the unprefixed form."""
    monkeypatch.setattr(news_identity, "lookup_company", lambda *_: {"status": "unresolved"})
    value = subject("ID", "listed", "ID")
    value["name"] = value["evidence"] = "PARENT"
    item = {"subject": value, "route": "id_stocks_news", "ticker": "PARENT", "title": "PARENT: Transaksi nego besar"}
    normalized, verified = news_identity.prepare_item(item, "PARENT mencatat transaksi nego besar")
    assert verified is None and normalized["title"] == "PARENT Transaksi nego besar"


def _unknown_company():
    return {"kind": "company", "name": "BNI", "evidence": "BNI Mobile Banking",
            "company": {"business_home": "UNKNOWN", "listing_status": "listed", "security_market": ""}}


def test_uncertain_company_follows_an_account_with_one_company_destination():
    snapped, route = news_subject.snap_unknown_geography(_unknown_company(), {"macro_news", "id_stocks_news", "id_stocks_swing"})
    assert route == "id_stocks_news" and snapped["company"]["business_home"] == "ID"
    assert news_subject.route_for(snapped) == "id_stocks_news"
    assert _unknown_company()["company"]["business_home"] == "UNKNOWN"  # the input is never mutated


@pytest.mark.parametrize("configured", [
    {"macro_news"},                                   # no destination of its kind
    {"id_stocks_news", "us_stocks_news"},             # two destinations: nothing to infer
    {"id_stocks_news", "id_industry_news"},           # an industry destination is another kind
])
def test_snap_needs_exactly_one_company_destination(configured):
    result = news_subject.snap_unknown_geography(_unknown_company(), configured)
    assert (result is None) == ("id_stocks_news" not in configured or len(configured & news_subject.COMPANY_ROUTES) != 1)


@pytest.mark.parametrize("home", ["ID", "US", "GLOBAL"])
def test_snap_never_overrides_an_explicit_geography(home):
    value = _unknown_company()
    value["company"]["business_home"] = home
    assert news_subject.snap_unknown_geography(value, {"id_stocks_news"}) is None


def test_uncertain_industry_follows_an_account_with_one_industry_destination():
    value = {"kind": "industry", "name": "Perbankan", "evidence": "NIM perbankan", "industry": {"region": "UNKNOWN"}}
    snapped, route = news_subject.snap_unknown_geography(value, {"macro_news", "id_industry_news"})
    assert route == "id_industry_news" and snapped["industry"]["region"] == "ID"
    assert news_subject.snap_unknown_geography({**value, "industry": {"region": "US"}}, {"id_industry_news"}) is None


def test_macro_subject_is_never_snapped():
    assert news_subject.snap_unknown_geography({"kind": "macro", "name": "Inflasi", "evidence": "CPI"}, {"id_stocks_news"}) is None


def test_snapped_listed_company_gets_the_destinations_security_market():
    snapped, _ = news_subject.snap_unknown_geography(_unknown_company(), {"id_stocks_news"})
    assert snapped["company"]["security_market"] == "ID"
    private = _unknown_company()
    private["company"]["listing_status"] = "private"
    assert news_subject.snap_unknown_geography(private, {"id_stocks_news"})[0]["company"]["security_market"] == ""
    assert news_subject.snap_unknown_geography(_unknown_company(), {"global_company_news"})[0]["company"]["security_market"] == ""
