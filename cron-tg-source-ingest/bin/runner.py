"""Scheduled Telegram source intake for the Phintraco and Kelas pilot."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for local, installed in (("lib-bursawatch-control", "lib-bursawatch-control"), ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"), ("lib-bursawatch-source-media", "lib-bursawatch-source-media"), ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"), ("lib-telegram-resilience", "lib-telegram-resilience")):
    candidate = ROOT / local / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / installed / "bin"
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from pipeline_runtime import PipelineRuntime
from source_event_client import SourceEventClient
from telegram_resilience import PolyCopResilience, acquire_probe_after_active_lease, is_transport_error
from adapter import endpoints as normalize_endpoints, envelope as make_envelope, ingest_all
from bursawatch_discord_delivery import DeliveryClient, OperationIntent

WATCHER = "bursawatch-tg-source-ingest"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
HEARTBEAT_DELIVERY_WAIT_SECONDS = 10
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
WIB = ZoneInfo("Asia/Jakarta")
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})
PIPELINE_OWNERS = {
    "swing_plan": "cron-tg-phintraco-swing",
    "stock_status": "cron-tg-market-news",
    "swing_support": "cron-tg-kelas-investasi-gtw",
    "company_news": "cron-tg-market-news",
    "macro_news": "cron-tg-market-news",
}
AGENT_OWNERS = {
    "market_news": {
        "package": "cron-tg-market-news",
        "pipelines": None,
        "status_args": ("agent-status",),
        "claim_args": ("claim-agent",),
    },
    "kelas_investasi": {
        "package": "cron-tg-kelas-investasi-gtw",
        "pipelines": frozenset({"swing_support"}),
        "status_args": ("--agent-status",),
        "claim_args": ("--claim-agent",),
    },
}


def _owner_path(package: str) -> Path:
    local = ROOT / package / "bin" / "pipeline_owner.py"
    if local.is_file():
        return local
    runtime = package.replace("cron-", "bursawatch-")
    return Path.home() / ".agents" / "skills" / runtime / "bin" / "pipeline_owner.py"


def _owner_environment(package: str) -> dict[str, str]:
    environment = os.environ.copy()
    if package == "cron-tg-market-news" and not environment.get("IDX_MARKET_NEWS_STATE_PATH"):
        # Direct owner calls bypass the wrapper that selects this canonical ledger.
        environment["IDX_MARKET_NEWS_STATE_PATH"] = str(
            Path.home() / ".hermes" / "state" / "idx-market-news.json"
        )
    return environment


def _owner_handler(package: str, *, no_post: bool):
    path = _owner_path(package)

    def handle(item: dict[str, Any]) -> None:
        environment = _owner_environment(package)
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


def _owner_command(package: str, *arguments: str) -> dict[str, Any]:
    path = _owner_path(package)
    result = subprocess.run(
        [sys.executable, str(path), *arguments],
        text=True,
        capture_output=True,
        timeout=60,
        env=_owner_environment(package),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("agent owner command failed")
    try:
        value = json.loads(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("agent owner response is invalid") from error
    if type(value) is not dict:
        raise RuntimeError("agent owner response is invalid")
    return value


def _read_last_agent_owner(state_root: Path) -> str | None:
    path = state_root / "agent-dispatch.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise RuntimeError("agent dispatch state is unavailable") from None
    if type(value) is not dict or set(value) != {"version", "last_owner"} or value["version"] != 1 or value["last_owner"] not in AGENT_OWNERS:
        raise RuntimeError("agent dispatch state is invalid")
    return value["last_owner"]


def _write_last_agent_owner(state_root: Path, owner: str) -> None:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state_root / "agent-dispatch.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".agent-dispatch-", dir=state_root)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"version": 1, "last_owner": owner}, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(state_root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _ready_agent_candidate(owner: str, status: dict[str, Any]) -> dict[str, Any] | None:
    if type(status.get("ready")) is not bool:
        raise RuntimeError("agent owner status is invalid")
    if not status["ready"]:
        return None
    specification = AGENT_OWNERS[owner]
    pipeline_id = status.get("pipeline_id")
    event_key = status.get("event_key")
    published_at = status.get("published_at")
    supported_pipelines = specification["pipelines"]
    if ((supported_pipelines is not None and pipeline_id not in supported_pipelines) or type(event_key) is not str
            or not event_key or len(event_key) > 256 or type(published_at) is not str):
        raise RuntimeError("agent owner status is invalid")
    try:
        timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("agent owner timestamp is invalid") from error
    if timestamp.tzinfo is None:
        raise RuntimeError("agent owner timestamp is invalid")
    return {
        "owner": owner,
        "pipeline_id": pipeline_id,
        "event_key": event_key,
        "published_at": timestamp.astimezone(timezone.utc),
    }


def _claimed_agent_payload(owner: str, claim: dict[str, Any]) -> dict[str, Any] | None:
    if type(claim.get("wakeAgent")) is not bool:
        raise RuntimeError("agent owner claim is invalid")
    if not claim["wakeAgent"]:
        return None
    if owner == "market_news":
        items = claim.get("items")
        if type(items) is not list or len(items) != 1 or type(items[0]) is not dict:
            raise RuntimeError("Market News wake payload is invalid")
        return {"wakeAgent": True, "agent_target": owner, "items": items}
    item = claim.get("item")
    if type(item) is not dict:
        raise RuntimeError("Kelas wake payload is invalid")
    return {"wakeAgent": True, "agent_target": owner, "item": item}


def dispatch_agent(state_root: Path, *, owner_command: Any = _owner_command) -> dict[str, Any]:
    """Claim at most one oldest ready Hermes task across the Telegram owners."""
    last_owner = _read_last_agent_owner(state_root)
    owners = list(AGENT_OWNERS)
    if last_owner in owners:
        start = (owners.index(last_owner) + 1) % len(owners)
        tie_order = owners[start:] + owners[:start]
    else:
        tie_order = owners
    tie_rank = {owner: index for index, owner in enumerate(tie_order)}
    candidates = []
    unavailable = []
    for owner, specification in AGENT_OWNERS.items():
        try:
            status = owner_command(specification["package"], *specification["status_args"])
            candidate = _ready_agent_candidate(owner, status)
        except Exception:
            unavailable.append(owner)
            continue
        if candidate is not None:
            candidate["tie_rank"] = tie_rank[owner]
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item["published_at"], item["tie_rank"], item["owner"]))
    for candidate in candidates:
        owner = candidate["owner"]
        specification = AGENT_OWNERS[owner]
        try:
            claim = owner_command(specification["package"], *specification["claim_args"])
            payload = _claimed_agent_payload(owner, claim)
        except Exception:
            unavailable.append(owner)
            continue
        if payload is None:
            continue
        _write_last_agent_owner(state_root, owner)
        if unavailable:
            payload["agent_dispatch_warning"] = True
        return payload
    result = {"wakeAgent": False}
    if unavailable:
        result["agent_dispatch_warning"] = True
    return result


def _process_pending(inbox: Any, state_root: Path, *, handlers: dict[str, Any] | None = None, agent_dispatcher: Any = dispatch_agent, owner_command: Any = _owner_command) -> dict[str, Any]:
    selected = handlers if handlers is not None else {pipeline: _owner_handler(package, no_post=False) for pipeline, package in PIPELINE_OWNERS.items()}
    work = PipelineRuntime(inbox, selected).run_once(limit=20)
    delivery: dict[str, Any] = {}
    delivery_warning = False
    if handlers is None:
        try:
            delivery = owner_command("cron-tg-market-news", "drain-delivery")
            if (
                type(delivery.get("news_delivered")) is not int
                or type(delivery.get("stock_status_delivered")) is not int
                or type(delivery.get("pending")) is not int
            ):
                raise RuntimeError("Market News owner drain response is invalid")
        except Exception:
            delivery_warning = True
    agent = agent_dispatcher(state_root) if agent_dispatcher is not None else {"wakeAgent": False}
    return {"work": work, "owner_delivery": delivery, "owner_delivery_warning": delivery_warning, **agent}


def format_heartbeat(now: datetime, result: dict[str, Any]) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("heartbeat time must be timezone-aware")
    source = result.get("source", [])
    work = result.get("work", [])
    if type(source) is not list or type(work) is not list:
        raise ValueError("heartbeat counters are invalid")
    accepted = sum(item.get("accepted", 0) for item in source if type(item) is dict and type(item.get("accepted", 0)) is int)
    endpoint_count = len({item.get("endpoint_id") for item in source if type(item) is dict and type(item.get("endpoint_id")) is str})
    pending = sum(item.get("status") in {"retry", "settlement_unconfirmed", "begin_rejected", "unsupported_pipeline", "dead_letter"} for item in work if type(item) is dict)
    target = result.get("agent_target", "none")
    if target not in {"none", *AGENT_OWNERS}:
        target = "invalid"
    warning = bool(result.get("agent_dispatch_warning") or result.get("owner_delivery_warning")) or pending > 0 or any(
        type(item) is dict and item.get("status") in {"resilience_blocked", "auth_required", "blocked"}
        for item in source
    )
    suffix = " ⚠️" if warning else ""
    return (
        f"🫀 {WATCHER} · {now.astimezone(WIB):%H:%M} WIB · "
        f"endpoints={endpoint_count} accepted={accepted} work={len(work)} pending={pending} agent={target}{suffix}"
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
        raise RuntimeError("heartbeat receipt is invalid")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = delivery_client.wait(operation.key, HEARTBEAT_DELIVERY_WAIT_SECONDS)
    if receipt.key != operation.key or receipt.digest != operation.digest or receipt.status != "delivered":
        raise RuntimeError("heartbeat delivery is incomplete")


async def run_once(telegram: Any, snapshot: dict[str, Any], state_root: Path, inbox: Any, now: datetime, *, handlers: dict[str, Any] | None = None, media_store: Any = None, agent_dispatcher: Any = None) -> dict[str, Any]:
    try:
        source = await ingest_all(telegram, snapshot, state_root, inbox, now, media_store=media_store)
    except Exception:
        # Existing owner deliveries are independent of a fresh source poll.
        if handlers is None:
            try:
                _owner_command("cron-tg-market-news", "drain-delivery")
            except Exception:
                pass
        raise
    dispatch = agent_dispatcher
    if dispatch is None and handlers is None:
        dispatch = dispatch_agent
    pending = _process_pending(inbox, state_root, handlers=handlers, agent_dispatcher=dispatch)
    return {"source": source, **pending}


def _client() -> SourceEventClient:
    url = os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_URL"]
    token_file = Path(os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE"])
    if token_file.stat().st_mode & 0o077:
        raise RuntimeError("source inbox token file permissions are too broad")
    return SourceEventClient(url, token_file.read_text().strip())


def _media_client():
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    if not token_file or not url:
        return None
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token_file))


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
        return {"source": [{"status": "resilience_blocked"}], **_process_pending(inbox, state_root)}
    telegram = _telegram_client()
    try:
        await telegram.connect()
        if not await telegram.is_user_authorized():
            resilience.record_auth_required(decision.lease_id, WATCHER, now)
            return {"source": [{"status": "auth_required"}], **_process_pending(inbox, state_root)}
        resilience.record_authenticated_success(decision.lease_id, WATCHER, now, getattr(telegram.session, "dc_id", None), None)
        return await run_once(telegram, snapshot, state_root, inbox, now, media_store=_media_client())
    except Exception as error:
        if is_transport_error(error):
            resilience.record_transport_failure(decision.lease_id, WATCHER, error, now)
        raise
    finally:
        await telegram.disconnect()


def main() -> int:
    if os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected synthetic clients for no-post validation")
    now = datetime.now(timezone.utc)
    try:
        result = asyncio.run(_run_live())
    except Exception:
        try:
            post_heartbeat(format_fatal(now), now)
        except Exception:
            pass
        raise RuntimeError("source processing failed") from None
    post_heartbeat(format_heartbeat(now, result), now)
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


def verify_synthetic() -> int:
    """Exercise only pure adapter contracts with synthetic, in-memory data."""
    from types import SimpleNamespace

    snapshot = {
        "revision": 1,
        "subscriptions": [{
            "platform": "telegram",
            "endpoint_id": "telegram:phintraprofits",
            "publisher_id": "phintraco",
            "address": "phintraprofits",
            "provider_id": "1444713822",
            "capability_id": "trading_plans",
            "verification_status": "verified",
            "enabled": True,
        }],
    }
    bound = normalize_endpoints(snapshot)["telegram:phintraprofits"]
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    message = SimpleNamespace(
        id=424242,
        raw_text="Synthetic Telegram source event",
        date=now,
        media=None,
        photo=None,
        reply_to_msg_id=None,
    )
    event = make_envelope(bound, message, now)
    if event["provider_event_id"] != "424242" or event["payload"]["text"] != message.raw_text:
        raise RuntimeError("synthetic Telegram adapter verification failed")
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
    if sys.argv[1:] == ["--verify-synthetic"]:
        raise SystemExit(verify_synthetic())
    raise SystemExit(main())
