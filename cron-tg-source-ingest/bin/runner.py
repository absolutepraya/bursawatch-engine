"""One scheduled Telegram boundary, without a registered production job."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for local, installed in (("lib-bursawatch-control", "lib-bursawatch-control"), ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"), ("lib-telegram-resilience", "lib-telegram-resilience")):
    candidate = ROOT / local / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / installed / "bin"
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from pipeline_runtime import PipelineRuntime
from source_event_client import SourceEventClient
from telegram_resilience import PolyCopResilience, acquire_probe_after_active_lease, is_transport_error
from adapter import ingest_all

WATCHER = "bursawatch-tg-source-ingest"
# Agent News and Kelas require a bounded classifier/media handoff. They stay
# visible as pending inbox work instead of being marked done by this pilot.
PIPELINE_OWNERS = {"swing_plan": "cron-tg-phintraco-swing", "stock_status": "cron-tg-market-news"}


def _owner_path(package: str) -> Path:
    local = ROOT / package / "bin" / "pipeline_owner.py"
    if local.is_file():
        return local
    runtime = package.replace("cron-", "bursawatch-")
    return Path.home() / ".agents" / "skills" / runtime / "bin" / "pipeline_owner.py"


def _owner_handler(package: str, *, no_post: bool):
    path = _owner_path(package)

    def handle(item: dict[str, Any]) -> None:
        environment = os.environ.copy()
        if no_post:
            environment["BURSAWATCH_TG_SOURCE_NO_POST"] = "1"
        result = subprocess.run([sys.executable, str(path)], input=json.dumps(item, ensure_ascii=False, allow_nan=False), text=True, capture_output=True, timeout=60, env=environment, check=False)
        if result.returncode != 0:
            raise RuntimeError("domain owner did not acknowledge source work")
        try:
            receipt = json.loads(result.stdout.strip())
        except ValueError as error:
            raise RuntimeError("domain owner receipt is invalid") from error
        if receipt.get("outcome") not in {"accepted", "irrelevant", "rejected"}:
            raise RuntimeError("domain owner receipt is invalid")
    return handle


async def run_once(telegram: Any, snapshot: dict[str, Any], state_root: Path, inbox: Any, now: datetime, *, handlers: dict[str, Any] | None = None) -> dict[str, Any]:
    source = await ingest_all(telegram, snapshot, state_root, inbox, now)
    selected = handlers if handlers is not None else {pipeline: _owner_handler(package, no_post=False) for pipeline, package in PIPELINE_OWNERS.items()}
    work = PipelineRuntime(inbox, selected).run_once(limit=20)
    return {"source": source, "work": work}


def _client() -> SourceEventClient:
    url = os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_URL"]
    token_file = Path(os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE"])
    if token_file.stat().st_mode & 0o077:
        raise RuntimeError("source inbox token file permissions are too broad")
    return SourceEventClient(url, token_file.read_text().strip())


def _telegram_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(os.environ["POLYCOP_SESSION_STRING"]), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])


async def _run_live() -> dict[str, Any]:
    inbox = _client()
    snapshot = inbox.get_effective()
    state_root = Path(os.environ.get("BURSAWATCH_TG_SOURCE_STATE_ROOT", str(Path.home() / ".hermes" / "state" / WATCHER)))
    now = datetime.now(timezone.utc)
    resilience = PolyCopResilience.from_defaults()
    decision = await acquire_probe_after_active_lease(resilience, WATCHER, now)
    if decision.kind != "probe":
        return {"source": [{"status": "resilience_blocked"}], "work": PipelineRuntime(inbox, {pipeline: _owner_handler(package, no_post=False) for pipeline, package in PIPELINE_OWNERS.items()}).run_once(limit=20)}
    telegram = _telegram_client()
    try:
        await telegram.connect()
        if not await telegram.is_user_authorized():
            resilience.record_auth_required(decision.lease_id, WATCHER, now)
            return {"source": [{"status": "auth_required"}], "work": []}
        resilience.record_authenticated_success(decision.lease_id, WATCHER, now, getattr(telegram.session, "dc_id", None), None)
        return await run_once(telegram, snapshot, state_root, inbox, now)
    except Exception as error:
        if is_transport_error(error):
            resilience.record_transport_failure(decision.lease_id, WATCHER, error, now)
        raise
    finally:
        await telegram.disconnect()


def main() -> int:
    if os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected synthetic clients for no-post validation")
    result = asyncio.run(_run_live())
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
