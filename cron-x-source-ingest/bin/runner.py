"""Unscheduled X source entry point with the existing watcher as domain owner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for package, installed in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
    ("lib-bursawatch-source-media", "lib-bursawatch-source-media"),
    ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
    ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"),
):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / installed / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-x-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from adapter import run_once
from config import load_watch_config_for_run
from pipeline_runtime import PipelineRuntime
from bursawatch_discord_delivery import DeliveryClient, OperationIntent

WATCHER = "bursawatch-x-source-ingest"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
HEARTBEAT_DELIVERY_WAIT_SECONDS = 10
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
WIB = ZoneInfo("Asia/Jakarta")
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


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


def format_heartbeat(now: datetime, result: dict) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("heartbeat time must be timezone-aware")
    source = result.get("source", [])
    work = result.get("work", [])
    if type(source) is not list or type(work) is not list:
        raise ValueError("heartbeat counters are invalid")
    accepted = sum(item.get("accepted", 0) for item in source if type(item) is dict and type(item.get("accepted", 0)) is int)
    pending_statuses = {"retry", "settlement_unconfirmed", "begin_rejected", "unsupported_pipeline", "dead_letter"}
    pending = sum(type(item) is dict and item.get("status") in pending_statuses for item in work)
    warning = pending > 0 or any(type(item) is dict and item.get("status") == "blocked" for item in source)
    suffix = " ⚠️" if warning else ""
    return (
        f"🫀 {WATCHER} · {now.astimezone(WIB):%H:%M} WIB · "
        f"endpoints={len(source)} accepted={accepted} work={len(work)} pending={pending}{suffix}"
    )


def format_fatal(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("heartbeat time must be timezone-aware")
    return f"❌ {WATCHER} · {now.astimezone(WIB):%H:%M} WIB · failed: source processing failed"


def post_heartbeat(content: str, now: datetime, *, delivery_client=None) -> None:
    if len(content) > 2000:
        raise ValueError("heartbeat exceeds Discord message limit")
    if delivery_client is None:
        base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", DELIVERY_OWNER_URL)
        token_path = Path(os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / DELIVERY_CLIENT_TOKEN_FILE),
        )).expanduser()
        delivery_client = DeliveryClient(base_url, token_path)
    operation = OperationIntent(
        key=f"{WATCHER}:heartbeat:{now.astimezone(timezone.utc):%Y%m%dT%H%M%S%f}",
        kind="channel_message_create",
        ordering_key=f"channel:{HEARTBEAT_CHANNEL_ID}",
        target={"channel_id": HEARTBEAT_CHANNEL_ID},
        payload={"content": content, "allowed_mentions": {"parse": []}},
    )
    receipt = delivery_client.status(operation.key)
    if receipt is None:
        receipt = delivery_client.submit(operation)
    if receipt.key != operation.key or receipt.digest != operation.digest:
        raise RuntimeError("heartbeat receipt is invalid")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = delivery_client.wait(operation.key, HEARTBEAT_DELIVERY_WAIT_SECONDS)
    if receipt.key != operation.key or receipt.digest != operation.digest or receipt.status != "delivered":
        raise RuntimeError("heartbeat delivery is incomplete")


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
    if sys.argv[1:] == ["--verify-synthetic"]:
        return verify_synthetic()
    if os.environ.get("BURSAWATCH_X_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected source and inbox fakes for no-post validation")
    now = datetime.now(timezone.utc)
    try:
        loaded = load_watch_config_for_run()
        if loaded.revision is None:
            raise RuntimeError("X source adapter requires a live watcher configuration revision")
        inbox = client("BURSAWATCH_X_SOURCE")
        snapshot = inbox.get_effective()
        source = run_once(snapshot, loaded.config.profiles, state_root("BURSAWATCH_X_SOURCE", WATCHER), inbox, now, media_store=_media_client())
        work = process_pending(inbox)
        result = {"source": source, "work": work}
    except Exception:
        try:
            post_heartbeat(format_fatal(now), now)
        except Exception:
            pass
        raise RuntimeError("source processing failed") from None
    post_heartbeat(format_heartbeat(now, result), now)
    print(json.dumps(result, separators=(",", ":")))
    return 0


def verify_synthetic() -> int:
    """Exercise event binding and serialization with in-memory synthetic data."""
    from adapter import _item, endpoints
    from models import PostKind, SourcePost
    from source_ingest import envelope

    profile = SimpleNamespace(id="kutekians", enabled=True, handle="Kutekians")
    endpoint_id = "x:kutekians"
    snapshot = {
        "revision": 1,
        "subscriptions": [{
            "platform": "x",
            "endpoint_id": endpoint_id,
            "publisher_id": "x-kutekians",
            "address": "Kutekians",
            "provider_id": None,
            "capability_id": "company_news",
            "verification_status": "verified",
            "enabled": True,
        }],
    }
    selected, _ = endpoints(snapshot, (profile,))
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    post = SourcePost(
        profile_id=profile.id,
        post_id="1960000000000000000",
        url="https://x.com/Kutekians/status/1960000000000000000",
        published_at=now,
        content_html="<p>Synthetic X source event</p>",
        kind=PostKind.NORMAL,
        quoted_url=None,
        quoted_content_html=None,
        media=(),
        quoted_media=(),
    )
    item = _item(post, endpoint_id, None, upload_media=False)
    event = envelope(selected[endpoint_id], item, now, "x-watch-parser-1")
    if event["provider_event_id"] != post.post_id or event["payload"]["post"]["content_html"] != post.content_html:
        raise RuntimeError("synthetic X adapter verification failed")
    print(json.dumps({
        "outcome": "synthetic-ok",
        "network": False,
        "secrets": False,
        "writes": False,
        "events": 1,
        "content_hash": event["content_hash"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
