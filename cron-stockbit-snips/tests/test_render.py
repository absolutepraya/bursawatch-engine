from __future__ import annotations

from datetime import UTC, datetime

from models import Analysis, Article, FeedLane, Route
from render import render


def article() -> Article:
    return Article(
        lane=FeedLane.UNBOXING_IPO,
        lane_label="Unboxing IPO",
        guid="swap-guid",
        url="https://snips.stockbit.com/unboxing-ipo/swap",
        source_title="Unboxing IPO $SWAP",
        source_text="SWAP memproduksi produk kesehatan.",
        published_at=datetime(2026, 8, 25, 5, 25, tzinfo=UTC),
    )


def analysis(route: Route = Route.ID_STOCKS_NEWS) -> Analysis:
    return Analysis(
        candidate_key=article().key,
        ticker="SWAP" if route is Route.ID_STOCKS_NEWS else "",
        title="SWAP: profil bisnis produk kesehatan" if route is Route.ID_STOCKS_NEWS else "Peluang sektor kesehatan di pasar modal",
        summary="SWAP memproduksi produk kesehatan dan berencana melakukan penawaran umum.",
        material_facts=("SWAP memproduksi produk kesehatan.",),
        dedupe_facts=("SWAP IPO",),
        eligible=True,
        route=route,
        source_evidence="Supplied Stockbit article.",
    )


def test_ipo_without_price_uses_dash_and_grey_status() -> None:
    content = render(article(), analysis(), None)

    assert "Harga terakhir (IDR): **-**" in content
    assert content.count("<:grey:1531279158913536182>") == 4
    assert "**0**" not in content
    assert "-# Stockbit" in content
    assert "<:stockbit:1552220036557578311>" in content
    assert "[View on Stockbit]" in content


def test_macro_article_omits_market_card() -> None:
    content = render(article(), analysis(Route.MACRO_NEWS), None)

    assert "Harga terakhir" not in content
    assert "<:grey:1531279158913536182>" not in content



def test_company_context_is_between_prices_and_source_for_idr_cards_only() -> None:
    context = {"rating": {"buy": 5, "hold": 0, "sell": 0, "strong_buy": 0, "strong_sell": 0, "updated_on": "2026-09-02"},
               "business_summary": "Health products maker.", "overview": {"sector": "Healthcare"}}
    content = render(article(), analysis(), None, context=context)
    assert content.index("Harga terakhir") < content.index("Konsensus analis") < content.index("Tentang SWAP:") < content.index("[View on Stockbit]")
    assert "Konsensus" not in render(article(), analysis(Route.MACRO_NEWS), None, context=context)
