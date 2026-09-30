#!/usr/bin/env python3
"""Preview and apply one cursor-preserving Stockbit RSS catalog edge."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from datetime import datetime
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for local_name, runtime_name in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
):
    candidate = ROOT / local_name / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / runtime_name / "bin"
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
if str(owner) not in sys.path:
    sys.path.insert(0, str(owner))

from adapter import IntakeBlocked, _load_validators, endpoints
from config import FEEDS, load_watch_config_for_run
from legacy_cursor_seed import LegacySeedBlocked, plan_catalog_revision_transition

_APPLY_ENV = "BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TRANSITION_TYPE = "rss-compatible-catalog-transition"
_REASON = "The complete enabled Stockbit RSS projection is unchanged across this adjacent catalog revision."


class TransitionBlocked(RuntimeError):
    """The catalogs, live watcher config, or persisted source state are unsafe."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise TransitionBlocked("catalog transition input is not canonical JSON") from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_object(path: Path, label: str, *, private: bool = False) -> tuple[dict[str, Any], bytes]:
    path = path.expanduser()
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise TransitionBlocked(f"{label} is not a regular file")
        if private and stat.S_IMODE(metadata.st_mode) != 0o600:
            raise TransitionBlocked(f"{label} must have mode 0600")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except TransitionBlocked:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise TransitionBlocked(f"{label} is unavailable or invalid") from error
    if type(value) is not dict:
        raise TransitionBlocked(f"{label} must be a JSON object")
    return value, raw


def _read_catalog_snapshot(value: dict[str, Any], label: str) -> tuple[int, list[dict[str, Any]]]:
    if type(value) is not dict or type(value.get("revision")) is not int or value["revision"] < 1:
        raise TransitionBlocked(f"{label} revision is invalid")
    if type(value.get("subscriptions")) is not list or any(type(row) is not dict for row in value["subscriptions"]):
        raise TransitionBlocked(f"{label} subscriptions are invalid")
    _canonical(value)
    return value["revision"], value["subscriptions"]


def _resolved_state_root(value: Path) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise TransitionBlocked("source state root is a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise TransitionBlocked("source state root is unavailable") from error
    if resolved.is_symlink() or not resolved.is_dir():
        raise TransitionBlocked("source state root is invalid")
    return resolved


def _read_marker(path: Path, label: str) -> tuple[int, str]:
    record, raw = _read_object(path, label)
    if set(record) != {"revision"} or type(record.get("revision")) is not int or record["revision"] < 1:
        raise TransitionBlocked(f"{label} is invalid")
    return record["revision"], _sha256(raw)


def _effective_projection(snapshot: dict[str, Any], loaded_config: Any, label: str) -> list[dict[str, Any]]:
    if type(snapshot.get("subscriptions")) is not list:
        raise TransitionBlocked(f"{label} subscriptions are invalid")
    try:
        selected, _feeds = endpoints(snapshot, loaded_config)
    except (IntakeBlocked, AttributeError, KeyError, TypeError, ValueError) as error:
        raise TransitionBlocked(f"{label} does not match the validated Stockbit watcher config") from error

    expected_lanes = {feed.lane.value for feed in FEEDS}
    configured = getattr(getattr(loaded_config, "config", None), "feeds", None)
    if type(configured) not in {tuple, list}:
        raise TransitionBlocked("validated Stockbit watcher config is invalid")
    configured_lanes = {
        getattr(setting, "lane", None).value
        for setting in configured
        if getattr(setting, "lane", None) is not None and getattr(setting, "enabled", None) is True
    }
    if len(FEEDS) != 4 or configured_lanes != expected_lanes:
        raise TransitionBlocked("Stockbit watcher config must enable exactly the four fixed lanes")

    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for row in snapshot["subscriptions"]:
        if row.get("platform") != "rss" or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        capability_id = row.get("capability_id")
        if type(endpoint_id) is not str or type(capability_id) is not str:
            raise TransitionBlocked(f"{label} enabled RSS identity is invalid")
        identity = (endpoint_id, capability_id)
        if identity in identities:
            raise TransitionBlocked(f"{label} repeats an enabled RSS identity")
        identities.add(identity)
        rows.append(row)

    expected = {(f"rss:stockbit:{lane}", "stockbit_snips") for lane in expected_lanes}
    if identities != expected or set(selected) != {endpoint_id for endpoint_id, _capability in expected}:
        raise TransitionBlocked(f"{label} must contain exactly the four enabled Stockbit RSS lanes")
    rows.sort(key=lambda row: (row["endpoint_id"], row["capability_id"]))
    return rows


def _valid_digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_timestamp(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _seed_origin(root: Path, through_revision: int) -> tuple[int, str, dict[str, str]]:
    from config import FEEDS as configured_feeds

    origins: set[int] = set()
    legacy_digests: set[str] = set()
    checked_hashes: dict[str, str] = {}
    for feed in configured_feeds:
        lane = feed.lane.value
        endpoint_id = f"rss:stockbit:{lane}"
        endpoint = {
            "platform": "rss",
            "endpoint_id": endpoint_id,
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": lane,
        }
        lane_root = root / endpoint_id.replace(":", "-")
        cursor_path = lane_root / "cursor.json"
        validator_path = lane_root / "http-validators.json"
        cursor, cursor_raw = _read_object(cursor_path, "Stockbit cursor")
        if type(cursor.get("initialized")) is not bool or cursor["initialized"] is not True:
            raise TransitionBlocked("Stockbit cursor is not initialized")
        if not _valid_digest(cursor.get("anchor")) or type(cursor.get("position")) not in {str, type(None)}:
            raise TransitionBlocked("Stockbit cursor shape is invalid")
        boundary = cursor.get("boundary_published_at")
        if not _valid_timestamp(boundary):
            raise TransitionBlocked("Stockbit cursor boundary is invalid")
        seed = cursor.get("legacy_seed")
        if type(seed) is not dict:
            raise TransitionBlocked("Stockbit legacy seed provenance is missing")
        origin = seed.get("catalog_revision")
        digest = seed.get("legacy_state_sha256")
        if (
            type(origin) is not int
            or origin < 1
            or origin > through_revision
            or seed.get("endpoint") != endpoint
            or seed.get("cursor_shape") != "generic"
            or not _valid_digest(seed.get("proposed_anchor"))
            or not _valid_digest(digest)
            or not _valid_timestamp(seed.get("boundary_timestamp"))
        ):
            raise TransitionBlocked("Stockbit legacy seed provenance is invalid")
        origins.add(origin)
        legacy_digests.add(digest)
        checked_hashes[str(cursor_path.relative_to(root))] = _sha256(cursor_raw)

        if validator_path.is_symlink() or not validator_path.is_file():
            raise TransitionBlocked("Stockbit endpoint validator file is missing or invalid")
        try:
            validator_before = validator_path.read_bytes()
        except OSError as error:
            raise TransitionBlocked("Stockbit endpoint validator file is unreadable") from error
        try:
            _load_validators(root, endpoint_id)
        except (IntakeBlocked, OSError, ValueError) as error:
            raise TransitionBlocked("Stockbit endpoint validator file is invalid") from error
        try:
            validator_after = validator_path.read_bytes()
        except OSError as error:
            raise TransitionBlocked("Stockbit endpoint validator file is unreadable") from error
        if validator_before != validator_after:
            raise TransitionBlocked("Stockbit endpoint validators changed while planning")
        checked_hashes[str(validator_path.relative_to(root))] = _sha256(validator_after)

    if len(origins) != 1 or len(legacy_digests) != 1:
        raise TransitionBlocked("Stockbit cursors do not share one legacy seed origin")
    return next(iter(origins)), next(iter(legacy_digests)), checked_hashes


def _read_journal(path: Path) -> dict[str, Any]:
    journal, _raw = _read_object(path, "RSS catalog transition journal", private=True)
    if (
        set(journal) != {"version", "status", "plan", "seeded_endpoints"}
        or type(journal.get("version")) is not int
        or journal["version"] != 1
        or type(journal.get("status")) is not str
        or journal["status"] not in {"applying", "complete"}
        or type(journal.get("plan")) is not dict
        or journal.get("seeded_endpoints") != []
    ):
        raise TransitionBlocked("RSS catalog transition journal is malformed")
    return journal


def _metadata_matches(
    metadata: Any,
    *,
    projection_sha256: str,
    watch_config_revision: int,
    seed_origin_revision: int,
) -> bool:
    return (
        type(metadata) is dict
        and metadata.get("transition_type") == _TRANSITION_TYPE
        and metadata.get("projection_sha256") == projection_sha256
        and type(metadata.get("watch_config_revision")) is int
        and metadata.get("watch_config_revision") == watch_config_revision
        and type(metadata.get("seed_origin_revision")) is int
        and metadata.get("seed_origin_revision") == seed_origin_revision
        and _valid_digest(metadata.get("prior_catalog_sha256"))
        and _valid_digest(metadata.get("target_catalog_sha256"))
        and type(metadata.get("reason")) is str
    )


def _validate_completed_edge(
    root: Path,
    path: Path,
    from_revision: int,
    to_revision: int,
    *,
    projection_sha256: str,
    watch_config_revision: int,
    seed_origin_revision: int,
) -> None:
    journal = _read_journal(path)
    plan = journal["plan"]
    expected_path = root / "catalog-transitions" / f"{from_revision}-to-{to_revision}.json"
    if (
        type(plan.get("version")) is not int
        or journal["status"] != "complete"
        or plan.get("version") != 1
        or plan.get("status") != "preview"
        or plan.get("apply") is not False
        or plan.get("revision_only") is not True
        or type(plan.get("from_revision")) is not int
        or plan.get("from_revision") != from_revision
        or type(plan.get("to_revision")) is not int
        or plan.get("to_revision") != to_revision
        or plan.get("state_root") != str(root)
        or plan.get("transition_path") != str(expected_path)
        or plan.get("seeds") != []
        or not _metadata_matches(
            plan.get("metadata"),
            projection_sha256=projection_sha256,
            watch_config_revision=watch_config_revision,
            seed_origin_revision=seed_origin_revision,
        )
    ):
        raise TransitionBlocked("RSS catalog transition journal does not prove this compatible edge")
    state_files = plan.get("state_files")
    if type(state_files) is not dict or any(type(key) is not str or not _valid_digest(value) for key, value in state_files.items()):
        raise TransitionBlocked("RSS catalog transition journal state fingerprint is invalid")


def _validate_prior_chain(
    root: Path,
    origin_revision: int,
    prior_revision: int,
    *,
    projection_sha256: str,
    watch_config_revision: int,
    current_transition_path: Path,
) -> None:
    directory = root / "catalog-transitions"
    if directory.is_symlink():
        raise TransitionBlocked("RSS catalog transition directory cannot be a symlink")
    expected_paths = {
        directory / f"{revision}-to-{revision + 1}.json"
        for revision in range(origin_revision, prior_revision)
    }
    allowed = set(expected_paths)
    if current_transition_path.exists() or current_transition_path.is_symlink():
        allowed.add(current_transition_path)
        if current_transition_path.is_symlink() or not current_transition_path.is_file():
            raise TransitionBlocked("current RSS catalog transition journal is unsafe")
        _read_journal(current_transition_path)
    if directory.exists():
        if not directory.is_dir():
            raise TransitionBlocked("RSS catalog transition path is invalid")
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise TransitionBlocked("RSS catalog transition directory must be private")
        try:
            entries = set(directory.iterdir())
        except OSError as error:
            raise TransitionBlocked("RSS catalog transition directory is unreadable") from error
        if entries != allowed:
            raise TransitionBlocked("RSS catalog transition history has a gap or unexpected entry")
    elif expected_paths:
        raise TransitionBlocked("RSS catalog transition history is incomplete")

    for edge_path in sorted(expected_paths):
        from_revision = int(edge_path.stem.split("-to-")[0])
        _validate_completed_edge(
            root,
            edge_path,
            from_revision,
            from_revision + 1,
            projection_sha256=projection_sha256,
            watch_config_revision=watch_config_revision,
            seed_origin_revision=origin_revision,
        )


def _state_plan(
    *,
    root: Path,
    from_revision: int,
    to_revision: int,
    metadata: dict[str, Any],
    apply: bool = False,
    expected_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return plan_catalog_revision_transition(
            state_root=root,
            from_revision=from_revision,
            to_revision=to_revision,
            seeds=[],
            metadata=metadata,
            allow_empty_seeds=True,
            apply=apply,
            expected_plan=expected_plan,
            apply_guard_env=_APPLY_ENV,
        )
    except LegacySeedBlocked as error:
        raise TransitionBlocked("shared source-state transition planner rejected the RSS edge") from error


def _package_plan(
    prior: dict[str, Any],
    target: dict[str, Any],
    state_root: Path,
    loaded_config: Any,
) -> dict[str, Any]:
    root = _resolved_state_root(state_root)
    prior_revision, _prior_rows = _read_catalog_snapshot(prior, "prior catalog")
    target_revision, _target_rows = _read_catalog_snapshot(target, "target catalog")
    if target_revision != prior_revision + 1:
        raise TransitionBlocked("RSS transition requires one adjacent catalog revision")
    config_revision = getattr(loaded_config, "revision", None)
    if type(config_revision) is not int or config_revision < 1:
        raise TransitionBlocked("validated Stockbit watcher revision is invalid")

    prior_projection = _effective_projection(prior, loaded_config, "prior catalog")
    target_projection = _effective_projection(target, loaded_config, "target catalog")
    if prior_projection != target_projection:
        raise TransitionBlocked("enabled Stockbit RSS projection changed across catalog revisions")
    projection_sha256 = _sha256(_canonical(prior_projection))
    prior_catalog_sha256 = _sha256(_canonical(prior))
    target_catalog_sha256 = _sha256(_canonical(target))

    marker_revision, _marker_hash = _read_marker(root / "catalog-revision.json", "source catalog revision marker")
    watcher_revision, watcher_hash = _read_marker(root / "watch-config-revision.json", "Stockbit watcher revision marker")
    if watcher_revision != config_revision:
        raise TransitionBlocked("source state watcher revision differs from validated live config")
    if marker_revision not in {prior_revision, target_revision}:
        raise TransitionBlocked("source state marker is not at the expected adjacent catalog edge")

    origin_revision, legacy_state_sha256, seed_hashes = _seed_origin(root, prior_revision)
    current_transition_path = root / "catalog-transitions" / f"{prior_revision}-to-{target_revision}.json"
    _validate_prior_chain(
        root,
        origin_revision,
        prior_revision,
        projection_sha256=projection_sha256,
        watch_config_revision=config_revision,
        current_transition_path=current_transition_path,
    )
    if marker_revision == target_revision and not current_transition_path.exists():
        raise TransitionBlocked("target source marker has no current-edge journal")
    if current_transition_path.exists():
        current_journal = _read_journal(current_transition_path)
        if marker_revision == prior_revision and current_journal["status"] == "complete":
            raise TransitionBlocked("completed RSS journal is ahead of its source marker")

    metadata = {
        "transition_type": _TRANSITION_TYPE,
        "projection_sha256": projection_sha256,
        "watch_config_revision": config_revision,
        "prior_catalog_sha256": prior_catalog_sha256,
        "target_catalog_sha256": target_catalog_sha256,
        "seed_origin_revision": origin_revision,
        "reason": _REASON,
    }
    shared_plan = _state_plan(
        root=root,
        from_revision=prior_revision,
        to_revision=target_revision,
        metadata=metadata,
    )
    state_files = shared_plan.get("state_files")
    if type(state_files) is not dict:
        raise TransitionBlocked("shared source-state fingerprint is invalid")
    for relative, digest in {**seed_hashes, "watch-config-revision.json": watcher_hash}.items():
        if state_files.get(relative) != digest:
            raise TransitionBlocked("source state changed while the RSS transition was being planned")
    if _read_marker(root / "catalog-revision.json", "source catalog revision marker")[0] != marker_revision:
        raise TransitionBlocked("source catalog marker changed while planning")

    package_plan: dict[str, Any] = {
        "version": 1,
        "status": "preview",
        "apply": False,
        "state_root": str(root),
        "from_revision": prior_revision,
        "to_revision": target_revision,
        "prior_catalog_sha256": prior_catalog_sha256,
        "target_catalog_sha256": target_catalog_sha256,
        "projection_sha256": projection_sha256,
        "watch_config_revision": config_revision,
        "seed_origin_revision": origin_revision,
        "legacy_state_sha256": legacy_state_sha256,
        "revision_only": True,
        "state_files": state_files,
        "state_plan": shared_plan,
    }
    package_plan["plan_sha256"] = _sha256(_canonical(package_plan))
    return package_plan


def build_plan(prior: dict[str, Any], target: dict[str, Any], state_root: Path, loaded_config: Any) -> dict[str, Any]:
    """Preview one adjacent edge without changing the RSS source state."""
    return _package_plan(prior, target, state_root, loaded_config)


def apply_plan(
    expected: dict[str, Any],
    prior: dict[str, Any],
    target: dict[str, Any],
    state_root: Path,
    loaded_config: Any,
) -> dict[str, Any]:
    """Apply or resume exactly the RSS transition represented by a preview."""
    current = _package_plan(prior, target, state_root, loaded_config)
    if type(expected) is not dict or expected != current:
        raise TransitionBlocked("catalog, config, state, or plan changed after preview")
    revision_plan = expected.get("state_plan")
    if type(revision_plan) is not dict:
        raise TransitionBlocked("shared source-state preview is missing")
    metadata = revision_plan.get("metadata")
    applied = _state_plan(
        root=Path(expected["state_root"]),
        from_revision=expected["from_revision"],
        to_revision=expected["to_revision"],
        metadata=metadata,
        apply=True,
        expected_plan=revision_plan,
    )
    return {
        "status": "applied",
        "from_revision": expected["from_revision"],
        "to_revision": expected["to_revision"],
        "state_file_count": len(expected["state_files"]),
        "plan_sha256": expected["plan_sha256"],
    }


def _validate_plan_path(value: Path, state_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise TransitionBlocked("catalog transition plan cannot be a symlink")
    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.exists() and ancestor.is_symlink():
            raise TransitionBlocked("catalog transition plan path cannot traverse a symlink")
        ancestor = ancestor.parent
    resolved = path.resolve()
    try:
        resolved.relative_to(state_root)
    except ValueError:
        pass
    else:
        raise TransitionBlocked("catalog transition plan must be outside the source state root")
    parent = resolved.parent
    if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise TransitionBlocked("catalog transition plan directory must be private")
    return resolved


def _write_new_private_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser()
    if path.is_symlink():
        raise TransitionBlocked("catalog transition plan cannot be a symlink")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise TransitionBlocked("catalog transition plan directory must be private")
    raw = _canonical(value) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".rss-catalog-plan-", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise TransitionBlocked("catalog transition plan already exists") from error
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--prior-catalog", type=Path, required=True)
    parser.add_argument("--target-catalog", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True, help="private plan path outside the source state root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _resolved_state_root(args.state_root)
        plan_path = _validate_plan_path(args.plan_file, root)
        prior, _prior_raw = _read_object(args.prior_catalog, "prior effective catalog")
        target, _target_raw = _read_object(args.target_catalog, "target effective catalog")
        loaded_config = load_watch_config_for_run()
        if args.action == "preview":
            plan = build_plan(prior, target, root, loaded_config)
            _write_new_private_json(plan_path, plan)
            result = {
                "status": "preview",
                "from_revision": plan["from_revision"],
                "to_revision": plan["to_revision"],
                "seed_origin_revision": plan["seed_origin_revision"],
                "watch_config_revision": plan["watch_config_revision"],
                "state_file_count": len(plan["state_files"]),
                "plan_sha256": plan["plan_sha256"],
            }
        else:
            expected, _plan_raw = _read_object(plan_path, "catalog transition plan", private=True)
            result = apply_plan(expected, prior, target, root, loaded_config)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        print("catalog transition blocked: current catalogs, Stockbit config, plan, or source state failed validation", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
