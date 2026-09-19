#!/usr/bin/env python3
"""Seed source-reviewed watcher configs once, without overwriting dashboard edits."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from control_plane.baselines import BaselineSeedError, seed_baselines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "baseline-configs",
        help="directory containing the reviewed baseline JSON snapshots",
    )
    args = parser.parse_args()
    try:
        outcomes = seed_baselines(os.environ.get("DATABASE_URL", ""), args.baseline_dir)
    except BaselineSeedError as exc:
        print(f"baseline seed refused: {exc}", file=sys.stderr)
        return 1
    for outcome in outcomes:
        print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
