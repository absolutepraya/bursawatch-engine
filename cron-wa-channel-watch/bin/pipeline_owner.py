"""Accept WhatsApp source work into the existing Channel watcher ledger."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-media"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))

import agent_protocol
import archive
import config
import event_queue
import scan
import source_work_routes
import state
from normalize import deserialize_queue_event, normalize_bridge_event
from models import ChannelMedia


class OwnerPending(RuntimeError):
    """The existing watcher cannot durably accept this source work yet."""


PUBLISHERS = {"whatsapp:0029VbAjdnb60eBhwVdJxj1c": "bri-danareksa"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEDIA_SUFFIXES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/avif": ".avif", "video/mp4": ".mp4",
    "video/quicktime": ".mov", "video/webm": ".webm",
}
_MEDIA_TYPES = {
    "image": {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"},
    "video": {"video/mp4", "video/quicktime", "video/webm"},
}


def _state_path() -> Path:
    return Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_STATE_PATH", str(Path.home() / ".hermes/state/whatsapp-channel-watch/state.json")))


def _config_path() -> Path:
    return Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_CONFIG_PATH", str(ROOT / "cron-wa-channel-watch/config/watches.json")))


def _archive_root() -> Path:
    return Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT", str(Path.home() / ".hermes/state/whatsapp-channel-watch/archive")))


def _staging_root() -> Path:
    return Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_MEDIA_STAGING_DIR", str(Path.home() / ".hermes/state/whatsapp-channel-watch/media-staging")))


def _resolved(path: Path) -> Path:
    return Path(os.path.expanduser(os.path.abspath(os.fspath(path)))).resolve(strict=False)


def _assert_no_post_isolated(no_post: bool, paths: tuple[Path, ...]) -> None:
    if not no_post:
        return
    live_root = _resolved(Path.home() / ".hermes/state/whatsapp-channel-watch")
    for path in paths:
        if not path.is_absolute() or _resolved(path).is_relative_to(live_root):
            raise ValueError("no-post requires absolute paths outside live WhatsApp watcher state")


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / "pipeline-owner.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _inbox_client():
    from source_event_client import SourceEventClient

    url = os.environ.get("BURSAWATCH_WA_SOURCE_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_WA_SOURCE_CONTROL_PLANE_TOKEN_FILE")
    if not url or not token_file:
        raise OwnerPending("WhatsApp Source Inbox access is unavailable")
    token_path = Path(token_file)
    if token_path.stat().st_mode & 0o077:
        raise ValueError("WhatsApp Source Inbox token file is not private")
    return SourceEventClient(url, token_path.read_text(encoding="utf-8").strip())


def _media_client():
    from bursawatch_source_media import SourceMediaClient

    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE")
    if not url or not token_file:
        raise OwnerPending("Source Media Owner read access is unavailable")
    return SourceMediaClient(url, Path(token_file))


def _work_profile(work: dict[str, Any], profiles: tuple[Any, ...]) -> Any:
    endpoint_id = work.get("endpoint_id")
    publisher = work.get("publisher_id")
    profile = next((row for row in profiles if row.enabled and row.is_forwarding and f"whatsapp:{row.channel_url.rstrip('/').rsplit('/', 1)[-1]}" == endpoint_id), None)
    if profile is None or PUBLISHERS.get(endpoint_id) != publisher:
        raise ValueError("WhatsApp source endpoint is not an enabled reviewed BRI publisher")
    return profile


def _timestamp(value: Any, label: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"WhatsApp {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"WhatsApp {label} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"WhatsApp {label} is invalid")
    return parsed.astimezone(timezone.utc)


def _validate_work(work: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[Any, Any, list[dict[str, Any]], int]:
    if type(work) is not dict:
        raise ValueError("WhatsApp source work is invalid")
    capability = work.get("pipeline_id")
    if capability not in source_work_routes.CAPABILITY_ROUTE_KEYS:
        raise ValueError("WhatsApp source pipeline is unsupported")
    envelope = work.get("envelope")
    event_key = work.get("event_key")
    expected_work_key = hashlib.sha256(f"{event_key}:1:{capability}".encode()).hexdigest()
    expected_event_key = hashlib.sha256(json.dumps(
        ["whatsapp", envelope.get("endpoint_id"), envelope.get("provider_event_id")],
        separators=(",", ":"),
    ).encode()).hexdigest() if type(envelope) is dict else None
    if (
        type(envelope) is not dict
        or work.get("capability_id") != capability
        or work.get("version") != 1
        or work.get("event_kind") != "original"
        or type(event_key) is not str
        or not _SHA256_RE.fullmatch(event_key)
        or event_key != expected_event_key
        or work.get("effect_key") != expected_work_key
        or work.get("work_key") != expected_work_key
        or envelope.get("platform") != "whatsapp"
        or type(work.get("catalog_revision")) is not int
        or work["catalog_revision"] < 1
    ):
        raise ValueError("WhatsApp source work identity is invalid")
    profile = _work_profile(envelope, profiles)
    payload = envelope.get("payload")
    refs = envelope.get("media_refs")
    provider_id = envelope.get("provider_event_id")
    endpoint_id = envelope.get("endpoint_id")
    if (
        type(payload) is not dict or type(refs) is not list
        or type(provider_id) is not str or not provider_id
        or endpoint_id != f"whatsapp:{profile.channel_url.rstrip('/').rsplit('/', 1)[-1]}"
        or type(envelope.get("content_hash")) is not str
        or not _SHA256_RE.fullmatch(envelope["content_hash"])
        or envelope.get("source_url") != profile.channel_url
        or type(payload.get("channel_jid")) is not str
        or payload["channel_jid"] != profile.channel_jid
        or type(payload.get("text")) is not str
        or type(payload.get("links")) is not list
        or payload.get("owner_config_revision") is not None
        and (type(payload["owner_config_revision"]) is not int or payload["owner_config_revision"] < 1)
    ):
        raise ValueError("WhatsApp source envelope is invalid")
    published_at = _timestamp(envelope.get("published_at"), "publication timestamp")
    received_at = _timestamp(envelope.get("observed_at"), "observation timestamp")
    raw_manifest = payload.get("media_manifest")
    raw_ref_ids = payload.get("media_ref_ids")
    unavailable_manifest = payload.get("unavailable_media_manifest", [])
    if type(raw_manifest) is not list or type(raw_ref_ids) is not list or len(refs) > 8 or len(raw_manifest) != len(refs) or raw_ref_ids != [item.get("ref") for item in refs if type(item) is dict]:
        raise ValueError("WhatsApp media manifest does not match Source Inbox references")
    if envelope.get("media_required") is not bool(refs):
        raise ValueError("WhatsApp media requirement does not match its references")
    if (
        type(unavailable_manifest) is not list or len(unavailable_manifest) > 8
        or (unavailable_manifest and (refs or not payload["text"].strip()))
    ):
        raise ValueError("WhatsApp unavailable-media fallback is invalid")

    media_rows = []
    total = 0
    required_ref_keys = {"ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"}
    for index, (manifest, reference) in enumerate(zip(raw_manifest, refs, strict=True)):
        if (
            type(manifest) is not dict or set(manifest) != {"index", "kind", "mime", "ref_id"}
            or manifest.get("index") != index
            or type(reference) is not dict or set(reference) != required_ref_keys
            or reference.get("durable") is not True
            or manifest.get("ref_id") != reference.get("ref")
            or type(manifest.get("index")) is not int
            or manifest.get("kind") != reference.get("kind")
            or manifest.get("mime") != reference.get("content_type")
        ):
            raise ValueError("WhatsApp source media metadata is invalid")
        try:
            if str(uuid.UUID(reference["ref"])) != reference["ref"]:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("WhatsApp source media reference is invalid") from None
        kind, content_type = reference.get("kind"), reference.get("content_type")
        if type(kind) is not str or content_type not in _MEDIA_TYPES.get(kind, set()):
            raise ValueError("WhatsApp source media type is invalid")
        size = reference.get("size_bytes")
        if (
            type(size) is not int or not 1 <= size <= 8 * 1024 * 1024
            or type(reference.get("sha256")) is not str or not _SHA256_RE.fullmatch(reference["sha256"])
            or type(reference.get("filename")) is not str or not _MEDIA_FILENAME_RE.fullmatch(reference["filename"])
        ):
            raise ValueError("WhatsApp source media bounds are invalid")
        total += size
        if total > 25 * 1024 * 1024:
            raise ValueError("WhatsApp source media exceeds the event bound")
        media_rows.append({"kind": kind, "mime": content_type, "ref": reference})
    if len(raw_manifest) != len(set(row["ref"]["ref"] for row in media_rows)):
        raise ValueError("WhatsApp source media references repeat")
    fallback_rows = []
    for index, row in enumerate(unavailable_manifest):
        if (
            type(row) is not dict or set(row) != {"index", "kind", "mime"}
            or row["index"] != index or row["kind"] not in _MEDIA_TYPES
            or row["mime"] is not None and type(row["mime"]) is not str
        ):
            raise ValueError("WhatsApp unavailable-media manifest is invalid")
        fallback_rows.append({"kind": row["kind"], "mime": row["mime"]})

    normalized = normalize_bridge_event({
        "channel_jid": profile.channel_jid,
        "message_id": provider_id,
        "published_at": published_at.isoformat(),
        "text": payload["text"],
        "media": [{"kind": row["kind"], "mime": row["mime"]} for row in media_rows] + fallback_rows,
    }, received_at=received_at)
    if list(normalized.links) != payload["links"]:
        raise ValueError("WhatsApp links do not match source text")
    return profile, normalized, media_rows, payload["owner_config_revision"]


def _sibling_scope(work: dict[str, Any], inbox: Any) -> tuple[list[str], list[str]]:
    inspected = inbox.inspect(work["event_key"])
    event = inspected.get("event")
    rows = inspected.get("work")
    if type(event) is not dict or event.get("event_key") != work["event_key"] or type(rows) is not list:
        raise ValueError("WhatsApp source work inspection is invalid")
    versions = event.get("versions")
    envelope = work["envelope"]
    if type(versions) is not list or not any(
        type(version) is dict and version.get("version") == 1 and version.get("envelope") == envelope
        for version in versions
    ):
        raise ValueError("WhatsApp source event version is invalid")
    capabilities: list[str] = []
    keys: list[str] = []
    current_active = False
    for row in rows:
        if type(row) is not dict or row.get("version") != 1:
            continue
        capability = row.get("capability_id")
        if capability not in source_work_routes.CAPABILITY_ROUTE_KEYS:
            continue
        expected = hashlib.sha256(f'{work["event_key"]}:1:{capability}'.encode()).hexdigest()
        if (
            row.get("pipeline_id") != capability or row.get("work_key") != expected
            or row.get("effect_key") != expected or row.get("catalog_revision") != work.get("catalog_revision")
            or row.get("settings") != {}
        ):
            raise ValueError("WhatsApp sibling work identity is invalid")
        if row.get("status") not in {"suppressed", "dead_letter", "superseded"}:
            capabilities.append(capability)
            keys.append(expected)
        if expected == work["work_key"]:
            current_active = row.get("status") == "executing" and row.get("lease_token") == work.get("lease_token")
    if not current_active or work["work_key"] not in keys:
        raise ValueError("WhatsApp source work is not active")
    return sorted(set(capabilities)), sorted(set(keys))


def _write_staged(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise ValueError("WhatsApp staged source media conflicts")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".wa-source-media-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _hydrate_event(event: Any, media_rows: list[dict[str, Any]], staging_root: Path, media_store: Any) -> Any:
    event_root = staging_root / hashlib.sha256(event.event_key.encode()).hexdigest()
    media = []
    store = media_store or _media_client()
    for row in media_rows:
        reference = row["ref"]
        content_type = reference["content_type"]
        downloaded = store.download(reference["ref"])
        data = getattr(downloaded, "data", None)
        if (
            type(data) is not bytes or not 1 <= len(data) <= 8 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != reference["sha256"]
            or len(data) != reference["size_bytes"]
            or getattr(downloaded, "content_type", None) != content_type
            or getattr(downloaded, "kind", None) != reference["kind"]
        ):
            raise OwnerPending("Source Media Owner returned invalid WhatsApp media")
        suffix = _MEDIA_SUFFIXES[content_type]
        path = event_root / f"{len(media)}{suffix}"
        _write_staged(path, data)
        media.append(ChannelMedia(row["kind"], len(media), row["mime"], str(path)))
    return replace(event, media=tuple(media))


def submit(
    work: dict[str, Any], *, no_post: bool = False, inbox: Any = None, media_store: Any = None,
    config_path: Path | None = None, state_path: Path | None = None,
    archive_root: Path | None = None, staging_root: Path | None = None,
) -> str:
    config_path = config_path or _config_path()
    state_path = state_path or _state_path()
    archive_root = archive_root or _archive_root()
    staging_root = staging_root or _staging_root()
    _assert_no_post_isolated(no_post, (state_path, archive_root, staging_root))
    if any(not path.is_absolute() for path in (state_path, archive_root, staging_root)):
        raise ValueError("WhatsApp owner state paths must be absolute")
    loaded = config.load_for_run(config_path)
    profile, event, media_rows, archive_revision = _validate_work(work, loaded.config.profiles)
    inbox = inbox or _inbox_client()
    capabilities, work_keys = _sibling_scope(work, inbox)
    route_keys = source_work_routes.route_keys(capabilities)
    owner_event_key = event.event_key
    source_record = {
        "summary_media_refs": work["envelope"]["media_refs"],
        "source_event_key": work["event_key"],
        "source_content_hash": work["envelope"]["content_hash"],
        "source_catalog_revision": work["catalog_revision"],
        "source_pipeline_capabilities": capabilities,
        "source_pipeline_work_keys": work_keys,
        "source_pipeline_route_keys": route_keys,
    }
    if work["envelope"]["payload"].get("unavailable_media_manifest"):
        source_record["source_media_unavailable"] = True

    with _state_lock(state_path):
        value = state.load(state_path)
        existing = next((row for row in value["outbox"] if type(row) is dict and row.get("event_key") == owner_event_key), None)
        if existing is not None:
            if any(existing.get(key) != expected for key, expected in source_record.items() if key != "summary_media_refs" or key in existing):
                raise ValueError("WhatsApp source event conflicts with existing watcher work")
            return "accepted"

        hydrated = _hydrate_event(event, media_rows, staging_root, media_store) if media_rows else event
        archive.ensure(archive_root, profile.id, hydrated, archive_revision, staging_root=staging_root)
        canonical_event = replace(
            hydrated,
            media=tuple(ChannelMedia(item.kind, item.index, item.mime, None) for item in hydrated.media),
        )
        record: dict[str, object] = {
            "event_key": owner_event_key,
            "profile_id": profile.id,
            "event": event_queue.serialize_event(canonical_event),
            "agent_phase": "pending" if profile.uses_llm else "ready",
            "agent_lease_until": None,
            "items": None if profile.uses_llm else scan._deterministic_items(profile),
            "item_index": 0,
            "text_index": 0,
            "text_message_ids": [],
            "text_message_id": None,
            "media_index": 0,
            "media_message_ids": [],
            "media_skipped_indexes": [],
            "media_delivery_status": "pending",
            "media_error": None,
            "board_phase": "pending",
            "board_link_phase": "pending",
            "archive_complete": True,
            "routable": True,
            **source_record,
        }
        value["outbox"].append(record)  # type: ignore[union-attr]
        state.save(state_path, value)
    return "accepted"


def claim_agent(
    *, no_post: bool = False, config_path: Path | None = None, state_path: Path | None = None,
    archive_root: Path | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    config_path = config_path or _config_path()
    state_path = state_path or _state_path()
    archive_root = archive_root or _archive_root()
    _assert_no_post_isolated(no_post, (state_path, archive_root))
    if not state_path.is_absolute():
        raise ValueError("WhatsApp owner state path must be absolute")
    if not archive_root.is_absolute():
        raise ValueError("WhatsApp archive path must be absolute")
    loaded = config.load_for_run(config_path)
    observed = now or datetime.now(timezone.utc)
    with _state_lock(state_path):
        value = state.load(state_path)
        expired = state.expire_leases(value, observed)
        profiles = {profile.id: profile for profile in loaded.config.profiles}
        errors: list[str] = []
        delivered = scan._deliver_ready(
            value,
            profiles,
            dry_run=no_post,
            state_path=state_path,
            archive_dir=archive_root,
            errors=errors,
        )
        claimed = None
        for record in scan._active_records(value, profiles):
            if record.get("agent_phase") != "pending":
                continue
            profile = profiles.get(str(record.get("profile_id")))
            if profile is None:
                continue
            event = deserialize_queue_event(record["event"])
            record["agent_phase"] = "awaiting_agent"
            record["agent_lease_until"] = state.lease_until(observed)
            route_override = agent_protocol.deterministic_route(profile, event)
            agent_event = replace(event, media=()) if record.get("source_media_unavailable") is True else event
            claimed = agent_protocol.agent_item(profile, agent_event, relevance_guard_required=route_override is not None)
            import summary_context
            selected_route = route_override if profile.enable_llm_routing else profile.discord_channels[0].key
            if selected_route != "id_stocks_swing":
                claimed["instruction"] += summary_context.context_instruction(
                    summary_context.claim_from_state(value, record["event_key"], state_path.parent / "summary-context"),
                    "~/.hermes/scripts/bursawatch-wa-channel-watch.sh prepare-summary-images --json",
                )
            break
        state.save(state_path, value)
    return {
        **agent_protocol.build_wake_payload(claimed),
        "delivered": delivered,
        "expired": expired,
        "delivery_errors": len(errors),
    }


def main() -> int:
    no_post = os.environ.get("BURSAWATCH_WA_SOURCE_NO_POST") == "1"
    if len(sys.argv) == 2 and sys.argv[1] == "claim-agent":
        result = claim_agent(no_post=no_post)
    elif len(sys.argv) == 1:
        work = json.load(sys.stdin)
        result = {"outcome": submit(work, no_post=no_post)}
    else:
        raise ValueError("unsupported WhatsApp source owner command")
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
