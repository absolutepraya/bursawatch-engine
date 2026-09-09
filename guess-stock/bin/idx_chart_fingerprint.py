#!/usr/bin/env python3
"""CLI for the deterministic first-pass candidate matcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence import normalize_evidence
from matching import rank_candidates


def _fields(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in ("price", "volume", "volume_average", "macd", "macd_signal", "macd_hist", "rsi"):
        value = getattr(args, name)
        if value is not None:
            fields[name] = value
    if args.pivots:
        fields["pivots"] = [item.strip() for item in args.pivots.split(",") if item.strip()]
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Score IDX candidates against visible chart evidence")
    parser.add_argument("--price")
    parser.add_argument("--volume")
    parser.add_argument("--volume-average")
    parser.add_argument("--macd")
    parser.add_argument("--macd-signal", dest="macd_signal")
    parser.add_argument("--histogram", dest="macd_hist")
    parser.add_argument("--rsi")
    parser.add_argument("--pivots", help="comma-separated normalized or numeric pivot values")
    parser.add_argument("--as-of")
    parser.add_argument("--candidate-file", required=True, type=Path)
    parser.add_argument("--rejected", action="append", default=[])
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    raw_candidates = json.loads(args.candidate_file.read_text(encoding="utf-8"))
    if isinstance(raw_candidates, dict):
        raw_candidates = raw_candidates.get("candidates", [])
    if not isinstance(raw_candidates, list):
        parser.error("candidate file must contain a list or an object with candidates")
    evidence = normalize_evidence(
        {
            "kind": "chart",
            "source": "user-image",
            "as_of": args.as_of,
            "fields": _fields(args),
        }
    )
    results = rank_candidates(evidence, raw_candidates, rejected_tickers=args.rejected, limit=max(args.top, 0))
    print(json.dumps({"evidence": evidence.to_dict(), "results": [result.to_dict() for result in results]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
