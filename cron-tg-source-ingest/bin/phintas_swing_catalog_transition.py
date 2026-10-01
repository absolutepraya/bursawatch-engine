"""Preview and apply the exact Phintas Swing catalog move without cursor changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from adapter import LegacySeedBlocked, plan_phintas_swing_catalog_transition


def _require_private_parent(path: Path) -> Path:
    parent = Path(os.path.abspath(path.expanduser().parent))
    if parent != parent.resolve():
        raise ValueError("plan directory cannot traverse a symlink")
    parent_info = parent.stat()
    if (not parent.is_dir() or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077):
        raise ValueError("plan directory must be private")
    return parent


def _load_object(path: Path, label: str, *, private: bool = False) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    if private and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError(f"{label} must have mode 0600")
    if private:
        _require_private_parent(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} is not readable JSON") from error
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _write_new_private_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError("plan file cannot be a symlink")
    parent = Path(os.path.abspath(path.parent))
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _require_private_parent(path)
    fd, temporary = tempfile.mkstemp(prefix=".phintas-plan-", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ValueError("plan file already exists; choose a new path") from error
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--prior-catalog", type=Path, required=True)
    parser.add_argument("--target-catalog", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True, help="private preview plan outside the source state root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.state_root.expanduser()
    plan_path = args.plan_file.expanduser()
    if root.is_symlink() or plan_path.is_symlink():
        print("source state root and plan file cannot be symlinks", file=sys.stderr)
        return 2
    try:
        resolved_root = root.resolve(strict=True)
        resolved_plan = plan_path.resolve()
        resolved_plan.relative_to(resolved_root)
    except ValueError:
        pass
    except OSError:
        print("source state root is unavailable", file=sys.stderr)
        return 2
    else:
        print("catalog transition plan must be outside the source state root", file=sys.stderr)
        return 2
    try:
        prior = _load_object(args.prior_catalog, "prior effective catalog")
        target = _load_object(args.target_catalog, "target effective catalog")
        if args.action == "preview":
            plan = plan_phintas_swing_catalog_transition(prior, target, root)
            _write_new_private_json(plan_path, plan)
            raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            print(json.dumps({
                "status": "preview",
                "from_revision": plan["from_revision"],
                "to_revision": plan["to_revision"],
                "preserved_cursor": plan["metadata"]["preserved_cursor"],
                "preserved_state_file_count": len(plan["state_files"]),
                "plan_sha256": hashlib.sha256(raw).hexdigest(),
                "plan_file": str(plan_path.resolve()),
            }, sort_keys=True))
            return 0
        expected = _load_object(plan_path, "catalog transition plan", private=True)
        result = plan_phintas_swing_catalog_transition(
            prior, target, root, apply=True, expected_plan=expected,
        )
        print(json.dumps({
            "status": result["status"],
            "from_revision": result["from_revision"],
            "to_revision": result["to_revision"],
            "preserved_cursor": result["metadata"]["preserved_cursor"],
            "preserved_state_file_count": len(result["state_files"]),
        }, sort_keys=True))
        return 0
    except (LegacySeedBlocked, OSError, TypeError, ValueError) as error:
        print(f"Phintas swing catalog transition blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
