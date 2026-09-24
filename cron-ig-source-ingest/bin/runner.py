"""Unscheduled Instagram source entry point. Media remains pending locally."""
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
owner = ROOT / "cron-ig-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-ig-account-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from adapter import run_once
from config import load_watch_config_for_run


def main() -> int:
    if os.environ.get("BURSAWATCH_IG_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected source and inbox fakes for no-post validation")
    loaded = load_watch_config_for_run()
    if loaded.revision is None:
        raise RuntimeError("Instagram source adapter requires a live watcher configuration revision")
    inbox = client("BURSAWATCH_IG_SOURCE")
    results = run_once(inbox.get_effective(), loaded.config.profiles, state_root("BURSAWATCH_IG_SOURCE", "bursawatch-ig-source-ingest"), inbox, datetime.now(timezone.utc))
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
