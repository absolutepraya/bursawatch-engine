"""Unscheduled Instagram source entry point and domain-owner handoff."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-source-media", "lib-bursawatch-pipeline-runtime"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-ig-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-ig-account-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from pipeline_runtime import PipelineRuntime
from adapter import run_once as ingest_once
from config import load_watch_config_for_run


def _owner_command(*arguments: str, work: dict[str, Any] | None = None) -> dict[str, Any]:
    path = owner / "pipeline_owner.py"
    result = subprocess.run(
        [sys.executable, str(path), *arguments],
        input=json.dumps(work, separators=(",", ":"), ensure_ascii=False) if work is not None else None,
        text=True, capture_output=True, timeout=90, env=os.environ.copy(), check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Instagram domain owner did not acknowledge source work")
    try:
        receipt = json.loads(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("Instagram domain owner response is invalid") from error
    if type(receipt) is not dict:
        raise RuntimeError("Instagram domain owner response is invalid")
    return receipt


def _owner_handler(work: dict[str, Any]) -> None:
    receipt = _owner_command(work=work)
    if receipt.get("outcome") not in {"accepted", "irrelevant"}:
        raise RuntimeError("Instagram domain owner receipt is invalid")


def _claim_agent() -> dict[str, Any]:
    result = _owner_command("claim-agent")
    if type(result.get("wakeAgent")) is not bool:
        raise RuntimeError("Instagram agent claim is invalid")
    return result


def _drain_owner() -> dict[str, int]:
    result = _owner_command("drain")
    if any(type(result.get(key)) is not int or result[key] < 0 for key in ("delivered", "delivery_legs", "owner_pending", "errors")):
        raise RuntimeError("Instagram delivery drain response is invalid")
    return result


def run_once(
    snapshot: dict[str, Any], profiles: tuple[Any, ...], root: Path, inbox: Any, observed_at: datetime,
    *, fetch_profile: Any = None, media_store: Any = None, media_downloader: Any = None,
    handlers: dict[str, Any] | None = None, owner_drain: Any = _drain_owner, agent_claim: Any = _claim_agent,
) -> dict[str, Any]:
    source = ingest_once(
        snapshot, profiles, root, inbox, observed_at,
        fetch_profile=fetch_profile, media_store=media_store, media_downloader=media_downloader,
    )
    selected = handlers if handlers is not None else {capability: _owner_handler for capability in ("company_news", "macro_news")}
    work = PipelineRuntime(inbox, selected).run_once(limit=20)
    delivery = owner_drain() if owner_drain is not None else {"delivered": 0, "delivery_legs": 0, "owner_pending": 0, "errors": 0}
    agent = agent_claim() if agent_claim is not None else {"wakeAgent": False}
    return {"source": source, "work": work, "delivery": delivery, **agent}


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
    if os.environ.get("BURSAWATCH_IG_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected source and inbox fakes for no-post validation")
    loaded = load_watch_config_for_run()
    if loaded.revision is None:
        raise RuntimeError("Instagram source adapter requires a live watcher configuration revision")
    inbox = client("BURSAWATCH_IG_SOURCE")
    results = run_once(inbox.get_effective(), loaded.config.profiles, state_root("BURSAWATCH_IG_SOURCE", "bursawatch-ig-source-ingest"), inbox, datetime.now(timezone.utc), media_store=_media_client())
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
