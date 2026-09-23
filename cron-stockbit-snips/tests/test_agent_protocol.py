from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_protocol import agent_item, build_wake_payload, validate_submission
from models import Article, FeedLane, Route


@pytest.fixture
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


def valid_payload(article: Article) -> dict[str, object]:
    return {
        "candidate_key": article.key,
        "ticker": "SWAP",
        "title": "SWAP: profil bisnis produk kesehatan",
        "summary": "SWAP memproduksi produk kesehatan dan berencana melakukan penawaran umum.",
        "material_facts": ["SWAP memproduksi produk kesehatan."],
        "dedupe_facts": ["SWAP IPO"],
        "eligible": True,
        "route": "id_stocks_news",
        "source_evidence": "Source title and supplied article content identify SWAP.",
    }


def test_agent_item_is_one_bounded_source(article: Article) -> None:
    item = agent_item(article)
    assert set(item) == {
        "candidate_key", "lane", "lane_label", "source_url", "source_published_at",
        "source_title", "source_text", "instruction",
    }
    assert build_wake_payload(article)["wakeAgent"] is True


def test_valid_issuer_submission_is_accepted(article: Article) -> None:
    result = validate_submission(article, valid_payload(article))
    assert result.route is Route.ID_STOCKS_NEWS
    assert result.ticker == "SWAP"


def test_multi_issuer_macro_submission_has_no_ticker(article: Article) -> None:
    payload = valid_payload(article)
    payload.update(
        {
            "ticker": "",
            "title": "Logam global dan proksi IDX menghadapi perubahan siklus",
            "summary": "Perubahan siklus logam berdampak pada sejumlah komoditas dan emiten terkait.",
            "route": "macro_news",
        }
    )
    result = validate_submission(article, payload)
    assert result.route is Route.MACRO_NEWS
    assert result.ticker == ""


@pytest.mark.parametrize("title", ["SWAP: Judul berakhir titik.", "SWAP: Lihat https://example.test", "SWAP"])
def test_title_contract_is_enforced(article: Article, title: str) -> None:
    payload = valid_payload(article)
    payload["title"] = title
    with pytest.raises(ValueError):
        validate_submission(article, payload)


def test_ringkasan_marker_is_renderer_owned(article: Article) -> None:
    payload = valid_payload(article)
    payload["summary"] = "*(Ringkasan)* SWAP memiliki bisnis produk kesehatan."
    with pytest.raises(ValueError, match="Ringkasan"):
        validate_submission(article, payload)
