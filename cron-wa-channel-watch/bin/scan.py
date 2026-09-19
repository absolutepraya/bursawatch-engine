#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import agent_protocol
import config
import discord
import event_queue
from normalize import deserialize_queue_event
import render
import state


try:
    from control_plane_runtime import ControlPlaneRun
except ModuleNotFoundError:
    class ControlPlaneRun:
        @classmethod
        def begin(cls, *_args, **_kwargs):
            return cls()

        def event(self, *_args, **_kwargs):
            pass

        def finish(self, *_args, **_kwargs):
            pass


WATCHER_HEARTBEAT_NAME = "whatsapp-channel"
WIB = ZoneInfo("Asia/Jakarta")


def _default_path(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name, fallback))


def _profile_state(value: dict[str, object], profile_id: str) -> dict[str, object]:
    profiles = value["profiles"]
    record = profiles.setdefault(profile_id, {})  # type: ignore[union-attr]
    if type(record) is not dict:
        raise ValueError("profile state is invalid")
    return record


def _active_records(value: dict[str, object]) -> list[dict[str, object]]:
    return [record for record in value["outbox"] if isinstance(record, dict) and record.get("agent_phase") not in {"filtered", "delivered"}]  # type: ignore[union-attr]


def _newest(items: list[dict[str, object]]) -> dict[str, object] | None:
    return max(items, key=state.cursor_key, default=None)


def _heartbeat(now: datetime, fetched: int, queued: int, claimed: int, expired: int, errors: list[str]) -> str:
    warning = " ⚠️" if errors else ""
    suffix = f" · {errors[0]}" if errors else ""
    return f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · {fetched} fetched · {queued} queued · {claimed} claimed · {expired} expired · {len(errors)} errors" + suffix + warning


def _delivery_channel(profile: config.ChannelProfile, analysis: dict[str, object]) -> str:
    route = analysis.get("route")
    if profile.enable_llm_routing:
        if not isinstance(route, str):
            raise ValueError("ready analysis has no route")
        return profile.channel_for(route).channel_id
    return profile.discord_channels[0].channel_id


def _deliver_ready(
    value: dict[str, object],
    profiles: dict[str, config.ChannelProfile],
    *,
    dry_run: bool,
    state_path: Path,
    errors: list[str],
) -> int:
    delivered = 0
    for record in value["outbox"]:  # type: ignore[union-attr]
        if not isinstance(record, dict) or record.get("agent_phase") != "ready":
            continue
        profile = profiles.get(str(record.get("profile_id")))
        if profile is None:
            errors.append(f"unknown profile for {record.get('event_key')}")
            continue
        try:
            event = deserialize_queue_event(record["event"])
            analysis = record.get("analysis") or {}
            if type(analysis) is not dict:
                raise ValueError("ready analysis is invalid")
            target = _delivery_channel(profile, analysis)
            messages = render.render_post(
                profile,
                event,
                title=analysis.get("title") if profile.enable_llm_title else None,
                summary=analysis.get("summary") if profile.enable_llm_summary else None,
            )
            text_index = int(record.get("text_index", 0))
            while text_index < len(messages):
                discord.post_text(messages[text_index], target, dry_run, discord.nonce(str(record["event_key"]), f"text:{text_index}"))
                text_index += 1
                record["text_index"] = text_index
                state.save(state_path, value)
            media_index = int(record.get("media_index", 0))
            if profile.forward_media:
                while media_index < len(event.media):
                    media = event.media[media_index]
                    if not media.path:
                        raise FileNotFoundError(f"source {media.kind} is unavailable")
                    discord.post_media(Path(media.path), target, dry_run, discord.nonce(str(record["event_key"]), f"media:{media_index}"))
                    media_index += 1
                    record["media_index"] = media_index
                    state.save(state_path, value)
            record["agent_phase"] = "delivered"
            record["delivered_at"] = datetime.now(timezone.utc).isoformat()
            state.save(state_path, value)
            delivered += 1
        except Exception as exc:
            record["last_error"] = " ".join(str(exc).split())[:180]
            state.save(state_path, value)
            errors.append(str(record["last_error"]))
    return delivered


def run(*, config_path: Path, state_path: Path, queue_dir: Path, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    run_now = now or datetime.now(timezone.utc)
    loaded_config = config.load_for_run(config_path)
    control_run = ControlPlaneRun.begin(
        "WHATSAPP_CHANNEL_WATCH",
        loaded_config.revision,
        scheduler_job_id="bursawatch-wa-channel-watch",
    )
    control_run.event(
        "run-started",
        level="info",
        phase="lifecycle",
        event_type="run.started",
        message="WhatsApp Channel watcher run started",
        attributes={"config_revision": loaded_config.revision, "no_post": no_post},
    )
    try:
        result = _run(
            config_path=config_path,
            state_path=state_path,
            queue_dir=queue_dir,
            now=run_now,
            no_post=no_post,
            watch_config=loaded_config.config,
        )
    except Exception as exc:
        reason = " ".join(str(exc).split())[:500]
        control_run.event(
            "run-failed",
            level="fatal",
            phase="lifecycle",
            event_type="run.failed",
            message="WhatsApp Channel watcher run failed",
            attributes={"error": reason},
        )
        control_run.finish("failed", reason)
        raise
    errors = result.get("errors")
    degraded = isinstance(errors, list) and bool(errors)
    control_run.event(
        "source-queue-inspected",
        level="warning" if degraded else "info",
        phase="source",
        event_type="source.queue.inspected",
        message="WhatsApp Channel bridge queue inspected",
        attributes={
            "queue_items": result.get("queue_items", 0),
            "enabled_profiles": result.get("enabled_profiles", 0),
            "initialized_profiles": result.get("initialized_profiles", 0),
            "source_items": result.get("fetched", 0),
            "queued": result.get("queued", 0),
            "expired_agent_leases": result.get("expired", 0),
        },
    )
    control_run.event(
        "delivery-drain-completed",
        level="warning" if degraded else "info",
        phase="delivery",
        event_type="delivery.drain.completed",
        message="WhatsApp Channel delivery drain completed",
        attributes={
            "delivered": result.get("delivered", 0),
            "errors": errors[:10] if isinstance(errors, list) else [],
        },
    )
    if result.get("claimed"):
        control_run.event(
            "agent-wake-requested",
            level="info",
            phase="agent",
            event_type="agent.wake.requested",
            message="WhatsApp Channel event claimed for agent analysis",
            attributes={"claimed": result.get("claimed", 0)},
        )
    control_run.event(
        "run-completed",
        level="warning" if degraded else "info",
        phase="lifecycle",
        event_type="run.completed",
        message="WhatsApp Channel watcher run completed",
        attributes={
            "fetched": result.get("fetched", 0),
            "queued": result.get("queued", 0),
            "claimed": result.get("claimed", 0),
            "expired": result.get("expired", 0),
            "delivered": result.get("delivered", 0),
            "errors": errors[:10] if isinstance(errors, list) else [],
        },
    )
    control_run.finish("degraded" if degraded else "ok")
    return result


def _run(
    *,
    config_path: Path,
    state_path: Path,
    queue_dir: Path,
    now: datetime | None = None,
    no_post: bool = False,
    watch_config: config.WatchConfig | None = None,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    watch_config = watch_config or config.load_for_run(config_path).config
    value = state.load(state_path)
    expired = state.expire_leases(value, now)
    queued = 0
    fetched = 0
    initialized_profiles = 0
    errors: list[str] = []
    queue_items = event_queue.list_events(queue_dir)
    by_channel: dict[str, list[dict[str, object]]] = {}
    for item in queue_items:
        by_channel.setdefault(str(item["channel_jid"]), []).append(item)
    known = {str(record.get("event_key")) for record in value["outbox"] if isinstance(record, dict)}
    profiles = {profile.id: profile for profile in watch_config.profiles}
    enabled_profiles = sum(profile.enabled for profile in watch_config.profiles)

    for profile in watch_config.profiles:
        if not profile.enabled:
            continue
        items = by_channel.get(profile.channel_jid, [])
        fetched += len(items)
        if not items:
            continue
        profile_value = _profile_state(value, profile.id)
        cursor = profile_value.get("cursor")
        if cursor is None:
            newest = _newest(items)
            if newest is not None:
                profile_value["cursor"] = {"published_at": newest["published_at"], "event_key": newest["event_key"]}
                profile_value["initialized"] = True
                initialized_profiles += 1
            continue
        if type(cursor) is not dict or not {"published_at", "event_key"}.issubset(cursor):
            errors.append(f"{profile.id}: invalid cursor")
            continue
        candidates = [item for item in items if state.cursor_key(item) > (str(cursor["published_at"]), str(cursor["event_key"])) and str(item["event_key"]) not in known]
        for item in candidates[: profile.max_items_per_poll]:
            event = deserialize_queue_event(item)
            value["outbox"].append({
                "event_key": event.event_key,
                "profile_id": profile.id,
                "event": event_queue.serialize_event(event),
                "agent_phase": "pending" if profile.uses_llm else "ready",
                "agent_lease_until": None,
                "analysis": None,
            })
            known.add(event.event_key)
            queued += 1
        newest = _newest(items)
        if newest is not None and state.cursor_key(newest) > state.cursor_key(cursor):
            profile_value["cursor"] = {"published_at": newest["published_at"], "event_key": newest["event_key"]}

    delivered = _deliver_ready(value, profiles, dry_run=no_post, state_path=state_path, errors=errors)
    claimed_item: dict[str, object] | None = None
    for record in _active_records(value):
        if record.get("agent_phase") != "pending":
            continue
        profile = profiles.get(str(record.get("profile_id")))
        if profile is None:
            errors.append(f"unknown profile for {record.get('event_key')}")
            continue
        event = deserialize_queue_event(record["event"])
        record["agent_phase"] = "awaiting_agent"
        record["agent_lease_until"] = state.lease_until(now)
        route_override = agent_protocol.deterministic_route(profile, event)
        claimed_item = agent_protocol.agent_item(
            profile,
            event,
            relevance_guard_required=route_override is not None,
        )
        break

    state.save(state_path, value)
    heartbeat = _heartbeat(now, fetched, queued, int(claimed_item is not None), expired, errors)
    if not no_post:
        discord.post_text(heartbeat, "1505162000420835388", False, discord.nonce("heartbeat", now.astimezone(WIB).strftime("%Y%m%d%H%M")))
    return {
        "wakeAgent": claimed_item is not None,
        "item": claimed_item,
        "heartbeat": heartbeat,
        "delivered": delivered,
        "fetched": fetched,
        "queued": queued,
        "claimed": int(claimed_item is not None),
        "expired": expired,
        "queue_items": len(queue_items),
        "enabled_profiles": enabled_profiles,
        "initialized_profiles": initialized_profiles,
        "errors": errors,
    }


def submit_analysis(*, config_path: Path, state_path: Path, payload: object, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    loaded_config = config.load_for_run(config_path)
    watch_config = loaded_config.config
    control_run = ControlPlaneRun.begin(
        "WHATSAPP_CHANNEL_WATCH",
        loaded_config.revision,
        scheduler_job_id="bursawatch-wa-channel-watch",
        trigger="agent_submission",
    )
    control_run.event(
        "agent-submission-started",
        level="info",
        phase="agent",
        event_type="agent.submission.started",
        message="WhatsApp Channel agent submission started",
        attributes={"no_post": no_post},
    )
    try:
        value = state.load(state_path)
        event_key = payload.get("event_key") if isinstance(payload, dict) else None
        record = next((item for item in value["outbox"] if isinstance(item, dict) and item.get("event_key") == event_key), None)  # type: ignore[union-attr]
        if record is None:
            raise ValueError("analysis event_key is not pending")
        profile = next((item for item in watch_config.profiles if item.id == record.get("profile_id")), None)
        if profile is None:
            raise ValueError("analysis profile is not configured")
        if record.get("agent_phase") != "awaiting_agent":
            raise ValueError("analysis event is not leased to the agent")
        until = datetime.fromisoformat(str(record["agent_lease_until"]))
        if until <= now:
            raise ValueError("analysis lease expired")
        event = deserialize_queue_event(record["event"])
        route_override = agent_protocol.deterministic_route(profile, event)
        result = agent_protocol.validate_submission(profile, payload)
        if result.get("is_relevant") is False and route_override is not None:
            raise ValueError("TechnicalReview posts must be submitted as relevant")
        if profile.enable_llm_routing:
            route = result.get("route")
            if route == "id_stocks_swing" and route_override != "id_stocks_swing":
                raise ValueError("id_stocks_swing requires a leading #TechnicalReview tag")
            if route_override is not None:
                result["route"] = route_override
        record["analysis"] = result
        record["agent_lease_until"] = None
        record["agent_phase"] = "filtered" if result.get("is_relevant") is False else "ready"
        errors: list[str] = []
        delivered = _deliver_ready(
            value,
            {item.id: item for item in watch_config.profiles},
            dry_run=no_post,
            state_path=state_path,
            errors=errors,
        )
        state.save(state_path, value)
    except ValueError as exc:
        reason = " ".join(str(exc).split())[:500]
        control_run.event(
            "agent-submission-rejected",
            level="warning",
            phase="agent",
            event_type="agent.submission.rejected",
            message="WhatsApp Channel agent submission rejected",
            attributes={"reason": reason},
        )
        control_run.finish("degraded", reason)
        raise
    except Exception as exc:
        reason = " ".join(str(exc).split())[:500]
        control_run.event(
            "agent-submission-failed",
            level="fatal",
            phase="agent",
            event_type="agent.submission.failed",
            message="WhatsApp Channel agent submission failed",
            attributes={"error": reason},
        )
        control_run.finish("failed", reason)
        raise

    control_run.event(
        "agent-submission-accepted",
        level="info",
        phase="agent",
        event_type="agent.submission.accepted",
        message="WhatsApp Channel agent submission accepted",
        attributes={
            "is_relevant": result.get("is_relevant"),
            "agent_phase": record["agent_phase"],
        },
    )
    control_run.event(
        "agent-delivery-drain-completed",
        level="warning" if errors else "info",
        phase="delivery",
        event_type="delivery.drain.completed",
        message="WhatsApp Channel agent delivery drain completed",
        attributes={"delivered": delivered, "errors": errors[:10]},
    )
    control_run.finish("degraded" if errors else "ok")
    return {"accepted": True, "event_key": event_key, "agent_phase": record["agent_phase"], "delivered": delivered}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process WhatsApp Channel queue")
    parser.add_argument("command", nargs="?", choices={"run", "submit-analysis"}, default="run")
    parser.add_argument("--json", dest="payload")
    parser.add_argument("--no-post", action="store_true")
    parser.add_argument("--config", type=Path, default=_default_path("WHATSAPP_CHANNEL_WATCH_CONFIG_PATH", "config/watches.json"))
    parser.add_argument("--state", type=Path, default=_default_path("WHATSAPP_CHANNEL_WATCH_STATE_PATH", "state/state.json"))
    parser.add_argument("--queue-dir", type=Path, default=_default_path("WHATSAPP_CHANNEL_WATCH_QUEUE_DIR", "queue"))
    args = parser.parse_args()
    no_post = args.no_post or os.environ.get("WHATSAPP_CHANNEL_WATCH_NO_POST") == "1"
    if args.command == "submit-analysis":
        if not args.payload:
            parser.error("submit-analysis requires --json")
        result = submit_analysis(config_path=args.config, state_path=args.state, payload=json.loads(args.payload), no_post=no_post)
    else:
        result = run(config_path=args.config, state_path=args.state, queue_dir=args.queue_dir, no_post=no_post)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
