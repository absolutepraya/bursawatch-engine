"""Accept Instagram Source Inbox work into the existing watcher ledger."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import rsshub
import scan
import source_work_routes
import state
from models import DownloadedAsset, DownloadedPublication, MediaKind, PublicationKind, SourceMedia, SourcePost


class OwnerPending(RuntimeError):
    """Durable media or owner state is temporarily unavailable."""


_SUFFIXES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
}


def _inbox_client():
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    installed = Path.home() / ".agents" / "skills" / "lib-bursawatch-control" / "bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from source_event_client import SourceEventClient

    url = os.environ.get("BURSAWATCH_IG_SOURCE_CONTROL_PLANE_URL")
    token_file = os.environ.get("BURSAWATCH_IG_SOURCE_CONTROL_PLANE_TOKEN_FILE")
    if not url or not token_file:
        raise OwnerPending("Instagram Source Inbox access is unavailable")
    token_path = Path(token_file)
    if token_path.stat().st_mode & 0o077:
        raise ValueError("Instagram Source Inbox token file is not private")
    return SourceEventClient(url, token_path.read_text().strip())


def _source_media_client():
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE")
    if not url or not token_file:
        raise OwnerPending("Source Media Owner read access is unavailable")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
    installed = Path.home() / ".agents" / "skills" / "lib-bursawatch-source-media" / "bin"
    library = local if local.is_dir() else installed
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from bursawatch_source_media import SourceMediaClient

    return SourceMediaClient(url, Path(token_file))


def _validated_work(work: dict[str, Any], profiles: tuple[Any, ...]) -> tuple[Any, SourcePost, list[dict[str, Any]]]:
    if type(work) is not dict or work.get("pipeline_id") not in source_work_routes.CAPABILITY_ROUTES:
        raise ValueError("Instagram source pipeline is unsupported")
    capability = work["pipeline_id"]
    envelope = work.get("envelope")
    if type(envelope) is not dict:
        raise ValueError("Instagram source envelope is invalid")
    identity = [envelope.get("platform"), envelope.get("endpoint_id"), envelope.get("provider_event_id")]
    if any(type(value) is not str or not value for value in identity):
        raise ValueError("Instagram source event identity is invalid")
    expected_event_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    expected_work_key = hashlib.sha256(f'{expected_event_key}:1:{capability}'.encode()).hexdigest()
    if (
        work.get("capability_id") != capability or work.get("version") != 1
        or type(work.get("capability_version")) is not int or work["capability_version"] != 1
        or type(work.get("catalog_revision")) is not int or work["catalog_revision"] < 1
        or work.get("event_kind") != "original"
        or work.get("event_key") != expected_event_key
        or work.get("effect_key") != expected_work_key or work.get("work_key") != expected_work_key
        or work.get("settings") not in ({}, None)
        or envelope.get("platform") != "instagram"
    ):
        raise ValueError("Instagram source work identity is invalid")
    endpoint_id = envelope.get("endpoint_id")
    profile = next((item for item in profiles if item.enabled and f"instagram:{item.handle.casefold()}" == endpoint_id), None)
    if profile is None or envelope.get("publisher_id") != f"instagram-{profile.id}":
        raise ValueError("Instagram source profile or publisher is invalid")
    if not profile.enable_llm_routing:
        raise ValueError("Instagram source route cannot be classified")
    publication_id = envelope.get("provider_event_id")
    body = envelope.get("payload")
    refs = envelope.get("media_refs")
    if type(publication_id) is not str or type(body) is not dict or type(refs) is not list:
        raise ValueError("Instagram source publication is invalid")
    ids = body.get("media_ref_ids", [])
    if type(ids) is not list or len(ids) != len(refs) or ids != [ref.get("ref") for ref in refs if type(ref) is dict]:
        raise ValueError("Instagram source media order is invalid")
    if envelope.get("media_required") != bool(refs) or len(refs) > 16:
        raise ValueError("Instagram source media coverage is invalid")
    try:
        kind = PublicationKind(body["kind"])
        published_at = datetime.fromisoformat(envelope["published_at"])
        if published_at.tzinfo is None:
            raise ValueError("publication timestamp is naive")
        media = tuple(
            SourceMedia("", MediaKind(ref["kind"]), index, hashlib.sha256(f'source-media-ref:{ref["ref"]}'.encode()).hexdigest())
            for index, ref in enumerate(refs)
        )
        post = SourcePost(profile.id, publication_id, envelope["source_url"], published_at, body["caption_html"], kind, media)
        state.serialize_post(post)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Instagram source publication cannot be reconstructed") from exc
    expected_path = f"/{'reel' if kind is PublicationKind.REEL else 'p'}/{publication_id}"
    if not post.url.removesuffix("/").endswith(expected_path):
        raise ValueError("Instagram source URL does not match publication")
    return profile, post, refs


def _sibling_work(work: dict[str, Any], inbox: Any) -> tuple[list[str], list[str]]:
    inspected = inbox.inspect(work["event_key"])
    event = inspected.get("event")
    rows = inspected.get("work")
    if type(event) is not dict or event.get("event_key") != work["event_key"] or type(rows) is not list:
        raise ValueError("Instagram source work inspection is invalid")
    versions = event.get("versions")
    if type(versions) is not list or not any(
        type(version) is dict and version.get("version") == 1 and version.get("envelope") == work["envelope"]
        for version in versions
    ):
        raise ValueError("Instagram source event version is invalid")
    capabilities: list[str] = []
    keys: list[str] = []
    current_active = False
    for row in rows:
        if type(row) is not dict or row.get("version") != 1:
            continue
        capability = row.get("capability_id")
        if capability not in source_work_routes.CAPABILITY_ROUTES:
            continue
        expected = hashlib.sha256(f'{work["event_key"]}:1:{capability}'.encode()).hexdigest()
        if (row.get("pipeline_id") != capability or row.get("event_key") != work["event_key"]
            or row.get("work_key") != expected
            or row.get("effect_key") != expected or row.get("settings") != {}
            or type(row.get("capability_version")) is not int
            or row["capability_version"] != work["capability_version"]
            or row.get("catalog_revision") != work.get("catalog_revision")):
            raise ValueError("Instagram sibling work identity is invalid")
        if row.get("status") not in {"suppressed", "superseded"}:
            capabilities.append(capability)
            keys.append(expected)
        if expected == work["work_key"]:
            current_active = row.get("status") == "executing" and row.get("lease_token") == work.get("lease_token")
    if not current_active or work["work_key"] not in keys:
        raise ValueError("Instagram source work is not active")
    return sorted(set(capabilities)), sorted(set(keys))


def _write_asset(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("Instagram media directory is unsafe")
    descriptor, temporary = tempfile.mkstemp(prefix=".source-media-", dir=path.parent)
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


def _download_originals(post: SourcePost, refs: list[dict[str, Any]], media_root: Path, media_store: Any) -> DownloadedPublication:
    event_root = media_root / post.publication_id
    if event_root.is_symlink() or event_root.exists() and not event_root.is_dir():
        raise ValueError("Instagram publication media path is unsafe")
    assets: list[DownloadedAsset] = []
    store = media_store or _source_media_client()
    for source, ref in zip(post.media, refs, strict=True):
        content_type = ref.get("content_type")
        suffix = _SUFFIXES.get(content_type)
        if suffix is None or ref.get("kind") != source.kind.value:
            raise ValueError("Instagram source asset type is unsupported")
        downloaded = store.download(ref["ref"])
        data = getattr(downloaded, "data", None)
        if (
            type(data) is not bytes or not 1 <= len(data) <= 8 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != ref.get("sha256")
            or len(data) != ref.get("size_bytes")
            or getattr(downloaded, "content_type", None) != content_type
            or getattr(downloaded, "kind", None) != source.kind.value
        ):
            raise OwnerPending("Source Media Owner returned an invalid Instagram original")
        path = event_root / f"{source.index}{suffix}"
        _write_asset(path, data)
        assets.append(DownloadedAsset(source, path, ref["sha256"], len(data), content_type))
    return DownloadedPublication(tuple(assets), event_root)


def submit(work: dict[str, Any], *, no_post: bool = False, inbox: Any = None, media_store: Any = None) -> str:
    if no_post:
        scan._require_no_post_isolation()
    loaded = config.load_watch_config_for_run(scan.config_path())
    if loaded.revision is None and not no_post:
        raise ValueError("Instagram pipeline requires a live watcher configuration revision")
    profile, post, refs = _validated_work(work, loaded.config.profiles)
    capabilities, keys = _sibling_work(work, inbox if inbox is not None else _inbox_client())
    if any(source_work_routes.CAPABILITY_ROUTES[capability] not in {channel.key for channel in profile.discord_channels} for capability in capabilities):
        raise ValueError("Instagram subscribed route is absent from watcher configuration")
    owner_event_key = f"{post.profile_id}:{post.publication_id}"
    route_record = {
        "owner_event_key": owner_event_key, "source_event_key": work["event_key"],
        "content_hash": work["envelope"]["content_hash"], "profile_id": post.profile_id,
        "publication_id": post.publication_id, "capabilities": capabilities, "work_keys": keys,
        "summary_media_refs": work["envelope"]["media_refs"],
        "outcome": "accepted" if rsshub.is_forwardable(profile, post) else "irrelevant",
    }
    storage = scan.state_path()
    with scan._process_lock(storage, blocking=True) as acquired:
        if not acquired:
            raise OwnerPending("Instagram watcher ledger is busy")
        existing = source_work_routes.read(storage, owner_event_key)
        if existing is not None:
            if {k:v for k,v in existing.items() if k != "summary_media_refs"} != {k:v for k,v in route_record.items() if k != "summary_media_refs"} or ("summary_media_refs" in existing and existing["summary_media_refs"] != route_record["summary_media_refs"]) or work["work_key"] not in existing["work_keys"]:
                raise ValueError("Instagram source publication conflicts with prior handoff")
            if existing["outcome"] == "irrelevant":
                return "irrelevant"
        value = state.load_state(storage)
        owned = any(item["event_key"] == owner_event_key for item in (*value["outbox"], *value["deliveries"]))
        if existing is not None:
            if owned or source_work_routes.terminal(storage, owner_event_key) is not None:
                return "accepted"
            # A process may have stopped after writing the route record and
            # before committing the outbox. Rebuild from durable originals.
        elif owned:
            raise ValueError("Instagram publication already belongs to the watcher")
        if route_record["outcome"] == "irrelevant":
            source_work_routes.write(storage, route_record)
            return "irrelevant"
        root = scan._ensure_media_root()
        downloaded = _download_originals(post, refs, root, media_store)
        prepared = scan._prepare_downloaded_event(
            post, profile, downloaded, scan.ocr_cache_path(), None, scan.RunStats(), news_screening=True,
        )
        event = state._event_for_publication(profile, post, prepared)
        source_work_routes.write(storage, route_record)
        value["outbox"].append(event)
        state.save_state(storage, value)
        return "accepted"


def claim_agent(*, no_post: bool = False) -> dict[str, Any]:
    if no_post:
        scan._require_no_post_isolation()
    storage = scan.state_path()
    loaded = config.load_watch_config_for_run(scan.config_path())
    if loaded.revision is None and not no_post:
        raise ValueError("Instagram agent claim requires live watcher configuration")
    with scan._process_lock(storage, blocking=True) as acquired:
        if not acquired:
            raise OwnerPending("Instagram watcher ledger is busy")
        value = state.load_state(storage)
        profiles = {profile.id: profile for profile in loaded.config.profiles}
        return scan._claim_agent(value, profiles, storage, datetime.now(scan.WIB), scan.RunStats())


def drain(*, no_post: bool = False) -> dict[str, int]:
    """Continue the watcher's text-before-original-media Delivery Owner outbox."""
    if no_post:
        scan._require_no_post_isolation()
    storage = scan.state_path()
    loaded = config.load_watch_config_for_run(scan.config_path())
    if loaded.revision is None and not no_post:
        raise ValueError("Instagram delivery drain requires live watcher configuration")
    with scan._process_lock(storage, blocking=True) as acquired:
        if not acquired:
            raise OwnerPending("Instagram watcher ledger is busy")
        value = state.load_state(storage)
        if no_post:
            return {"delivered": 0, "delivery_legs": 0, "owner_pending": 0, "errors": 0}
        scan._ensure_media_root()
        now = datetime.now(scan.WIB)
        stats = scan.RunStats()
        profiles = {profile.id: profile for profile in loaded.config.profiles}
        state.prune_deliveries(value, now)
        scan._drain_deliveries(value, profiles, storage, stats, now)
        scan._retry_media_cleanup(value, storage, stats, no_post=False)
        state.save_state(storage, value)
        return {
            "delivered": stats.delivered,
            "delivery_legs": stats.delivery_legs,
            "owner_pending": stats.owner_pending,
            "errors": stats.errors,
        }


def main() -> int:
    no_post = os.environ.get("BURSAWATCH_IG_SOURCE_NO_POST") == "1"
    if len(sys.argv) == 2 and sys.argv[1] == "claim-agent":
        result = claim_agent(no_post=no_post)
    elif len(sys.argv) == 2 and sys.argv[1] == "drain":
        result = drain(no_post=no_post)
    elif len(sys.argv) == 1:
        result = {"outcome": submit(json.load(sys.stdin), no_post=no_post)}
    else:
        raise ValueError("unsupported Instagram source owner command")
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
