from copy import deepcopy

import pytest

import news_format


def item(home="GLOBAL", status="listed", market="US", ticker="EXAMPLE"):
    return {"title": "Example Business expands production", "summary": "Example Business adds capacity.",
            "route": {"ID": "id_stocks_news", "US": "us_stocks_news"}.get(home, "global_company_news"),
            "ticker": ticker, "subject": {"kind": "company", "name": "Example Business", "evidence": "adds capacity",
                "company": {"business_home": home, "listing_status": status, "security_market": market}}}


def test_global_destination_can_render_us_quote_without_rewriting_heading():
    calls = []
    def fetch(ticker, route):
        calls.append((ticker, route))
        return {"latest_price": 25, "currency": "USD", "as_of": "2026-11-03T00:00:00+00:00"}
    value = item()
    cards = news_format.freeze_cards([value], lambda i: "### " + i["title"], "https://example.test/news", "Source",
                                    fetch=fetch, target_for=lambda _: "123456789012345678")
    assert calls == [("EXAMPLE", "us_stocks_news")]
    assert news_format.validate_cards(cards) == cards
    assert cards[0]["route"] == "global_company_news"
    text = "\n".join(cards[0]["messages"])
    assert text.startswith("### Example Business expands production")
    assert "USD" in text and "Saham: EXAMPLE (US)" in text and "IDR" not in text


@pytest.mark.parametrize("status", ["private", "pre_ipo", "formerly_listed", "unknown"])
def test_private_company_card_has_no_tracker_or_empty_stock_fields(status):
    value = item("US", status, "", "")
    cards = news_format.freeze_cards([value], lambda i: "### " + i["title"], "https://example.test/news", "Source",
                                    fetch=lambda *_: pytest.fail("must not fetch a price"))
    text = "\n".join(cards[0]["messages"])
    assert "Harga terakhir" not in text and "Saham:" not in text
    assert "Example Business" in text and "View on Source" in text


def test_unsupported_quote_market_does_not_prevent_global_news():
    value = item("GLOBAL", "listed", "", "")
    cards = news_format.freeze_cards([value], lambda i: "### " + i["title"], "https://example.test/news", "Source",
                                    fetch=lambda *_: pytest.fail("unsupported exchange must not fetch"))
    assert news_format.validate_cards(cards)[0]["ticker"] is None


def test_validation_does_not_modify_frozen_legacy_messages():
    cards = news_format.freeze_cards([{"title": "ABCD: Old company headline", "summary": "Old summary", "route": "id_stocks_news"}],
                                    lambda i: "### " + i["title"], "https://example.test/news", "Source", fetch=lambda *_: None)
    before = deepcopy(cards)
    assert news_format.validate_cards(cards) == before
    assert cards == before
