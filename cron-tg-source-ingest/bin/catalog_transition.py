"""Preview and apply the reviewed, future-only Telegram News cursor cutover."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from adapter import IntakeBlocked, LegacySeedBlocked, plan_market_news_catalog_transition


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} is not readable JSON") from error
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _write_new_private_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".catalog-plan-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ValueError("plan file already exists; use a new path") from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _not_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--prior-catalog", type=Path, required=True, help="effective catalog snapshot before activation")
    parser.add_argument("--target-catalog", type=Path, required=True, help="effective catalog snapshot after activation")
    parser.add_argument("--legacy-news-state", type=Path, required=True, help="fresh, checksummed legacy Market News state snapshot")
    parser.add_argument("--state-root", type=Path, required=True, help="Telegram source-ingest private state root")
    parser.add_argument("--plan-file", type=Path, required=True, help="private preview plan path, outside the state root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    state_root = args.state_root.expanduser().resolve()
    plan_file = args.plan_file.expanduser().resolve()
    if not _not_under(plan_file, state_root):
        print("catalog transition plan must be stored outside the source state root", file=sys.stderr)
        return 2
    try:
        prior = _load_object(args.prior_catalog, "prior effective catalog")
        target = _load_object(args.target_catalog, "target effective catalog")
        if args.action == "preview":
            plan = plan_market_news_catalog_transition(prior, target, args.legacy_news_state, state_root)
            _write_new_private_json(plan_file, plan)
            raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            print(json.dumps({
                "status": "preview",
                "from_revision": plan["from_revision"],
                "to_revision": plan["to_revision"],
                "endpoints": [seed["endpoint"]["endpoint_id"] for seed in plan["seeds"]],
                "plan_sha256": hashlib.sha256(raw).hexdigest(),
                "plan_file": str(plan_file),
            }, sort_keys=True))
            return 0
        expected = _load_object(plan_file, "catalog transition plan")
        result = plan_market_news_catalog_transition(
            prior,
            target,
            args.legacy_news_state,
            state_root,
            apply=True,
            expected_plan=expected,
        )
        print(json.dumps({
            "status": result["status"],
            "from_revision": result["from_revision"],
            "to_revision": result["to_revision"],
            "endpoints": [seed["endpoint"]["endpoint_id"] for seed in result["seeds"]],
        }, sort_keys=True))
        return 0
    except (IntakeBlocked, LegacySeedBlocked, OSError, ValueError) as error:
        print(f"catalog transition blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
