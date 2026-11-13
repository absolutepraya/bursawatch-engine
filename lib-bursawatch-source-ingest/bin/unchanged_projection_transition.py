#!/usr/bin/env python3
"""Advance a source state root across one adjacent catalog revision, only when it is a no-op for it.

An ingest whose state root records a catalog revision fails closed when the catalog moves on. When
the revision changed only other platforms' subscriptions, the reviewed fact for this root is that its
own platform projection (every effective row of that platform) and the selected securities are
byte-identical across the two revisions. This tool proves exactly that, then uses the shared
source-state planner for a revision-only transition: it fingerprints the state, writes a private
journal, and advances the marker last. It never seeds, rewrites or reads cursor contents.

    unchanged_projection_transition.py preview|apply --platform rss \
        --prior-catalog prior.json --target-catalog target.json \
        --state-root ROOT --plan-file PLAN

Apply needs the unchanged preview plan and BURSAWATCH_UNCHANGED_PROJECTION_TRANSITION_ALLOW_APPLY=1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from legacy_cursor_seed import LegacySeedBlocked, plan_catalog_revision_transition

APPLY_ENV = "BURSAWATCH_UNCHANGED_PROJECTION_TRANSITION_ALLOW_APPLY"
TRANSITION_TYPE = "unchanged-platform-projection-transition"
PLATFORMS = ("telegram", "x", "instagram", "whatsapp", "rss")


class TransitionBlocked(RuntimeError):
    """The catalogs or source state do not prove a safe no-op transition."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise TransitionBlocked("catalog input is not canonical JSON") from error


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _projection(snapshot: Any, platform: str, label: str) -> list[dict[str, Any]]:
    if type(snapshot) is not dict or type(snapshot.get("revision")) is not int or type(snapshot.get("subscriptions")) is not list:
        raise TransitionBlocked(f"{label} effective catalog is invalid")
    rows = [row for row in snapshot["subscriptions"] if type(row) is dict and row.get("platform") == platform]
    if not rows or any(type(row.get("endpoint_id")) is not str or type(row.get("capability_id")) is not str for row in rows):
        raise TransitionBlocked(f"{label} catalog has no valid {platform} rows")
    rows.sort(key=lambda row: (row["endpoint_id"], row["capability_id"]))
    return rows


def _state_root(value: Path) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise TransitionBlocked("source state root cannot be a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise TransitionBlocked("source state root is unavailable") from error
    if not resolved.is_dir() or stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise TransitionBlocked("source state root must be a private directory")
    return resolved


def build_plan(platform: str, prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise TransitionBlocked("platform is not supported")
    root = _state_root(root)
    prior_rows, target_rows = _projection(prior, platform, "prior"), _projection(target, platform, "target")
    if target["revision"] != prior["revision"] + 1:
        raise TransitionBlocked("transition requires one adjacent catalog revision")
    if prior.get("selected_securities") != target.get("selected_securities"):
        raise TransitionBlocked("selected securities changed across catalog revisions")
    prior_raw, target_raw = _canonical(prior_rows), _canonical(target_rows)
    if prior_raw != target_raw:
        raise TransitionBlocked(f"effective {platform} projection changed across catalog revisions")
    metadata = {
        "transition_type": TRANSITION_TYPE,
        "platform": platform,
        "projection_sha256": _sha(prior_raw),
        "prior_catalog_sha256": _sha(_canonical(prior)),
        "target_catalog_sha256": _sha(_canonical(target)),
        "reason": f"The complete effective {platform} subscription projection is unchanged across catalog revisions "
                  f"{prior['revision']} and {target['revision']}.",
    }
    try:
        state_plan = plan_catalog_revision_transition(
            state_root=root, from_revision=prior["revision"], to_revision=target["revision"], seeds=[],
            metadata=metadata, allow_empty_seeds=True, apply_guard_env=APPLY_ENV,
        )
    except LegacySeedBlocked as error:
        raise TransitionBlocked("shared source-state planner rejected the transition") from error
    return {"version": 1, "platform": platform, "from_revision": prior["revision"], "to_revision": target["revision"],
            "projection_sha256": metadata["projection_sha256"], "state_plan": state_plan}


def apply_plan(expected: dict[str, Any], platform: str, prior: dict[str, Any], target: dict[str, Any], root: Path) -> dict[str, Any]:
    current = build_plan(platform, prior, target, root)
    if expected != current:
        raise TransitionBlocked("catalogs, source state, or preview changed")
    plan = current["state_plan"]
    try:
        plan_catalog_revision_transition(
            state_root=Path(plan["state_root"]), from_revision=current["from_revision"], to_revision=current["to_revision"],
            seeds=[], metadata=plan["metadata"], allow_empty_seeds=True, apply=True, expected_plan=plan, apply_guard_env=APPLY_ENV,
        )
    except LegacySeedBlocked as error:
        raise TransitionBlocked("shared source-state apply guard or planner rejected the transition") from error
    return {"status": "applied", "platform": platform, "from_revision": current["from_revision"],
            "to_revision": current["to_revision"], "projection_sha256": current["projection_sha256"]}


def _load_object(path: Path, label: str, *, private: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise TransitionBlocked(f"{label} is not a regular file")
    if private and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise TransitionBlocked(f"{label} must have mode 0600")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TransitionBlocked(f"{label} is not readable JSON") from error
    if type(value) is not dict:
        raise TransitionBlocked(f"{label} must be a JSON object")
    return value


def _write_new_private_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise TransitionBlocked("plan file cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".catalog-plan-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--prior-catalog", type=Path, required=True)
    parser.add_argument("--target-catalog", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True, help="private plan outside the source state root")
    args = parser.parse_args(argv)
    try:
        root = _state_root(args.state_root)
        plan_path = Path(os.path.abspath(args.plan_file.expanduser()))
        if plan_path.is_symlink() or any(parent.is_symlink() for parent in plan_path.parents):
            raise TransitionBlocked("plan path cannot traverse a symlink")
        try:
            plan_path.resolve().relative_to(root)
        except ValueError:
            pass
        else:
            raise TransitionBlocked("plan file must be outside the source state root")
        prior, target = _load_object(args.prior_catalog, "prior catalog"), _load_object(args.target_catalog, "target catalog")
        if args.action == "preview":
            plan = build_plan(args.platform, prior, target, root)
            _write_new_private_json(plan_path, plan)
            output = {"status": "preview", "platform": args.platform, "from_revision": plan["from_revision"],
                      "to_revision": plan["to_revision"], "projection_sha256": plan["projection_sha256"]}
        else:
            output = apply_plan(_load_object(plan_path, "plan", private=True), args.platform, prior, target, root)
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except (TransitionBlocked, LegacySeedBlocked, OSError, ValueError, KeyError, TypeError) as error:
        print(f"catalog transition blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
