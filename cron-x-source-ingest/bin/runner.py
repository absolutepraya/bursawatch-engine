"""Unscheduled X source entry point with the existing watcher as domain owner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-source-media", "lib-bursawatch-pipeline-runtime"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-x-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from adapter import run_once
from config import load_watch_config_for_run
from pipeline_runtime import PipelineRuntime


def _owner_path() -> Path:
    local = ROOT / "cron-x-account-watch" / "bin" / "pipeline_owner.py"
    if local.is_file():
        return local
    return Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin" / "pipeline_owner.py"


def _owner_handler(work: dict) -> None:
    result = subprocess.run(
        [sys.executable, str(_owner_path())],
        input=json.dumps(work, ensure_ascii=False, allow_nan=False),
        text=True, capture_output=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("X owner did not acknowledge source work")
    try:
        receipt = json.loads(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("X owner receipt is invalid") from error
    if type(receipt) is not dict or receipt.get("outcome") not in {"accepted", "irrelevant"}:
        raise RuntimeError("X owner receipt is invalid")


def process_pending(inbox, *, handler=_owner_handler) -> list[dict[str, str]]:
    return PipelineRuntime(inbox, {"company_news": handler, "macro_news": handler}).run_once(limit=20)


def _media_client():
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    if not token_file and not url:
        return None
    if not token_file or not url:
        raise RuntimeError("source media service configuration is incomplete")
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token_file))


def main() -> int:
    if os.environ.get("BURSAWATCH_X_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected source and inbox fakes for no-post validation")
    loaded = load_watch_config_for_run()
    if loaded.revision is None:
        raise RuntimeError("X source adapter requires a live watcher configuration revision")
    inbox = client("BURSAWATCH_X_SOURCE")
    snapshot = inbox.get_effective()
    results = run_once(snapshot, loaded.config.profiles, state_root("BURSAWATCH_X_SOURCE", "bursawatch-x-source-ingest"), inbox, datetime.now(timezone.utc), media_store=_media_client())
    work = process_pending(inbox)
    print(json.dumps({"source": results, "work": work}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
