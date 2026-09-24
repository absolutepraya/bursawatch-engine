"""Unscheduled RSS source entry point for Stockbit's fixed lanes only."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from adapter import run_once
from config import load_watch_config_for_run


def main() -> int:
    if os.environ.get("BURSAWATCH_RSS_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected feed and inbox fakes for no-post validation")
    loaded = load_watch_config_for_run()
    inbox = client("BURSAWATCH_RSS_SOURCE")
    results = run_once(inbox.get_effective(), loaded, state_root("BURSAWATCH_RSS_SOURCE", "bursawatch-rss-source-ingest"), inbox, datetime.now(timezone.utc))
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
