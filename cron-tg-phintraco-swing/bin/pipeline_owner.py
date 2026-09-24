"""Task 4 source-work entry into the existing Phintraco owner ledger."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import scan


class OwnerPending(RuntimeError):
    """The existing durable owner has not acknowledged every delivery leg."""


def _receipt_path(effect_key: str) -> Path:
    return scan.state_path().parent / "pipeline-receipts" / f"{effect_key}.json"


def _acknowledge_effect(path: Path, work: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".effect-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"effect_key": work["effect_key"], "event_key": work["event_key"], "version": work["version"]}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _source_message(envelope: dict[str, Any]) -> SimpleNamespace:
    body = envelope["payload"]
    return SimpleNamespace(
        id=int(envelope["provider_event_id"]),
        message=body["text"],
        date=datetime.fromisoformat(envelope["published_at"]),
        photo=None,
    )


def submit(work: dict[str, Any], *, no_post: bool = False) -> str:
    loaded = scan.config.load_watch_config_for_run()
    if loaded.revision is None:
        raise ValueError("Phintraco pipeline requires an effective live watch config")
    if (loaded.config.telegram_channel_id, loaded.config.telegram_username) != (1444713822, "phintraprofits"):
        raise ValueError("Phintraco pipeline source does not match canonical endpoint")
    with scan.config.activate_watch_config(loaded.config):
        return _submit_with_config(work, no_post=no_post)


def _submit_with_config(work: dict[str, Any], *, no_post: bool) -> str:
    if no_post:
        isolated = os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH")
        if not isolated or Path(isolated).expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
            raise ValueError("no-post owner work requires isolated state")
    envelope = work["envelope"]
    if (work["pipeline_id"], work["capability_id"], work["version"], envelope["endpoint_id"], envelope["publisher_id"]) != ("swing_plan", "trading_plans", 1, "telegram:phintraprofits", "phintraco"):
        raise ValueError("unsupported Phintraco source work")
    expected = hashlib.sha256(f'{work["event_key"]}:1:trading_plans'.encode()).hexdigest()
    if work["effect_key"] != expected or work["work_key"] != expected or envelope["media_required"] or envelope["media_refs"]:
        raise ValueError("Phintraco work identity or media contract is invalid")
    message = _source_message(envelope)
    call = scan.parse_source_event(message)
    if call is None and envelope["payload"].get("reply_parent"):
        parent = envelope["payload"]["reply_parent"]
        if type(parent) is not dict or set(parent) != {"message_id", "text", "published_at", "has_photo"}:
            raise ValueError("Phintraco reply parent is invalid")
        parent_message = SimpleNamespace(id=parent["message_id"], message=parent["text"], date=datetime.fromisoformat(parent["published_at"]), photo=object() if parent["has_photo"] else None)
        call = scan.parse_reply_status(message.id, message.message, False, message.date, scan.parse_source_event(parent_message))
    if call is None:
        if scan.looks_like_swing_call(message.message):
            raise ValueError("malformed Phintraco plan")
        return "irrelevant"
    if call.has_source_chart:
        raise ValueError("Phintraco chart needs durable media")
    now = datetime.now(scan.WIB)
    with scan.run_lock() as acquired:
        if not acquired:
            raise OwnerPending("Phintraco owner ledger is busy")
        receipt_path = _receipt_path(work["effect_key"])
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != {"effect_key": work["effect_key"], "event_key": work["event_key"], "version": work["version"]}:
                raise ValueError("Phintraco effect receipt is invalid")
            return "accepted"
        state = scan.load_state()
        scan.enqueue_call(state, call, now)
        scan.save_state(state)
        scan.drain_outbox(state, now, dry_run=no_post)
        if str(call.source_message_id) in state["outbox"]:
            raise OwnerPending("Phintraco owner delivery remains pending")
        _acknowledge_effect(receipt_path, work)
    return "accepted"


def main() -> int:
    import os
    import sys
    work = json.load(sys.stdin)
    result = submit(work, no_post=os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1")
    print(json.dumps({"outcome": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
