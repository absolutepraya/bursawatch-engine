from __future__ import annotations

import hashlib

from idx_tickers import (
    IDX_TICKERS,
    IDX_TICKERS_RETRIEVED_DATE,
    IDX_TICKERS_SNAPSHOT_COUNT,
    IDX_TICKERS_SNAPSHOT_SHA256,
    IDX_TICKERS_SOURCE_URL,
)
from parsing import extract_plan, parse_gtw_header


def test_header_is_case_insensitive_and_normalizes_ticker() -> None:
    header = parse_gtw_header("good to watch - ctra #gtw")
    assert header is not None
    assert header.ticker == "CTRA"


def test_untagged_and_non_idx_headers_are_rejected() -> None:
    assert parse_gtw_header("Good to watch - CTRA") is None
    assert parse_gtw_header("Good to watch - AAPL #GTW") is None
    assert parse_gtw_header("Good to watch - ZZZZZ #GTW") is None


def test_header_accepts_known_idx_tickers_from_offline_membership_snapshot() -> None:
    for ticker in ("CTRA", "RAJA", "BREN", "TOWR", "DKFT", "RATU", "FORE"):
        header = parse_gtw_header(f"Good to watch - {ticker} #GTW")
        assert header is not None
        assert header.ticker == ticker


def test_offline_idx_snapshot_provenance_and_integrity_are_stable() -> None:
    canonical = "\n".join(sorted(IDX_TICKERS)) + "\n"
    assert len(IDX_TICKERS) == IDX_TICKERS_SNAPSHOT_COUNT == 840
    assert hashlib.sha256(canonical.encode("ascii")).hexdigest() == IDX_TICKERS_SNAPSHOT_SHA256
    assert IDX_TICKERS_SOURCE_URL.startswith("https://www.idx.co.id/")
    assert IDX_TICKERS_RETRIEVED_DATE == "2026-08-11"


def test_header_rejects_promotional_text_and_requires_standalone_tag() -> None:
    assert parse_gtw_header("Good to watch - CTRA #GTW join premium") is None
    assert parse_gtw_header("Good to watch - CTRA #GTWXYZ") is None


def test_plan_uses_dash_for_absent_fields() -> None:
    plan = extract_plan("Buy area: 605–630\nTP 1: 655\nTP 2: 675")
    assert (plan.buy_area, plan.targets, plan.stoploss) == ("605 sampai 630", "655, 675", "-")


def test_plan_collects_targets_in_source_order() -> None:
    plan = extract_plan("TP 2: 675\nTarget 1: 655\nTP 3: 700\nStop-loss: <573")
    assert plan.targets == "675, 655, 700"
    assert plan.stoploss == "<573"


def test_plan_accepts_singular_target_and_no_labels() -> None:
    assert extract_plan("Target: 655").targets == "655"
    plan = extract_plan("Analisis saham CTRA tanpa rencana")
    assert (plan.buy_area, plan.targets, plan.stoploss) == ("-", "-", "-")


def test_plan_accepts_bulleted_source_labels_and_strips_gain_annotations() -> None:
    plan = extract_plan(
        "\n".join(
            (
                "• Buy area: 660–765",
                "• TP 1: 875 → potensi gain sekitar +22,4%",
                "• TP 2: 995 → potensi gain sekitar +39,2%",
                "• Stoploss utama: <620 → potensi risiko sekitar -10%",
            )
        )
    )

    assert (plan.buy_area, plan.targets, plan.stoploss) == ("660 sampai 765", "875, 995", "<620")
