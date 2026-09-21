#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import agent_protocol
import archive
from classification import is_technical_review
import config
import discord
import event_queue
from normalize import deserialize_queue_event
import render
import state
import swing_board


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
BRI_PROFILE_ID = "bri-danareksa-sekuritas"


def _default_path(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name, fallback))


def _profile_state(value: dict[str, object], profile_id: str) -> dict[str, object]:
    profiles = value["profiles"]
    record = profiles.setdefault(profile_id, {})  # type: ignore[union-attr]
    if type(record) is not dict:
        raise ValueError("profile state is invalid")
    return record


def _record_is_routable(
    value: dict[str, object],
    profile: config.ChannelProfile,
    record: dict[str, object],
) -> bool:
    if not profile.is_forwarding:
        return False
    profile_value = value["profiles"].get(profile.id)  # type: ignore[union-attr]
    return not (
        isinstance(profile_value, dict)
        and profile_value.get("cutover_complete") is True
        and record.get("routable") is not True
    )


def _active_records(
    value: dict[str, object],
    profiles: dict[str, config.ChannelProfile],
) -> list[dict[str, object]]:
    return [
        record
        for record in value["outbox"]  # type: ignore[union-attr]
        if isinstance(record, dict)
        and record.get("agent_phase") not in {"filtered", "delivered"}
        and (profile := profiles.get(str(record.get("profile_id")))) is not None
        and _record_is_routable(value, profile, record)
    ]


def _newest(items: list[dict[str, object]]) -> dict[str, object] | None:
    return max(items, key=state.cursor_key, default=None)


def _heartbeat(now: datetime, fetched: int, archived: int, queued: int, claimed: int, expired: int, errors: list[str]) -> str:
    warning = " ⚠️" if errors else ""
    suffix = f" · {errors[0]}" if errors else ""
    return f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · {fetched} fetched · {archived} archived · {queued} queued · {claimed} claimed · {expired} expired · {len(errors)} errors" + suffix + warning


def _delivery_channel(profile: config.ChannelProfile, item: dict[str, object]) -> str:
    route = item.get("route")
    if profile.enable_llm_routing:
        if not isinstance(route, str):
            raise ValueError("ready analysis has no route")
        return profile.channel_for(route).channel_id
    return profile.discord_channels[0].channel_id


def _deterministic_items(profile: config.ChannelProfile) -> list[dict[str, object]]:
    if not profile.discord_channels:
        raise ValueError("forward profile has no Discord route")
    return [{"title": None, "summary": None, "route": profile.discord_channels[0].key, "ticker": None}]


def _archived_media(archive_root: Path, event) -> dict[int, tuple[str, Path]]:
    """Return only validated, archive-owned media files for one event."""
    records = archive.query(archive_root, event_key=event.event_key)
    if len(records) != 1:
        return {}
    captured: dict[int, tuple[str, Path]] = {}
    media = records[0].data.get("media")
    if type(media) is not list:
        return {}
    for item in media:
        if type(item) is not dict or item.get("capture_status") != "captured":
            continue
        index, kind, relative_path = item.get("index"), item.get("kind"), item.get("archive_path")
        if type(index) is not int or not isinstance(kind, str) or not isinstance(relative_path, str):
            continue
        path = archive_root / relative_path
        if path.is_file() and not path.is_symlink():
            captured[index] = (kind, path)
    return captured


def _archived_images(archive_root: Path, event) -> tuple[Path, ...]:
    return tuple(
        path
        for _index, (kind, path) in sorted(_archived_media(archive_root, event).items())
        if kind == "image"
    )


def _deliver_ready(
    value: dict[str, object],
    profiles: dict[str, config.ChannelProfile],
    *,
    dry_run: bool,
    state_path: Path,
    archive_dir: Path,
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
        if not _record_is_routable(value, profile, record):
            continue
        try:
            event = deserialize_queue_event(record["event"])
            items = record.get("items")
            if type(items) is not list or not items:
                raise ValueError("ready record has no news items")
            technical_review = profile.id == BRI_PROFILE_ID and is_technical_review(event.text)
            archived_images = _archived_images(archive_dir, event) if technical_review else ()
            if technical_review and len(archived_images) != 1:
                raise FileNotFoundError("technical review requires exactly one archived image")
            item_index = int(record.get("item_index", 0))
            while item_index < len(items):
                item = items[item_index]
                if type(item) is not dict:
                    raise ValueError("ready news item is invalid")
                target = _delivery_channel(profile, item)
                messages = render.render_post(
                    profile,
                    event,
                    title=item.get("title") if profile.enable_llm_title else None,
                    summary=item.get("summary") if profile.enable_llm_summary else None,
                )
                text_index = int(record.get("text_index", 0))
                while text_index < len(messages):
                    discord.post_text(
                        messages[text_index],
                        target,
                        dry_run,
                        discord.nonce(str(record["event_key"]), f"item:{item_index}:text:{text_index}"),
                    )
                    text_index += 1
                    record["text_index"] = text_index
                    state.save(state_path, value)
                item_index += 1
                record["item_index"] = item_index
                record["text_index"] = 0
                if technical_review and item_index == 1:
                    record["all_content"] = "\n\n".join(messages)
                state.save(state_path, value)
            media_paths: tuple[Path, ...]
            if technical_review:
                media_paths = archived_images
            else:
                media_indexes = agent_protocol.media_delivery_indexes(item_count=len(items), media_count=len(event.media))
                archived_media = _archived_media(archive_dir, event)
                paths: list[Path] = []
                for source_index in media_indexes:
                    media = event.media[source_index]
                    archived = archived_media.get(source_index)
                    if archived is None or archived[0] != media.kind:
                        raise FileNotFoundError(f"archived {media.kind} is unavailable")
                    paths.append(archived[1])
                media_paths = tuple(paths)
            media_index = int(record.get("media_index", 0))
            if profile.forward_media or technical_review:
                target = _delivery_channel(profile, items[0])
                while media_index < len(media_paths):
                    source_index = media_index
                    discord.post_media(
                        media_paths[media_index],
                        target,
                        dry_run,
                        discord.nonce(str(record["event_key"]), f"media:{source_index}"),
                    )
                    media_index += 1
                    record["media_index"] = media_index
                    state.save(state_path, value)
            if technical_review:
                item = items[0]
                if type(item) is not dict:
                    raise ValueError("ready news item is invalid")
                if not swing_board.is_eligible(event, item, archived_images[0]):
                    record["board_phase"] = "not_eligible"
                    state.save(state_path, value)
                elif record.get("board_phase") != "accepted":
                    acknowledgement = (
                        swing_board.BoardSubmission(True, None, True)
                        if dry_run
                        else swing_board.submit_chart_context(
                            event,
                            item,
                            str(record.get("all_content") or ""),
                            archived_images[0],
                        )
                    )
                    if not acknowledgement.accepted:
                        raise RuntimeError("Swing Board source-event submission was not accepted")
                    record["board_phase"] = "accepted"
                    record["board_acknowledgement"] = {
                        "board_url": acknowledgement.board_url,
                        "board_pending": acknowledgement.board_pending,
                    }
                    state.save(state_path, value)
            elif record.get("board_phase") == "pending":
                record["board_phase"] = "not_eligible"
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


def run(
    *,
    config_path: Path,
    state_path: Path,
    queue_dir: Path,
    archive_dir: Path | None = None,
    media_staging_dir: Path | None = None,
    now: datetime | None = None,
    no_post: bool = False,
) -> dict[str, object]:
    run_now = now or datetime.now(timezone.utc)
    if archive_dir is None:
        configured_archive = os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT")
        archive_dir = Path(configured_archive) if configured_archive else (
            state_path.parent / "archive" if no_post else Path.home() / ".hermes/state/whatsapp-channel-watch/archive"
        )
    if not archive_dir.is_absolute():
        raise ValueError("WhatsApp Channel archive path must be absolute")
    if media_staging_dir is None:
        configured_staging = os.environ.get("WHATSAPP_CHANNEL_WATCH_MEDIA_STAGING_DIR")
        media_staging_dir = Path(configured_staging) if configured_staging else (
            Path.home() / ".hermes/state/whatsapp-channel-watch/media-staging"
        )
    if not media_staging_dir.is_absolute():
        raise ValueError("WhatsApp Channel media staging path must be absolute")
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
            archive_dir=archive_dir,
            media_staging_dir=media_staging_dir,
            now=run_now,
            no_post=no_post,
            watch_config=loaded_config.config,
            config_revision=loaded_config.revision,
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
            "archived": result.get("archived", 0),
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
    archive_dir: Path,
    media_staging_dir: Path,
    now: datetime | None = None,
    no_post: bool = False,
    watch_config: config.WatchConfig | None = None,
    config_revision: int | None = None,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    watch_config = watch_config or config.load_for_run(config_path).config
    value = state.load(state_path)
    expired = state.expire_leases(value, now)
    queued = 0
    fetched = 0
    archived = 0
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
        archive_ready: list[dict[str, object]] = []
        archive_blocked = False
        for item in items:
            try:
                event = deserialize_queue_event(item)
                archive.ensure(
                    archive_dir,
                    profile.id,
                    event,
                    config_revision,
                    staging_root=media_staging_dir,
                )
            except Exception as exc:
                errors.append(f"{profile.id}: archive failed: {' '.join(str(exc).split())[:160]}")
                archive_blocked = True
                continue
            archived += 1
            if not archive_blocked:
                archive_ready.append(item)
        if profile.is_observing:
            continue
        if not profile.is_forwarding:
            continue
        if not archive_ready:
            continue
        profile_value = _profile_state(value, profile.id)
        cursor = profile_value.get("cursor")
        if cursor is None:
            newest = _newest(archive_ready)
            if newest is not None:
                profile_value["cursor"] = state.cursor(newest)
                profile_value["initialized"] = True
                initialized_profiles += 1
            continue
        if type(cursor) is not dict or not {"published_at", "event_key"}.issubset(cursor):
            errors.append(f"{profile.id}: invalid cursor")
            continue
        candidates = sorted(
            (
                item
                for item in archive_ready
                if state.cursor_key(item) > state.cursor_key(cursor)
                and str(item["event_key"]) not in known
            ),
            key=state.cursor_key,
        )
        for item in candidates[: profile.max_items_per_poll]:
            event = deserialize_queue_event(item)
            value["outbox"].append({
                "event_key": event.event_key,
                "profile_id": profile.id,
                "event": event_queue.serialize_event(event),
                "agent_phase": "pending" if profile.uses_llm else "ready",
                "agent_lease_until": None,
                "items": None if profile.uses_llm else _deterministic_items(profile),
                "item_index": 0,
                "text_index": 0,
                "media_index": 0,
                "board_phase": "pending",
                "archive_complete": True,
                "routable": True,
            })
            known.add(event.event_key)
            queued += 1
        newest = _newest(archive_ready)
        if newest is not None and state.cursor_key(newest) > state.cursor_key(cursor):
            profile_value["cursor"] = state.cursor(newest)

    delivered = _deliver_ready(
        value,
        profiles,
        dry_run=no_post,
        state_path=state_path,
        archive_dir=archive_dir,
        errors=errors,
    )
    claimed_item: dict[str, object] | None = None
    for record in _active_records(value, profiles):
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
    heartbeat = _heartbeat(now, fetched, archived, queued, int(claimed_item is not None), expired, errors)
    if not no_post:
        discord.post_text(heartbeat, "1505162000420835388", False, discord.nonce("heartbeat", now.astimezone(WIB).strftime("%Y%m%d%H%M")))
    return {
        "wakeAgent": claimed_item is not None,
        "item": claimed_item,
        "heartbeat": heartbeat,
        "delivered": delivered,
        "fetched": fetched,
        "archived": archived,
        "queued": queued,
        "claimed": int(claimed_item is not None),
        "expired": expired,
        "queue_items": len(queue_items),
        "enabled_profiles": enabled_profiles,
        "initialized_profiles": initialized_profiles,
        "errors": errors,
    }


def submit_analysis(
    *,
    config_path: Path,
    state_path: Path,
    payload: object,
    archive_dir: Path | None = None,
    now: datetime | None = None,
    no_post: bool = False,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if archive_dir is None:
        configured_archive = os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT")
        archive_dir = Path(configured_archive) if configured_archive else (
            state_path.parent / "archive" if no_post else Path.home() / ".hermes/state/whatsapp-channel-watch/archive"
        )
    if not archive_dir.is_absolute():
        raise ValueError("WhatsApp Channel archive path must be absolute")
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
        if not _record_is_routable(value, profile, record):
            raise ValueError("analysis event is not routable")
        if record.get("agent_phase") != "awaiting_agent":
            raise ValueError("analysis event is not leased to the agent")
        until = datetime.fromisoformat(str(record["agent_lease_until"]))
        if until <= now:
            raise ValueError("analysis lease expired")
        event = deserialize_queue_event(record["event"])
        route_override = agent_protocol.deterministic_route(profile, event)
        result = agent_protocol.validate_submission(profile, payload, event=event)
        if result.get("is_relevant") is False and route_override is not None:
            raise ValueError("TechnicalReview posts must be submitted as relevant")
        if profile.enable_llm_routing and result.get("is_relevant") is not False:
            items = result.get("items")
            if type(items) is not list or not items:
                raise ValueError("relevant submission has no news items")
            routes = [item.get("route") for item in items if type(item) is dict]
            if "id_stocks_swing" in routes and route_override != "id_stocks_swing":
                raise ValueError("id_stocks_swing requires a leading #TechnicalReview tag")
        record["items"] = (
            None
            if result.get("is_relevant") is False
            else result.get("items") or _deterministic_items(profile)
        )
        record["item_index"] = 0
        record["text_index"] = 0
        record["media_index"] = 0
        record["agent_lease_until"] = None
        record["agent_phase"] = "filtered" if result.get("is_relevant") is False else "ready"
        errors: list[str] = []
        delivered = _deliver_ready(
            value,
            {item.id: item for item in watch_config.profiles},
            dry_run=no_post,
            state_path=state_path,
            archive_dir=archive_dir,
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
    parser.add_argument("--archive-dir", type=Path, default=_default_path("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT", str(Path.home() / ".hermes/state/whatsapp-channel-watch/archive")))
    parser.add_argument("--media-staging-dir", type=Path, default=_default_path("WHATSAPP_CHANNEL_WATCH_MEDIA_STAGING_DIR", str(Path.home() / ".hermes/state/whatsapp-channel-watch/media-staging")))
    args = parser.parse_args()
    no_post = args.no_post or os.environ.get("WHATSAPP_CHANNEL_WATCH_NO_POST") == "1"
    if args.command == "submit-analysis":
        if not args.payload:
            parser.error("submit-analysis requires --json")
        result = submit_analysis(
            config_path=args.config,
            state_path=args.state,
            payload=json.loads(args.payload),
            archive_dir=args.archive_dir,
            no_post=no_post,
        )
    else:
        result = run(
            config_path=args.config,
            state_path=args.state,
            queue_dir=args.queue_dir,
            archive_dir=args.archive_dir,
            media_staging_dir=args.media_staging_dir,
            no_post=no_post,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
