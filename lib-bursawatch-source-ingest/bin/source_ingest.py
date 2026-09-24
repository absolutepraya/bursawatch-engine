"""Private, endpoint-local source handoff shared by platform adapters.

This module has no delivery or domain-effect authority. A caller supplies an
already parsed, bounded provider page and keeps its former owner in service
until a separately reviewed state migration and scheduler transition.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from source_event_client import SourceEventHandoff

MAX_BATCH = 20
MAX_PAGE = 100


class IntakeBlocked(RuntimeError):
    """An endpoint cannot safely advance its source cursor."""


def select_endpoints(snapshot: dict[str, Any], platform: str, bindings: dict[str, dict[str, Any]], allowed: set[str]) -> dict[str, dict[str, Any]]:
    if type(snapshot) is not dict or type(snapshot.get("revision")) is not int or type(snapshot.get("subscriptions")) is not list:
        raise IntakeBlocked("effective source catalog is invalid")
    selected: dict[str, dict[str, Any]] = {}
    for row in snapshot["subscriptions"]:
        if type(row) is not dict or row.get("platform") != platform or row.get("enabled") is not True:
            continue
        endpoint_id = row.get("endpoint_id")
        binding = bindings.get(endpoint_id) if type(endpoint_id) is str else None
        if binding is None or row.get("verification_status") != "verified" or row.get("capability_id") not in allowed:
            raise IntakeBlocked("enabled endpoint is not verified and owned by this adapter")
        if any(row.get(field) != binding.get(field) for field in ("publisher_id", "address", "provider_id")):
            raise IntakeBlocked("effective endpoint identity differs from source configuration")
        existing = selected.setdefault(endpoint_id, {**binding, "endpoint_id": endpoint_id, "capabilities": set(), "catalog_revision": snapshot["revision"]})
        existing["capabilities"].add(row["capability_id"])
    return selected


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".source-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
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


def _cursor(path: Path) -> tuple[str, str] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    order = value.get("order") if type(value) is dict else None
    if type(order) is not list or len(order) != 2 or any(type(part) is not str or not part for part in order):
        raise IntakeBlocked("source cursor is invalid")
    return (order[0], order[1])


def bind_catalog_revision(state_root: Path, revision: int) -> None:
    """A changed subscription set needs a reviewed future-only cursor plan."""
    if type(revision) is not int or revision < 1:
        raise IntakeBlocked("source catalog revision is invalid")
    path = state_root / "catalog-revision.json"
    if not path.exists():
        if any(state_root.glob("*/cursor.json")):
            raise IntakeBlocked("source cursors have no recorded catalog revision")
        _write(path, {"revision": revision})
        return
    try:
        recorded = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("source catalog revision record is invalid") from error
    if type(recorded) is not dict or recorded.get("revision") != revision:
        raise IntakeBlocked("source catalog revision changed; reviewed future-only transition required")


def _order(item: dict[str, Any]) -> tuple[str, str]:
    published = item.get("published_at")
    identity = item.get("provider_event_id")
    if type(published) is not str or type(identity) is not str or not identity:
        raise IntakeBlocked("source event identity is invalid")
    try:
        stamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError as error:
        raise IntakeBlocked("source timestamp is invalid") from error
    return (stamp.astimezone(timezone.utc).isoformat(), identity)


def envelope(endpoint: dict[str, Any], item: dict[str, Any], observed_at: datetime, parser_version: str) -> dict[str, Any]:
    if observed_at.tzinfo is None:
        raise IntakeBlocked("observation timestamp is invalid")
    payload = item.get("payload")
    if type(payload) is not dict or type(item.get("source_url")) is not str or not item["source_url"]:
        raise IntakeBlocked("source payload is invalid")
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 64_000:
        raise IntakeBlocked("source payload exceeds the adapter bound")
    return {"version": 1, "endpoint_id": endpoint["endpoint_id"], "publisher_id": endpoint["publisher_id"], "platform": endpoint["platform"], "provider_event_id": item["provider_event_id"], "published_at": item["published_at"], "observed_at": observed_at.astimezone(timezone.utc).isoformat(), "source_url": item["source_url"], "parser_version": parser_version, "content_hash": hashlib.sha256(raw).hexdigest(), "payload": payload, "media_refs": [], "media_required": False}


def _without_media_locators(value: Any) -> Any:
    if type(value) is dict:
        return {key: _without_media_locators(child) for key, child in value.items() if key not in {"media", "quoted_media", "media_url", "path", "locator_digest"}}
    if type(value) is list:
        return [_without_media_locators(child) for child in value]
    return value


def ingest_endpoint(endpoint: dict[str, Any], fetch: Callable[[str | None], list[dict[str, Any]]], state_root: Path, inbox: Any, observed_at: datetime, parser_version: str, *, batch: int = MAX_BATCH) -> dict[str, Any]:
    if type(batch) is not int or not 1 <= batch <= MAX_BATCH:
        raise ValueError("source batch must be between 1 and 20")
    root = state_root / endpoint["endpoint_id"].replace(":", "-")
    path = root / "cursor.json"
    cursor = _cursor(path)
    handoff = SourceEventHandoff(root / "handoff", inbox)
    pending = handoff.spool.pending()
    if pending:
        if cursor is None or len(pending) != 1 or pending[0].endpoint != "/v1/source-events":
            raise IntakeBlocked("endpoint handoff is inconsistent")
        staged = pending[0].payload.get("envelope")
        if type(staged) is not dict or staged.get("endpoint_id") != endpoint["endpoint_id"]:
            raise IntakeBlocked("endpoint handoff identity is inconsistent")
        staged_order = _order(staged)
        if staged_order <= cursor:
            raise IntakeBlocked("endpoint handoff precedes cursor")
        if len(handoff.flush(limit=1)) != 1:
            raise IntakeBlocked("endpoint handoff lacks durable receipt")
        _write(path, {"order": list(staged_order)})
        cursor = staged_order
    items = fetch(cursor[1] if cursor else None)
    if type(items) is not list or any(type(item) is not dict for item in items):
        raise IntakeBlocked("source page is invalid")
    if len(items) > MAX_PAGE:
        raise IntakeBlocked("source page exceeds the safe batch; cursor retained")
    if not items:
        return {"endpoint_id": endpoint["endpoint_id"], "status": "empty", "accepted": 0}
    ordered = sorted(items, key=_order)
    if len({_order(item) for item in ordered}) != len(ordered):
        raise IntakeBlocked("source page contains duplicate identities")
    if cursor is None:
        _write(path, {"order": list(_order(ordered[-1]))})
        return {"endpoint_id": endpoint["endpoint_id"], "status": "bootstrapped", "accepted": 0}
    fresh = [item for item in ordered if _order(item) > cursor]
    if len(fresh) > batch:
        raise IntakeBlocked("source page exceeds the safe batch; cursor retained")
    accepted = 0
    for item in fresh:
        if item.get("media_required") is True:
            # Durable metadata/text is retained while the media integration is
            # unreviewed. The provider must still be able to supply the bytes
            # later; this record never pretends to be a durable media object.
            safe_payload = _without_media_locators(item.get("blocked_payload", item.get("payload")))
            if type(safe_payload) is not dict or len(json.dumps(safe_payload, ensure_ascii=False, allow_nan=False).encode()) > 64_000:
                raise IntakeBlocked("media-blocked payload exceeds the adapter bound")
            _write(root / "blocked-media.json", {"status": "media_blocked", "endpoint_id": endpoint["endpoint_id"], "provider_event_id": item["provider_event_id"], "published_at": item["published_at"], "source_url": item.get("source_url"), "payload": safe_payload})
            raise IntakeBlocked("source media requires reviewed durable storage")
        event = envelope(endpoint, item, observed_at, parser_version)
        handoff.stage(event)
        if len(handoff.flush(limit=1)) != 1:
            raise IntakeBlocked("source inbox did not acknowledge handoff")
        cursor = _order(item)
        _write(path, {"order": list(cursor)})
        (root / "blocked-media.json").unlink(missing_ok=True)
        accepted += 1
    return {"endpoint_id": endpoint["endpoint_id"], "status": "accepted", "accepted": accepted}


def ingest_all(selected: dict[str, dict[str, Any]], fetchers: dict[str, Callable[[str | None], list[dict[str, Any]]]], state_root: Path, inbox: Any, observed_at: datetime, parser_version: str) -> list[dict[str, Any]]:
    outcomes = []
    for endpoint_id, endpoint in selected.items():
        try:
            outcomes.append(ingest_endpoint(endpoint, fetchers[endpoint_id], state_root, inbox, observed_at, parser_version))
        except IntakeBlocked as error:
            reason = str(error)
            code = "media_blocked" if "media" in reason else "batch_overflow" if "batch" in reason else "source_blocked"
            outcomes.append({"endpoint_id": endpoint_id, "status": "blocked", "reason": code})
        except Exception:
            outcomes.append({"endpoint_id": endpoint_id, "status": "blocked", "reason": "handoff_or_fetch_failed"})
    return outcomes
