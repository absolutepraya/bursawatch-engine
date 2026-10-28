from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import news_subject


@pytest.mark.parametrize("kind,name,evidence,route", [
    ("company", "Bach Multi Global", "Bach Multi Global membukukan laba naik 32%", "id_stocks_news"),
    ("company", "United Tractors", "Pendapatan United Tractors turun 10%", "id_stocks_news"),
    ("industry", "kelapa sawit", "Permintaan industri kelapa sawit meningkat", "id_industry_news"),
    ("industry", "pertanian", "Kekeringan menekan produksi sektor pertanian", "id_industry_news"),
    ("macro", "inflasi", "Inflasi Indonesia turun menjadi 2,4%", "macro_news"),
])
def test_subject_route_depends_on_meaning_not_header_or_ticker(kind, name, evidence, route):
    source = f"Catatan riset terbaru\n{evidence}. Emiten AALI disebut sebagai contoh."
    subject = news_subject.validate_subject({"kind": kind, "name": name, "evidence": evidence}, source)
    assert news_subject.route_for(subject) == route


def test_company_without_verified_ticker_remains_company_news():
    subject = news_subject.validate_subject(
        {"kind": "company", "name": "Perusahaan Nusantara", "evidence": "Perusahaan Nusantara memperoleh kontrak baru"},
        "Perusahaan Nusantara memperoleh kontrak baru.",
    )
    assert news_subject.route_for(subject) == "id_stocks_news"


def test_sector_story_with_company_examples_cannot_use_macro_or_stocks():
    subject = news_subject.validate_subject(
        {"kind": "industry", "name": "kelapa sawit", "evidence": "Ekspor kelapa sawit melemah"},
        "Ekspor kelapa sawit melemah; AALI dan LSIP terdampak.",
    )
    for wrong_route in ["macro_news", "id_stocks_news"]:
        with pytest.raises(ValueError, match="subject"):
            news_subject.validate_route(subject, wrong_route)


def test_company_story_cannot_fall_back_to_macro_when_identity_is_unresolved():
    subject = {"kind": "company", "name": "Perusahaan Nusantara", "evidence": "Kontrak baru"}
    with pytest.raises(ValueError, match="subject"):
        news_subject.validate_route(subject, "macro_news")


def test_subject_requires_source_grounding_instead_of_model_confidence():
    with pytest.raises(ValueError, match="evidence"):
        news_subject.validate_subject(
            {"kind": "industry", "name": "kelapa sawit", "evidence": "Penjualan sawit tumbuh 50%"},
            "Harga minyak dunia naik.",
        )


def test_source_evidence_tolerates_whitespace_without_inventing_content():
    value = {"kind": "company", "name": "BACH", "evidence": "BACH membukukan laba naik"}
    assert news_subject.validate_subject(value, "BACH\n  membukukan\tlaba naik")["kind"] == "company"


def test_unknown_subject_or_extra_fields_are_rejected():
    for value in [
        {"kind": "unknown", "name": "Tidak jelas", "evidence": "Tidak jelas"},
        {"kind": "macro", "name": "Inflasi", "evidence": "Inflasi", "confidence": 0.99},
    ]:
        with pytest.raises(ValueError, match="subject"):
            news_subject.validate_subject(value, "Inflasi belum jelas")


def test_existing_us_company_route_is_preserved():
    subject = {"kind": "company", "name": "Microsoft", "evidence": "Microsoft reports earnings"}
    assert news_subject.route_for(subject, company_route="us_stocks_news") == "us_stocks_news"


def test_ticker_must_be_in_supplied_evidence_and_does_not_determine_category():
    source = "PT Bach Multi Global Tbk (BACH) membukukan laba naik."
    assert news_subject.validate_ticker("BACH", source) == "BACH"
    assert news_subject.validate_ticker("", source) is None
    with pytest.raises(ValueError, match="ticker"):
        news_subject.validate_ticker("UNTR", source)
