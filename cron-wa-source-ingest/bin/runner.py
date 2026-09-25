"""Unscheduled WhatsApp bridge queue reader. No bridge state is mutated."""
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
owner = ROOT / "cron-wa-channel-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-wa-channel-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from pipeline_runtime import PipelineRuntime
from adapter import run_once as ingest_once
from config import load_for_run

_CAPABILITIES = ("company_news", "macro_news", "swing_chart_context")


def _owner_command(*arguments: str, work: dict[str, Any] | None = None) -> dict[str, Any]:
    path = owner / "pipeline_owner.py"
    result = subprocess.run(
        [sys.executable, str(path), *arguments],
        input=json.dumps(work, separators=(",", ":"), ensure_ascii=False) if work is not None else None,
        text=True,
        capture_output=True,
        timeout=90,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("WhatsApp domain owner did not acknowledge source work")
    try:
        receipt = json.loads(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("WhatsApp domain owner response is invalid") from error
    if type(receipt) is not dict:
        raise RuntimeError("WhatsApp domain owner response is invalid")
    return receipt


def _owner_handler(work: dict[str, Any]) -> None:
    receipt = _owner_command(work=work)
    if receipt.get("outcome") not in {"accepted", "irrelevant"}:
        raise RuntimeError("WhatsApp domain owner receipt is invalid")


def _claim_agent() -> dict[str, Any]:
    result = _owner_command("claim-agent")
    if type(result.get("wakeAgent")) is not bool:
        raise RuntimeError("WhatsApp agent claim is invalid")
    return result


def run_once(
    snapshot: dict[str, Any], profiles: tuple[Any, ...], queue_dir: Path, root: Path,
    inbox: Any, observed_at: datetime, *, scan_queue: Any = None, archive_root: Path | None = None,
    media_store: Any = None, handlers: dict[str, Any] | None = None,
    agent_claim: Any = _claim_agent, owner_config_revision: int | None = None,
) -> dict[str, Any]:
    source = ingest_once(
        snapshot, profiles, queue_dir, root, inbox, observed_at,
        scan_queue=scan_queue, archive_root=archive_root, media_store=media_store,
        owner_config_revision=owner_config_revision,
    )
    selected = handlers if handlers is not None else {capability: _owner_handler for capability in _CAPABILITIES}
    work = PipelineRuntime(inbox, selected).run_once(limit=20)
    agent = agent_claim() if agent_claim is not None else {"wakeAgent": False, "item": None}
    if type(agent) is not dict or type(agent.get("wakeAgent")) is not bool:
        raise RuntimeError("WhatsApp agent claim is invalid")
    return {"source": source, "work": work, **agent}


def _media_client():
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    if not token_file or not url:
        return None
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token_file))


def main() -> int:
    if os.environ.get("BURSAWATCH_WA_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected queue and inbox fakes for no-post validation")
    loaded = load_for_run(Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_CONFIG_PATH", str(owner.parent / "config" / "watches.json"))))
    if loaded.revision is None:
        raise RuntimeError("WhatsApp source adapter requires a live watcher configuration revision")
    inbox = client("BURSAWATCH_WA_SOURCE")
    queue_dir = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_QUEUE_DIR", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "queue")))
    archive_root = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "archive")))
    results = run_once(inbox.get_effective(), loaded.config.profiles, queue_dir, state_root("BURSAWATCH_WA_SOURCE", "bursawatch-wa-source-ingest"), inbox, datetime.now(timezone.utc), archive_root=archive_root, media_store=_media_client(), owner_config_revision=loaded.revision)
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
