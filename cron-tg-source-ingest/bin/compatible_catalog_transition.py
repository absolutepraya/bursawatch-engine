"""Preview and apply a cursor-preserving Telegram catalog revision transition."""
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

ROOT = Path(__file__).resolve().parents[2]
for local_name, runtime_name in (
    ("lib-bursawatch-control", "lib-bursawatch-control"),
    ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
):
    support_bin = ROOT / local_name / "bin"
    if not support_bin.exists():
        support_bin = Path.home() / ".agents" / "skills" / runtime_name / "bin"
    if support_bin.is_dir() and str(support_bin) not in sys.path:
        sys.path.insert(0, str(support_bin))

from adapter import IntakeBlocked, endpoints


class TransitionBlocked(RuntimeError):
    """Inputs or persisted source state do not prove a safe transition."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_object(path: Path, label: str, *, private: bool = False) -> dict[str, Any]:
    path = path.expanduser()
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
    path = path.expanduser()
    if path.is_symlink():
        raise TransitionBlocked("plan file cannot be a symlink")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise TransitionBlocked("plan directory must be private")
    fd, temporary = tempfile.mkstemp(prefix=".catalog-plan-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise TransitionBlocked("plan file already exists; choose a new path") from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_private_json(path: Path, value: dict[str, Any]) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        os.chmod(path.parent, 0o700)
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise TransitionBlocked("source transition directory must be private and cannot be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".catalog-transition-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _enabled_telegram_projection(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if type(snapshot.get("subscriptions")) is not list:
        raise TransitionBlocked("effective catalog subscriptions are invalid")
    try:
        endpoints(snapshot)
    except (IntakeBlocked, KeyError, TypeError, ValueError) as error:
        raise TransitionBlocked("enabled Telegram catalog rows are not valid for the source pilot") from error
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for row in snapshot["subscriptions"]:
        if type(row) is not dict:
            raise TransitionBlocked("effective catalog subscription is invalid")
        if row.get("platform") != "telegram" or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        capability_id = row.get("capability_id")
        if type(endpoint_id) is not str or type(capability_id) is not str:
            raise TransitionBlocked("enabled Telegram subscription identity is invalid")
        identity = (endpoint_id, capability_id)
        if identity in identities:
            raise TransitionBlocked("effective catalog repeats an enabled Telegram capability")
        identities.add(identity)
        # Compare the entire enabled row so settings, identity, credential reference,
        # dispatch metadata, and provenance cannot drift unnoticed.
        rows.append(row)
    rows.sort(key=lambda row: (row["endpoint_id"], row["capability_id"]))
    return rows


def _state_hashes(root: Path, excluded: set[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        paths = sorted(root.rglob("*"))
    except OSError as error:
        raise TransitionBlocked("source state cannot be inventoried") from error
    for path in paths:
        if path in excluded:
            continue
        if path.is_symlink():
            raise TransitionBlocked("source state contains an unsupported symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise TransitionBlocked("source state contains an unsupported filesystem entry")
        try:
            result[str(path.relative_to(root))] = _sha256(path.read_bytes())
        except OSError as error:
            raise TransitionBlocked("source state could not be fingerprinted") from error
    return result


def _read_revision(path: Path) -> int:
    if path.is_symlink() or not path.is_file():
        raise TransitionBlocked("source catalog revision marker is not a regular file")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TransitionBlocked("source catalog revision marker is unavailable") from error
    if type(record) is not dict or type(record.get("revision")) is not int:
        raise TransitionBlocked("source catalog revision marker is invalid")
    return record["revision"]


def build_plan(prior: dict[str, Any], target: dict[str, Any], state_root: Path, *, allow_target_revision: bool = False) -> dict[str, Any]:
    if state_root.expanduser().is_symlink():
        raise TransitionBlocked("source state root is a symlink")
    root = state_root.expanduser().resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise TransitionBlocked("source state root is invalid")
    from_revision = prior.get("revision")
    to_revision = target.get("revision")
    if type(from_revision) is not int or type(to_revision) is not int or to_revision != from_revision + 1:
        raise TransitionBlocked("compatible transition requires exactly one consecutive catalog revision")
    if (type(prior.get("selected_securities")) is not list
            or any(type(symbol) is not str for symbol in prior["selected_securities"])
            or type(target.get("selected_securities")) is not list
            or any(type(symbol) is not str for symbol in target["selected_securities"])):
        raise TransitionBlocked("effective catalog selected securities are invalid")
    if prior["selected_securities"] != target["selected_securities"]:
        raise TransitionBlocked("selected securities changed across catalog revisions")
    before = _enabled_telegram_projection(prior)
    after = _enabled_telegram_projection(target)
    if before != after:
        raise TransitionBlocked("enabled Telegram subscriptions changed across catalog revisions")

    revision_path = root / "catalog-revision.json"
    transition_path = root / "catalog-transitions" / f"compatible-{from_revision}-to-{to_revision}.json"
    journal_exists = transition_path.exists()
    current_revision = _read_revision(revision_path)
    allowed = {from_revision, to_revision} if allow_target_revision and journal_exists else {from_revision}
    if current_revision not in allowed:
        raise TransitionBlocked("source state is not at the expected prior catalog revision")
    if current_revision == to_revision and not journal_exists:
        raise TransitionBlocked("target revision has no matching transition journal")
    if transition_path.is_symlink():
        raise TransitionBlocked("source transition journal is a symlink")

    cursor_hashes: dict[str, str] = {}
    for endpoint_id in sorted({row["endpoint_id"] for row in after}):
        state_name = endpoint_id.replace(":", "-", 1)
        cursor_path = root / state_name / "cursor.json"
        if cursor_path.is_symlink() or not cursor_path.is_file():
            raise TransitionBlocked(f"enabled Telegram endpoint cursor is missing: {endpoint_id}")
        try:
            cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise TransitionBlocked(f"enabled Telegram endpoint cursor is invalid: {endpoint_id}") from error
        if (type(cursor) is not dict or type(cursor.get("cursor")) is not int or cursor["cursor"] < 0
                or ("bootstrap_cursor" in cursor and (type(cursor["bootstrap_cursor"]) is not int or not 0 <= cursor["bootstrap_cursor"] <= cursor["cursor"]))):
            raise TransitionBlocked(f"enabled Telegram endpoint cursor is invalid: {endpoint_id}")
        relative = str(cursor_path.relative_to(root))
        cursor_hashes[relative] = _sha256(cursor_path.read_bytes())

    state_files = _state_hashes(root, {revision_path, transition_path})
    if any(state_files.get(path) != digest for path, digest in cursor_hashes.items()):
        raise TransitionBlocked("source cursor inventory changed while planning")
    return {
        "version": 1,
        "status": "preview",
        "apply": False,
        "state_root": str(root),
        "transition_path": str(transition_path),
        "from_revision": from_revision,
        "to_revision": to_revision,
        "prior_catalog_sha256": _sha256(_json_bytes(prior)),
        "target_catalog_sha256": _sha256(_json_bytes(target)),
        "selected_securities_sha256": _sha256(_json_bytes(prior["selected_securities"])),
        "enabled_telegram_rows_sha256": _sha256(_json_bytes(after)),
        "enabled_telegram_endpoints": sorted({row["endpoint_id"] for row in after}),
        "cursor_sha256": cursor_hashes,
        "state_files": state_files,
    }


def apply_plan(expected: dict[str, Any], prior: dict[str, Any], target: dict[str, Any], state_root: Path) -> dict[str, Any]:
    if state_root.expanduser().is_symlink():
        raise TransitionBlocked("source state root is a symlink")
    root = state_root.expanduser().resolve(strict=True)
    transition_path = root / "catalog-transitions" / f"compatible-{prior.get('revision')}-to-{target.get('revision')}.json"
    journal_exists = transition_path.exists()
    plan = build_plan(prior, target, root, allow_target_revision=journal_exists)
    if plan != expected:
        raise TransitionBlocked("catalog or source state changed after preview")
    if journal_exists:
        journal = _load_object(transition_path, "source transition journal", private=True)
        if set(journal) != {"version", "status", "plan"} or journal.get("version") != 1 or journal.get("status") not in {"applying", "complete"} or journal.get("plan") != plan:
            raise TransitionBlocked("source transition journal does not match this preview")
    else:
        journal = {"version": 1, "status": "applying", "plan": plan}

    current_revision = _read_revision(root / "catalog-revision.json")
    if current_revision == plan["from_revision"]:
        if os.environ.get("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY") != "1":
            raise TransitionBlocked("apply requires BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY=1")
        if not journal_exists:
            _atomic_private_json(transition_path, journal)
        _atomic_private_json(root / "catalog-revision.json", {"revision": plan["to_revision"]})
        journal["status"] = "complete"
        _atomic_private_json(transition_path, journal)
    elif current_revision == plan["to_revision"] and journal_exists:
        if journal["status"] != "complete":
            if os.environ.get("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY") != "1":
                raise TransitionBlocked("resuming an interrupted apply requires the explicit apply guard")
            journal["status"] = "complete"
            _atomic_private_json(transition_path, journal)
    else:
        raise TransitionBlocked("source catalog revision changed after preview")
    return {"status": "applied", "from_revision": plan["from_revision"], "to_revision": plan["to_revision"], "preserved_cursor_count": len(plan["cursor_sha256"]), "preserved_state_file_count": len(plan["state_files"])}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--prior-catalog", type=Path, required=True)
    parser.add_argument("--target-catalog", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True, help="private plan outside the source state root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    state_root = args.state_root.expanduser()
    if state_root.is_symlink():
        print("source state root cannot be a symlink", file=sys.stderr)
        return 2
    state_root = state_root.resolve()
    if args.plan_file.expanduser().is_symlink():
        print("catalog transition plan cannot be a symlink", file=sys.stderr)
        return 2
    plan_file = args.plan_file.expanduser().resolve()
    try:
        plan_file.relative_to(state_root)
    except ValueError:
        pass
    else:
        print("catalog transition plan must be outside the source state root", file=sys.stderr)
        return 2
    try:
        prior = _load_object(args.prior_catalog, "prior effective catalog")
        target = _load_object(args.target_catalog, "target effective catalog")
        if args.action == "preview":
            plan = build_plan(prior, target, args.state_root.expanduser())
            _write_new_private_json(plan_file, plan)
            print(json.dumps({"status": "preview", "from_revision": plan["from_revision"], "to_revision": plan["to_revision"], "enabled_telegram_endpoints": plan["enabled_telegram_endpoints"], "preserved_cursor_count": len(plan["cursor_sha256"]), "state_file_count": len(plan["state_files"]), "plan_file": str(plan_file), "plan_sha256": _sha256(_json_bytes(plan))}, sort_keys=True))
            return 0
        expected = _load_object(plan_file, "catalog transition plan", private=True)
        result = apply_plan(expected, prior, target, args.state_root.expanduser())
        print(json.dumps(result, sort_keys=True))
        return 0
    except (IntakeBlocked, KeyError, OSError, TypeError, ValueError, TransitionBlocked) as error:
        print(f"catalog transition blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
