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

from calendar import CalendarCoverageError
import config
from discord_forum import DiscordForumClient, forum_thread_url
from engine import BoardEngine
from models import SourceEvent
from render import WIB
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
    if arguments.command == "drain":
        health = {"drained": engine.drain(), **engine.store.outbox_health()}
        print(json.dumps(health, separators=(",", ":")))
        return int(health["pending"] > 0 or health["failed"] > 0)
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
                    if episode.thread_id and episode.starter_message_id and episode.title != episode.ticker
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
    subcommands.add_parser("drain")
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
        engine.client.post_heartbeat(loaded_config.config.heartbeat_discord_channel_id, heartbeat)
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
        engine.client.post_heartbeat(loaded_config.config.heartbeat_discord_channel_id, heartbeat)
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
        engine.client.post_heartbeat(loaded_config.config.heartbeat_discord_channel_id, heartbeat)
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


def _failure_reason(error: object) -> str:
    return " ".join(str(error).split())[:500] or "board operation failed"


def _own_media(event: SourceEvent) -> SourceEvent:
    if event.media_path is None:
        return event
    source = Path(event.media_path)
    if not source.is_file():
        raise ValueError("source media is unavailable")
    root = _media_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = source.suffix.lower() if source.suffix else ".bin"
    digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
    destination = root / f"{digest}{suffix}"
    if destination.is_file():
        return replace(event, media_path=str(destination))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return replace(event, media_path=str(destination))


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
