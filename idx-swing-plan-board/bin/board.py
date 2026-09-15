"""Runnable deterministic owner entry point for the IDX Swing plan board."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

from discord_forum import DiscordForumClient
from engine import BoardEngine
from models import SourceEvent
from render import WIB
from store import BoardStore


HERMES_HEARTBEAT_CHANNEL_ID = "1505162000420835388"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    engine = BoardEngine(BoardStore(_state_path()), DiscordForumClient())
    if arguments.command == "submit-source-event":
        return _submit_source_event(engine)
    if arguments.command == "drain":
        print(json.dumps({"drained": engine.drain()}, separators=(",", ":")))
        return 0
    result = engine.after_close(arguments.phase, datetime.now(WIB))
    engine.drain()
    # ``pending`` describes retained owner work after this invocation, not the
    # number of operations just completed.
    result["pending"] = engine.store.pending_outbox_count()
    heartbeat = _heartbeat(arguments.phase, result)
    engine.client.post_heartbeat(HERMES_HEARTBEAT_CHANNEL_ID, heartbeat)
    print(heartbeat)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    submit = subcommands.add_parser("submit-source-event")
    submit.add_argument("--stdin", action="store_true", required=True)
    subcommands.add_parser("drain")
    after_close = subcommands.add_parser("after-close")
    after_close.add_argument("--phase", choices=("initial", "retry"), required=True)
    return parser


def _submit_source_event(engine: BoardEngine) -> int:
    payload = json.load(sys.stdin)
    event = SourceEvent.from_json(payload)
    event = _own_media(event)
    # The engine's one transition commits immutable intake and every resulting
    # outbox intent together before the acknowledgement is written.
    engine.submit(event, datetime.now(WIB))
    engine.drain()
    print(json.dumps({"accepted": True}, separators=(",", ":")))
    return 0


def _own_media(event: SourceEvent) -> SourceEvent:
    if event.media_path is None:
        return event
    source = Path(event.media_path)
    if not source.is_file():
        raise ValueError("source media is unavailable")
    root = _media_root()
    root.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() if source.suffix else ".bin"
    digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
    destination = root / f"{digest}{suffix}"
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
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
    warning = " ⚠️" if result["unavailable"] else ""
    return (
        f"🫀 idx-swing-plan-board · {clock} WIB · active={result['active']} "
        f"checked={result['checked']} unavailable={result['unavailable']} "
        f"pending={result['pending']}{warning}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
