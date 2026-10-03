"""Frozen Source Catalog route permissions for watcher-owned publications."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


CAPABILITY_ROUTES = {"company_news": "id_stocks_news", "macro_news": "macro_news"}
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _path(storage: Path, owner_event_key: str) -> Path:
    digest = hashlib.sha256(owner_event_key.encode("utf-8")).hexdigest()
    return storage.parent / "source-work" / f"{digest}.json"


def _validate(value: object, owner_event_key: str) -> dict:
    if (
        type(value) is not dict
        or set(value) - {"summary_media_refs"} != {"owner_event_key", "source_event_key", "content_hash", "profile_id", "publication_id", "capabilities", "work_keys", "outcome"}
        or value["owner_event_key"] != owner_event_key
        or type(value["source_event_key"]) is not str or not _HASH.fullmatch(value["source_event_key"])
        or type(value["content_hash"]) is not str or not _HASH.fullmatch(value["content_hash"])
        or type(value["profile_id"]) is not str or type(value["publication_id"]) is not str
        or owner_event_key != f'{value["profile_id"]}:{value["publication_id"]}'
        or type(value["capabilities"]) is not list or not value["capabilities"]
        or value["capabilities"] != sorted(set(value["capabilities"]))
        or any(capability not in CAPABILITY_ROUTES for capability in value["capabilities"])
        or type(value["work_keys"]) is not list or len(value["work_keys"]) != len(value["capabilities"])
        or value["work_keys"] != sorted(set(value["work_keys"]))
        or any(type(key) is not str or not _HASH.fullmatch(key) for key in value["work_keys"])
        or value["outcome"] not in {"accepted", "irrelevant"}
    ):
        raise ValueError("Instagram source route record is invalid")
    return value


def read(storage: Path, owner_event_key: str) -> dict | None:
    path = _path(storage, owner_event_key)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("Instagram source route record is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Instagram source route record is unavailable") from None
    return _validate(value, owner_event_key)


def write(storage: Path, value: dict) -> None:
    owner_event_key = value.get("owner_event_key")
    if type(owner_event_key) is not str:
        raise ValueError("Instagram source route record is invalid")
    _validate(value, owner_event_key)
    path = _path(storage, owner_event_key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise ValueError("Instagram source route directory is unsafe")
    existing = read(storage, owner_event_key)
    if existing is not None:
        if {k:v for k,v in existing.items() if k != "summary_media_refs"} != {k:v for k,v in value.items() if k != "summary_media_refs"} or ("summary_media_refs" in existing and existing["summary_media_refs"] != value.get("summary_media_refs")):
            raise ValueError("Instagram source route record conflicts")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".source-work-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), ensure_ascii=False)
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


def allowed_routes(storage: Path, owner_event_key: str) -> frozenset[str] | None:
    record = read(storage, owner_event_key)
    if record is None:
        return None
    return frozenset(CAPABILITY_ROUTES[capability] for capability in record["capabilities"])


def terminal(storage: Path, owner_event_key: str) -> dict | None:
    path = _path(storage, owner_event_key).with_suffix(".outcome.json")
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("Instagram source outcome audit is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Instagram source outcome audit is unavailable") from None
    record = read(storage, owner_event_key)
    if (
        record is None or type(value) is not dict
        or set(value) != {"owner_event_key", "source_event_key", "content_hash", "outcome", "classified_route"}
        or value["owner_event_key"] != owner_event_key
        or value["source_event_key"] != record["source_event_key"]
        or value["content_hash"] != record["content_hash"]
        or value["outcome"] not in {"route_not_subscribed", "irrelevant", "delivered"}
        or (value["classified_route"] not in CAPABILITY_ROUTES.values() if value["outcome"] == "route_not_subscribed" else value["classified_route"] is not None)
    ):
        raise ValueError("Instagram source outcome audit is invalid")
    return value


def record_terminal(storage: Path, owner_event_key: str, outcome: str, route: str | None = None) -> None:
    """Persist the outcome before removing an accepted event from owner state."""
    allowed = allowed_routes(storage, owner_event_key)
    if allowed is None or outcome not in {"route_not_subscribed", "irrelevant", "delivered"}:
        raise ValueError("Instagram source terminal outcome is invalid")
    if outcome == "route_not_subscribed":
        if route not in CAPABILITY_ROUTES.values() or route in allowed:
            raise ValueError("Instagram route no-match is invalid")
    elif route is not None:
        raise ValueError("Instagram source terminal route is invalid")
    original = read(storage, owner_event_key)
    assert original is not None
    path = _path(storage, owner_event_key).with_suffix(".outcome.json")
    outcome = {
        "owner_event_key": owner_event_key,
        "source_event_key": original["source_event_key"],
        "content_hash": original["content_hash"],
        "outcome": outcome,
        "classified_route": route,
    }
    existing = terminal(storage, owner_event_key)
    if existing is not None:
        if existing != outcome:
            raise ValueError("Instagram route no-match audit conflicts")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".source-outcome-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(outcome, stream, separators=(",", ":"), ensure_ascii=False)
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
