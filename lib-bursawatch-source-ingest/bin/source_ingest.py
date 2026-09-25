"""Private, endpoint-local source handoff shared by platform adapters.

This module has no delivery or domain-effect authority. A caller supplies an
already parsed, bounded provider page and keeps its former owner in service
until a separately reviewed state migration and scheduler transition.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from source_event_client import SourceEventHandoff

MAX_BATCH = 20
MAX_PAGE = 100
MAX_MEDIA_REFS = 16
MAX_MEDIA_OBJECT_BYTES = 8 * 1024 * 1024
MAX_EVENT_MEDIA_BYTES = 25 * 1024 * 1024
_MEDIA_REF = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_MEDIA_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MEDIA_KIND_TYPES = {
    "image": {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"},
    "video": {"video/mp4", "video/quicktime", "video/webm"},
    "document": {"application/pdf", "application/zip", "text/plain"},
    "audio": {"audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4"},
}


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


def _cursor(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("source cursor is invalid") from error
    if type(value) is not dict or value.get("initialized") is not True or type(value.get("anchor")) not in {str, type(None)} or type(value.get("position")) not in {str, type(None)}:
        raise IntakeBlocked("source cursor is invalid")
    return value


def _save_cursor(path: Path, anchor: str | None, position: str | None, published_at: str | None = None) -> dict[str, Any]:
    value = {"initialized": True, "anchor": anchor, "position": position}
    if path.exists():
        try:
            previous = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise IntakeBlocked("source cursor is invalid") from error
        if type(previous) is dict and isinstance(previous.get("legacy_seed"), dict):
            value["legacy_seed"] = previous["legacy_seed"]
    if published_at is not None:
        value["boundary_published_at"] = published_at
    elif path.exists():
        previous = json.loads(path.read_text())
        if type(previous) is dict and isinstance(previous.get("boundary_published_at"), str):
            value["boundary_published_at"] = previous["boundary_published_at"]
    _write(path, value)
    return value


def _after_cursor_boundary(items: list[dict[str, Any]], cursor: dict[str, Any], id_order: str | None) -> list[dict[str, Any]]:
    """Prove a bounded RSS page is beyond a cursor even if its ID fell off."""
    anchor = cursor.get("anchor")
    if anchor is None:
        return items
    if id_order == "numeric_provider_event_id":
        return [item for item in items if int(item["provider_event_id"]) > int(anchor)]
    if not isinstance(cursor.get("legacy_seed"), dict):
        raise IntakeBlocked("source cursor is absent from the bounded page; migration boundary proof is unavailable")
    boundary_time = cursor.get("boundary_published_at")
    if isinstance(boundary_time, str):
        try:
            from datetime import datetime
            boundary = datetime.fromisoformat(boundary_time.replace("Z", "+00:00"))
            if boundary.tzinfo is None:
                raise ValueError("boundary timezone missing")
            fresh = []
            for item in items:
                published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
                if published.tzinfo is None:
                    raise ValueError("item timezone missing")
                item_id = str(item["provider_event_id"])
                anchor_id = str(anchor)
                if published == boundary and item_id != anchor_id and id_order != "numeric_provider_event_id":
                    raise ValueError("provider ID order is not declared")
                later_id = int(item_id) > int(anchor_id) if id_order == "numeric_provider_event_id" else item_id > anchor_id
                if published > boundary or (published == boundary and later_id):
                    fresh.append(item)
            return fresh
        except (KeyError, TypeError, ValueError) as error:
            raise IntakeBlocked("source page cannot be ordered against the imported cursor") from error
    raise IntakeBlocked("source cursor is absent from the bounded page and order cannot be proven")


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


def _page(raw: Any) -> dict[str, Any]:
    page = {"items": raw, "truncated": False, "contiguous": False, "scanned_through": None, "bootstrap_position": None, "id_order": None} if type(raw) is list else raw
    if type(page) is not dict or type(page.get("items")) is not list or any(type(item) is not dict for item in page["items"]):
        raise IntakeBlocked("source page is invalid")
    if type(page.get("truncated")) is not bool or type(page.get("contiguous")) is not bool:
        raise IntakeBlocked("source page completeness is invalid")
    if type(page.get("scanned_through")) not in {str, type(None)} or type(page.get("bootstrap_position")) not in {str, type(None)}:
        raise IntakeBlocked("source page position is invalid")
    if type(page.get("id_order")) not in {str, type(None)} or page.get("id_order") not in {None, "numeric_provider_event_id"}:
        raise IntakeBlocked("source page ID ordering contract is invalid")
    if len(page["items"]) > MAX_PAGE:
        raise IntakeBlocked("source page exceeds the safe batch; cursor retained")
    ids = [item.get("provider_event_id") for item in page["items"]]
    if any(type(identity) is not str or not identity for identity in ids) or len(set(ids)) != len(ids):
        raise IntakeBlocked("source page identities are invalid")
    if page.get("id_order") == "numeric_provider_event_id":
        numeric_ids = [int(identity) for identity in ids if identity.isdigit()]
        if len(numeric_ids) != len(ids) or numeric_ids != sorted(numeric_ids):
            raise IntakeBlocked("source page numeric ID ordering is invalid")
    if page["contiguous"]:
        positions = [item.get("ingest_position") for item in page["items"]]
        if any(type(position) is not str or not position for position in positions) or positions != sorted(set(positions)):
            raise IntakeBlocked("source page arrival positions are invalid")
    return page


def _validate_media_refs(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > MAX_MEDIA_REFS:
        raise IntakeBlocked("source media references exceed the event bound")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    required_fields = {"ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"}
    for reference in value:
        if type(reference) is not dict or set(reference) != required_fields or reference.get("durable") is not True:
            raise IntakeBlocked("source media reference metadata is invalid")
        ref = reference.get("ref")
        if type(ref) is not str or not _MEDIA_REF.fullmatch(ref):
            raise IntakeBlocked("source media reference identity is invalid")
        try:
            if str(uuid.UUID(ref)) != ref:
                raise ValueError
        except (ValueError, AttributeError):
            raise IntakeBlocked("source media reference identity is invalid") from None
        if ref in seen:
            raise IntakeBlocked("source media references cannot repeat an object")
        seen.add(ref)
        if type(reference.get("sha256")) is not str or not _MEDIA_SHA256.fullmatch(reference["sha256"]):
            raise IntakeBlocked("source media reference digest is invalid")
        kind = reference.get("kind")
        content_type = reference.get("content_type")
        if type(kind) is not str or kind not in _MEDIA_KIND_TYPES or type(content_type) is not str or content_type not in _MEDIA_KIND_TYPES[kind]:
            raise IntakeBlocked("source media kind and content type do not match")
        size = reference.get("size_bytes")
        if type(size) is not int or not 1 <= size <= MAX_MEDIA_OBJECT_BYTES:
            raise IntakeBlocked("source media object exceeds the 8 MiB bound")
        filename = reference.get("filename")
        if type(filename) is not str or not _MEDIA_FILENAME.fullmatch(filename):
            raise IntakeBlocked("source media filename is invalid")
        total_bytes += size
        result.append(dict(reference))
    if total_bytes > MAX_EVENT_MEDIA_BYTES:
        raise IntakeBlocked("source media exceeds the 25 MiB event bound")
    return result


def envelope(endpoint: dict[str, Any], item: dict[str, Any], observed_at: datetime, parser_version: str) -> dict[str, Any]:
    if observed_at.tzinfo is None:
        raise IntakeBlocked("observation timestamp is invalid")
    payload = item.get("payload")
    if type(payload) is not dict or type(item.get("source_url")) is not str or not item["source_url"]:
        raise IntakeBlocked("source payload is invalid")
    media_required = item.get("media_required", False)
    if type(media_required) is not bool:
        raise IntakeBlocked("source media requirement is invalid")
    media_refs = _validate_media_refs(item.get("media_refs", []))
    if media_required and not media_refs:
        raise IntakeBlocked("media-dependent processing requires durable media refs")
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 64_000:
        raise IntakeBlocked("source payload exceeds the adapter bound")
    hash_input = raw
    if media_refs:
        hash_input = json.dumps({"payload": payload, "media_refs": media_refs}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return {"version": 1, "endpoint_id": endpoint["endpoint_id"], "publisher_id": endpoint["publisher_id"], "platform": endpoint["platform"], "provider_event_id": item["provider_event_id"], "published_at": item["published_at"], "observed_at": observed_at.astimezone(timezone.utc).isoformat(), "source_url": item["source_url"], "parser_version": parser_version, "content_hash": hashlib.sha256(hash_input).hexdigest(), "payload": payload, "media_refs": media_refs, "media_required": media_required}


def _without_media_locators(value: Any) -> Any:
    if type(value) is dict:
        return {key: _without_media_locators(child) for key, child in value.items() if key not in {"media", "quoted_media", "media_url", "path", "locator_digest"}}
    if type(value) is list:
        return [_without_media_locators(child) for child in value]
    return value


def ingest_endpoint(endpoint: dict[str, Any], fetch: Callable[[dict[str, Any] | None], Any], state_root: Path, inbox: Any, observed_at: datetime, parser_version: str, *, batch: int = MAX_BATCH) -> dict[str, Any]:
    if type(batch) is not int or not 1 <= batch <= MAX_BATCH:
        raise ValueError("source batch must be between 1 and 20")
    root = state_root / endpoint["endpoint_id"].replace(":", "-")
    path = root / "cursor.json"
    cursor = _cursor(path)
    handoff = SourceEventHandoff(root / "handoff", inbox)
    intent_path = root / "pending-position.json"
    pending = handoff.spool.pending()
    if intent_path.exists():
        try:
            intent = json.loads(intent_path.read_text())
        except (OSError, ValueError) as error:
            raise IntakeBlocked("endpoint handoff intent is invalid") from error
        staged = intent.get("envelope") if type(intent) is dict else None
        position = intent.get("position") if type(intent) is dict else None
        if cursor is None or type(staged) is not dict or staged.get("endpoint_id") != endpoint["endpoint_id"] or type(staged.get("provider_event_id")) is not str or type(position) not in {str, type(None)}:
            raise IntakeBlocked("endpoint handoff intent identity is invalid")
        if pending:
            if len(pending) != 1 or pending[0].endpoint != "/v1/source-events" or pending[0].payload.get("envelope") != staged:
                raise IntakeBlocked("endpoint handoff is inconsistent")
        else:
            # The inbox may have accepted and acknowledged the request before
            # cursor persistence. Reaccept the same event for its duplicate
            # receipt, then finish the local cursor update.
            handoff.stage(staged)
        if len(handoff.flush(limit=1)) != 1:
            raise IntakeBlocked("endpoint handoff lacks durable receipt")
        cursor = _save_cursor(path, staged["provider_event_id"], position if position is not None else cursor["position"], staged["published_at"])
        intent_path.unlink()
    elif pending:
        raise IntakeBlocked("endpoint handoff lacks a durable position intent")

    page = _page(fetch(cursor))
    items = page["items"]
    if cursor is None:
        newest = items[-1] if items else None
        bootstrap_position = page.get("bootstrap_position") or (newest.get("ingest_position") if newest else None)
        _save_cursor(path, newest["provider_event_id"] if newest else None, bootstrap_position, newest.get("published_at") if newest else None)
        return {"endpoint_id": endpoint["endpoint_id"], "status": "bootstrapped" if newest else "bootstrapped_empty", "accepted": 0}
    identities = [item["provider_event_id"] for item in items]
    anchor = cursor["anchor"]
    if page["truncated"] and (anchor is None or anchor not in identities):
        raise IntakeBlocked("source page is truncated before the prior cursor")
    if not items:
        scanned = page.get("scanned_through")
        if page["contiguous"] and scanned is not None and (cursor["position"] is None or scanned > cursor["position"]):
            _save_cursor(path, cursor["anchor"], scanned)
        return {"endpoint_id": endpoint["endpoint_id"], "status": "empty", "accepted": 0}
    if page["contiguous"]:
        fresh = [item for item in items if cursor["position"] is None or item["ingest_position"] > cursor["position"]]
    else:
        fresh = items[identities.index(anchor) + 1:] if anchor in identities else _after_cursor_boundary(items, cursor, page.get("id_order"))
    partial_batch = len(fresh) > batch
    if partial_batch:
        # A complete ordered page is safe even after an empty bootstrap. A
        # truncated identity-anchored page is safe only when its old anchor is
        # still visible; that case was checked above. Position-ordered pages
        # also resume from each acknowledged event on the next poll.
        fresh = fresh[:batch]
    accepted = 0
    for item in fresh:
        media_required = item.get("media_required", False)
        if type(media_required) is not bool:
            raise IntakeBlocked("source media requirement is invalid")
        media_refs = _validate_media_refs(item.get("media_refs", []))
        if media_required and not media_refs:
            # Durable metadata/text is retained while the media integration is
            # unreviewed. The provider must still be able to supply the bytes
            # later; this record never pretends to be a durable media object.
            safe_payload = _without_media_locators(item.get("blocked_payload", item.get("payload")))
            if type(safe_payload) is not dict or len(json.dumps(safe_payload, ensure_ascii=False, allow_nan=False).encode()) > 64_000:
                raise IntakeBlocked("media-blocked payload exceeds the adapter bound")
            _write(root / "blocked-media.json", {"status": "media_blocked", "endpoint_id": endpoint["endpoint_id"], "provider_event_id": item["provider_event_id"], "published_at": item["published_at"], "source_url": item.get("source_url"), "payload": safe_payload})
            raise IntakeBlocked("source media requires reviewed durable storage")
        event = envelope(endpoint, item, observed_at, parser_version)
        position = item.get("ingest_position") if page["contiguous"] else None
        _write(intent_path, {"envelope": event, "position": position})
        handoff.stage(event)
        if len(handoff.flush(limit=1)) != 1:
            raise IntakeBlocked("source inbox did not acknowledge handoff")
        cursor = _save_cursor(path, item["provider_event_id"], position if position is not None else cursor["position"], item["published_at"])
        intent_path.unlink()
        (root / "blocked-media.json").unlink(missing_ok=True)
        accepted += 1
    scanned = page.get("scanned_through")
    if (
        page["contiguous"]
        and not partial_batch
        and accepted == len(fresh)
        and scanned is not None
        and (cursor["position"] is None or scanned > cursor["position"])
    ):
        _save_cursor(path, cursor["anchor"], scanned)
    return {"endpoint_id": endpoint["endpoint_id"], "status": "accepted", "accepted": accepted}


def ingest_all(selected: dict[str, dict[str, Any]], fetchers: dict[str, Callable[[dict[str, Any] | None], Any]], state_root: Path, inbox: Any, observed_at: datetime, parser_version: str) -> list[dict[str, Any]]:
    outcomes = []
    for endpoint_id, endpoint in selected.items():
        try:
            outcomes.append(ingest_endpoint(endpoint, fetchers[endpoint_id], state_root, inbox, observed_at, parser_version))
        except IntakeBlocked as error:
            reason = str(error)
            code = "media_blocked" if "media" in reason else "page_truncated" if "truncated" in reason else "batch_overflow" if "batch" in reason else "source_blocked"
            outcomes.append({"endpoint_id": endpoint_id, "status": "blocked", "reason": code})
        except Exception:
            outcomes.append({"endpoint_id": endpoint_id, "status": "blocked", "reason": "handoff_or_fetch_failed"})
    return outcomes
