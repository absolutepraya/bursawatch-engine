"""Telegram source work accepted into the existing Market News owner ledger."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import scan
from agent_protocol import agent_item, build_wake_payload
from domain import Provider
from news_source_work import candidate_keys, loaded_config_for, provenance, put_provenance
from sources import PhintracoNewsAdapter, TuntunNewsAdapter
from state import (
    StateBlockedError, claim_oldest_pending_analysis, enqueue_candidate,
    enqueue_stock_status, expire_agent_leases, has_stock_status_event,
    load_state, reject_stock_status, run_lock, save_state,
)
from stock_status import StockStatusError, format_stock_status, is_stock_information, parse_stock_information


class OwnerPending(RuntimeError):
    pass


NEWS_ENDPOINTS = {
    "telegram:phintasprofits": ("phintraco", "phintasprofits", Provider.PHINTRACO),
    "telegram:tuntunsekuritas": ("tuntun", "tuntunsekuritas", Provider.TUNTUN),
}


def _check_no_post(no_post: bool) -> None:
    if no_post:
        isolated = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
        if not isolated or Path(isolated).expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
            raise ValueError("no-post owner work requires isolated state")


def _check_identity(work: dict[str, Any], capability: str) -> dict[str, Any]:
    envelope = work["envelope"]
    expected = hashlib.sha256(f'{work["event_key"]}:1:{capability}'.encode()).hexdigest()
    endpoint_id = envelope.get("endpoint_id")
    if not isinstance(endpoint_id, str):
        raise ValueError("News work source is not supported for this pipeline")
    source = NEWS_ENDPOINTS.get(endpoint_id)
    if (capability == "stock_status" and endpoint_id != "telegram:phintasprofits") or source is None:
        raise ValueError("News work source is not supported for this pipeline")
    identity = (work["pipeline_id"], work["capability_id"], work["version"], envelope["publisher_id"])
    if identity != (capability, capability, 1, source[0]):
        raise ValueError("News work identity or media contract is invalid")
    if (
        work["effect_key"] != expected
        or work["work_key"] != expected
        or type(envelope["media_refs"]) is not list
        or type(envelope["media_required"]) is not bool
        or (envelope["media_required"] and not envelope["media_refs"])
    ):
        raise ValueError("News work identity or media contract is invalid")
    return envelope


def _inbox_client():
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents" / "skills" / "lib-bursawatch-control" / "bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from source_event_client import SourceEventClient

    token_file = Path(os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE"])
    if token_file.stat().st_mode & 0o077:
        raise ValueError("source inbox token file permissions are too broad")
    return SourceEventClient(
        os.environ["BURSAWATCH_TG_SOURCE_CONTROL_PLANE_URL"],
        token_file.read_text().strip(),
    )


def _news_siblings(work: dict[str, Any], inbox: Any) -> dict[str, str]:
    inspected = inbox.inspect(work["event_key"])
    event = inspected.get("event")
    rows = inspected.get("work")
    if not isinstance(event, dict) or event.get("event_key") != work["event_key"] or not isinstance(rows, list):
        raise ValueError("News source-work inspection is invalid")
    versions = event.get("versions")
    if not isinstance(versions, list) or not any(
        isinstance(version, dict) and version.get("version") == work["version"]
        and version.get("envelope") == work["envelope"] for version in versions
    ):
        raise ValueError("News source-work version is invalid")
    keys: dict[str, str] = {}
    active = False
    for row in rows:
        if not isinstance(row, dict) or row.get("version") != work["version"]:
            continue
        capability = row.get("capability_id")
        if capability not in {"company_news", "macro_news"}:
            continue
        expected = hashlib.sha256(f'{work["event_key"]}:{work["version"]}:{capability}'.encode()).hexdigest()
        if (row.get("work_key") != expected or row.get("effect_key") != expected
            or row.get("pipeline_id") != capability or row.get("settings") != {}
            or row.get("catalog_revision") != work.get("catalog_revision")):
            raise ValueError("News sibling work identity is invalid")
        # The sibling rows capture the capabilities enabled when the event was
        # accepted. Execution status must not change route eligibility or the
        # stable provenance recorded when another sibling is replayed.
        keys[capability] = expected
        if expected == work["work_key"]:
            active = row.get("status") == "executing" and row.get("lease_token") == work.get("lease_token")
    if not active or work["capability_id"] not in keys:
        raise ValueError("News source work has not begun or was superseded")
    return keys


def submit_news(work: dict[str, Any], *, no_post: bool = False, inbox: Any = None) -> str:
    """Accept one source publication once, even with two route subscriptions."""
    _check_no_post(no_post)
    capability = work.get("pipeline_id")
    if capability not in {"company_news", "macro_news"}:
        raise ValueError("unsupported News pipeline")
    envelope = _check_identity(work, capability)
    if work.get("event_kind") != "original" or work.get("version") != 1:
        raise ValueError("News corrections require a separate reviewed owner contract")
    message_id_text = envelope.get("provider_event_id")
    if not isinstance(message_id_text, str) or not re.fullmatch(r"[1-9][0-9]*", message_id_text):
        raise ValueError("News source message ID is invalid")
    message_id = int(message_id_text)
    source = NEWS_ENDPOINTS[envelope["endpoint_id"]]
    _, handle, provider = source
    if envelope.get("source_url") != f"https://t.me/{handle}/{message_id}":
        raise ValueError("News source URL is invalid")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("News source payload is invalid")
    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("News source text is invalid")
    published_at = datetime.fromisoformat(envelope["published_at"])
    if published_at.tzinfo is None:
        raise ValueError("News source time is not timezone-aware")
    keys = _news_siblings(work, inbox if inbox is not None else _inbox_client())
    if provider is Provider.PHINTRACO and is_stock_information(text):
        return "irrelevant"
    direct_image = any(ref.get("kind") == "image" for ref in envelope["media_refs"])
    if provider is Provider.TUNTUN:
        topic_id = payload.get("topic_id")
        if topic_id is not None and (type(topic_id) is not int or topic_id < 1):
            raise ValueError("Tuntun topic identity is invalid")
        extracted = TuntunNewsAdapter().extract_candidates(message_id, text, published_at, topic_id, direct_image)
    else:
        extracted = PhintracoNewsAdapter().extract_candidates(message_id, text, published_at, direct_image)
    if not extracted:
        return "irrelevant"
    if (
        any(candidate.provider is not provider for candidate in extracted)
        or len({candidate.key for candidate in extracted}) != len(extracted)
    ):
        raise ValueError("News source produced an unexpected candidate set")
    with run_lock():
        state = load_state()
        candidates = state["candidates"]
        assert isinstance(candidates, dict)
        loaded = None
        for candidate in extracted:
            existing = provenance(state, candidate.key)
            if existing is None and candidate.key in candidates:
                raise StateBlockedError("News candidate already exists without source-work provenance")
            if existing is not None:
                frozen = loaded_config_for(state, candidate.key)
                assert frozen is not None
                if loaded is not None and loaded != frozen:
                    raise StateBlockedError("one News source event has conflicting frozen config snapshots")
                loaded = frozen
        if loaded is None:
            loaded = config.load_watch_config_for_run()
        username = loaded.config.phintraco_username if provider is Provider.PHINTRACO else loaded.config.tuntun_username
        if username != handle:
            raise ValueError("Market News provider config differs from source identity")
        enqueued_at = datetime.now(scan.WIB)
        for candidate in extracted:
            put_provenance(
                state, candidate.key, event_key=work["event_key"],
                version=work["version"], content_hash=envelope["content_hash"],
                source_url=envelope["source_url"], work_keys=keys,
                loaded_config=loaded, summary_media_refs=envelope["media_refs"],
            )
            enqueue_candidate(state, candidate, enqueued_at)
    return "accepted"


def agent_status(now: datetime | None = None) -> dict[str, Any]:
    """Inspect owner work without claiming a candidate or rewriting state."""
    now = now or datetime.now(scan.WIB)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("agent status time must be timezone-aware")
    state = load_state(migrate=False)
    records = state["candidates"]
    assert isinstance(records, dict)
    phases = {"pending_analysis": 0, "awaiting_agent": 0, "pending_selection": 0, "pending_delivery": 0}
    ready: list[tuple[str, str, str]] = []
    for key in candidate_keys(state):
        record = records[key]
        phase = record["phase"]
        if phase in phases:
            phases[phase] += 1
        retry = record["retry"]
        due = retry["next_attempt_at"]
        pending_due = phase == "pending_analysis" and (due is None or datetime.fromisoformat(due) <= now)
        lease_until = record["agent_lease_until"]
        lease_expired = (
            phase == "awaiting_agent" and isinstance(lease_until, str)
            and datetime.fromisoformat(lease_until) <= now
        )
        if pending_due or lease_expired:
            origin = provenance(state, key)
            assert origin is not None
            ready.append((record["enqueued_at"], key, origin["event_key"]))
    if ready:
        _, key, event_key = min(ready)
        published_at = records[key]["candidate"]["published_at"]
    else:
        event_key = published_at = None
    return {
        "wakeAgent": False, "ready": bool(ready), "event_key": event_key,
        "published_at": published_at, "candidates": phases,
    }


def claim_agent(now: datetime | None = None) -> dict[str, Any]:
    """Return at most one exact existing Hermes classifier item."""
    now = now or datetime.now(scan.WIB)
    with run_lock():
        state = load_state()
        keys = candidate_keys(state)
        expire_agent_leases(state, now, candidate_keys=keys)
        candidate = claim_oldest_pending_analysis(state, now, candidate_keys=keys)
        if candidate is None:
            return {"wakeAgent": False, "items": []}
        frozen = loaded_config_for(state, candidate.key)
        assert frozen is not None
        with config.activate_watch_config(frozen.config):
            import summary_context
            import state as owner_state
            item = agent_item(candidate)
            instruction_suffix = summary_context.context_instruction(
                summary_context.claim_from_state(state, candidate.key, owner_state._state_path().parent / "summary-context"),
                "~/.hermes/scripts/bursawatch-tg-market-news.sh prepare-summary-images --json",
            )
            item["instruction"] += instruction_suffix
            return build_wake_payload([item], instruction_suffix=instruction_suffix)


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
                enqueue_stock_status(
                    state, parsed, envelope["source_url"],
                    loaded.config.id_stocks_news_channel_id, content, now,
                    source_event_key=work["event_key"],
                    config_revision=loaded.revision,
                )
                save_state(state)
            asyncio.run(scan._drain_stock_status_events(state, now, no_post))
            scan._drain_publications(state, now, dry_run=no_post)
            key = f"phintraco-stock-status:{message_id}"
            record = state["stats"]["stock_status_events"][key]
            if record["phase"] == "pending_delivery":
                raise OwnerPending("News owner delivery remains pending")
    return "accepted"


def submit(work: dict[str, Any], *, no_post: bool = False, inbox: Any = None) -> str:
    if work.get("pipeline_id") in {"company_news", "macro_news"}:
        return submit_news(work, no_post=no_post, inbox=inbox)
    if work.get("pipeline_id") != "stock_status":
        raise ValueError("unsupported Market News pipeline")
    return submit_stock_status(work, no_post=no_post)



def drain_deliveries(now: datetime | None = None, *, no_post: bool = False) -> dict[str, int]:
    """Settle due owner deliveries without polling Telegram or claiming agent work."""
    if no_post:
        raise ValueError("delivery drain is unavailable in source no-post mode")
    observed = now or datetime.now(scan.WIB)
    loaded = config.load_watch_config_for_run()
    with config.activate_watch_config(loaded.config):
        with run_lock():
            state = load_state()
            scan._drain_publications(state, observed)
            delivery_client = scan.delivery_client_from_environment()
            news_delivered = asyncio.run(scan._drain_delivery(
                state, None, observed, False, delivery_client=delivery_client, limit=3,
            ))
            stock_status_delivered = asyncio.run(scan._drain_stock_status_events(
                state, observed, False, delivery_client=delivery_client, limit=1,
            ))
            scan._drain_publications(state, observed)
            pending = scan._pending_count(state)
    return {
        "news_delivered": news_delivered,
        "stock_status_delivered": stock_status_delivered,
        "pending": pending,
    }


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "agent-status":
        print(json.dumps(agent_status(), separators=(",", ":")))
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "claim-agent":
        print(json.dumps(claim_agent(), separators=(",", ":"), ensure_ascii=False))
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "drain-delivery":
        print(json.dumps(drain_deliveries(
            no_post=os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1"
        ), separators=(",", ":")))
        return 0
    if len(sys.argv) != 1:
        raise ValueError("unsupported Market News owner command")
    work = json.load(sys.stdin)
    result = submit(work, no_post=os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1")
    print(json.dumps({"outcome": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
