"""Deterministic candidate scoring and confidence gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from evidence import (
    EvidenceBundle,
    canonical_field_name,
    compare_as_of,
    normalized_mae,
    parse_number,
    path_correlation,
)


METRIC_WEIGHTS = {
    "macd": 4.0,
    "macd_signal": 4.0,
    "macd_hist": 4.0,
    "volume": 3.0,
    "volume_average": 2.5,
    "price": 2.0,
    "pivots": 3.0,
    "rsi": 1.0,
}


def _ticker(value: object) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("IDX:"):
        text = text[4:]
    if text.endswith(".JK"):
        text = text[:-3]
    return text


def _normalized_fields(fields: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in fields.items():
        result[canonical_field_name(name)] = value
    return result


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    ticker: str
    as_of: str | None
    source: str
    fields: Mapping[str, object]
    pivots: tuple[object, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "CandidateSnapshot":
        fields_raw = raw.get("fields")
        fields = _normalized_fields(fields_raw if isinstance(fields_raw, Mapping) else raw)
        pivots_raw = raw.get("pivots", fields.get("pivots", ()))
        if isinstance(pivots_raw, Sequence) and not isinstance(pivots_raw, (str, bytes)):
            pivots = tuple(pivots_raw)
        else:
            pivots = ()
        return cls(
            ticker=_ticker(raw.get("ticker", raw.get("symbol", raw.get("s", "")))),
            as_of=str(raw["as_of"]) if raw.get("as_of") is not None else None,
            source=str(raw.get("source", "market-data")),
            fields=fields,
            pivots=pivots,
        )


@dataclass(frozen=True, slots=True)
class MatchResult:
    ticker: str
    status: str
    score: float
    matched_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    reasons: tuple[str, ...]
    as_of_status: str
    path_correlation: float | None
    path_mae: float | None
    independent_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "score": round(self.score, 4),
            "matched_fields": list(self.matched_fields),
            "mismatched_fields": list(self.mismatched_fields),
            "reasons": list(self.reasons),
            "as_of_status": self.as_of_status,
            "path_correlation": None if self.path_correlation is None else round(self.path_correlation, 4),
            "path_mae": None if self.path_mae is None else round(self.path_mae, 4),
            "independent_sources": list(self.independent_sources),
        }


def _numeric_match(name: str, observed: object, candidate: object) -> bool | None:
    observed_number = parse_number(observed)
    candidate_number = parse_number(candidate)
    if observed_number is None or candidate_number is None:
        if isinstance(observed, str) and isinstance(candidate, str):
            return observed.strip().casefold() == candidate.strip().casefold()
        return None

    difference = abs(observed_number - candidate_number)
    if name == "rsi":
        return difference <= 2.0
    if name.startswith("macd"):
        return difference <= max(0.08, abs(observed_number) * 0.12)
    if name in {"price", "volume", "volume_average"}:
        return difference <= max(1.0 if name == "price" else 0.0, abs(observed_number) * (0.015 if name == "price" else 0.05))
    return difference <= max(0.02, abs(observed_number) * 0.03)


def _category(name: str) -> str:
    if name in {"price", "volume", "volume_average", "pivots", "rsi"} or name.startswith("macd"):
        return "technical"
    if name in {"total_assets", "total_liabilities", "total_debt", "net_debt", "common_equity", "total_equity"}:
        return "fundamental"
    return "other"


def score_candidate(
    evidence: EvidenceBundle,
    candidate: CandidateSnapshot | Mapping[str, object],
    *,
    rejected_tickers: Sequence[str] = (),
) -> MatchResult:
    if not isinstance(candidate, CandidateSnapshot):
        candidate = CandidateSnapshot.from_mapping(candidate)
    rejected = {_ticker(value) for value in rejected_tickers}
    if candidate.ticker in rejected:
        return MatchResult(
            candidate.ticker,
            "Rejected",
            0.0,
            (),
            (),
            ("user_rejection",),
            compare_as_of(evidence.as_of, candidate.as_of),
            None,
            None,
            tuple(dict.fromkeys((*evidence.sources, candidate.source))),
        )

    observed_fields: dict[str, object] = {}
    for field in evidence.fields:
        observed_fields.setdefault(field.name, field.value)
    candidate_fields = dict(candidate.fields)
    if candidate.pivots:
        candidate_fields["pivots"] = candidate.pivots
    observed_path = observed_fields.get("pivots")
    candidate_path = candidate_fields.get("pivots")

    matched: list[str] = []
    mismatched: list[str] = []
    reasons: list[str] = []
    available_weight = 0.0
    matched_weight = 0.0
    categories: set[str] = set()

    for name, observed in observed_fields.items():
        weight = METRIC_WEIGHTS.get(name, 1.0)
        available_weight += weight
        if name == "pivots":
            if not isinstance(candidate_path, Sequence) or isinstance(candidate_path, (str, bytes)):
                reasons.append("candidate_missing_pivots")
            continue
        if name not in candidate_fields:
            mismatched.append(name)
            reasons.append(f"candidate_missing_{name}")
            continue
        result = _numeric_match(name, observed, candidate_fields[name])
        if result:
            matched.append(name)
            matched_weight += weight
            categories.add(_category(name))
        else:
            mismatched.append(name)
            reasons.append(f"{name}_mismatch")

    correlation = None
    mae = None
    path_ok = True
    if isinstance(observed_path, Sequence) and not isinstance(observed_path, (str, bytes)):
        if isinstance(candidate_path, Sequence) and not isinstance(candidate_path, (str, bytes)):
            correlation = path_correlation(observed_path, candidate_path)
            mae = normalized_mae(observed_path, candidate_path)
            path_ok = correlation is not None and mae is not None and correlation >= 0.70 and mae <= 0.25
            if path_ok:
                matched.append("pivots")
                matched_weight += METRIC_WEIGHTS["pivots"]
                categories.add("technical")
            else:
                mismatched.append("pivots")
                reasons.append("chronology_or_path_mismatch")
        else:
            reasons.append("candidate_missing_pivots")

    as_of_status = compare_as_of(evidence.as_of, candidate.as_of)
    if as_of_status == "mismatch":
        reasons.append("as_of_mismatch")
    elif as_of_status == "unknown":
        reasons.append("as_of_unverified")

    score = matched_weight / available_weight if available_weight else 0.0
    independent_sources = tuple(dict.fromkeys((*evidence.sources, candidate.source)))
    hard_path_rejection = correlation is not None and mae is not None and (correlation < 0.45 or mae > 0.40)
    if as_of_status == "mismatch" or hard_path_rejection:
        status = "Rejected"
    elif not observed_fields:
        status = "Insufficient evidence"
        reasons.append("no_visible_fields")
    elif (
        score >= 0.75
        and len(matched) >= 2
        and len(categories) >= 1
        and as_of_status == "exact"
        and path_ok
        and len(independent_sources) >= 2
    ):
        status = "Confirmed"
    elif score >= 0.50 and len(matched) >= 2:
        status = "Strong lead"
    elif matched:
        status = "Lookalike"
    else:
        status = "Insufficient evidence"

    return MatchResult(
        candidate.ticker,
        status,
        score,
        tuple(dict.fromkeys(matched)),
        tuple(dict.fromkeys(mismatched)),
        tuple(dict.fromkeys(reasons)),
        as_of_status,
        correlation,
        mae,
        independent_sources,
    )


_STATUS_ORDER = {"Confirmed": 0, "Strong lead": 1, "Lookalike": 2, "Insufficient evidence": 3, "Rejected": 4}


def rank_candidates(
    evidence: EvidenceBundle,
    candidates: Sequence[CandidateSnapshot | Mapping[str, object]],
    *,
    rejected_tickers: Sequence[str] = (),
    limit: int | None = None,
) -> list[MatchResult]:
    results = [score_candidate(evidence, candidate, rejected_tickers=rejected_tickers) for candidate in candidates]
    results.sort(key=lambda result: (_STATUS_ORDER.get(result.status, 99), -result.score, result.ticker))
    return results if limit is None else results[:limit]
