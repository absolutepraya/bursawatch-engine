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
from legacy_cursor_seed import LegacySeedBlocked, plan_catalog_revision_transition
from source_ingest import IntakeBlocked
from adapter import endpoints
from config import load_watch_config

APPLY_ENV = "BURSAWATCH_X_CATALOG_TRANSITION_ALLOW_APPLY"
REVIEWED_PROJECTION_SHA256 = "877e8fce0e374dc2c94fa28e0e374dc2c94fa28e0e374dc2c94fa28e0e374dc3"
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


def _projection(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        config_path = ROOT / "cron-x-account-watch/config/watches.json"
        if not config_path.is_file():
            config_path = Path.home() / ".agents/skills/bursawatch-x-account-watch/config/watches.json"
        profiles = tuple(p for p in load_watch_config(config_path).profiles if p.enabled)
        selected, _ = endpoints(snapshot, profiles)
    except (IntakeBlocked, OSError, ValueError, KeyError, TypeError) as error:
        raise TransitionBlocked("catalog does not match reviewed enabled X profiles") from error
    if len(selected) != 8:
        raise TransitionBlocked("reviewed X projection must contain exactly eight enabled profiles")
    rows = [row for row in snapshot.get("subscriptions", []) if type(row) is dict and row.get("platform") == "x" and row.get("enabled") is True]
    rows.sort(key=lambda row: (row.get("endpoint_id", ""), row.get("capability_id", "")))
    return rows


def _transition_plan(prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    root = _state_root(root)
    if type(prior.get("revision")) is not int or type(target.get("revision")) is not int or target["revision"] != prior["revision"] + 1:
        raise TransitionBlocked("X transition requires adjacent catalog revisions")
    prior_projection, target_projection = _projection(prior), _projection(target)
    raw = _canonical(prior_projection)
    if raw != _canonical(target_projection) or _sha(raw) != REVIEWED_PROJECTION_SHA256:
        raise TransitionBlocked("enabled X projection differs from the reviewed revision 7 to 8 proof")
    if (prior["revision"], target["revision"]) != (7, 8):
        raise TransitionBlocked("this package release owns only the reviewed X 7 to 8 edge")
    metadata = {
        "transition_type": TRANSITION_TYPE,
        "projection_sha256": REVIEWED_PROJECTION_SHA256,
        "prior_catalog_sha256": _sha(_canonical(prior)),
        "target_catalog_sha256": _sha(_canonical(target)),
        "reason": "The complete enabled X projection is unchanged across catalog revisions 7 and 8.",
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


def _require_x_transition_chain(root: Path, revision: int) -> None:
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
    if entries != expected:
        raise IntakeBlocked("X catalog transition history has a gap or unexpected entry")
    edges = (("5-to-7.json", 5, 7),) if revision == 7 else (("5-to-7.json", 5, 7), ("7-to-8.json", 7, 8))
    for name, source, target in edges:
        path = directory / name
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise IntakeBlocked("X catalog transition journal is unsafe")
        try:
            journal = json.loads(path.read_text())
            plan = journal["plan"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise IntakeBlocked("X catalog transition journal is invalid") from error
        if (type(journal) is not dict or set(journal) != {"version", "status", "plan", "seeded_endpoints"}
            or type(journal.get("version")) is not int or journal.get("version") != 1 or journal.get("status") != "complete"
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
                or set(metadata) != {"transition_type", "projection_sha256", "prior_catalog_sha256", "target_catalog_sha256", "reason"}
                or metadata.get("projection_sha256") != REVIEWED_PROJECTION_SHA256
                or any(type(metadata.get(key)) is not str or re.fullmatch(r"[0-9a-f]{64}", metadata[key]) is None
                       for key in ("prior_catalog_sha256", "target_catalog_sha256"))
                or type(metadata.get("reason")) is not str or len(metadata["reason"]) < 20):
                raise IntakeBlocked("X 7 to 8 journal does not prove the reviewed projection")


def require_catalog_revision(root: Path, revision: int, bind: Any) -> None:
    root = Path(root).expanduser()
    marker = root / "catalog-revision.json"
    if marker.is_symlink():
        raise IntakeBlocked("source catalog revision record cannot be a symlink")
    if not marker.exists():
        if revision > 7:
            raise IntakeBlocked("new X source state cannot start from an unjournaled catalog revision")
        bind(root, revision)
        return
    try:
        record = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("source catalog revision record is unavailable") from error
    if type(record) is not dict or type(record.get("revision")) is not int or record["revision"] != revision:
        raise IntakeBlocked("source catalog revision requires a package-owned transition")
    _require_x_transition_chain(root, revision)


def preview(prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    return _transition_plan(prior, target, root)


def apply(expected: dict[str, Any], prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
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
            output = {"status": "preview", "from_revision": 7, "to_revision": 8, "projection_sha256": REVIEWED_PROJECTION_SHA256}
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
