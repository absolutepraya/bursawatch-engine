"""Forward-only WhatsApp bridge intake with the existing channel domain owner."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-source-media", "lib-bursawatch-pipeline-runtime", "lib-bursawatch-discord-delivery"):
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
from bursawatch_discord_delivery import DeliveryClient, OperationIntent

_CAPABILITIES = ("company_news", "macro_news", "swing_chart_context")
WATCHER = "whatsapp-channel"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
HEARTBEAT_DELIVERY_WAIT_SECONDS = 10
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
WIB = ZoneInfo("Asia/Jakarta")
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


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


def format_heartbeat(now: datetime, result: dict[str, Any]) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("heartbeat time must be timezone-aware")
    source = result.get("source", [])
    work = result.get("work", [])
    if type(source) is not list or type(work) is not list:
        raise ValueError("WhatsApp heartbeat counters are invalid")
    accepted = sum(row.get("accepted", 0) for row in source if type(row) is dict and type(row.get("accepted", 0)) is int)
    blocked = sum(type(row) is dict and row.get("status") == "blocked" for row in source)
    pending = sum(type(row) is dict and row.get("status") in {"retry", "settlement_unconfirmed", "begin_rejected", "unsupported_pipeline", "dead_letter"} for row in work)
    claimed = int(result.get("wakeAgent") is True)
    delivered = result.get("delivered", 0)
    delivery_errors = result.get("delivery_errors", 0)
    if type(delivered) is not int or type(delivery_errors) is not int:
        raise ValueError("WhatsApp heartbeat delivery counters are invalid")
    warning = " ⚠️" if blocked or pending or delivery_errors else ""
    return (
        f"🫀 {WATCHER} · {now.astimezone(WIB):%H:%M} WIB · "
        f"accepted={accepted} work={len(work)} pending={pending} "
        f"claimed={claimed} delivered={delivered} blocked={blocked}"
        f"{warning}"
    )


def format_fatal(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("heartbeat time must be timezone-aware")
    return f"❌ {WATCHER} · {now.astimezone(WIB):%H:%M} WIB · failed: source processing failed"


def post_heartbeat(content: str, now: datetime, *, delivery_client: Any = None) -> None:
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
        raise RuntimeError("WhatsApp heartbeat receipt is invalid")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = delivery_client.wait(operation.key, HEARTBEAT_DELIVERY_WAIT_SECONDS)
    if receipt.key != operation.key or receipt.digest != operation.digest or receipt.status != "delivered":
        raise RuntimeError("WhatsApp heartbeat delivery is incomplete")


def _media_client():
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    if not token_file or not url:
        return None
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token_file))


def main() -> int:
    if sys.argv[1:] == ["--verify-synthetic"]:
        return verify_synthetic()
    if os.environ.get("BURSAWATCH_WA_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected queue and inbox fakes for no-post validation")
    now = datetime.now(timezone.utc)
    try:
        loaded = load_for_run(Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_CONFIG_PATH", str(owner.parent / "config" / "watches.json"))))
        if loaded.revision is None:
            raise RuntimeError("WhatsApp source adapter requires a live watcher configuration revision")
        inbox = client("BURSAWATCH_WA_SOURCE")
        queue_dir = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_QUEUE_DIR", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "queue")))
        archive_root = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "archive")))
        results = run_once(inbox.get_effective(), loaded.config.profiles, queue_dir, state_root("BURSAWATCH_WA_SOURCE", "bursawatch-wa-source-ingest"), inbox, now, archive_root=archive_root, media_store=_media_client(), owner_config_revision=loaded.revision)
    except Exception:
        try:
            post_heartbeat(format_fatal(now), now)
        except Exception:
            pass
        raise RuntimeError("WhatsApp source processing failed") from None
    post_heartbeat(format_heartbeat(now, results), now)
    print(json.dumps(results, separators=(",", ":")))
    return 0


def verify_synthetic() -> int:
    """Exercise a fresh forward cursor, accepted event, and heartbeat without services."""
    from adapter import run_once as ingest
    from config import load
    from event_queue import enqueue, event_filename
    from models import ChannelEvent

    class Inbox:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def accept(self, event: dict[str, Any]) -> dict[str, Any]:
            self.events.append(event)
            identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
            event_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
            return {"event_key": event_key, "version": 1, "duplicate": False, "work_keys": []}

    profiles = load(owner.parent / "config" / "watches.json").profiles
    bri = next(profile for profile in profiles if profile.id == "bri-danareksa-sekuritas")
    endpoint_id = f"whatsapp:{bri.channel_url.rstrip('/').rsplit('/', 1)[-1]}"
    snapshot = {
        "revision": 1,
        "subscriptions": [{
            "platform": "whatsapp", "endpoint_id": endpoint_id,
            "publisher_id": "bri-danareksa", "address": bri.channel_url,
            "provider_id": bri.channel_jid, "capability_id": "company_news",
            "verification_status": "verified", "enabled": True,
        }],
    }
    now = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
    inbox = Inbox()
    with tempfile.TemporaryDirectory(prefix="wa-source-verify-") as directory:
        base = Path(directory)
        queue = base / "queue"
        state = base / "state"
        first = ChannelEvent(bri.channel_jid, "synthetic-boundary", now, "synthetic boundary", (), (), now)
        enqueue(queue, first)
        first_path = next(queue.glob("*.json"))
        os.utime(first_path, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
        bootstrapped = ingest(snapshot, profiles, queue, state, inbox, now, owner_config_revision=1)
        second = ChannelEvent(bri.channel_jid, "synthetic-new", now, "synthetic new event", (), (), now)
        enqueue(queue, second)
        second_path = queue / event_filename(second)
        os.utime(second_path, ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))
        accepted = ingest(snapshot, profiles, queue, state, inbox, now, owner_config_revision=1)
    summary = {"source": accepted, "work": [], "wakeAgent": False, "delivered": 0, "delivery_errors": 0}
    heartbeat = format_heartbeat(now, summary)
    if bootstrapped[0].get("status") != "bootstrapped_empty" or bootstrapped[0].get("accepted") != 0 or accepted[0].get("accepted") != 1 or len(inbox.events) != 1 or inbox.events[0].get("provider_event_id") != "synthetic-new" or "whatsapp-channel" not in heartbeat:
        raise RuntimeError("synthetic WhatsApp source verification failed")
    print(json.dumps({
        "outcome": "synthetic-ok", "network": False, "secrets": False,
        "writes": False, "events": len(inbox.events),
        "content_hash": inbox.events[0]["content_hash"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
