"""Deterministic Stock Information work through the current News owner ledger.

Agent-classified News still needs a bounded Hermes classifier submission
interface before it can be claimed by the source-work runtime.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import scan
from state import has_stock_status_event, load_state, run_lock, save_state, enqueue_stock_status, reject_stock_status
from stock_status import StockStatusError, format_stock_status, is_stock_information, parse_stock_information


class OwnerPending(RuntimeError):
    pass


def _check_no_post(no_post: bool) -> None:
    if no_post:
        isolated = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
        if not isolated or Path(isolated).expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
            raise ValueError("no-post owner work requires isolated state")


def _check_identity(work: dict[str, Any], capability: str) -> dict[str, Any]:
    envelope = work["envelope"]
    expected = hashlib.sha256(f'{work["event_key"]}:1:{capability}'.encode()).hexdigest()
    if (work["pipeline_id"], work["capability_id"], work["version"], envelope["endpoint_id"], envelope["publisher_id"]) != (capability, capability, 1, "telegram:phintasprofits", "phintraco") or work["effect_key"] != expected or work["work_key"] != expected or type(envelope["media_refs"]) is not list or (envelope["media_required"] and not envelope["media_refs"]):
        raise ValueError("News work identity or media contract is invalid")
    return envelope


def submit_stock_status(work: dict[str, Any], *, no_post: bool = False) -> str:
    _check_no_post(no_post)
    envelope = _check_identity(work, "stock_status")
    text = envelope["payload"]["text"]
    if not is_stock_information(text):
        return "irrelevant"
    message_id = int(envelope["provider_event_id"])
    now = datetime.now(scan.WIB)
    loaded = config.load_watch_config_for_run()
    with config.activate_watch_config(loaded.config):
        with run_lock():
            state = load_state()
            if not has_stock_status_event(state, message_id):
                try:
                    parsed = parse_stock_information(message_id, text)
                    content = format_stock_status(parsed, envelope["source_url"])
                except StockStatusError as error:
                    code = "message_too_long" if "exceeds Discord limit" in str(error) else "invalid_status"
                    reject_stock_status(state, message_id, envelope["source_url"], code, now)
                    save_state(state)
                    return "rejected"
                enqueue_stock_status(state, parsed, envelope["source_url"], loaded.config.id_stocks_news_channel_id, content, now)
                save_state(state)
            asyncio.run(scan._drain_stock_status_events(state, now, no_post))
            key = f"phintraco-stock-status:{message_id}"
            record = state["stats"]["stock_status_events"][key]
            if record["phase"] == "pending_delivery":
                raise OwnerPending("News owner delivery remains pending")
    return "accepted"


def submit(work: dict[str, Any], *, no_post: bool = False) -> str:
    if work.get("pipeline_id") != "stock_status":
        raise ValueError("agent News work has no bounded Hermes classifier handoff")
    return submit_stock_status(work, no_post=no_post)


def main() -> int:
    import sys
    work = json.load(sys.stdin)
    result = submit(work, no_post=os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1")
    print(json.dumps({"outcome": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
