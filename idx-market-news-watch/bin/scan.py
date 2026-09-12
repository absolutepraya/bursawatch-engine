#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from telegram_resilience import (
    PolyCopResilience,
    StateBlockedError as ResilienceStateBlockedError,
    acquire_probe_after_active_lease,
    is_transport_error,
)

from agent_protocol import agent_item, build_wake_payload, submit_classification as submit_agent_classification
from delivery import deliver_event, post_discord_text
from domain import CompanyCandidate, EventClass, Provider, SourceKind
from selection import (
    SelectionCandidate,
    assign_tier,
    is_confident_duplicate,
    pending_selection_candidates,
)
from sources import PhintracoNewsAdapter, TuntunNewsAdapter, bootstrap_provider, fetch_unseen_messages
from state import (
    StateBlockedError,
    abandon_active_candidates,
    advance_provider_cursor,
    claim_oldest_pending_analysis,
    enqueue_candidate,
    expire_agent_leases,
    load_state,
    mark_terminal,
    provider_bootstrap_complete,
    provider_cursor,
    run_lock,
    save_state,
)

WIB = ZoneInfo("Asia/Jakarta")
WATCHER_NAME = "idx-market-news"
ALERT_CHANNEL_ID = "1525102508714889257"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
PHINTRACO_ENTITY = "phintasprofits"
TUNTUN_ENTITY = "tuntunsekuritas"
_DELIVERY_CONTRACT_MIGRATION_KEY = "immediate_delivery_contract_v1"
_ACTIVE_PHASES = frozenset(
    {
        "pending_analysis",
        "awaiting_agent",
        "pending_selection",
        "pending_delivery",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeClients:
    """One shared Telegram client with the two pre-resolved allowed entities."""

    client: Any
    phintraco_entity: Any
    tuntun_entity: Any


def _require_aware(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def _dry_run() -> bool:
    return os.environ.get("IDX_MARKET_NEWS_NO_POST") == "1"


def _hour_key(now: datetime) -> str:
    return now.astimezone(WIB).strftime("%Y-%m-%dT%H%z")


def _clean_reason(reason: object) -> str:
    return re.sub(r"\s+", " ", str(reason)).strip()[:180]


def error_fingerprint(reason: object) -> str:
    import hashlib

    return hashlib.sha256(_clean_reason(reason).encode("utf-8")).hexdigest()[:16]


def format_fatal(now: datetime, reason: object) -> str:
    _require_aware(now)
    return f"❌ {WATCHER_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {_clean_reason(reason)}"


def format_heartbeat(
    now: datetime,
    source_messages: int,
    classified_candidates: int,
    news_delivered: int,
    pending: int,
    *,
    provider_errored: bool = False,
    retrying: bool = False,
    delivery_pending: bool = False,
) -> str:
    """Render the fixed watcher heartbeat, including only operational counters."""
    _require_aware(now)
    line = (
        f"🫀 {WATCHER_NAME} · {now.astimezone(WIB):%H:%M} WIB · "
        f"{source_messages} source messages · {classified_candidates} classified candidates · "
        f"{news_delivered} news delivered · {pending} pending"
    )
    return line + (" ⚠️" if provider_errored or retrying or delivery_pending else "")


def post_hermes_text(content: str, event_key: str, dry_run: bool) -> str | None:
    """Post watcher operations only to the Hermes heartbeat channel."""
    return post_discord_text(content, HEARTBEAT_CHANNEL_ID, event_key, dry_run=dry_run)


def _make_client() -> Any:
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session = os.environ.get("POLYCOP_SESSION_STRING")
    if not api_id or not api_hash or not session:
        raise RuntimeError("TELEGRAM_API_ID, TELEGRAM_API_HASH, and POLYCOP_SESSION_STRING are required")
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(session), int(api_id), api_hash)


def resilience() -> PolyCopResilience:
    return PolyCopResilience.from_defaults()


def _connection_metadata(client: object) -> tuple[int | None, str | None]:
    session = getattr(client, "session", None)
    dc_id = getattr(session, "dc_id", None)
    endpoint = getattr(session, "server_address", None)
    port = getattr(session, "port", None)
    if isinstance(endpoint, str) and isinstance(port, int):
        endpoint = f"{endpoint}:{port}"
    return (dc_id if isinstance(dc_id, int) else None, endpoint if isinstance(endpoint, str) else None)


async def _disconnect_quietly(client: object) -> None:
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        await disconnect()
    except Exception:
        pass


def deliver_resilience_notification(
    control: PolyCopResilience, now: datetime, dry_run: bool
) -> None:
    try:
        notification = control.claim_notification(WATCHER_NAME, now)
    except ResilienceStateBlockedError:
        return
    if notification is None:
        return
    try:
        message_id = post_hermes_text(notification.content, notification.event_key, dry_run)
    except Exception:
        return
    if message_id is None:
        return
    try:
        control.acknowledge_notification(notification.claim_id, now)
    except (ResilienceStateBlockedError, ValueError):
        return


def _report_resilience_state_blocked(now: datetime, dry_run: bool) -> None:
    try:
        post_hermes_text(
            f"❌ telegram-polycop · {now.astimezone(WIB):%H:%M} WIB · control state unavailable",
            f"telegram-resilience-state-blocked-{now.astimezone(WIB):%Y%m%d%H}",
            dry_run,
        )
    except Exception:
        pass


async def _resolve_runtime_clients(client: Any) -> RuntimeClients:
    """Resolve each allowed entity independently so one inaccessible lane cannot stop the other."""
    resolved = await asyncio.gather(
        client.get_entity(PHINTRACO_ENTITY),
        client.get_entity(TUNTUN_ENTITY),
        return_exceptions=True,
    )
    return RuntimeClients(client, resolved[0], resolved[1])


def _provided_runtime_clients(clients: object) -> RuntimeClients:
    if isinstance(clients, RuntimeClients):
        return clients
    client = getattr(clients, "client", None)
    phintraco_entity = getattr(clients, "phintraco_entity", None)
    tuntun_entity = getattr(clients, "tuntun_entity", None)
    if client is None or phintraco_entity is None or tuntun_entity is None:
        raise ValueError("clients must provide client, phintraco_entity, and tuntun_entity")
    return RuntimeClients(client, phintraco_entity, tuntun_entity)


def _message_text(message: object) -> str:
    for attribute in ("message", "text", "raw_text"):
        value = getattr(message, attribute, None)
        if isinstance(value, str):
            return value
    return ""


def _message_topic_id(message: object) -> int | None:
    direct = getattr(message, "reply_to_top_id", None)
    if isinstance(direct, int) and not isinstance(direct, bool):
        return direct
    reply_to = getattr(message, "reply_to", None)
    nested = getattr(reply_to, "reply_to_top_id", None)
    if isinstance(nested, int) and not isinstance(nested, bool):
        return nested
    if getattr(reply_to, "forum_topic", False):
        root = getattr(reply_to, "reply_to_msg_id", None)
        if isinstance(root, int) and not isinstance(root, bool):
            return root
    return None


def _message_published_at(message: object) -> datetime:
    published_at = getattr(message, "date", None)
    if not isinstance(published_at, datetime) or published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("source message has no timezone-aware date")
    return published_at


def _message_id(message: object) -> int:
    value = getattr(message, "id", None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("source message has an invalid id")
    return value


def _provider_lane(state: dict[str, object], provider: Provider) -> dict[str, object]:
    providers = state["providers"]
    assert isinstance(providers, dict)
    lane = providers[provider.value]
    assert isinstance(lane, dict)
    return lane


def _mark_provider_success(state: dict[str, object], provider: Provider, now: datetime) -> None:
    lane = _provider_lane(state, provider)
    lane["last_poll_success"] = now.isoformat()
    lane["last_error"] = None
    state["last_poll_success"] = now.isoformat()
    save_state(state)


def _mark_provider_error(state: dict[str, object], provider: Provider, error: Exception) -> None:
    _provider_lane(state, provider)["last_error"] = _clean_reason(error)
    save_state(state)


async def _ingest_provider(
    state: dict[str, object],
    runtime: RuntimeClients,
    provider: Provider,
    entity: object,
    now: datetime,
) -> tuple[int, int, str | None]:
    """Bootstrap or ingest exactly one provider lane without touching the other."""
    try:
        if not provider_bootstrap_complete(state, provider):
            await bootstrap_provider(runtime.client, entity, state, provider)
            _mark_provider_success(state, provider, now)
            return 0, 0, None

        messages = await fetch_unseen_messages(runtime.client, entity, provider_cursor(state, provider))
        adapter = TuntunNewsAdapter() if provider is Provider.TUNTUN else PhintracoNewsAdapter()
        candidates = 0
        for message in messages:
            message_id = _message_id(message)
            text = _message_text(message)
            published_at = _message_published_at(message)
            direct_image = bool(getattr(message, "photo", None))
            extracted = (
                adapter.extract_candidates(message_id, text, published_at, _message_topic_id(message), direct_image)
                if provider is Provider.TUNTUN
                else adapter.extract_candidates(message_id, text, published_at, direct_image)
            )
            for candidate in extracted:
                if enqueue_candidate(state, candidate, now):
                    candidates += 1
            advance_provider_cursor(state, provider, message_id)
        _mark_provider_success(state, provider, now)
        return len(messages), candidates, None
    except Exception as error:
        _mark_provider_error(state, provider, error)
        return 0, 0, _clean_reason(error)


def _selection_item_from_record(key: str, record: Mapping[str, object]) -> SelectionCandidate | None:
    payload = record.get("candidate")
    selection_data = record.get("selection")
    classification = record.get("classification")
    if not isinstance(payload, Mapping) or not isinstance(selection_data, Mapping) or not isinstance(classification, str):
        return None
    try:
        candidate = CompanyCandidate(
            provider=Provider(payload["provider"]),
            source_message_id=payload["source_message_id"],
            ticker=payload["ticker"],
            source_kind=SourceKind(payload["source_kind"]),
            published_at=datetime.fromisoformat(payload["published_at"]),
            source_text=payload["source_text"],
            direct_image=payload["direct_image"],
        )
        item = SelectionCandidate(
            candidate=candidate,
            event_class=EventClass(classification),
            ranking_band=selection_data["ranking_band"],
            material_facts=selection_data["material_facts"],
            dedupe_facts=selection_data["dedupe_facts"],
            summary=selection_data.get("summary", ""),
            title=selection_data.get("title", ""),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StateBlockedError(f"candidate {key!r} has invalid durable selection data") from error
    if item.key != key:
        raise StateBlockedError(f"candidate {key!r} does not match durable selection data")
    return item


def _all_classified(state: dict[str, object]) -> list[SelectionCandidate]:
    records = state["candidates"]
    assert isinstance(records, dict)
    result = [
        item
        for key, record in records.items()
        if isinstance(key, str) and isinstance(record, Mapping)
        for item in [_selection_item_from_record(key, record)]
        if item is not None
    ]
    return sorted(result, key=lambda item: (item.published_at, item.key))


def _suppress_duplicate(state: dict[str, object], duplicate: SelectionCandidate, original: SelectionCandidate) -> None:
    dedupe = state["dedupe"]
    assert isinstance(dedupe, dict)
    dedupe[duplicate.key] = original.key
    mark_terminal(state, duplicate.key, "suppressed_duplicate")


def _migrate_scheduled_delivery_backlog(state: dict[str, object], now: datetime) -> int:
    """Suppress pre-cutover queued work so a delivery-contract change cannot backfill it."""
    stats = state["stats"]
    assert isinstance(stats, dict)
    marker = stats.get(_DELIVERY_CONTRACT_MIGRATION_KEY)
    if marker is not None:
        if isinstance(marker, Mapping) and marker.get("complete") is True:
            return 0
        raise StateBlockedError("malformed state: immediate delivery migration marker is invalid")
    abandoned = abandon_active_candidates(state, "suppressed by immediate delivery contract migration")
    stats[_DELIVERY_CONTRACT_MIGRATION_KEY] = {
        "abandoned": abandoned,
        "complete": True,
        "completed_at": now.isoformat(),
    }
    save_state(state)
    return abandoned


def _route_pending(state: dict[str, object]) -> int:
    """Apply deterministic cross-provider dedupe before immediate delivery routing."""
    pending = pending_selection_candidates(state)
    classified = _all_classified(state)
    routed = 0
    for item in pending:
        earlier = [
            existing
            for existing in classified
            if existing.key != item.key
            and (existing.published_at, existing.key) < (item.published_at, item.key)
            and is_confident_duplicate(existing, item)
        ]
        if earlier:
            _suppress_duplicate(state, item, min(earlier, key=lambda existing: (existing.published_at, existing.key)))
            routed += 1
            continue
        assign_tier(state, item)
        routed += 1
    return routed


def _retry_due(record: Mapping[str, object], now: datetime) -> bool:
    retry = record.get("retry")
    if not isinstance(retry, Mapping):
        return False
    next_attempt_at = retry.get("next_attempt_at")
    if next_attempt_at is None:
        return True
    return isinstance(next_attempt_at, str) and datetime.fromisoformat(next_attempt_at) <= now


def _pending_delivery(state: dict[str, object], now: datetime) -> list[SelectionCandidate]:
    records = state["candidates"]
    assert isinstance(records, dict)
    pending: list[SelectionCandidate] = []
    for key, record in records.items():
        if not isinstance(key, str) or not isinstance(record, Mapping) or record.get("phase") != "pending_delivery":
            continue
        item = _selection_item_from_record(key, record)
        if item is not None and _retry_due(record, now):
            pending.append(item)
    return sorted(pending, key=lambda item: (item.published_at, item.key))




async def _drain_delivery(
    state: dict[str, object], runtime: RuntimeClients | None, now: datetime, dry_run: bool
) -> int:
    delivered = 0
    entities = {} if runtime is None else {
        Provider.PHINTRACO: runtime.phintraco_entity,
        Provider.TUNTUN: runtime.tuntun_entity,
    }
    for item in _pending_delivery(state, now):
        did_deliver = await deliver_event(
            state,
            item,
            ALERT_CHANNEL_ID,
            now,
            dry_run=dry_run,
            client=None if runtime is None else runtime.client,
            entity=entities.get(item.provider),
        )
        if did_deliver:
            delivered += 1
    return delivered


def _pending_count(state: Mapping[str, object]) -> int:
    candidates = state["candidates"]
    assert isinstance(candidates, Mapping)
    return sum(
        1
        for record in candidates.values()
        if isinstance(record, Mapping) and record.get("phase") in _ACTIVE_PHASES
    )


def _health_and_warning(state: Mapping[str, object]) -> tuple[bool, bool, bool]:
    providers = state["providers"]
    candidates = state["candidates"]
    assert isinstance(providers, Mapping) and isinstance(candidates, Mapping)
    provider_errored = any(isinstance(lane, Mapping) and lane.get("last_error") for lane in providers.values())
    retrying = any(
        isinstance(record, Mapping)
        and record.get("phase") in _ACTIVE_PHASES
        and isinstance(record.get("retry"), Mapping)
        and int(record["retry"].get("attempts", 0)) > 0
        for record in candidates.values()
    )
    delivery_pending = any(isinstance(record, Mapping) and record.get("phase") == "pending_delivery" for record in candidates.values())
    return provider_errored, retrying, delivery_pending


def _post_heartbeat_if_due(
    state: dict[str, object],
    now: datetime,
    source_messages: int,
    classified_candidates: int,
    news_delivered: int,
    dry_run: bool,
) -> bool:
    hour = _hour_key(now)
    if os.environ.get("IDX_MARKET_NEWS_FORCE_HEARTBEAT") != "1" and state.get("last_heartbeat_hour") == hour:
        return False
    provider_errored, retrying, delivery_pending = _health_and_warning(state)
    message_id = post_hermes_text(
        format_heartbeat(
            now,
            source_messages,
            classified_candidates,
            news_delivered,
            _pending_count(state),
            provider_errored=provider_errored,
            retrying=retrying,
            delivery_pending=delivery_pending,
        ),
        f"heartbeat-{hour}",
        dry_run,
    )
    if message_id is None:
        return False
    state["last_heartbeat_hour"] = hour
    save_state(state)
    return True


def _provider_result(state: Mapping[str, object], provider: Provider) -> dict[str, object]:
    providers = state["providers"]
    assert isinstance(providers, Mapping)
    lane = providers[provider.value]
    assert isinstance(lane, Mapping)
    return {"healthy": lane.get("last_error") is None, "error": lane.get("last_error")}


async def _route_and_deliver(
    state: dict[str, object], runtime: RuntimeClients | None, now: datetime, dry_run: bool
) -> tuple[int, int]:
    classified = _route_pending(state)
    news_delivered = await _drain_delivery(state, runtime, now, dry_run)
    return classified, news_delivered


async def run(now: datetime | None = None, clients: object | None = None) -> dict[str, object]:
    """Perform one locked poll, delivery drain, heartbeat, and single agent claim."""
    now = _require_aware(now or datetime.now(WIB))
    dry_run = _dry_run()
    with run_lock():
        owned_client: Any | None = None
        if clients is None:
            control = resilience()
            decision = await acquire_probe_after_active_lease(
                control, WATCHER_NAME, now
            )
            if decision.kind == "state_blocked":
                _report_resilience_state_blocked(now, dry_run)
                return {"wakeAgent": False, "_telegram_resilience_handled": True}
            if decision.kind != "probe":
                deliver_resilience_notification(control, now, dry_run)
                return {"wakeAgent": False, "_telegram_resilience_handled": True}

            owned_client = _make_client()
            try:
                await owned_client.connect()
                if not await owned_client.is_user_authorized():
                    control.record_auth_required(decision.lease_id, WATCHER_NAME, now)
                    deliver_resilience_notification(control, now, dry_run)
                    await _disconnect_quietly(owned_client)
                    return {"wakeAgent": False, "_telegram_resilience_handled": True}
                await owned_client.get_me()
                dc_id, endpoint = _connection_metadata(owned_client)
                control.record_authenticated_success(
                    decision.lease_id, WATCHER_NAME, now, dc_id, endpoint
                )
                deliver_resilience_notification(control, now, dry_run)
            except Exception as error:
                if is_transport_error(error):
                    control.record_transport_failure(
                        decision.lease_id, WATCHER_NAME, error, now
                    )
                    deliver_resilience_notification(control, now, dry_run)
                    await _disconnect_quietly(owned_client)
                    return {"wakeAgent": False, "_telegram_resilience_handled": True}
                await _disconnect_quietly(owned_client)
                raise

        state = load_state()
        _migrate_scheduled_delivery_backlog(state, now)
        runtime: RuntimeClients | None = None
        source_messages = source_candidates = 0
        try:
            if clients is None:
                assert owned_client is not None
                runtime = await _resolve_runtime_clients(owned_client)
            else:
                runtime = _provided_runtime_clients(clients)

            lanes = (
                (Provider.PHINTRACO, runtime.phintraco_entity),
                (Provider.TUNTUN, runtime.tuntun_entity),
            )
            for provider, entity in lanes:
                if isinstance(entity, Exception):
                    _mark_provider_error(state, provider, entity)
                    continue
                messages, candidates, _ = await _ingest_provider(state, runtime, provider, entity, now)
                source_messages += messages
                source_candidates += candidates
            classified, news_delivered = await _route_and_deliver(state, runtime, now, dry_run)
        finally:
            if owned_client is not None:
                await owned_client.disconnect()

        _post_heartbeat_if_due(
            state, now, source_messages, classified, news_delivered, dry_run
        )
        # Task 4 lease expiry must happen immediately before this sole claim, so an
        # expired lease cannot incorrectly hide the deterministic oldest candidate.
        expire_agent_leases(state, now)
        candidate = claim_oldest_pending_analysis(state, now)
        result: dict[str, object] = {
            "providers": {
                Provider.PHINTRACO.value: _provider_result(state, Provider.PHINTRACO),
                Provider.TUNTUN.value: _provider_result(state, Provider.TUNTUN),
            },
            "source_messages": source_messages,
            "source_candidates": source_candidates,
            "classified_candidates": classified,
            "news_delivered": news_delivered,
        }
        if candidate is None:
            result.update({"wakeAgent": False, "items": []})
        else:
            result.update(build_wake_payload([agent_item(candidate)]))
        return result


def _candidate_for_submission(state: Mapping[str, object], candidate_key: object) -> CompanyCandidate:
    if not isinstance(candidate_key, str):
        raise ValueError("candidate_key must be nonempty text")
    records = state.get("candidates")
    if not isinstance(records, Mapping):
        raise StateBlockedError("malformed state: candidates must be an object")
    record = records.get(candidate_key)
    if not isinstance(record, Mapping):
        raise StateBlockedError(f"candidate {candidate_key!r} is not in durable state")
    item = _selection_item_from_record(candidate_key, record)
    if item is not None:
        return item.candidate
    payload = record.get("candidate")
    if not isinstance(payload, Mapping):
        raise StateBlockedError(f"candidate {candidate_key!r} has invalid durable payload")
    try:
        candidate = CompanyCandidate(
            provider=Provider(payload["provider"]),
            source_message_id=payload["source_message_id"],
            ticker=payload["ticker"],
            source_kind=SourceKind(payload["source_kind"]),
            published_at=datetime.fromisoformat(payload["published_at"]),
            source_text=payload["source_text"],
            direct_image=payload["direct_image"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StateBlockedError(f"candidate {candidate_key!r} has invalid durable payload") from error
    if candidate.key != candidate_key:
        raise StateBlockedError(f"candidate {candidate_key!r} does not match durable payload")
    return candidate


async def submit_classification_payload(
    payload: Mapping[str, object], now: datetime | None = None, clients: object | None = None
) -> dict[str, object]:
    """Validate, persist, route, and immediately drain one active agent lease."""
    now = _require_aware(now or datetime.now(WIB))
    if not isinstance(payload, Mapping):
        raise ValueError("submission must be a JSON object")
    with run_lock():
        state = load_state()
        _migrate_scheduled_delivery_backlog(state, now)
        candidate = _candidate_for_submission(state, payload.get("candidate_key"))
        classification = submit_agent_classification(state, candidate, payload, now)
        runtime: RuntimeClients | None = None
        owned_client: Any | None = None
        try:
            if clients is not None:
                runtime = _provided_runtime_clients(clients)
            classified, news_delivered = await _route_and_deliver(state, runtime, now, _dry_run())
        finally:
            if owned_client is not None:
                await owned_client.disconnect()
        return {
            "classified_candidates": classified,
            "news_delivered": news_delivered,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    submit = subparsers.add_parser("submit-classification")
    submit.add_argument("--json", required=True, dest="payload")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "submit-classification":
            payload = json.loads(arguments.payload)
            result = asyncio.run(submit_classification_payload(payload))
        else:
            result = asyncio.run(run())
    except Exception as error:
        print(json.dumps({"wakeAgent": False, "error": _clean_reason(error)}, ensure_ascii=False))
        return 1
    if result.pop("_telegram_resilience_handled", False):
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
