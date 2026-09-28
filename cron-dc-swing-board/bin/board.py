"""Runnable deterministic owner entry point for the IDX Swing plan board."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Sequence
from uuid import uuid4

from calendar import CalendarCoverageError
import config
from discord_forum import DiscordForumClient, forum_thread_url
from engine import BoardEngine
from models import SourceEvent
from render import WIB, episode_title
from store import BoardStore


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "bootstrap":
        if arguments.dry_run:
            return _bootstrap_dry_run(arguments.lookback_sessions, arguments.manifest)
        return _bootstrap_apply(arguments.lookback_sessions, arguments.manifest)
    loaded_config = config.load_board_config_for_run()
    engine = BoardEngine(BoardStore(_state_path()), DiscordForumClient())
    if arguments.command == "submit-source-event":
        return _submit_source_event(engine, loaded_config)
    if arguments.command == "repair-starter-media":
        return _repair_starter_media(
            engine,
            arguments.event_key,
            arguments.expected_thread_id,
            apply=arguments.apply,
        )
    if arguments.command == "drain":
        health = {"drained": engine.drain(), **engine.store.outbox_health()}
        print(json.dumps(health, separators=(",", ":")))
        return int(health["pending"] > 0 or health["failed"] > 0)
    if arguments.command == "reconcile-lifecycle":
        return _reconcile_lifecycle(engine, loaded_config)
    if arguments.command == "migrate-format":
        if not arguments.apply:
            print(json.dumps({
                "apply_required": True,
                "planned_cards": len(engine.store.latest_plan_cards()),
                "planned_source_replies": len(engine.store.completed_source_replies()),
            }, separators=(",", ":")))
            return 0
        scheduled = engine.schedule_format_migration(datetime.now(WIB))
        health = {"scheduled": scheduled, "drained": engine.drain(), **engine.store.outbox_health()}
        print(json.dumps(health, separators=(",", ":")))
        return int(health["pending"] > 0 or health["failed"] > 0)
    if arguments.command == "cleanup-history":
        if not arguments.apply:
            print(json.dumps({
                "apply_required": True,
                "planned": engine.store.history_cleanup_count(),
            }, separators=(",", ":")))
            return 0
        if engine.client.no_post:
            print(json.dumps({"error": "cleanup-history requires live Discord", "apply_required": True}, separators=(",", ":")))
            return 2
        scheduled = engine.schedule_history_cleanup(datetime.now(WIB))
        health = {"scheduled": scheduled, "drained": engine.drain(), **engine.store.outbox_health()}
        print(json.dumps(health, separators=(",", ":")))
        return int(health["pending"] > 0 or health["failed"] > 0)
    if arguments.command == "migrate-titles":
        if not arguments.apply:
            print(json.dumps({
                "apply_required": True,
                "planned_episodes": sum(
                    1 for episode in engine.store.episodes()
                    if episode.thread_id and episode.starter_message_id
                    and episode.title != episode_title(episode.ticker, episode.opened_at)
                ),
            }, separators=(",", ":")))
            return 0
        result = engine.schedule_title_migration(datetime.now(WIB))
        health = {"drained": engine.drain(), **engine.store.outbox_health()}
        result.update({"pending": health["pending"], "failed": health["failed"]})
        print(json.dumps(result, separators=(",", ":")))
        return int(result["pending"] > 0 or result["failed"] > 0)
    if arguments.command == "migrate-tags":
        if not arguments.apply:
            print(json.dumps({
                "apply_required": True,
                "planned_episodes": len(engine.store.episodes()),
            }, separators=(",", ":")))
            return 0
        result = engine.schedule_tag_migration(datetime.now(WIB))
        engine.drain()
        result["pending"] = engine.store.pending_outbox_count()
        result["failed"] = engine.store.outbox_health()["failed"]
        print(json.dumps(result, separators=(",", ":")))
        return int(result["pending"] > 0 or result["failed"] > 0 or result["blocked"] > 0)
    return _after_close(engine, arguments.phase, loaded_config)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    submit = subcommands.add_parser("submit-source-event")
    submit.add_argument("--stdin", action="store_true", required=True)
    repair_media = subcommands.add_parser("repair-starter-media")
    repair_media.add_argument("--event-key", required=True)
    repair_media.add_argument("--expected-thread-id", required=True)
    repair_media.add_argument("--apply", action="store_true")
    subcommands.add_parser("drain")
    subcommands.add_parser("reconcile-lifecycle")
    migrate = subcommands.add_parser("migrate-format")
    migrate.add_argument("--apply", action="store_true")
    cleanup = subcommands.add_parser("cleanup-history")
    cleanup.add_argument("--apply", action="store_true")
    migrate_titles = subcommands.add_parser("migrate-titles")
    migrate_titles.add_argument("--apply", action="store_true")
    migrate_tags = subcommands.add_parser("migrate-tags")
    migrate_tags.add_argument("--apply", action="store_true")
    after_close = subcommands.add_parser("after-close")
    after_close.add_argument("--phase", choices=("initial", "retry"), required=True)
    bootstrap = subcommands.add_parser("bootstrap")
    mode = bootstrap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    bootstrap.add_argument("--lookback-sessions", type=int, default=20)
    bootstrap.add_argument("--manifest", type=Path)
    return parser


def _bootstrap_dry_run(lookback_sessions: int, manifest: Path | None) -> int:
    """Report candidates without opening Board state or Discord."""
    from bootstrap import BootstrapError, collect_manifest_report, collect_report, format_report

    try:
        if manifest is not None:
            report = asyncio.run(
                collect_manifest_report(
                    now=datetime.now(WIB),
                    lookback_sessions=lookback_sessions,
                    manifest_path=manifest,
                )
            )
            print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
            return 0
        report = asyncio.run(
            collect_report(now=datetime.now(WIB), lookback_sessions=lookback_sessions)
        )
    except (BootstrapError, ValueError) as exc:
        print(f"bootstrap dry-run failed: {exc}", file=sys.stderr)
        return 1
    print(format_report(report))
    return 0


def _bootstrap_apply(lookback_sessions: int, manifest: Path | None) -> int:
    """Apply only reviewed unresolved complete Primary-plan candidates."""
    from bootstrap import BootstrapError, apply_manifest, apply_primary_candidates, format_apply_report

    engine = BoardEngine(BoardStore(_state_path()), DiscordForumClient())
    try:
        if manifest is not None:
            report = asyncio.run(
                apply_manifest(
                    now=datetime.now(WIB),
                    lookback_sessions=lookback_sessions,
                    manifest_path=manifest,
                    engine=engine,
                )
            )
            print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
            return int(engine.store.pending_outbox_count() > 0)
        report = asyncio.run(
            apply_primary_candidates(
                now=datetime.now(WIB),
                lookback_sessions=lookback_sessions,
                engine=engine,
            )
        )
    except (BootstrapError, ValueError) as exc:
        print(f"bootstrap apply failed: {exc}", file=sys.stderr)
        return 1
    print(format_apply_report(report))
    return int(engine.store.pending_outbox_count() > 0)


def _submit_source_event(
    engine: BoardEngine, loaded_config: config.LoadedBoardConfig
) -> int:
    control_run = ControlPlaneRun.begin(
        "IDX_SWING_PLAN_BOARD",
        loaded_config.revision,
        scheduler_job_id="bursawatch-dc-swing-board",
        trigger="source_event",
    )
    control_run.event(
        "source-event-started",
        level="info",
        phase="source",
        event_type="source.event.started",
        message="Discord Swing Board source event started",
        attributes={"config_revision": loaded_config.revision},
    )
    outcome = "failed"
    failure: str | None = None
    try:
        payload = json.load(sys.stdin)
        event = SourceEvent.from_json(payload)
        event = _own_media(event)
        # The engine's one transition commits immutable intake and every resulting
        # outbox intent together before the acknowledgement is written.
        disposition = engine.submit(event, datetime.now(WIB))
        control_run.event(
            "source-event-accepted",
            level="info",
            phase="source",
            event_type="source.event.accepted",
            message="Discord Swing Board source event was accepted",
            attributes={"event_key": event.event_key, "disposition": disposition},
        )
        drained = engine.drain()
        health = engine.store.outbox_health()
        pending = int(health["pending"])
        failed = int(health["failed"])
        outcome = "degraded" if pending or failed else "ok"
        control_run.event(
            "source-event-delivery-drain-completed",
            level="warning" if outcome == "degraded" else "info",
            phase="delivery",
            event_type="delivery.drain.completed",
            message="Discord Swing Board source-event delivery drain completed",
            attributes={"drained": drained, "pending": pending, "failed": failed},
        )
        episode = engine.store.episode_for_event(event.event_key)
        board_url = None
        if episode is not None and episode.thread_id and not engine.client.no_post:
            board_url = forum_thread_url(episode.thread_id)
        acknowledgement = {"accepted": True, "board_url": board_url}
        if episode is not None and not episode.thread_id:
            acknowledgement["board_pending"] = True
        print(json.dumps(acknowledgement, separators=(",", ":")))
        return 0
    except Exception as error:
        failure = _failure_reason(error)
        control_run.event(
            "source-event-failed",
            level="fatal",
            phase="source",
            event_type="source.event.failed",
            message="Discord Swing Board source event failed",
            attributes={"error": failure},
        )
        raise
    finally:
        control_run.event(
            "source-event-completed",
            level="warning" if outcome == "degraded" else "info",
            phase="lifecycle",
            event_type="source.event.completed",
            message=f"Discord Swing Board source event {outcome}",
            attributes={"config_revision": loaded_config.revision},
        )
        control_run.finish(outcome, failure)


def _repair_starter_media(
    engine: BoardEngine,
    event_key: str,
    expected_thread_id: str,
    *,
    apply: bool,
) -> int:
    """Replace one open source card's wrongly named image through the owner outbox."""
    episode = engine.store.episode_for_event(event_key)
    if episode is None:
        raise ValueError("source event has no Board episode")
    if (
        episode.closed_at is not None
        or episode.lifecycle == "resolved"
        or episode.thread_id != expected_thread_id
        or not episode.starter_message_id
    ):
        raise ValueError("source event is not the expected open Board starter")

    event = engine.store.starter_source_event(episode.id)
    source_event_id = episode.starter_source_event_id
    if event is None or event.event_key != event_key or source_event_id is None:
        raise ValueError("source event does not own the current Board starter")
    if event.media_path is None:
        raise ValueError("Board starter has no source image")

    source_path = Path(event.media_path)
    if not source_path.is_file():
        raise ValueError("Board source image is unavailable")
    suffix = _media_suffix(source_path)
    if suffix not in {".jpg", ".png", ".gif", ".webp"}:
        raise ValueError("Board source media is not a recognized image")
    digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
    chart_path = _media_root() / f"{digest}{suffix}"

    thread = engine.client.get_thread(expected_thread_id)
    metadata = thread.get("thread_metadata")
    if (
        thread.get("parent_id") != "1548273399069933720"
        or thread.get("name") != event.ticker
        or not isinstance(metadata, dict)
        or metadata.get("archived") is not False
        or metadata.get("locked") is True
    ):
        raise ValueError("expected Board thread is archived, locked, or mismatched")
    current = engine.client.get_message(expected_thread_id, episode.starter_message_id)
    attachments = current.get("attachments")
    if not isinstance(attachments, list) or len(attachments) != 1:
        raise ValueError("Board starter attachment changed since review")
    attachment = attachments[0]
    if not isinstance(attachment, dict):
        raise ValueError("Board starter attachment changed since review")
    current_name = attachment.get("filename")
    expected_mime = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }[suffix]
    if current_name == chart_path.name and attachment.get("content_type") == expected_mime:
        print(json.dumps({
            "mode": "repair-starter-media",
            "status": "already-correct",
            "ticker": event.ticker,
            "thread_id": expected_thread_id,
            "message_id": episode.starter_message_id,
            "filename": chart_path.name,
            "created_thread": False,
        }, separators=(",", ":")))
        return 0
    if current_name != source_path.name:
        raise ValueError("Board starter filename changed since review")
    if current.get("content") is None or attachment.get("size") != source_path.stat().st_size:
        raise ValueError("Board starter content or image size changed since review")

    dedupe_key = (
        f"maintenance:chart-filename:{expected_thread_id}:"
        f"{episode.starter_message_id}:{attachment.get('id')}:{chart_path.name}"
    )
    report = {
        "mode": "repair-starter-media",
        "ticker": event.ticker,
        "thread_id": expected_thread_id,
        "message_id": episode.starter_message_id,
        "old_filename": current_name,
        "new_filename": chart_path.name,
        "created_thread": False,
    }
    if not apply:
        print(json.dumps({**report, "status": "planned", "apply_required": True}, separators=(",", ":")))
        return 0
    if engine.client.no_post:
        raise RuntimeError("repair-starter-media requires live Discord")

    with engine.store.delivery_lock() as acquired:
        if not acquired:
            raise RuntimeError("Board delivery is already in progress")
        if engine.store.outbox_health()["pending"]:
            raise RuntimeError("Board has pending deliveries; refusing unrelated outbox drain")
        latest_thread = engine.client.get_thread(expected_thread_id)
        latest_metadata = latest_thread.get("thread_metadata")
        latest_message = engine.client.get_message(expected_thread_id, episode.starter_message_id)
        latest_attachments = latest_message.get("attachments")
        if (
            latest_thread.get("parent_id") != "1548273399069933720"
            or latest_thread.get("name") != event.ticker
            or not isinstance(latest_metadata, dict)
            or latest_metadata.get("archived") is not False
            or latest_metadata.get("locked") is True
            or not isinstance(latest_attachments, list)
            or len(latest_attachments) != 1
            or not isinstance(latest_attachments[0], dict)
            or latest_attachments[0].get("id") != attachment.get("id")
            or latest_attachments[0].get("filename") != current_name
            or latest_attachments[0].get("size") != source_path.stat().st_size
            or latest_message.get("content") != current.get("content")
        ):
            raise RuntimeError("Board thread or starter changed during repair review")
        chart_event = _own_media(event)
        chart_path = Path(str(chart_event.media_path))
        if chart_path.name != report["new_filename"]:
            raise RuntimeError("Board image extension changed during repair")
        with engine.store.transaction() as tx:
            latest = tx.episode(episode.id)
            if (
                latest.closed_at is not None
                or latest.lifecycle == "resolved"
                or latest.thread_id != expected_thread_id
                or latest.starter_message_id != episode.starter_message_id
                or latest.starter_source_event_id != source_event_id
            ):
                raise RuntimeError("Board starter changed during repair review")
            tx.enqueue_outbox(
                "edit_starter",
                episode.id,
                {
                    "content": str(current["content"]),
                    "chart": str(chart_path),
                    "clear_attachments": False,
                    "nonce_value": dedupe_key,
                },
                dedupe_key,
                datetime.now(WIB),
            )
        drained = engine._drain_owned(datetime.now(WIB), limit=1)
    health = engine.store.outbox_health()
    if drained != 1 or health["pending"] or health["failed"]:
        raise RuntimeError("Board attachment repair remains pending")
    print(json.dumps({**report, "status": "edited", "drained": drained}, separators=(",", ":")))
    return 0


def _after_close(
    engine: BoardEngine,
    phase: str,
    loaded_config: config.LoadedBoardConfig,
) -> int:
    scheduler_job_id = (
        "bursawatch-dc-swing-board-close"
        if phase == "initial"
        else "bursawatch-dc-swing-board-retry"
    )
    control_run = ControlPlaneRun.begin(
        "IDX_SWING_PLAN_BOARD",
        loaded_config.revision,
        scheduler_job_id=scheduler_job_id,
    )
    control_run.event(
        "run-started",
        level="info",
        phase="lifecycle",
        event_type="run.started",
        message="Discord Swing Board after-close run started",
        attributes={"config_revision": loaded_config.revision, "phase": phase},
    )
    outcome = "failed"
    failure: str | None = None
    result: dict[str, int] = {}
    try:
        result = engine.after_close(phase, datetime.now(WIB))
    except CalendarCoverageError:
        # Calendar coverage is a fatal fail-closed condition, not a reason to
        # lose the required operational signal or replay any market mutation.
        engine.drain()
        failure = "calendar coverage unavailable"
        heartbeat = _fatal_heartbeat(phase, failure)
        _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id, heartbeat, phase)
        control_run.event(
            "run-failed",
            level="fatal",
            phase="market",
            event_type="run.failed",
            message="Discord Swing Board calendar coverage is unavailable",
            attributes={"error": failure},
        )
        print(heartbeat)
        return 0
    except Exception as error:
        engine.drain()
        failure = _failure_reason(error)
        heartbeat = _fatal_heartbeat(phase, "reconciliation failed")
        _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id, heartbeat, phase)
        control_run.event(
            "run-failed",
            level="fatal",
            phase="market",
            event_type="run.failed",
            message="Discord Swing Board reconciliation failed",
            attributes={"error": failure},
        )
        print(heartbeat)
        return 1
    else:
        engine.drain()
        # ``pending`` describes retained owner work after this invocation, not
        # the number of operations just completed.
        result["pending"] = engine.store.pending_outbox_count()
        heartbeat = _heartbeat(phase, result)
        _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id, heartbeat, phase)
        outcome = "degraded" if (
            result["unavailable"] or result["pending"] or result.get("invalid", 0)
        ) else "ok"
        control_run.event(
            "after-close-evaluated",
            level="warning" if outcome == "degraded" else "info",
            phase="market",
            event_type="market.close.evaluated",
            message="Discord Swing Board after-close evaluation completed",
            attributes={**result, "phase": phase},
        )
        control_run.event(
            "delivery-drain-completed",
            level="warning" if result["pending"] else "info",
            phase="delivery",
            event_type="delivery.drain.completed",
            message="Discord Swing Board delivery drain completed",
            attributes={"pending": result["pending"]},
        )
        print(heartbeat)
        return 0
    finally:
        control_run.event(
            "run-completed",
            level="warning" if outcome == "degraded" else "info",
            phase="lifecycle",
            event_type="run.completed",
            message=f"Discord Swing Board after-close run {outcome}",
            attributes={"config_revision": loaded_config.revision, "phase": phase, **result},
        )
        control_run.finish(outcome, failure)


def _reconcile_lifecycle(engine: BoardEngine, loaded_config: config.LoadedBoardConfig) -> int:
    """Run the daily inactivity and archive pass with a durable heartbeat."""
    now = datetime.now(WIB)
    try:
        result = engine.reconcile_lifecycle(now)
    except CalendarCoverageError:
        engine.drain()
        content = f"❌ swing-board-lifecycle · {now:%H:%M} WIB · failed: calendar coverage unavailable"
        _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id,
                         content, "lifecycle")
        print(content)
        return 1
    except Exception:
        engine.drain()
        content = f"❌ swing-board-lifecycle · {now:%H:%M} WIB · failed: reconciliation error"
        _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id,
                         content, "lifecycle")
        print(content)
        return 1
    drained = engine.drain()
    health = engine.store.outbox_health()
    warning = " ⚠️" if health["pending"] or health["failed"] else ""
    content = (f"🫀 swing-board-lifecycle · {now:%H:%M} WIB · "
               f"resolved={result['resolved']} quiet={result['quiet_started']} "
               f"archive={result['archived']} drained={drained} pending={health['pending']}{warning}")
    _queue_heartbeat(engine, loaded_config.config.heartbeat_discord_channel_id,
                     content, "lifecycle")
    print(content)
    return 0


def _queue_heartbeat(engine: BoardEngine, channel_id: str, content: str, phase: str) -> None:
    """Commit a stable channel intent before handing it to Delivery Owner."""
    identity = f"scheduled-heartbeat:v1:{phase}:{uuid4().hex}"
    engine.enqueue_heartbeat(channel_id, content, identity, datetime.now(WIB))
    engine.drain()


def _failure_reason(error: object) -> str:
    return " ".join(str(error).split())[:500] or "board operation failed"


def _own_media(event: SourceEvent) -> SourceEvent:
    if not event.media_paths:
        return event
    sources = tuple(Path(path) for path in event.media_paths)
    if any(not source.is_file() for source in sources):
        raise ValueError("source media is unavailable")
    root = _media_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
    destinations = []
    for index, source in enumerate(sources):
        suffix = _media_suffix(source)
        destination = root / f"{digest}-{index}{suffix}"
        if not destination.is_file():
            descriptor, temporary = tempfile.mkstemp(prefix=f".{digest}-{index}.", dir=root)
            try:
                with os.fdopen(descriptor, "wb") as target, source.open("rb") as incoming:
                    shutil.copyfileobj(incoming, target)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        destinations.append(str(destination))
    directory = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return replace(event, media_path=destinations[0], media_paths=tuple(destinations))


def _media_suffix(source: Path) -> str:
    """Keep owner media content-addressed while preserving its display type."""
    with source.open("rb") as stream:
        header = stream.read(16)
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return ".mp4"
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _state_path() -> Path:
    return Path(os.environ.get(
        "IDX_SWING_PLAN_BOARD_STATE_PATH", str(Path.home() / ".hermes/state/idx-swing-board.sqlite3")
    ))


def _media_root() -> Path:
    return Path(os.environ.get(
        "IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(Path.home() / ".hermes/state/idx-swing-board-media")
    ))


def _heartbeat(phase: str, result: dict[str, int]) -> str:
    clock = "16:30" if phase == "initial" else "17:00"
    warning = " ⚠️" if result["unavailable"] or result["pending"] or result.get("invalid", 0) else ""
    invalid = f" invalid={result['invalid']}" if result.get("invalid", 0) else ""
    return (
        f"🫀 bursawatch-dc-swing-board · {clock} WIB · active={result['active']} "
        f"checked={result['checked']} unavailable={result['unavailable']} "
        f"pending={result['pending']}{invalid}{warning}"
    )


def _fatal_heartbeat(phase: str, reason: str) -> str:
    clock = "16:30" if phase == "initial" else "17:00"
    return f"❌ bursawatch-dc-swing-board · {clock} WIB · failed: {reason}"


if __name__ == "__main__":
    raise SystemExit(main())
