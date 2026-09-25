"""Fail-closed plans for importing a legacy source high-water mark.

The caller derives the platform-specific boundary. This module binds that
boundary to the exact legacy snapshot and endpoint catalog revision.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class LegacySeedBlocked(RuntimeError):
    pass


def read_legacy_snapshot(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Read a legacy snapshot once so its hash and mapped boundary agree."""
    try:
        raw = Path(path).expanduser().read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as error:
        raise LegacySeedBlocked("legacy snapshot is unreadable JSON") from error
    if type(value) is not dict:
        raise LegacySeedBlocked("legacy snapshot root is invalid")
    return raw, value


def blocked_seed_plan(legacy_state_path: Path, endpoint: dict[str, Any], catalog_revision: int, reason: str) -> dict[str, Any]:
    """Return an auditable no-apply result when a boundary is not mappable."""
    try:
        digest = hashlib.sha256(Path(legacy_state_path).expanduser().read_bytes()).hexdigest()
    except OSError as error:
        raise LegacySeedBlocked("legacy snapshot is unreadable") from error
    return {
        "status": "blocked",
        "apply": False,
        "legacy_state_sha256": digest,
        "endpoint": {
            key: endpoint.get(key)
            for key in ("platform", "endpoint_id", "publisher_id", "address", "provider_id")
        },
        "catalog_revision": catalog_revision,
        "proposed_cursor": None,
        "reason": reason,
    }


def plan_seed(
    *,
    legacy_state_path: Path,
    state_root: Path,
    endpoint: dict[str, Any],
    snapshot_bytes: bytes,
    catalog_revision: int,
    anchor: str,
    cursor_shape: str,
    bootstrap_anchor: str | None = None,
    boundary_timestamp: str | None = None,
    apply: bool = False,
    expected_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview by default; `apply=True` is the explicit apply interface."""
    source = Path(legacy_state_path).expanduser().resolve(strict=True)
    root = Path(state_root).expanduser().resolve()
    if not source.is_file() or not isinstance(endpoint, dict):
        raise LegacySeedBlocked("legacy snapshot or endpoint identity is invalid")
    endpoint_id = endpoint.get("endpoint_id")
    if not isinstance(endpoint_id, str) or not endpoint_id or "/" in endpoint_id or "\\" in endpoint_id or ".." in endpoint_id or type(catalog_revision) is not int or catalog_revision < 1:
        raise LegacySeedBlocked("endpoint identity or catalog revision is invalid")
    if endpoint.get("catalog_revision") != catalog_revision:
        raise LegacySeedBlocked("endpoint catalog revision differs from the requested revision")
    if not isinstance(anchor, str) or not anchor or cursor_shape not in {"generic", "telegram"}:
        raise LegacySeedBlocked("proposed legacy cursor is invalid")
    raw = snapshot_bytes
    if type(raw) is not bytes:
        raise LegacySeedBlocked("legacy snapshot bytes are required")
    try:
        legacy = json.loads(raw)
    except ValueError as error:
        raise LegacySeedBlocked("legacy snapshot is unreadable JSON") from error
    try:
        source_unchanged = source.read_bytes() == raw
    except OSError as error:
        raise LegacySeedBlocked("legacy snapshot could not be verified") from error
    if type(legacy) is not dict or not source_unchanged:
        raise LegacySeedBlocked("legacy snapshot changed while its plan was being built")
    digest = hashlib.sha256(raw).hexdigest()
    endpoint_record = {
        key: endpoint[key]
        for key in ("platform", "endpoint_id", "publisher_id", "address", "provider_id")
        if key in endpoint
    }
    if set(endpoint_record) != {"platform", "endpoint_id", "publisher_id", "address", "provider_id"}:
        raise LegacySeedBlocked("endpoint identity is incomplete")
    cursor_path = root / endpoint_id.replace(":", "-") / "cursor.json"
    intent_path = cursor_path.parent / "pending-position.json"
    handoff_path = cursor_path.parent / "handoff"
    revision_path = root / "catalog-revision.json"
    if cursor_path.exists():
        raise LegacySeedBlocked("initialized source cursor cannot be overwritten")
    if intent_path.exists() or (handoff_path.exists() and any(p.is_file() for p in handoff_path.rglob("*"))):
        raise LegacySeedBlocked("pending source handoff prevents cursor seeding")
    if revision_path.exists():
        try:
            recorded = json.loads(revision_path.read_text())
        except (OSError, ValueError) as error:
            raise LegacySeedBlocked("catalog revision record is invalid") from error
        if type(recorded) is not dict or recorded.get("revision") != catalog_revision:
            raise LegacySeedBlocked("catalog revision does not match endpoint snapshot")
    provenance = {
        "legacy_state_sha256": digest,
        "endpoint": endpoint_record,
        "catalog_revision": catalog_revision,
        "proposed_anchor": anchor,
        "cursor_shape": cursor_shape,
    }
    if bootstrap_anchor is not None:
        provenance["bootstrap_anchor"] = bootstrap_anchor
    if boundary_timestamp is not None:
        provenance["boundary_timestamp"] = boundary_timestamp
    plan = {"status": "ready", "apply": bool(apply), "cursor_path": str(cursor_path), **provenance}
    if not apply:
        plan["status"] = "preview"
        return plan
    if (
        type(expected_plan) is not dict
        or expected_plan.get("status") != "preview"
        or expected_plan.get("apply") is not False
        or any(
        expected_plan.get(key) != plan.get(key)
            for key in ("legacy_state_sha256", "endpoint", "catalog_revision", "proposed_anchor", "cursor_shape", "boundary_timestamp", "bootstrap_anchor", "cursor_path")
        )
    ):
        raise LegacySeedBlocked("apply requires the unchanged preview plan for this snapshot, endpoint, and revision")
    if os.environ.get("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY") != "1":
        raise LegacySeedBlocked("apply requires BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1")
    try:
        current_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as error:
        raise LegacySeedBlocked("legacy snapshot could not be verified at apply") from error
    if current_digest != digest:
        raise LegacySeedBlocked("legacy snapshot changed after plan creation")
    if not revision_path.exists():
        from source_ingest import _write
        _write(revision_path, {"revision": catalog_revision})
    cursor_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if cursor_path.exists() or intent_path.exists() or (handoff_path.exists() and any(p.is_file() for p in handoff_path.rglob("*"))):
        raise LegacySeedBlocked("source cursor or handoff appeared before apply")
    if cursor_shape == "telegram":
        if not anchor.isdigit() or (bootstrap_anchor is not None and not bootstrap_anchor.isdigit()):
            raise LegacySeedBlocked("Telegram cursor seed must use numeric message IDs")
        record: dict[str, Any] = {"cursor": int(anchor), "legacy_seed": provenance}
        if bootstrap_anchor is not None:
            record["bootstrap_cursor"] = int(bootstrap_anchor)
    else:
        record = {"initialized": True, "anchor": anchor, "position": None, "boundary_published_at": boundary_timestamp, "legacy_seed": provenance}
    fd, temporary = tempfile.mkstemp(prefix=".legacy-seed-", dir=cursor_path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, cursor_path)
        except FileExistsError as error:
            raise LegacySeedBlocked("source cursor appeared during apply") from error
        directory = os.open(cursor_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    plan["status"] = "applied"
    return plan
