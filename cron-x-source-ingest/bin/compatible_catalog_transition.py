"""Preview and apply the reviewed cursor-preserving X catalog edge."""
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
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for local, installed in (("lib-bursawatch-control", "lib-bursawatch-control"), ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot")):
    candidate = ROOT / local / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / installed / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-x-account-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-x-account-watch" / "bin"
sys.path.insert(0, str(owner))
from legacy_cursor_seed import LegacySeedBlocked, _state_file_hashes, _write_private_json, plan_catalog_revision_transition
from source_ingest import IntakeBlocked
from adapter import endpoints
from config import load_watch_config_for_run

APPLY_ENV = "BURSAWATCH_X_CATALOG_TRANSITION_ALLOW_APPLY"
REVIEWED_PROJECTION_SHA256 = "877e8fce0e374dc2c94e876455d10087298ff837071d82c19d059e0450bef3d3"
# Revision 9 is revision 8 plus exactly the three route rows of the reviewed Serenity endpoint.
REVIEWED_PROJECTION_SHA256_REV9 = "f33381a2d0e452493d6c2f18ec63ce27b1433991abc247758b4e53db7c7f9a48"
GENERATION_ADDED_ENDPOINT = "x:aleabitoreddit"
GENERATION_JOURNAL = "generation-8-to-9.json"
GENERATION_REVISIONS = (8, 9)
TRANSITION_TYPE = "x-compatible-catalog-transition"


class TransitionBlocked(RuntimeError):
    """Catalog or source state failed the reviewed X transition proof."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise TransitionBlocked("catalog input is not canonical JSON") from error


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _state_root(value: Path) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise TransitionBlocked("X source state root cannot be a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise TransitionBlocked("X source state root is unavailable") from error
    if not resolved.is_dir():
        raise TransitionBlocked("X source state root is not a directory")
    return resolved


def _reviewed_projection(revision: int) -> str | None:
    return {8: REVIEWED_PROJECTION_SHA256, 9: REVIEWED_PROJECTION_SHA256_REV9}.get(revision)


def _projection(snapshot: dict[str, Any], profiles: tuple[Any, ...], allowed_selected: tuple[int, ...] = (8,)) -> list[dict[str, Any]]:
    try:
        selected, _ = endpoints(snapshot, tuple(p for p in profiles if p.enabled))
    except (IntakeBlocked, OSError, ValueError, KeyError, TypeError) as error:
        raise TransitionBlocked("catalog does not match reviewed enabled X profiles") from error
    if len(selected) not in allowed_selected:
        raise TransitionBlocked("reviewed X projection has an unreviewed number of enabled profiles")
    rows = [row for row in snapshot.get("subscriptions", []) if type(row) is dict and row.get("platform") == "x"]
    rows.sort(key=lambda row: (row.get("endpoint_id", ""), row.get("capability_id", "")))
    return rows


def _transition_plan(prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    root = _state_root(root)
    try:
        _require_x_transition_chain(root, 7, allow_in_progress_edge=True)
    except IntakeBlocked as error:
        raise TransitionBlocked("existing X catalog transition history is incomplete or unsafe") from error
    if type(prior.get("revision")) is not int or type(target.get("revision")) is not int or target["revision"] != prior["revision"] + 1:
        raise TransitionBlocked("X transition requires adjacent catalog revisions")
    try:
        loaded = load_watch_config_for_run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TransitionBlocked("current X watcher configuration is unavailable") from error
    watcher_revision = getattr(loaded, "revision", None)
    watcher_config = getattr(loaded, "config", None)
    profiles = getattr(watcher_config, "profiles", None)
    if type(watcher_revision) is not int or watcher_revision < 1 or type(profiles) not in {tuple, list}:
        raise TransitionBlocked("current X watcher config revision or profiles are invalid")
    prior_projection, target_projection = _projection(prior, tuple(profiles)), _projection(target, tuple(profiles))
    raw = _canonical(prior_projection)
    if raw != _canonical(target_projection) or _sha(raw) != REVIEWED_PROJECTION_SHA256:
        raise TransitionBlocked("full effective X projection differs from the reviewed revision 7 to 8 proof")
    if (prior["revision"], target["revision"]) != (7, 8):
        raise TransitionBlocked("this package release owns only the reviewed X 7 to 8 edge")
    metadata = {
        "transition_type": TRANSITION_TYPE,
        "projection_sha256": REVIEWED_PROJECTION_SHA256,
        "prior_catalog_sha256": _sha(_canonical(prior)),
        "target_catalog_sha256": _sha(_canonical(target)),
        "watch_config_revision": watcher_revision,
        "reason": "The complete effective X subscription projection is unchanged across catalog revisions 7 and 8.",
    }
    try:
        state_plan = plan_catalog_revision_transition(
            state_root=root, from_revision=7, to_revision=8, seeds=[], metadata=metadata,
            allow_empty_seeds=True, apply_guard_env=APPLY_ENV,
        )
    except LegacySeedBlocked as error:
        raise TransitionBlocked("shared source-state planner rejected X transition") from error
    return {"version": 1, "from_revision": 7, "to_revision": 8, "projection_sha256": REVIEWED_PROJECTION_SHA256,
            "prior_catalog_sha256": metadata["prior_catalog_sha256"], "target_catalog_sha256": metadata["target_catalog_sha256"],
            "state_plan": state_plan}


def _require_x_transition_chain(root: Path, revision: int, *, allow_in_progress_edge: bool = False) -> None:
    """Require the deployed 5→7 history and the package-owned 7→8 proof."""
    if type(revision) is not int or revision < 1:
        raise IntakeBlocked("X catalog revision is invalid")
    if revision < 7:
        return
    if revision > 8:
        raise IntakeBlocked("X catalog revision has no reviewed package transition")
    root = _state_root(root)
    directory = root / "catalog-transitions"
    expected = {"5-to-7.json"} if revision == 7 else {"5-to-7.json", "7-to-8.json"}
    if directory.is_symlink() or not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise IntakeBlocked("X catalog transition directory is unsafe")
    entries = {p.name for p in directory.iterdir() if not p.name.startswith(".catalog-transition-")}
    allowed_entries = expected | ({"7-to-8.json"} if revision == 7 and allow_in_progress_edge else set())
    if entries - allowed_entries or expected - entries:
        raise IntakeBlocked("X catalog transition history has a gap or unexpected entry")
    edges = [("5-to-7.json", 5, 7, False)] if revision == 7 else [("5-to-7.json", 5, 7, False), ("7-to-8.json", 7, 8, False)]
    if revision == 7 and allow_in_progress_edge and "7-to-8.json" in entries:
        edges.append(("7-to-8.json", 7, 8, True))
    for name, source, target, pending in edges:
        path = directory / name
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise IntakeBlocked("X catalog transition journal is unsafe")
        try:
            journal = json.loads(path.read_text())
            plan = journal["plan"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise IntakeBlocked("X catalog transition journal is invalid") from error
        if (type(journal) is not dict or set(journal) != {"version", "status", "plan", "seeded_endpoints"}
            or type(journal.get("version")) is not int or journal.get("version") != 1
            or journal.get("status") not in ({"applying", "complete"} if pending else {"complete"})
            or journal.get("seeded_endpoints") != [] or type(plan) is not dict
            or set(plan) != {"version", "status", "apply", "state_root", "transition_path", "from_revision", "to_revision", "state_files", "seeds", "metadata", "revision_only"}
            or plan.get("version") != 1 or plan.get("status") != "preview"
            or plan.get("state_root") != str(root.resolve())
            or plan.get("transition_path") != str(path)
            or plan.get("from_revision") != source or plan.get("to_revision") != target
            or plan.get("revision_only") is not True or plan.get("seeds") != [] or plan.get("apply") is not False
            or type(plan.get("state_files")) is not dict
            or any(type(key) is not str or Path(key).is_absolute() or ".." in Path(key).parts
                   or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                   for key, digest in plan["state_files"].items())):
            raise IntakeBlocked("X catalog transition journal does not prove a completed revision-only edge")
        if source == 7:
            metadata = plan.get("metadata")
            if (type(metadata) is not dict or metadata.get("transition_type") != TRANSITION_TYPE
                or set(metadata) != {"transition_type", "projection_sha256", "prior_catalog_sha256", "target_catalog_sha256", "watch_config_revision", "reason"}
                or metadata.get("projection_sha256") != REVIEWED_PROJECTION_SHA256
                or any(type(metadata.get(key)) is not str or re.fullmatch(r"[0-9a-f]{64}", metadata[key]) is None
                       for key in ("prior_catalog_sha256", "target_catalog_sha256"))
                or type(metadata.get("watch_config_revision")) is not int or metadata["watch_config_revision"] < 1
                or type(metadata.get("reason")) is not str or len(metadata["reason"]) < 20):
                raise IntakeBlocked("X 7 to 8 journal does not prove the reviewed projection")


def _fresh_generation_record(revision: int, snapshot: dict[str, Any] | None, profiles: tuple[Any, ...]) -> dict[str, Any]:
    if revision not in GENERATION_REVISIONS or type(snapshot) is not dict or snapshot.get("revision") != revision:
        raise IntakeBlocked("X generation requires a reviewed catalog revision")
    try:
        digest = _sha(_canonical(_projection(snapshot, profiles, (8,) if revision == 8 else (9,))))
    except (TransitionBlocked, TypeError, ValueError, KeyError) as error:
        raise IntakeBlocked("fresh X generation projection is unavailable") from error
    if digest != _reviewed_projection(revision):
        raise IntakeBlocked("fresh X generation projection differs from the reviewed catalog")
    return {"revision": revision, "generation": {"version": 1, "mode": "future_only", "projection_sha256": digest}}


def _write_fresh_generation_marker(root: Path, record: dict[str, Any]) -> None:
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Stage beside the root. A hard crash must not leave an orphan inside the
    # empty generation and prevent its next natural bootstrap.
    fd, temporary = tempfile.mkstemp(prefix=".x-generation-", dir=root.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(record))
            stream.flush()
            os.fsync(stream.fileno())
        root.mkdir(mode=0o700, exist_ok=True)
        os.link(temporary, root / "catalog-revision.json")
        for directory in (root, root.parent):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_catalog_revision(root: Path, revision: int, bind: Any, *, snapshot: dict[str, Any] | None = None, profiles: tuple[Any, ...] = ()) -> None:
    root = Path(root).expanduser()
    if root.is_symlink():
        raise IntakeBlocked("X source state root cannot be a symlink")
    marker = root / "catalog-revision.json"
    if marker.is_symlink():
        raise IntakeBlocked("source catalog revision record cannot be a symlink")
    if not marker.exists():
        if revision > 7:
            record = _fresh_generation_record(revision, snapshot, profiles)
            if root.exists() and (not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700 or any(root.iterdir())):
                raise IntakeBlocked("fresh X generation requires an empty private state root")
            # A new generation has no historical cursor transitions. Freeze its
            # reviewed starting projection atomically before provider bootstrap.
            _write_fresh_generation_marker(root, record)
            return
        bind(root, revision)
        return
    try:
        record = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("source catalog revision record is unavailable") from error
    if type(record) is not dict or type(record.get("revision")) is not int or record["revision"] != revision:
        raise IntakeBlocked("source catalog revision requires a package-owned transition")
    if "generation" in record:
        transitions = root / "catalog-transitions"
        if (record != _fresh_generation_record(revision, snapshot, profiles)
            or stat.S_IMODE(root.stat().st_mode) != 0o700 or stat.S_IMODE(marker.stat().st_mode) != 0o600):
            raise IntakeBlocked("fresh X generation record is invalid")
        if revision == 9 and (transitions.exists() or transitions.is_symlink()):
            _require_generation_journal(root, record)
        elif transitions.exists() or transitions.is_symlink():
            raise IntakeBlocked("fresh X generation record is invalid")
        return
    _require_x_transition_chain(root, revision)


def _load_profiles() -> tuple[int, tuple[Any, ...]]:
    try:
        loaded = load_watch_config_for_run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TransitionBlocked("current X watcher configuration is unavailable") from error
    watcher_revision = getattr(loaded, "revision", None)
    profiles = getattr(getattr(loaded, "config", None), "profiles", None)
    if type(watcher_revision) is not int or watcher_revision < 1 or type(profiles) not in {tuple, list}:
        raise TransitionBlocked("current X watcher config revision or profiles are invalid")
    return watcher_revision, tuple(profiles)


def _with_serenity(profiles: tuple[Any, ...], enabled: bool) -> tuple[Any, ...]:
    """The edge is reviewed for Serenity off before it and on after it, whatever the live profile says now."""
    from dataclasses import replace
    matches = [p for p in profiles if getattr(p, "id", None) == "aleabitoreddit"]
    if len(matches) != 1:
        raise TransitionBlocked("the reviewed Serenity profile must exist exactly once in the watcher configuration")
    return tuple(replace(p, enabled=enabled) if p.id == "aleabitoreddit" else p for p in profiles)


def _is_generation_root(root: Path) -> bool:
    try:
        record = json.loads((Path(root).expanduser() / "catalog-revision.json").read_text())
    except (OSError, ValueError):
        return False
    return type(record) is dict and "generation" in record


def _require_generation_journal(root: Path, record: dict[str, Any]) -> None:
    """Require the one completed reviewed 8 to 9 edge behind a transitioned generation."""
    directory = root / "catalog-transitions"
    if directory.is_symlink() or not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise IntakeBlocked("X generation transition directory is unsafe")
    entries = {p.name for p in directory.iterdir() if not p.name.startswith(".catalog-transition-")}
    if entries != {GENERATION_JOURNAL}:
        raise IntakeBlocked("X generation transition history has a gap or unexpected entry")
    path = directory / GENERATION_JOURNAL
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise IntakeBlocked("X generation transition journal is unsafe")
    try:
        journal = json.loads(path.read_text())
        plan = journal["plan"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IntakeBlocked("X generation transition journal is invalid") from error
    plan_keys = {"version", "status", "apply", "state_root", "from_revision", "to_revision", "prior_marker_sha256", "target_marker",
                 "projection_sha256", "added_endpoint", "prior_catalog_sha256", "target_catalog_sha256", "watch_config_revision",
                 "state_files", "reason"}
    if (type(journal) is not dict or set(journal) != {"version", "status", "plan"} or journal.get("version") != 1
        or journal.get("status") != "complete" or type(plan) is not dict or set(plan) != plan_keys
        or plan.get("version") != 1 or plan.get("status") != "preview" or plan.get("apply") is not False
        or plan.get("state_root") != str(root.resolve()) or (plan.get("from_revision"), plan.get("to_revision")) != (8, 9)
        or plan.get("projection_sha256") != {"prior": REVIEWED_PROJECTION_SHA256, "target": REVIEWED_PROJECTION_SHA256_REV9}
        or plan.get("added_endpoint") != GENERATION_ADDED_ENDPOINT or plan.get("target_marker") != record
        or any(type(plan.get(key)) is not str or re.fullmatch(r"[0-9a-f]{64}", plan[key]) is None
               for key in ("prior_marker_sha256", "prior_catalog_sha256", "target_catalog_sha256"))
        or type(plan.get("watch_config_revision")) is not int or type(plan.get("state_files")) is not dict):
        raise IntakeBlocked("X generation transition journal does not prove the reviewed 8 to 9 edge")


def _generation_plan(prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    """Plan the reviewed X generation edge: revision 8 plus exactly the Serenity route rows."""
    root = _state_root(root)
    if type(prior.get("revision")) is not int or type(target.get("revision")) is not int or (prior["revision"], target["revision"]) != (8, 9):
        raise TransitionBlocked("this package release owns only the reviewed X generation 8 to 9 edge")
    watcher_revision, live_profiles = _load_profiles()
    prior_profiles, target_profiles = _with_serenity(live_profiles, False), _with_serenity(live_profiles, True)
    try:
        prior_record = _fresh_generation_record(8, prior, prior_profiles)
        target_record = _fresh_generation_record(9, target, target_profiles)
        prior_rows, target_rows = _projection(prior, prior_profiles, (8,)), _projection(target, target_profiles, (9,))
    except (IntakeBlocked, TransitionBlocked) as error:
        raise TransitionBlocked("catalog projections differ from the reviewed X generation edge") from error
    added = [row for row in target_rows if row not in prior_rows]
    if (any(row not in target_rows for row in prior_rows) or len(added) != 3
        or {row.get("endpoint_id") for row in added} != {GENERATION_ADDED_ENDPOINT}):
        raise TransitionBlocked("catalog change is not exactly the reviewed Serenity route rows")
    marker = root / "catalog-revision.json"
    transitions = root / "catalog-transitions"
    journal_path = transitions / GENERATION_JOURNAL
    try:
        current = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise TransitionBlocked("X generation marker is unavailable") from error
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or stat.S_IMODE(marker.stat().st_mode) != 0o600:
        raise TransitionBlocked("X generation state root or marker is not private")
    journal_present = journal_path.exists() or transitions.is_symlink()
    if transitions.exists() or transitions.is_symlink():
        if (transitions.is_symlink() or not transitions.is_dir() or stat.S_IMODE(transitions.stat().st_mode) & 0o077
            or {p.name for p in transitions.iterdir() if not p.name.startswith(".catalog-transition-")} - {GENERATION_JOURNAL}):
            raise TransitionBlocked("X generation transition directory is unsafe")
    if current != prior_record and not (current == target_record and journal_present):
        raise TransitionBlocked("X generation state is not at the reviewed prior revision")
    try:
        state_files = _state_file_hashes(root, {marker, journal_path})
    except LegacySeedBlocked as error:
        raise TransitionBlocked("X source state cannot be hashed safely") from error
    return {
        "version": 1, "status": "preview", "apply": False, "state_root": str(root), "from_revision": 8, "to_revision": 9,
        "prior_marker_sha256": _sha(_canonical(prior_record)), "target_marker": target_record,
        "projection_sha256": {"prior": REVIEWED_PROJECTION_SHA256, "target": REVIEWED_PROJECTION_SHA256_REV9},
        "added_endpoint": GENERATION_ADDED_ENDPOINT, "prior_catalog_sha256": _sha(_canonical(prior)),
        "target_catalog_sha256": _sha(_canonical(target)), "watch_config_revision": watcher_revision,
        "state_files": state_files,
        "reason": "Catalog revision 9 adds exactly the three route rows of the reviewed Serenity endpoint to the revision 8 X projection.",
    }


def _generation_apply(expected: dict[str, Any], prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    current = _generation_plan(prior, target, root)
    if expected != current:
        raise TransitionBlocked("catalog, source state, or preview changed")
    if os.environ.get(APPLY_ENV) != "1":
        raise TransitionBlocked(f"apply requires {APPLY_ENV}=1")
    root = _state_root(root)
    marker = root / "catalog-revision.json"
    journal_path = root / "catalog-transitions" / GENERATION_JOURNAL
    if journal_path.exists():
        try:
            existing = json.loads(journal_path.read_text())
        except (OSError, ValueError) as error:
            raise TransitionBlocked("X generation journal is unreadable") from error
        if type(existing) is not dict or existing.get("plan") != current or existing.get("status") not in {"applying", "complete"}:
            raise TransitionBlocked("X generation journal differs from the reviewed plan")
    else:
        _write_private_json(journal_path, {"version": 1, "status": "applying", "plan": current})
    if json.loads(marker.read_text()) != current["target_marker"]:
        _write_private_json(marker, current["target_marker"])
    _write_private_json(journal_path, {"version": 1, "status": "complete", "plan": current})
    return {"status": "applied", "from_revision": 8, "to_revision": 9, "projection_sha256": REVIEWED_PROJECTION_SHA256_REV9}


def preview(prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    if _is_generation_root(root):
        return _generation_plan(prior, target, root)
    return _transition_plan(prior, target, root)


def apply(expected: dict[str, Any], prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    if _is_generation_root(root):
        return _generation_apply(expected, prior, target, root)
    current = _transition_plan(prior, target, root)
    if expected != current:
        raise TransitionBlocked("catalog, source state, or preview changed")
    plan = current["state_plan"]
    try:
        plan_catalog_revision_transition(
            state_root=Path(plan["state_root"]), from_revision=7, to_revision=8, seeds=[],
            metadata=plan["metadata"], allow_empty_seeds=True, apply=True,
            expected_plan=plan, apply_guard_env=APPLY_ENV,
        )
    except LegacySeedBlocked as error:
        raise TransitionBlocked("shared source-state apply guard or planner rejected X transition") from error
    return {"status": "applied", "from_revision": 7, "to_revision": 8, "projection_sha256": REVIEWED_PROJECTION_SHA256}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--prior-catalog", type=Path, required=True)
    parser.add_argument("--target-catalog", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = _state_root(args.state_root)
        plan_path = Path(args.plan_file).expanduser()
        if plan_path.is_symlink():
            raise TransitionBlocked("X catalog plan cannot be a symlink")
        resolved_plan = plan_path.resolve()
        try:
            resolved_plan.relative_to(root)
        except ValueError:
            pass
        else:
            raise TransitionBlocked("X catalog plan must be outside the source state root")
        original_plan = Path(os.path.abspath(plan_path))
        if any(parent.is_symlink() for parent in (original_plan, *original_plan.parents)):
            raise TransitionBlocked("X catalog plan path cannot traverse a symlink")
        prior, target = json.loads(args.prior_catalog.read_text()), json.loads(args.target_catalog.read_text())
        if args.action == "preview":
            result = preview(prior, target, root)
            resolved_plan.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if stat.S_IMODE(resolved_plan.parent.stat().st_mode) & 0o077:
                raise TransitionBlocked("X catalog plan directory must be private")
            fd, temporary = tempfile.mkstemp(prefix=".x-catalog-plan-", dir=resolved_plan.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as stream:
                    json.dump(result, stream, sort_keys=True, separators=(",", ":"))
                    stream.write("\n")
                os.link(temporary, resolved_plan)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            output = {"status": "preview", "from_revision": result["from_revision"], "to_revision": result["to_revision"],
                      "projection_sha256": result["projection_sha256"]["target"] if type(result["projection_sha256"]) is dict else result["projection_sha256"]}
        else:
            if not resolved_plan.is_file() or stat.S_IMODE(resolved_plan.stat().st_mode) != 0o600:
                raise TransitionBlocked("X catalog plan must be a private regular file")
            expected = json.loads(resolved_plan.read_text())
            output = apply(expected, prior, target, root)
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        print("X catalog transition blocked: catalogs, preview, or source state failed validation", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
