"""Unscheduled RSS source entry point for Stockbit's fixed lanes only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Keep synthetic release verification from creating source-tree bytecode.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
for local_name, runtime_name in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
    ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
):
    candidate = ROOT / local_name / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / runtime_name / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
sys.path.insert(0, str(owner))
import config as stockbit_config
from source_runner import client, state_root
from pipeline_runtime import PipelineRuntime
from adapter import require_legacy_cursor_seed, run_once as ingest_once
from config import HEARTBEAT_CHANNEL_ID, WATCHER_NAME, FEEDS, load_watch_config_for_run
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


def run_once(snapshot: dict | None, loaded_config: object | None, root: Path, inbox: object, observed_at: datetime, *, fetch_feed=None, handler=None, owner_command=None, require_legacy_seed: bool = False) -> dict:
    if snapshot is None or loaded_config is None:
        source = [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "intake_config_unavailable"}]
    elif require_legacy_seed:
        try:
            require_legacy_cursor_seed(root, snapshot, loaded_config)
        except IntakeBlocked:
            source = [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "migration_cursor_handoff_invalid"}]
        else:
            source = ingest_once(snapshot, loaded_config, root, inbox, observed_at, fetch_feed=fetch_feed)
    else:
        try:
            source = ingest_once(snapshot, loaded_config, root, inbox, observed_at, fetch_feed=fetch_feed)
        except IntakeBlocked:
            source = [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "intake_config_mismatch"}]
    work = PipelineRuntime(inbox, {"stockbit_snips": handler or _owner_handler}).run_once(limit=20)
    command = owner_command or _owner_command
    try:
        delivery = command("drain-delivery")
        if (
            type(delivery.get("delivered")) is not int
            or type(delivery.get("pending_delivery")) is not int
            or delivery["delivered"] < 0
            or delivery["pending_delivery"] < 0
        ):
            raise RuntimeError("Stockbit owner drain response is invalid")
        delivery_error = False
    except Exception:
        delivery = {"delivered": 0}
        delivery_error = True
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
    return {"source": source, "work": work, "owner_delivery": delivery, "owner_delivery_error": delivery_error, **agent}


def main() -> int:
    if sys.argv[1:] == ["--verify-synthetic"]:
        return verify_synthetic()
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
    observed_at = datetime.now(timezone.utc)
    try:
        results = run_once(
            snapshot,
            loaded,
            state_root("BURSAWATCH_RSS_SOURCE", "bursawatch-rss-source-ingest"),
            inbox,
            observed_at,
            require_legacy_seed=True,
        )
    except Exception:
        try:
            send_heartbeat({"source": [{"status": "blocked", "accepted": 0, "fetched": 0}], "work": [], "fatal": True}, observed_at)
        except Exception:
            pass
        raise RuntimeError("RSS source ingest run failed") from None
    try:
        send_heartbeat(results, observed_at)
    except Exception:
        results["heartbeat_error"] = True
    print(json.dumps(results, separators=(",", ":")))
    return 0


def _owner_pending_count() -> int:
    import state as stockbit_state

    runtime = stockbit_config.runtime()
    with stockbit_state.run_lock(runtime.state_path):
        value = stockbit_state.load_state(runtime.state_path, FEEDS)
    articles = value.get("articles")
    if type(articles) is not dict:
        raise RuntimeError("Stockbit owner state is invalid")
    return sum(
        1 for record in articles.values()
        if type(record) is dict and record.get("phase") in {"awaiting_agent", "pending_delivery"}
    )


def send_heartbeat(result: dict, now: datetime, *, pending_count: int | None = None, post_text=None) -> None:
    """Publish count-only run evidence through the existing Delivery Owner."""
    source = result.get("source")
    work = result.get("work")
    if type(source) is not list or type(work) is not list:
        raise RuntimeError("RSS heartbeat run summary is invalid")
    if any(type(row) is not dict for row in source + work):
        raise RuntimeError("RSS heartbeat run summary is invalid")
    fetched = sum(row.get("fetched", 0) for row in source if type(row.get("fetched", 0)) is int and row.get("fetched", 0) >= 0)
    queued = sum(row.get("accepted", 0) for row in source if type(row.get("accepted", 0)) is int and row.get("accepted", 0) >= 0)
    errors = sum(row.get("status") == "blocked" for row in source)
    errors += sum(row.get("status") != "done" for row in work)
    errors += int(result.get("fatal") is True)
    errors += int(result.get("owner_delivery_error") is True)
    delivery = result.get("owner_delivery", {})
    delivered = delivery.get("delivered", 0) if type(delivery) is dict else 0
    if type(delivered) is not int or delivered < 0:
        raise RuntimeError("RSS heartbeat delivered count is invalid")
    pending = _owner_pending_count() if pending_count is None else pending_count
    if type(pending) is not int or pending < 0:
        raise RuntimeError("RSS heartbeat pending count is invalid")
    local = now.astimezone(ZoneInfo("Asia/Jakarta"))
    warning = " ⚠️" if errors else ""
    content = (
        f"🫀 {WATCHER_NAME} · {local:%H:%M} WIB · {fetched} fetched · "
        f"{queued} queued · {delivered} delivered · {errors} errors · {pending} pending{warning}"
    )
    sender = post_text
    if sender is None:
        from discord import post_text as sender
    sender(
        content,
        HEARTBEAT_CHANNEL_ID,
        dry_run=False,
        event_key=f"heartbeat:{local:%Y%m%d%H%M}",
        leg="heartbeat",
    )


def verify_synthetic() -> int:
    """Exercise RSS endpoint binding and event serialization without side effects."""
    from adapter import _item, endpoints
    from config import FEEDS, ID_STOCKS_NEWS_CHANNEL_ID, MACRO_NEWS_CHANNEL_ID, LoadedStockbitConfig, load_watch_config_data
    from models import Article
    from source_ingest import envelope

    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    loaded = LoadedStockbitConfig(
        load_watch_config_data({
            "version": 1,
            "feeds": [{"id": feed.lane.value, "enabled": True} for feed in FEEDS],
            "destinations": {
                "id_stocks_news_channel_id": ID_STOCKS_NEWS_CHANNEL_ID,
                "macro_news_channel_id": MACRO_NEWS_CHANNEL_ID,
            },
            "additional_prompt_instruction": "",
        }),
        revision=1,
    )
    snapshot = {
        "revision": 1,
        "subscriptions": [{
            "platform": "rss",
            "endpoint_id": f"rss:stockbit:{feed.lane.value}",
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": feed.lane.value,
            "capability_id": "stockbit_snips",
            "verification_status": "verified",
            "enabled": True,
        } for feed in FEEDS],
    }
    selected, _ = endpoints(snapshot, loaded)
    feed = FEEDS[0]
    article = Article(
        feed.lane,
        feed.label,
        "synthetic-rss-guid",
        "https://snips.stockbit.com/synthetic",
        "Synthetic title",
        "Synthetic body",
        now,
    )
    item = _item(article, loaded)
    event = envelope(selected[f"rss:stockbit:{feed.lane.value}"], item, now, "stockbit-rss-parser-1")
    if (
        event["provider_event_id"] != item["provider_event_id"]
        or event["media_required"] is not False
        or event["media_refs"] != []
        or event["payload"]["article"]["guid"] != article.guid
        or loaded.config.additional_prompt_instruction != ""
    ):
        raise RuntimeError("synthetic RSS adapter verification failed")
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
