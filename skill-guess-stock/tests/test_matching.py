from __future__ import annotations

import json
from pathlib import Path

from evidence import normalize_evidence
from matching import rank_candidates, score_candidate


def chart_evidence(**fields):
    as_of = fields.pop("as_of", "2026-08-19")
    return normalize_evidence(
        {"kind": "chart", "source": "user-image", "as_of": as_of, "fields": fields}
    )


def test_exact_snapshot_can_be_confirmed_with_as_of_and_independent_source() -> None:
    evidence = chart_evidence(price=192, volume="189.01M", volume_average="21.2M")
    result = score_candidate(
        evidence,
        {
            "ticker": "IDX:APEX",
            "as_of": "2026-08-19",
            "source": "tradingview-indonesia",
            "fields": {"price": 192, "volume": 189_010_000, "volume_average": 21_200_000},
        },
    )

    assert result.status == "Confirmed"
    assert result.as_of_status == "exact"
    assert set(result.matched_fields) == {"price", "volume", "volume_average"}


def test_calendar_mismatch_is_rejected_even_when_numbers_match() -> None:
    evidence = chart_evidence(as_of="2026-08-26", price=296, volume="772.53K")
    result = score_candidate(
        evidence,
        {
            "ticker": "DEPO",
            "as_of": "2026-08-29",
            "source": "yahoo-finance",
            "fields": {"price": 296, "volume": 772_530},
        },
    )

    assert result.status == "Rejected"
    assert "as_of_mismatch" in result.reasons


def test_user_rejection_is_hard_for_the_current_puzzle() -> None:
    evidence = chart_evidence(price=685, volume="829.15M")
    result = score_candidate(
        evidence,
        {"ticker": "KIJA", "as_of": "2026-08-19", "fields": {"price": 685, "volume": 829_150_000}},
        rejected_tickers=["KIJA"],
    )

    assert result.status == "Rejected"
    assert result.reasons == ("user_rejection",)


def test_one_key_stat_cannot_be_confirmed() -> None:
    evidence = normalize_evidence(
        {
            "kind": "keystats",
            "source": "user-image",
            "as_of": "2026-06-30",
            "fields": {"total_assets": "193B"},
        }
    )
    result = score_candidate(
        evidence,
        {
            "ticker": "INPS",
            "as_of": "2026-06-30",
            "source": "yahoo-finance",
            "fields": {"total_assets": 193_000_000_000},
        },
    )

    assert result.status != "Confirmed"
    assert result.status == "Lookalike"


def test_shortlist_is_ranked_by_confidence_then_score() -> None:
    evidence = chart_evidence(price=192, volume="189.01M", volume_average="21.2M")
    results = rank_candidates(
        evidence,
        [
            {"ticker": "KIJA", "as_of": "2026-08-19", "fields": {"price": 190, "volume": 20_000_000}},
            {"ticker": "APEX", "as_of": "2026-08-19", "fields": {"price": 192, "volume": 189_010_000, "volume_average": 21_200_000}},
        ],
    )

    assert [item.ticker for item in results] == ["APEX", "KIJA"]
    assert results[0].status == "Confirmed"


def test_sanitized_corpus_has_no_raw_dialogue_or_attachment_paths() -> None:
    corpus = json.loads((Path(__file__).parent / "fixtures" / "corpus.json").read_text())
    assert corpus
    for case in corpus:
        assert set(case) >= {"case_id", "input_kinds", "observed", "expected_ticker", "expected_status"}
        assert "raw_message" not in case
        assert "attachment_path" not in case
