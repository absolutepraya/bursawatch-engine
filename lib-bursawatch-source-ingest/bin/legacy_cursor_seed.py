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
    expected_current_catalog_revision: int | None = None,
    allowed_current_catalog_revisions: tuple[int, ...] | None = None,
    allow_existing_matching_cursor: bool = False,
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
    expected_current_revision = catalog_revision if expected_current_catalog_revision is None else expected_current_catalog_revision
    if type(expected_current_revision) is not int or expected_current_revision < 1:
        raise LegacySeedBlocked("current catalog revision is invalid")
    allowed_revisions = set(allowed_current_catalog_revisions or (expected_current_revision,))
    if any(type(value) is not int or value < 1 for value in allowed_revisions) or expected_current_revision not in allowed_revisions:
        raise LegacySeedBlocked("allowed current catalog revisions are invalid")
    if revision_path.exists():
        try:
            recorded = json.loads(revision_path.read_text())
        except (OSError, ValueError) as error:
            raise LegacySeedBlocked("catalog revision record is invalid") from error
        if type(recorded) is not dict or type(recorded.get("revision")) is not int or recorded["revision"] not in allowed_revisions:
            raise LegacySeedBlocked("catalog revision does not match endpoint snapshot")
    elif expected_current_catalog_revision is not None:
        raise LegacySeedBlocked("catalog revision transition requires an existing revision record")
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
    plan = {
        "status": "ready",
        "apply": bool(apply),
        "legacy_state_path": str(source),
        "cursor_path": str(cursor_path),
        "current_catalog_revision": expected_current_revision,
        **provenance,
    }
    expected_cursor = _cursor_record_from_plan(plan)
    if cursor_path.exists():
        if not allow_existing_matching_cursor or cursor_path.read_bytes() != _cursor_bytes(expected_cursor):
            raise LegacySeedBlocked("initialized source cursor cannot be overwritten")
    if intent_path.exists() or (handoff_path.exists() and any(p.is_file() for p in handoff_path.rglob("*"))):
        raise LegacySeedBlocked("pending source handoff prevents cursor seeding")
    if not apply:
        plan["status"] = "preview"
        return plan
    if (
        type(expected_plan) is not dict
        or expected_plan.get("status") != "preview"
        or expected_plan.get("apply") is not False
        or any(
        expected_plan.get(key) != plan.get(key)
            for key in ("legacy_state_sha256", "endpoint", "catalog_revision", "proposed_anchor", "cursor_shape", "boundary_timestamp", "bootstrap_anchor", "cursor_path", "legacy_state_path", "current_catalog_revision")
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
        if expected_current_catalog_revision is not None:
            raise LegacySeedBlocked("catalog revision transition requires an existing revision record")
        from source_ingest import _write
        _write(revision_path, {"revision": catalog_revision})
    cursor_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if cursor_path.exists() or intent_path.exists() or (handoff_path.exists() and any(p.is_file() for p in handoff_path.rglob("*"))):
        raise LegacySeedBlocked("source cursor or handoff appeared before apply")
    _write_cursor_exclusive(cursor_path, expected_cursor)
    plan["status"] = "applied"
    return plan


def _cursor_record_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    provenance = {
        key: plan[key]
        for key in (
            "legacy_state_sha256",
            "endpoint",
            "catalog_revision",
            "proposed_anchor",
            "cursor_shape",
            "bootstrap_anchor",
            "boundary_timestamp",
        )
        if key in plan
    }
    if plan["cursor_shape"] == "telegram":
        anchor = plan["proposed_anchor"]
        bootstrap_anchor = plan.get("bootstrap_anchor")
        if not anchor.isdigit() or (bootstrap_anchor is not None and not bootstrap_anchor.isdigit()):
            raise LegacySeedBlocked("Telegram cursor seed must use numeric message IDs")
        record: dict[str, Any] = {"cursor": int(anchor), "legacy_seed": provenance}
        if bootstrap_anchor is not None:
            record["bootstrap_cursor"] = int(bootstrap_anchor)
        return record
    return {
        "initialized": True,
        "anchor": plan["proposed_anchor"],
        "position": None,
        "boundary_published_at": plan.get("boundary_timestamp"),
        "legacy_seed": provenance,
    }


def _cursor_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_cursor_exclusive(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".legacy-seed-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_cursor_bytes(record))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise LegacySeedBlocked("source cursor appeared during apply") from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".catalog-transition-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


def _state_file_hashes(root: Path, excluded: set[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if path in excluded:
            continue
        if path.is_symlink():
            raise LegacySeedBlocked("source state contains an unsupported filesystem entry")
        if path.is_dir():
            continue
        if not path.is_file():
            raise LegacySeedBlocked("source state contains an unsupported filesystem entry")
        try:
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise LegacySeedBlocked("source state could not be fingerprinted") from error
    return result


def plan_catalog_revision_transition(
    *,
    state_root: Path,
    from_revision: int,
    to_revision: int,
    seeds: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    apply: bool = False,
    expected_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview or apply a resumable, future-only catalog revision transition.

    The caller must separately prove that the catalog diff is safe and all
    writers are paused. This primitive verifies the exact source-state
    baseline, creates only absent endpoint cursors, then advances the revision
    marker last. An apply can resume after a process interruption.
    """
    root = Path(state_root).expanduser().resolve(strict=True)
    if type(from_revision) is not int or type(to_revision) is not int or to_revision <= from_revision:
        raise LegacySeedBlocked("catalog revision transition must move forward")
    if type(seeds) is not list or not seeds:
        raise LegacySeedBlocked("catalog revision transition needs at least one cursor seed")
    transition_path = root / "catalog-transitions" / f"{from_revision}-to-{to_revision}.json"
    revision_path = root / "catalog-revision.json"
    try:
        revision_record = json.loads(revision_path.read_text())
    except (OSError, ValueError) as error:
        raise LegacySeedBlocked("catalog revision record is unavailable") from error
    if type(revision_record) is not dict or type(revision_record.get("revision")) is not int or revision_record["revision"] not in {from_revision, to_revision}:
        raise LegacySeedBlocked("source state is not at the expected catalog revision")
    journal_exists = transition_path.exists()
    if revision_record["revision"] == to_revision and not journal_exists:
        raise LegacySeedBlocked("target catalog revision has no matching transition journal")
    try:
        journal = json.loads(transition_path.read_text()) if journal_exists else None
    except (OSError, ValueError) as error:
        raise LegacySeedBlocked("catalog transition journal is invalid") from error
    if journal_exists and (
        type(journal) is not dict
        or set(journal) != {"version", "status", "plan", "seeded_endpoints"}
        or journal.get("version") != 1
        or journal.get("status") not in {"applying", "complete"}
        or type(journal.get("plan")) is not dict
        or type(journal.get("seeded_endpoints")) is not list
        or any(type(value) is not str for value in journal.get("seeded_endpoints", []))
    ):
        raise LegacySeedBlocked("catalog transition journal is invalid")

    seed_plans: list[dict[str, Any]] = []
    cursor_paths: set[Path] = set()
    endpoint_ids: set[str] = set()
    for spec in seeds:
        if type(spec) is not dict:
            raise LegacySeedBlocked("catalog transition seed specification is invalid")
        args = dict(spec)
        args.pop("apply", None)
        args.pop("expected_plan", None)
        args["state_root"] = root
        args["catalog_revision"] = to_revision
        args["expected_current_catalog_revision"] = from_revision
        args["allowed_current_catalog_revisions"] = (from_revision, to_revision) if journal_exists else (from_revision,)
        args["allow_existing_matching_cursor"] = journal_exists
        seed_plan = plan_seed(**args)
        endpoint_id = seed_plan["endpoint"]["endpoint_id"]
        if endpoint_id in endpoint_ids:
            raise LegacySeedBlocked("catalog transition cannot seed an endpoint twice")
        endpoint_ids.add(endpoint_id)
        cursor_path = Path(seed_plan["cursor_path"])
        if cursor_path in cursor_paths:
            raise LegacySeedBlocked("catalog transition cursor paths collide")
        cursor_paths.add(cursor_path)
        seed_plans.append(seed_plan)

    excluded = {*cursor_paths, revision_path, transition_path}
    state_files = _state_file_hashes(root, excluded)
    plan = {
        "version": 1,
        "status": "preview",
        "apply": False,
        "state_root": str(root),
        "transition_path": str(transition_path),
        "from_revision": from_revision,
        "to_revision": to_revision,
        "state_files": state_files,
        "seeds": seed_plans,
        "metadata": metadata or {},
    }
    if journal_exists and journal["plan"] != plan:
        raise LegacySeedBlocked("catalog transition inputs differ from the durable apply journal")
    if journal_exists:
        expected_endpoint_ids = {seed["endpoint"]["endpoint_id"] for seed in seed_plans}
        seeded_endpoint_ids = journal["seeded_endpoints"]
        if len(seeded_endpoint_ids) != len(set(seeded_endpoint_ids)) or not set(seeded_endpoint_ids) <= expected_endpoint_ids:
            raise LegacySeedBlocked("catalog transition journal progress is invalid")
        if journal["status"] == "complete" and (set(seeded_endpoint_ids) != expected_endpoint_ids or revision_record["revision"] != to_revision):
            raise LegacySeedBlocked("completed catalog transition has incomplete state")
        if revision_record["revision"] == to_revision and set(seeded_endpoint_ids) != expected_endpoint_ids:
            raise LegacySeedBlocked("target catalog revision has incomplete cursor seeds")
        for seed_plan in seed_plans:
            endpoint_id = seed_plan["endpoint"]["endpoint_id"]
            if endpoint_id in seeded_endpoint_ids and not Path(seed_plan["cursor_path"]).is_file():
                raise LegacySeedBlocked("catalog transition journal references a missing cursor")
    if not apply:
        return plan
    if (
        type(expected_plan) is not dict
        or expected_plan.get("status") != "preview"
        or expected_plan.get("apply") is not False
        or expected_plan != plan
    ):
        raise LegacySeedBlocked("apply requires the unchanged catalog transition preview")
    if os.environ.get("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY") != "1":
        raise LegacySeedBlocked("apply requires BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1")
    current_files = _state_file_hashes(root, excluded)
    if current_files != state_files:
        raise LegacySeedBlocked("source state changed after the catalog transition preview")
    if not journal_exists:
        if revision_record["revision"] != from_revision:
            raise LegacySeedBlocked("catalog revision changed before transition apply")
        _write_private_json(transition_path, {"version": 1, "status": "applying", "plan": plan, "seeded_endpoints": []})
        journal_exists = True
        journal = {"version": 1, "status": "applying", "plan": plan, "seeded_endpoints": []}

    for seed_plan in seed_plans:
        cursor_path = Path(seed_plan["cursor_path"])
        record = _cursor_record_from_plan(seed_plan)
        if cursor_path.exists():
            if cursor_path.read_bytes() != _cursor_bytes(record):
                raise LegacySeedBlocked("transition cursor differs from its reviewed seed")
        else:
            _write_cursor_exclusive(cursor_path, record)
        seeded = list(journal.get("seeded_endpoints", []))
        endpoint_id = seed_plan["endpoint"]["endpoint_id"]
        if endpoint_id not in seeded:
            seeded.append(endpoint_id)
            journal["seeded_endpoints"] = seeded
            _write_private_json(transition_path, journal)

    for seed_plan in seed_plans:
        cursor_path = Path(seed_plan["cursor_path"])
        if not cursor_path.is_file() or cursor_path.read_bytes() != _cursor_bytes(_cursor_record_from_plan(seed_plan)):
            raise LegacySeedBlocked("transition cursor verification failed")
    try:
        latest_revision = json.loads(revision_path.read_text())
    except (OSError, ValueError) as error:
        raise LegacySeedBlocked("catalog revision record changed during apply") from error
    if type(latest_revision) is not dict or type(latest_revision.get("revision")) is not int or latest_revision["revision"] not in {from_revision, to_revision}:
        raise LegacySeedBlocked("catalog revision changed during apply")
    if latest_revision["revision"] == from_revision:
        _write_private_json(revision_path, {"revision": to_revision})
    journal["status"] = "complete"
    _write_private_json(transition_path, journal)
    plan["status"] = "applied"
    plan["apply"] = True
    return plan
