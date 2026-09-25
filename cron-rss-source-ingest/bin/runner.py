"""Unscheduled RSS source entry point for Stockbit's fixed lanes only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-pipeline-runtime"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from pipeline_runtime import PipelineRuntime
from adapter import run_once as ingest_once
from config import load_watch_config_for_run
from source_ingest import IntakeBlocked


def _owner_command(*arguments: str, work: dict | None = None) -> dict:
    local = ROOT / "cron-stockbit-snips" / "bin" / "pipeline_owner.py"
    owner_path = local if local.is_file() else Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin" / "pipeline_owner.py"
    result = subprocess.run(
        [sys.executable, str(owner_path), *arguments],
        input=json.dumps(work, ensure_ascii=False) if work is not None else None,
        text=True,
        capture_output=True,
        timeout=60,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Stockbit owner command failed")
    try:
        response = json.loads(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("Stockbit owner response is invalid") from error
    if type(response) is not dict:
        raise RuntimeError("Stockbit owner response is invalid")
    return response


def _owner_handler(item: dict) -> None:
    if _owner_command(work=item).get("outcome") != "accepted":
        raise RuntimeError("Stockbit owner did not acknowledge source work")


def run_once(snapshot: dict | None, loaded_config: object | None, root: Path, inbox: object, observed_at: datetime, *, fetch_feed=None, handler=None, owner_command=None) -> dict:
    if snapshot is None or loaded_config is None:
        source = [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "intake_config_unavailable"}]
    else:
        try:
            source = ingest_once(snapshot, loaded_config, root, inbox, observed_at, fetch_feed=fetch_feed)
        except IntakeBlocked:
            source = [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "intake_config_mismatch"}]
    work = PipelineRuntime(inbox, {"stockbit_snips": handler or _owner_handler}).run_once(limit=20)
    command = owner_command or _owner_command
    status = command("agent-status")
    if type(status.get("ready")) is not bool:
        raise RuntimeError("Stockbit owner status is invalid")
    if status["ready"]:
        if status.get("pipeline_id") != "stockbit_snips" or type(status.get("event_key")) is not str or type(status.get("published_at")) is not str:
            raise RuntimeError("Stockbit owner status is invalid")
        agent = command("claim-agent")
        if type(agent.get("wakeAgent")) is not bool or type(agent.get("items")) is not list or (agent["wakeAgent"] and (len(agent["items"]) != 1 or type(agent["items"][0]) is not dict)):
            raise RuntimeError("Stockbit owner claim is invalid")
    else:
        agent = {"wakeAgent": False, "items": []}
    return {"source": source, "work": work, **agent}


def main() -> int:
    if os.environ.get("BURSAWATCH_RSS_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected feed and inbox fakes for no-post validation")
    inbox = client("BURSAWATCH_RSS_SOURCE")
    try:
        loaded = load_watch_config_for_run()
    except Exception:
        loaded = None
    try:
        snapshot = inbox.get_effective()
    except Exception:
        snapshot = None
    results = run_once(snapshot, loaded, state_root("BURSAWATCH_RSS_SOURCE", "bursawatch-rss-source-ingest"), inbox, datetime.now(timezone.utc))
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
