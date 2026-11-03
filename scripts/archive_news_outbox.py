#!/usr/bin/env python3
"""Preview or archive X/WA pending output after an operator fences every writer.

This tool does not pause writers, move source cursors, reconcile receipts, or
delete media. Applying is one part of a separately reviewed recovery procedure.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > 128 * 1024 * 1024:
            raise ValueError("state must be a bounded regular file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(128 * 1024 * 1024 + 1)
        if len(raw) != details.st_size:
            raise ValueError("state changed while reading")
        return raw
    finally:
        os.close(fd)


def _selection(kind, value):
    if kind not in {"x", "wa"} or type(value) is not dict or type(value.get("outbox")) is not list:
        raise ValueError("unsupported owner state")
    result = []
    for index, item in enumerate(value["outbox"]):
        if type(item) is not dict:
            raise ValueError("outbox item must be an object")
        if kind == "wa":
            phase = item.get("agent_phase")
            if phase in {"delivered", "filtered"}:
                continue
            if phase not in {"pending", "awaiting_agent", "ready"}:
                raise ValueError("unrecognized WhatsApp phase")
        result.append(index)
    return result


def preview(kind, path):
    path = Path(path).absolute()
    try:
        raw = _read(path)
    except OSError as exc:
        raise ValueError("state must be a readable regular file") from exc
    value = json.loads(raw)
    selected = _selection(kind, value)
    selection = set(selected)
    after = dict(value, outbox=[item for i, item in enumerate(value["outbox"]) if i not in selection])
    return {
        "version": 1, "kind": kind, "state": str(path),
        "before_sha256": _sha(raw), "after_sha256": _sha(_bytes(after)),
        "selected": [{"index": i, "sha256": _sha(_bytes(value["outbox"][i]))} for i in selected],
        "remaining": len(after["outbox"]),
    }


def _write(path, raw):
    fd, name = tempfile.mkstemp(prefix=".archive-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _mkdir_durable(path, *, exclusive=False):
    if path.exists() or path.is_symlink():
        if exclusive or path.is_symlink() or not path.is_dir():
            raise ValueError("archive path must be a new private directory")
        return
    _mkdir_durable(path.parent)
    path.mkdir(mode=0o700)
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def apply(plan, archive_dir, *, writers_paused, open_operations):
    if not writers_paused:
        raise ValueError("all source, queue and agent writers must be paused and quiescent")
    path = Path(plan["state"])
    lock_name = "run.lock" if plan["kind"] == "x" else "pipeline-owner.lock"
    lock_fd = os.open(path.parent / lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if preview(plan["kind"], path) != plan:
            raise ValueError("state or selection changed after preview")
        if open_operations() != 0:
            raise ValueError("nonterminal delivery operations require receipt reconciliation")
        raw = _read(path)
        value = json.loads(raw)
        selection = {row["index"] for row in plan["selected"]}
        for index in selection:
            lease = value["outbox"][index].get("agent_lease_until")
            if lease is not None:
                try:
                    until = datetime.fromisoformat(lease.replace("Z", "+00:00"))
                    if until.tzinfo is None or until > datetime.now(timezone.utc):
                        raise ValueError("active or invalid agent lease; keep writers paused")
                except (TypeError, AttributeError) as exc:
                    raise ValueError("invalid agent lease") from exc
        after = _bytes(dict(value, outbox=[row for i, row in enumerate(value["outbox"]) if i not in selection]))
        archive_dir = Path(archive_dir)
        # Persist every newly created ancestor before the backup can become
        # the recovery source for the live state's atomic replacement.
        _mkdir_durable(archive_dir, exclusive=True)
        _write(archive_dir / "state-before.json", raw)
        _write(archive_dir / "plan.json", _bytes(plan))
        if _sha(_read(archive_dir / "state-before.json")) != plan["before_sha256"]:
            raise ValueError("archive verification failed")
        # Writers must remain fenced. Recheck after the durable backup and
        # before the atomic switch; never blindly overwrite observed drift.
        if _read(path) != raw or open_operations() != 0:
            raise ValueError("state changed or delivery became nonterminal during archive")
        _write(path, after)
        if _sha(_read(path)) != plan["after_sha256"]:
            raise ValueError("archived state verification failed; keep writers paused")
        receipt = {"archived_at": datetime.now(timezone.utc).isoformat(), "archived_count": len(selection), "after_sha256": plan["after_sha256"]}
        _write(archive_dir / "receipt.json", _bytes(receipt))
        return receipt
    finally:
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("x", "wa"))
    parser.add_argument("state", type=Path)
    parser.add_argument("--apply-plan", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--delivery-ledger", type=Path)
    parser.add_argument("--writers-paused", action="store_true")
    args = parser.parse_args()
    if args.apply_plan is None:
        print(json.dumps(preview(args.kind, args.state), sort_keys=True))
        return
    if os.environ.get("BURSAWATCH_RECOVERY_APPLY") != "1":
        raise ValueError("explicit BURSAWATCH_RECOVERY_APPLY=1 is required")
    if not args.archive_dir or not args.delivery_ledger:
        raise ValueError("archive directory and delivery ledger are required")
    archive = args.archive_dir.absolute()
    if not archive.resolve().is_relative_to((Path.home() / "backup/hermes/runtime-cutovers").resolve()):
        raise ValueError("use the canonical VPS runtime-cutovers backup tree")
    plan = json.loads(_read(args.apply_plan))
    if plan["kind"] != args.kind or Path(plan["state"]) != args.state.absolute():
        raise ValueError("plan identifies a different owner or state")
    def open_operations():
        prefix = "bursawatch-x-account-watch:" if args.kind == "x" else "bursawatch-wa-channel-watch:"
        with sqlite3.connect(args.delivery_ledger.absolute().as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute("SELECT count(*) FROM discord_operations WHERE operation_key LIKE ? AND status NOT IN ('delivered','rejected')", (prefix + "%",)).fetchone()[0]
    print(json.dumps(apply(plan, archive, writers_paused=args.writers_paused, open_operations=open_operations)))


if __name__ == "__main__":
    main()
