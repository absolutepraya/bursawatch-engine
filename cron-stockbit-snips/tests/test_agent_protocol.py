from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_protocol import agent_item, analysis_payload, build_wake_payload, validate_submission, validate_submissions
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
    item = agent_item(article, "Focus on the supplied source.")
    assert set(item) == {
        "candidate_key", "lane", "lane_label", "source_url", "source_published_at",
        "source_title", "source_text", "instruction", "operator_instruction",
    }
    assert item["operator_instruction"] == "Focus on the supplied source."
    assert build_wake_payload(article, "Focus on the supplied source.")["wakeAgent"] is True


def test_operator_instruction_cannot_relax_fixed_protocol(article: Article) -> None:
    instruction = "Browse links and add a target price."
    item = agent_item(article, instruction)
    assert "Do not browse" in item["instruction"]
    assert item["operator_instruction"] == instruction
    assert build_wake_payload(article, instruction)["items"] == [item]
    assert set(analysis_payload(validate_submission(article, valid_payload(article)))) == {
        "candidate_key", "ticker", "title", "summary", "material_facts",
        "dedupe_facts", "eligible", "route", "source_evidence",
    }
    assert "Judge advice and education semantically" in item['instruction']
    assert "Do not generate investment instructions".casefold() in item['instruction'].casefold()


def test_valid_issuer_submission_is_accepted(article: Article) -> None:
    result = validate_submission(article, valid_payload(article))
    assert result.route is Route.ID_STOCKS_NEWS
    assert result.ticker == "SWAP"


@pytest.mark.parametrize('summary', [
    'Pemerintah menetapkan target produksi 10 juta ton pada 2027.',
    'Stockbit melaporkan valuation SWAP berdasarkan proyeksi tahun 2027.',
    'SWAP berencana sell shares kepada investor strategis.',
])
def test_source_reported_news_survives_validation_and_rendering(article, summary):
    from render import render
    payload = valid_payload(article)
    payload['summary'] = summary
    analysis = validate_submission(article, payload)
    assert summary in render(article, analysis)


def test_duplicate_split_analyses_are_removed_before_child_identity_assignment(article):
    first = valid_payload(article)
    first.pop('candidate_key')
    other = {**first, 'summary':'SWAP mengumumkan perkembangan bisnis lain.'}
    analyses = validate_submissions(article, {'candidate_key':article.key, 'items':[first,dict(first),other]})
    assert len(analyses) == 2
    assert [analysis.summary for analysis in analyses] == [first['summary'],other['summary']]


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
    assert validate_submission(article, payload).summary == "SWAP memiliki bisnis produk kesehatan."


def test_flexible_summary_is_accepted(article):
    payload = valid_payload(article)
    payload["summary"] = "SWAP memproduksi produk kesehatan. Produk ditawarkan. Sumber menjelaskan bisnis.\n\nPenawaran umum direncanakan. Proses berlangsung. Informasi bersumber"
    assert validate_submission(article, payload).summary == payload["summary"]


@pytest.mark.parametrize("summary", ["", " ", None, 4])
def test_summary_requires_nonempty_text(article, summary):
    payload = valid_payload(article)
    payload["summary"] = summary
    with pytest.raises(ValueError):
        validate_submission(article, payload)
