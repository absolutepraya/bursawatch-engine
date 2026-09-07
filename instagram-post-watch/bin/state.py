from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from models import (
    DownloadedAsset,
    DownloadedPublication,
    FailedAsset,
    MediaKind,
    Profile,
    PublicationKind,
    SourceMedia,
    SourcePost,
    source_locator_digest,
)
from ocr import OCRResult, OCRStatus
from vision_gate import VisionDecision, VisionMode


STATE_VERSION = 1
AGENT_LEASE_DURATION = timedelta(minutes=15)
DELIVERY_RETENTION = timedelta(days=90)

MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_PROFILES = 256
MAX_OUTBOX_EVENTS = 2_000
MAX_DELIVERIES = 4_000
MAX_CLEANUP_ENTRIES = 2_000
MAX_MEDIA_ASSETS = 100
MAX_OCR_RESULTS = 100
MAX_TEXT = 4_000
MAX_CAPTION_HTML = 32_000
MAX_PUBLICATION_URL = 2_048
MAX_LOCAL_PATH = 4_096
MAX_ERROR = 512
MAX_MESSAGE_IDS = 100
MAX_MESSAGE_ID_LENGTH = 128
MAX_ANALYSIS_TEXT = 1_600
MAX_TITLE = 120
MAX_ROUTE = 64

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SAFE_ERROR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.: -]{0,511}$")
_SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}

_ROOT_KEYS = {
    "version",
    "profiles",
    "outbox",
    "deliveries",
    "cleanup",
    "filtered_since_last_heartbeat",
}
_PROFILE_KEYS = {"cursor", "cursor_published_at"}
_EVENT_KEYS = {
    "event_key",
    "profile_id",
    "publication_id",
    "source_publication_url",
    "post",
    "downloaded_publication",
    "ocr_results",
    "vision_decision",
    "agent_phase",
    "agent_lease_until",
    "ready_after",
    "text_index",
    "media_index",
    "text_message_ids",
    "media_message_ids",
    "last_error",
    "delivered_at",
    "cleanup_pending",
    "title",
    "summary",
    "route",
    "is_relevant",
}
_DELIVERY_KEYS = {
    "event_key",
    "profile_id",
    "publication_id",
    "text_message_ids",
    "media_message_ids",
    "delivered_at",
    "cleanup_pending",
}
_CLEANUP_KEYS = {
    "event_key",
    "profile_id",
    "publication_id",
    "media_root",
    "attempts",
    "last_error",
}
_PHASES = {"pending", "awaiting_agent", "ready"}
_ANALYSIS_KEYS = {"title", "summary", "route", "is_relevant"}


def new_state() -> dict:
    return {
        "version": STATE_VERSION,
        "profiles": {},
        "outbox": [],
        "deliveries": [],
        "cleanup": [],
        "filtered_since_last_heartbeat": 0,
    }


def _invalid() -> ValueError:
    return ValueError("instagram-post-watch state is invalid")


def _require_object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise _invalid()
    return value


def _bounded_string(value: object, limit: int, *, allow_empty: bool = False) -> str:
    if type(value) is not str or len(value) > limit or (not allow_empty and not value):
        raise _invalid()
    if any(ord(character) == 0 or ord(character) == 127 for character in value):
        raise _invalid()
    return value


def _safe_component(value: object) -> str:
    candidate = _bounded_string(value, 128)
    if not _SAFE_COMPONENT.fullmatch(candidate):
        raise _invalid()
    return candidate


def _safe_token(value: object, *, allow_empty: bool = False) -> str:
    candidate = _bounded_string(value, 256, allow_empty=allow_empty)
    if candidate and not _SAFE_TOKEN.fullmatch(candidate):
        raise _invalid()
    return candidate


def _safe_error(value: object) -> str:
    candidate = _bounded_string(value, MAX_ERROR)
    if not _SAFE_ERROR.fullmatch(candidate):
        raise _invalid()
    return candidate


def _aware_datetime(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _invalid()
    return value


def _datetime_text(value: object) -> str:
    return _aware_datetime(value).isoformat()


def _parse_aware_datetime(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _safe_local_path(value: object) -> str:
    if isinstance(value, Path):
        value = str(value)
    path_text = _bounded_string(value, MAX_LOCAL_PATH)
    if "://" in path_text or not Path(path_text).is_absolute():
        raise _invalid()
    if any(part in {".", ".."} for part in Path(path_text).parts):
        raise _invalid()
    return path_text


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _invalid() from exc
        if stat.S_ISLNK(mode):
            raise _invalid()


def _validated_media_root(value: object) -> Path:
    root = Path(_safe_local_path(value))
    _reject_symlink_components(root)
    try:
        resolved = root.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise _invalid() from exc
    if resolved == Path(resolved.anchor):
        raise _invalid()
    return root


def _confined_local_path(value: object, root: Path) -> Path:
    path = Path(_safe_local_path(value))
    _reject_symlink_components(root)
    _reject_symlink_components(path)
    try:
        resolved_root = root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        relative = resolved_path.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _invalid() from exc
    if not relative.parts:
        raise _invalid()
    return path


def _safe_publication_url(value: object) -> str:
    url = _bounded_string(value, MAX_PUBLICATION_URL)
    if url != url.strip() or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise _invalid()
    if "?" in url or "#" in url:
        raise _invalid()
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise _invalid() from exc
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"instagram.com", "www.instagram.com"}:
        raise _invalid()
    if parsed.params or parsed.username or parsed.password:
        raise _invalid()
    parts = parsed.path.split("/")
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    if len(parts) != 2 or parts[0] not in {"p", "reel"}:
        raise _invalid()
    _safe_component(parts[1])
    return url


def _media_kind(value: object) -> MediaKind:
    try:
        return MediaKind(value)
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc


def _publication_kind(value: object) -> PublicationKind:
    try:
        return PublicationKind(value)
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc


def _source_locator_digest(media: SourceMedia) -> str:
    digest = _bounded_string(media.locator_digest, 64)
    if not _SAFE_HASH.fullmatch(digest):
        raise _invalid()
    if media.url:
        try:
            if source_locator_digest(media.url) != digest:
                raise _invalid()
        except (TypeError, UnicodeError, ValueError) as exc:
            raise _invalid() from exc
    return digest


def _serialize_source_media(media: SourceMedia) -> dict[str, object]:
    if not isinstance(media, SourceMedia):
        raise _invalid()
    if type(media.index) is not int or not 0 <= media.index < MAX_MEDIA_ASSETS:
        raise _invalid()
    return {
        # Media URLs from RSSHub can be signed CDN URLs. They are deliberately
        # omitted from durable state while a one-way locator identity is retained.
        "url": "",
        "locator_digest": _source_locator_digest(media),
        "kind": _media_kind(media.kind).value,
        "index": media.index,
    }


def _deserialize_source_media(value: object) -> SourceMedia:
    raw = _require_object(value)
    if set(raw) != {"url", "locator_digest", "kind", "index"}:
        raise _invalid()
    if raw["url"] != "":
        raise _invalid()
    locator_digest = _bounded_string(raw["locator_digest"], 64)
    if not _SAFE_HASH.fullmatch(locator_digest):
        raise _invalid()
    index = raw.get("index")
    if type(index) is not int or not 0 <= index < MAX_MEDIA_ASSETS:
        raise _invalid()
    return SourceMedia("", _media_kind(raw.get("kind")), index, locator_digest)


def serialize_post(post: SourcePost) -> dict[str, object]:
    if not isinstance(post, SourcePost):
        raise _invalid()
    media = [_serialize_source_media(item) for item in post.media]
    if len(media) > MAX_MEDIA_ASSETS or len({item["index"] for item in media}) != len(media):
        raise _invalid()
    return {
        "profile_id": _safe_component(post.profile_id),
        "publication_id": _safe_component(post.publication_id),
        "url": _safe_publication_url(post.url),
        "published_at": _datetime_text(post.published_at),
        "caption_html": _bounded_string(post.caption_html, MAX_CAPTION_HTML, allow_empty=True),
        "kind": _publication_kind(post.kind).value,
        "media": media,
    }


def deserialize_post(value: object) -> SourcePost:
    raw = _require_object(value)
    if set(raw) != {"profile_id", "publication_id", "url", "published_at", "caption_html", "kind", "media"}:
        raise _invalid()
    published_at = _parse_aware_datetime(raw["published_at"])
    if published_at is None:
        raise _invalid()
    media_value = raw["media"]
    if type(media_value) is not list or len(media_value) > MAX_MEDIA_ASSETS:
        raise _invalid()
    media = tuple(_deserialize_source_media(item) for item in media_value)
    if len({item.index for item in media}) != len(media):
        raise _invalid()
    return SourcePost(
        profile_id=_safe_component(raw["profile_id"]),
        publication_id=_safe_component(raw["publication_id"]),
        url=_safe_publication_url(raw["url"]),
        published_at=published_at,
        caption_html=_bounded_string(raw["caption_html"], MAX_CAPTION_HTML, allow_empty=True),
        kind=_publication_kind(raw["kind"]),
        media=media,
    )


def _serialize_downloaded_asset(asset: DownloadedAsset) -> dict[str, object]:
    if not isinstance(asset, DownloadedAsset):
        raise _invalid()
    if type(asset.size_bytes) is not int or not 0 <= asset.size_bytes <= 25 * 1024 * 1024:
        raise _invalid()
    digest = _bounded_string(asset.sha256, 64)
    if not _SAFE_HASH.fullmatch(digest):
        raise _invalid()
    content_type = _bounded_string(asset.content_type, 64)
    if content_type not in _CONTENT_TYPES:
        raise _invalid()
    return {
        "source": _serialize_source_media(asset.source),
        "path": _safe_local_path(asset.path),
        "sha256": digest,
        "size_bytes": asset.size_bytes,
        "content_type": content_type,
    }


def _deserialize_downloaded_asset(value: object, media_root: Path) -> DownloadedAsset:
    raw = _require_object(value)
    if set(raw) != {"source", "path", "sha256", "size_bytes", "content_type"}:
        raise _invalid()
    path = _confined_local_path(raw["path"], media_root)
    size_bytes = raw["size_bytes"]
    if type(size_bytes) is not int or not 0 <= size_bytes <= 25 * 1024 * 1024:
        raise _invalid()
    digest = _bounded_string(raw["sha256"], 64)
    if not _SAFE_HASH.fullmatch(digest):
        raise _invalid()
    content_type = _bounded_string(raw["content_type"], 64)
    if content_type not in _CONTENT_TYPES:
        raise _invalid()
    return DownloadedAsset(
        source=_deserialize_source_media(raw["source"]),
        path=path,
        sha256=digest,
        size_bytes=size_bytes,
        content_type=content_type,
    )


def _serialize_failed_asset(asset: FailedAsset) -> dict[str, object]:
    if not isinstance(asset, FailedAsset):
        raise _invalid()
    return {
        "source": _serialize_source_media(asset.source),
        "reason": _safe_token(asset.reason),
    }


def _deserialize_failed_asset(value: object) -> FailedAsset:
    raw = _require_object(value)
    if set(raw) != {"source", "reason"}:
        raise _invalid()
    return FailedAsset(_deserialize_source_media(raw["source"]), _safe_token(raw["reason"]))


def serialize_downloaded_publication(value: DownloadedPublication) -> dict[str, object]:
    if not isinstance(value, DownloadedPublication):
        raise _invalid()
    media_root = Path(_safe_local_path(value.media_root))
    assets = [_serialize_downloaded_asset(asset) for asset in value.assets]
    failed_assets = [_serialize_failed_asset(asset) for asset in value.failed_assets]
    if len(assets) + len(failed_assets) > MAX_MEDIA_ASSETS:
        raise _invalid()
    result = {
        "assets": assets,
        "media_root": str(media_root),
        "failed_assets": failed_assets,
    }
    # Validate the relationship before returning the serialized form.
    deserialize_downloaded_publication(result)
    return result


def deserialize_downloaded_publication(value: object) -> DownloadedPublication:
    raw = _require_object(value)
    if set(raw) != {"assets", "media_root", "failed_assets"}:
        raise _invalid()
    media_root = _validated_media_root(raw["media_root"])
    assets_value = raw["assets"]
    failed_value = raw["failed_assets"]
    if type(assets_value) is not list or type(failed_value) is not list:
        raise _invalid()
    if len(assets_value) + len(failed_value) > MAX_MEDIA_ASSETS:
        raise _invalid()
    assets = tuple(_deserialize_downloaded_asset(item, media_root) for item in assets_value)
    failed_assets = tuple(_deserialize_failed_asset(item) for item in failed_value)
    source_indexes = [asset.source.index for asset in assets] + [asset.source.index for asset in failed_assets]
    if len(set(source_indexes)) != len(source_indexes):
        raise _invalid()
    return DownloadedPublication(assets, media_root, failed_assets)


def _serialize_confidence(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise _invalid()
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise _invalid()
    return parsed


def serialize_ocr_result(value: OCRResult) -> dict[str, object]:
    if not isinstance(value, OCRResult):
        raise _invalid()
    status = OCRStatus(value.status)
    text = _bounded_string(value.text, MAX_TEXT, allow_empty=True)
    confidence = _serialize_confidence(value.confidence)
    min_confidence = _serialize_confidence(value.min_confidence)
    if status is OCRStatus.NO_TEXT and (text or confidence is not None or min_confidence is not None):
        raise _invalid()
    if status is OCRStatus.SUCCESS and (not text or confidence is None or min_confidence is None):
        raise _invalid()
    if min_confidence is not None and confidence is not None and min_confidence > confidence:
        raise _invalid()
    languages = tuple(value.languages)
    if len(languages) > 8 or any(type(item) is not str or not _SAFE_COMPONENT.fullmatch(item) for item in languages):
        raise _invalid()
    if len(set(languages)) != len(languages):
        raise _invalid()
    return {
        "status": status.value,
        "text": text,
        "confidence": confidence,
        "min_confidence": min_confidence,
        "engine_id": _safe_token(value.engine_id, allow_empty=True),
        "model_version": _safe_token(value.model_version, allow_empty=True),
        "languages": list(languages),
        "error": None if value.error is None else _safe_error(value.error),
    }


def deserialize_ocr_result(value: object) -> OCRResult:
    raw = _require_object(value)
    expected = {"status", "text", "confidence", "min_confidence", "engine_id", "model_version", "languages", "error"}
    if set(raw) != expected:
        raise _invalid()
    try:
        status = OCRStatus(raw["status"])
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc
    text = _bounded_string(raw["text"], MAX_TEXT, allow_empty=True)
    confidence = _serialize_confidence(raw["confidence"])
    min_confidence = _serialize_confidence(raw["min_confidence"])
    if status is OCRStatus.NO_TEXT and (text or confidence is not None or min_confidence is not None):
        raise _invalid()
    if status is OCRStatus.SUCCESS and (not text or confidence is None or min_confidence is None):
        raise _invalid()
    if min_confidence is not None and confidence is not None and min_confidence > confidence:
        raise _invalid()
    languages = raw["languages"]
    if type(languages) is not list or len(languages) > 8:
        raise _invalid()
    language_values = tuple(_safe_component(item) for item in languages)
    if len(set(language_values)) != len(language_values):
        raise _invalid()
    error = raw["error"]
    if error is not None:
        error = _safe_error(error)
    return OCRResult(
        status=status,
        text=text,
        confidence=confidence,
        min_confidence=min_confidence,
        engine_id=_safe_token(raw["engine_id"], allow_empty=True),
        model_version=_safe_token(raw["model_version"], allow_empty=True),
        languages=language_values,
        error=error,
    )


def serialize_vision_decision(value: VisionDecision) -> dict[str, object]:
    if not isinstance(value, VisionDecision):
        raise _invalid()
    try:
        mode = VisionMode(value.mode)
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc
    asset_ids = tuple(value.asset_ids)
    if len(asset_ids) > MAX_MEDIA_ASSETS or any(type(item) is not int or not 0 <= item < MAX_MEDIA_ASSETS for item in asset_ids):
        raise _invalid()
    asset_paths = []
    for item in value.asset_paths:
        path = Path(_safe_local_path(item))
        _reject_symlink_components(path)
        asset_paths.append(str(path))
    if len(asset_paths) > MAX_MEDIA_ASSETS:
        raise _invalid()
    analysis_ids = [_safe_token(item) for item in value.analysis_ids]
    if len(analysis_ids) > MAX_MEDIA_ASSETS:
        raise _invalid()
    return {
        "mode": mode.value,
        "reason": _bounded_string(value.reason, 128),
        "asset_ids": list(asset_ids),
        "asset_paths": asset_paths,
        "analysis_ids": analysis_ids,
    }


def deserialize_vision_decision(value: object) -> VisionDecision:
    raw = _require_object(value)
    expected = {"mode", "reason", "asset_ids", "asset_paths", "analysis_ids"}
    if set(raw) != expected:
        raise _invalid()
    try:
        mode = VisionMode(raw["mode"])
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc
    asset_ids = raw["asset_ids"]
    asset_paths = raw["asset_paths"]
    analysis_ids = raw["analysis_ids"]
    if type(asset_ids) is not list or type(asset_paths) is not list or type(analysis_ids) is not list:
        raise _invalid()
    if len(asset_ids) > MAX_MEDIA_ASSETS or any(type(item) is not int or not 0 <= item < MAX_MEDIA_ASSETS for item in asset_ids):
        raise _invalid()
    if len(asset_paths) > MAX_MEDIA_ASSETS or len(analysis_ids) > MAX_MEDIA_ASSETS:
        raise _invalid()
    return VisionDecision(
        mode=mode,
        reason=_bounded_string(raw["reason"], 128),
        asset_ids=tuple(asset_ids),
        asset_paths=tuple(Path(_safe_local_path(item)) for item in asset_paths),
        analysis_ids=tuple(_safe_token(item) for item in analysis_ids),
    )


def _validate_message_ids(value: object) -> list[str]:
    if type(value) is not list or len(value) > MAX_MESSAGE_IDS:
        raise _invalid()
    result = []
    for item in value:
        candidate = _bounded_string(item, MAX_MESSAGE_ID_LENGTH)
        if not _SAFE_TOKEN.fullmatch(candidate):
            raise _invalid()
        result.append(candidate)
    return result


def _validate_optional_analysis(value: object, key: str) -> None:
    if value is None:
        return
    if key == "is_relevant":
        if type(value) is not bool:
            raise _invalid()
        return
    limit = MAX_TITLE if key == "title" else MAX_ANALYSIS_TEXT if key == "summary" else MAX_ROUTE
    candidate = _bounded_string(value, limit)
    if "http://" in candidate.lower() or "https://" in candidate.lower():
        raise _invalid()
    if key == "route" and not _SAFE_TOKEN.fullmatch(candidate):
        raise _invalid()


def _validate_event(value: object) -> dict[str, object]:
    event = _require_object(value)
    if set(event) != _EVENT_KEYS:
        raise _invalid()
    profile_id = _safe_component(event["profile_id"])
    publication_id = _safe_component(event["publication_id"])
    event_key = _safe_token(event["event_key"])
    if event_key != f"{profile_id}:{publication_id}":
        raise _invalid()
    post = deserialize_post(event["post"])
    if post.profile_id != profile_id or post.publication_id != publication_id:
        raise _invalid()
    source_publication_url = _safe_publication_url(event["source_publication_url"])
    if source_publication_url != post.url:
        raise _invalid()
    downloaded = event["downloaded_publication"]
    downloaded_value = None
    if downloaded is not None:
        downloaded_value = deserialize_downloaded_publication(downloaded)
    ocr_results = event["ocr_results"]
    if type(ocr_results) is not list or len(ocr_results) > MAX_OCR_RESULTS:
        raise _invalid()
    for result in ocr_results:
        deserialize_ocr_result(result)
    vision = event["vision_decision"]
    vision_value = None
    if vision is not None:
        vision_value = deserialize_vision_decision(vision)
        if vision_value.asset_paths:
            if downloaded_value is None:
                raise _invalid()
            for path in vision_value.asset_paths:
                _confined_local_path(path, downloaded_value.media_root)
    phase = event["agent_phase"]
    if type(phase) is not str or phase not in _PHASES:
        raise _invalid()
    lease = event["agent_lease_until"]
    if lease is not None and type(lease) is not str:
        raise _invalid()
    if phase != "awaiting_agent" and lease is not None:
        raise _invalid()
    for key in ("ready_after", "delivered_at"):
        timestamp = event[key]
        if timestamp is not None and (type(timestamp) is not str or _parse_aware_datetime(timestamp) is None):
            raise _invalid()
    for key in ("text_index", "media_index"):
        index = event[key]
        if type(index) is not int or not 0 <= index <= MAX_MEDIA_ASSETS:
            raise _invalid()
    _validate_message_ids(event["text_message_ids"])
    _validate_message_ids(event["media_message_ids"])
    last_error = event["last_error"]
    if last_error is not None:
        _safe_error(last_error)
    if type(event["cleanup_pending"]) is not bool:
        raise _invalid()
    for key in _ANALYSIS_KEYS:
        _validate_optional_analysis(event[key], key)
    return event


def _validate_delivery(value: object) -> dict[str, object]:
    delivery = _require_object(value)
    if set(delivery) != _DELIVERY_KEYS:
        raise _invalid()
    profile_id = _safe_component(delivery["profile_id"])
    publication_id = _safe_component(delivery["publication_id"])
    if _safe_token(delivery["event_key"]) != f"{profile_id}:{publication_id}":
        raise _invalid()
    _validate_message_ids(delivery["text_message_ids"])
    _validate_message_ids(delivery["media_message_ids"])
    if _parse_aware_datetime(delivery["delivered_at"]) is None:
        raise _invalid()
    if type(delivery["cleanup_pending"]) is not bool:
        raise _invalid()
    return delivery


def _validate_cleanup(value: object) -> dict[str, object]:
    cleanup = _require_object(value)
    if set(cleanup) != _CLEANUP_KEYS:
        raise _invalid()
    profile_id = _safe_component(cleanup["profile_id"])
    publication_id = _safe_component(cleanup["publication_id"])
    if _safe_token(cleanup["event_key"]) != f"{profile_id}:{publication_id}":
        raise _invalid()
    media_root = cleanup["media_root"]
    if media_root is not None:
        _validated_media_root(media_root)
    attempts = cleanup["attempts"]
    if type(attempts) is not int or not 0 <= attempts <= MAX_CLEANUP_ENTRIES:
        raise _invalid()
    if cleanup["last_error"] is not None:
        _safe_error(cleanup["last_error"])
    return cleanup


def _validate_state(value: object) -> dict[str, object]:
    root = _require_object(value)
    if set(root) != _ROOT_KEYS or root["version"] != STATE_VERSION or type(root["version"]) is not int:
        raise _invalid()
    profiles = root["profiles"]
    if type(profiles) is not dict or len(profiles) > MAX_PROFILES:
        raise _invalid()
    for profile_id, record_value in profiles.items():
        if not isinstance(profile_id, str) or not _SAFE_COMPONENT.fullmatch(profile_id):
            raise _invalid()
        record = _require_object(record_value)
        if set(record) != _PROFILE_KEYS:
            raise _invalid()
        cursor = record["cursor"]
        if cursor is not None:
            _safe_component(cursor)
        cursor_time = record["cursor_published_at"]
        if cursor_time is not None and _parse_aware_datetime(cursor_time) is None:
            raise _invalid()
    outbox = root["outbox"]
    if type(outbox) is not list or len(outbox) > MAX_OUTBOX_EVENTS:
        raise _invalid()
    event_keys: set[str] = set()
    for event in outbox:
        normalized = _validate_event(event)
        if normalized["event_key"] in event_keys:
            raise _invalid()
        event_keys.add(normalized["event_key"])
    deliveries = root["deliveries"]
    if type(deliveries) is not list or len(deliveries) > MAX_DELIVERIES:
        raise _invalid()
    for delivery in deliveries:
        _validate_delivery(delivery)
    cleanup = root["cleanup"]
    if type(cleanup) is not list or len(cleanup) > MAX_CLEANUP_ENTRIES:
        raise _invalid()
    cleanup_keys: set[str] = set()
    for item in cleanup:
        normalized = _validate_cleanup(item)
        if normalized["event_key"] in cleanup_keys:
            raise _invalid()
        cleanup_keys.add(normalized["event_key"])
    filtered = root["filtered_since_last_heartbeat"]
    if type(filtered) is not int or not 0 <= filtered <= MAX_DELIVERIES:
        raise _invalid()
    return root


def _absolute_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise _invalid()
    return Path(os.path.abspath(path))


def _check_parent_chain(path: Path) -> None:
    current = path.parent
    missing: list[Path] = []
    while True:
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise _invalid()
            current = parent
            continue
        except OSError as exc:
            raise _invalid() from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise _invalid()
        break
    # The list is intentionally retained until the existing ancestor has been
    # checked. It prevents a missing path from being mistaken for a safe path
    # when an ancestor is a symlink.
    del missing


def _check_target(path: Path, *, allow_missing: bool) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        if allow_missing:
            return False
        raise _invalid()
    except OSError as exc:
        raise _invalid() from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise _invalid()
    return True


def load_state(path: Path) -> dict:
    target = _absolute_path(path)
    _check_parent_chain(target)
    if not _check_target(target, allow_missing=True):
        return new_state()
    try:
        if target.stat().st_size > MAX_STATE_BYTES:
            raise _invalid()
        raw = target.read_text(encoding="utf-8")
        value = json.loads(raw)
    except ValueError:
        raise _invalid()
    except Exception as exc:
        raise _invalid() from exc
    return _validate_state(value)


def _serialized_state_bytes(value: dict) -> bytes:
    _validate_state(value)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise _invalid() from exc
    if len(serialized) > MAX_STATE_BYTES:
        raise ValueError("instagram-post-watch state exceeds the size limit")
    return serialized


def save_state(path: Path, value: dict) -> None:
    serialized = _serialized_state_bytes(value)
    target = _absolute_path(path)
    _check_parent_chain(target)
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise _invalid() from exc
    _check_parent_chain(target)
    _check_target(target, allow_missing=True)
    temporary_name: str | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except ValueError:
        raise _invalid()
    except Exception as exc:
        raise _invalid() from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except Exception:
                pass


def _profile_map(profiles: object) -> dict[str, Profile]:
    if isinstance(profiles, Mapping):
        result = dict(profiles)
    elif hasattr(profiles, "profiles"):
        result = {profile.id: profile for profile in profiles.profiles}
    elif isinstance(profiles, Sequence) and not isinstance(profiles, (str, bytes, bytearray)):
        result = {profile.id: profile for profile in profiles}
    else:
        raise _invalid()
    if any(not isinstance(profile, Profile) for profile in result.values()):
        raise _invalid()
    return result


def _prepare_metadata(prepared: object, publication: SourcePost) -> dict[str, object]:
    if type(prepared) is not dict:
        raise _invalid()
    post = prepared.get("post", publication)
    if not isinstance(post, SourcePost) or post.profile_id != publication.profile_id or post.publication_id != publication.publication_id:
        raise _invalid()
    downloaded = prepared.get("downloaded_publication", prepared.get("downloaded_assets"))
    downloaded_value = None if downloaded is None else serialize_downloaded_publication(downloaded)
    ocr_values = prepared.get("ocr_results", prepared.get("ocr", ()))
    if ocr_values is None:
        ocr_values = ()
    if not isinstance(ocr_values, Sequence) or isinstance(ocr_values, (str, bytes, bytearray)):
        raise _invalid()
    ocr_serialized = [serialize_ocr_result(result) for result in ocr_values]
    vision = prepared.get("vision_decision", prepared.get("vision"))
    vision_value = None if vision is None else serialize_vision_decision(vision)
    ready_after = prepared.get("ready_after")
    if ready_after is not None:
        if isinstance(ready_after, datetime):
            ready_after = _datetime_text(ready_after)
        elif _parse_aware_datetime(ready_after) is None:
            raise _invalid()
    return {
        "post": serialize_post(post),
        "downloaded_publication": downloaded_value,
        "ocr_results": ocr_serialized,
        "vision_decision": vision_value,
        "ready_after": ready_after,
    }


def _event_for_publication(profile: Profile, publication: SourcePost, prepared: object) -> dict[str, object]:
    metadata = _prepare_metadata(prepared, publication)
    event_key = f"{_safe_component(profile.id)}:{_safe_component(publication.publication_id)}"
    event = {
        "event_key": event_key,
        "profile_id": profile.id,
        "publication_id": publication.publication_id,
        "source_publication_url": publication.url,
        **metadata,
        "agent_phase": "pending" if profile.uses_llm else "ready",
        "agent_lease_until": None,
        "text_index": 0,
        "media_index": 0,
        "text_message_ids": [],
        "media_message_ids": [],
        "last_error": None,
        "delivered_at": None,
        "cleanup_pending": False,
        "title": None,
        "summary": None,
        "route": None,
        "is_relevant": None,
    }
    _validate_event(event)
    return event


def _publication_order(post: SourcePost) -> tuple[datetime, str]:
    _aware_datetime(post.published_at)
    return post.published_at, post.publication_id


def _id_is_newer(candidate: str, cursor: str) -> bool:
    if candidate == cursor:
        return False
    if candidate.isdigit() and cursor.isdigit():
        return int(candidate) > int(cursor)
    return candidate > cursor


def _is_newer_than_cursor(post: SourcePost, cursor: str, cursor_time: datetime | None) -> bool:
    if post.publication_id == cursor:
        return False
    if cursor_time is not None:
        if post.published_at > cursor_time:
            return True
        if post.published_at < cursor_time:
            return False
    return _id_is_newer(post.publication_id, cursor)


def observe_publications(
    value: dict,
    profile: Profile,
    publications: Sequence[SourcePost],
    now: datetime,
    prepare_event,
) -> int:
    _validate_state(value)
    if not isinstance(profile, Profile) or not isinstance(publications, Sequence) or isinstance(publications, (str, bytes, bytearray)):
        raise _invalid()
    _aware_datetime(now)
    if not profile.enabled:
        return 0
    posts = list(publications)
    for publication in posts:
        if not isinstance(publication, SourcePost) or publication.profile_id != profile.id:
            raise _invalid()
        _aware_datetime(publication.published_at)
    ordered: list[SourcePost] = []
    by_id: dict[str, SourcePost] = {}
    for publication in posts:
        previous = by_id.get(publication.publication_id)
        if previous is None or _publication_order(publication) > _publication_order(previous):
            by_id[publication.publication_id] = publication
    ordered = sorted(by_id.values(), key=_publication_order)

    record = value["profiles"].get(profile.id)
    if record is None:
        newest = ordered[-1] if ordered else None
        value["profiles"][profile.id] = {
            "cursor": newest.publication_id if newest else None,
            "cursor_published_at": _datetime_text(newest.published_at) if newest else None,
        }
        return 0
    if record["cursor"] is None:
        newest = ordered[-1] if ordered else None
        record["cursor"] = newest.publication_id if newest else None
        record["cursor_published_at"] = _datetime_text(newest.published_at) if newest else None
        return 0
    cursor = record["cursor"]
    cursor_time = _parse_aware_datetime(record["cursor_published_at"])
    fresh = [post for post in ordered if _is_newer_than_cursor(post, cursor, cursor_time)]
    known = {
        event["event_key"] for event in value["outbox"]
    } | {
        delivery["event_key"] for delivery in value["deliveries"]
    }
    new_events: list[dict[str, object]] = []
    try:
        for publication in fresh:
            event_key = f"{profile.id}:{publication.publication_id}"
            if event_key in known:
                continue
            new_events.append(_event_for_publication(profile, publication, prepare_event(publication)))
            known.add(event_key)
    except Exception as exc:
        # Do not advance the cursor or append a partial outbox when media/OCR
        # preparation fails for any publication in this observation.
        raise ValueError("publication preparation failed") from exc
    value["outbox"].extend(new_events)
    if fresh:
        newest = fresh[-1]
        record["cursor"] = newest.publication_id
        record["cursor_published_at"] = _datetime_text(newest.published_at)
    return len(new_events)


def is_ready(event: dict, now: datetime) -> bool:
    if type(event) is not dict:
        return False
    _aware_datetime(now)
    ready_after = event.get("ready_after")
    if ready_after is None:
        return True
    parsed = _parse_aware_datetime(ready_after)
    return parsed is not None and parsed <= now


def _expire_agent_leases(value: dict, now: datetime) -> None:
    for event in value["outbox"]:
        if event["agent_phase"] != "awaiting_agent":
            continue
        lease = _parse_aware_datetime(event["agent_lease_until"])
        if lease is None or lease <= now:
            event["agent_phase"] = "pending"
            event["agent_lease_until"] = None


def claim_oldest_agent(value: dict, profiles: object, now: datetime) -> dict | None:
    _validate_state(value)
    _aware_datetime(now)
    profile_map = _profile_map(profiles)
    _expire_agent_leases(value, now)
    for event in value["outbox"]:
        profile = profile_map.get(event["profile_id"])
        if profile is not None and profile.uses_llm and event["agent_phase"] == "pending" and is_ready(event, now):
            event["agent_phase"] = "awaiting_agent"
            event["agent_lease_until"] = (now + AGENT_LEASE_DURATION).isoformat()
            return event
    return None


def _valid_event_key(event_key: object) -> str:
    candidate = _bounded_string(event_key, 257)
    if candidate.count(":") != 1:
        raise _invalid()
    profile_id, publication_id = candidate.split(":")
    return f"{_safe_component(profile_id)}:{_safe_component(publication_id)}"


def awaiting_analysis_event(value: dict, event_key: str) -> dict:
    _validate_state(value)
    normalized_key = _valid_event_key(event_key)
    for event in value["outbox"]:
        if event["event_key"] == normalized_key:
            if event["agent_phase"] != "awaiting_agent":
                raise ValueError("analysis event is not awaiting the agent")
            return event
    raise ValueError("analysis event is not in durable state")


def _active_lease(event: dict, now: datetime) -> None:
    lease = _parse_aware_datetime(event.get("agent_lease_until"))
    if lease is None or lease <= now:
        raise ValueError("analysis lease is not active")


def _validate_analysis(value: object) -> dict[str, object]:
    if type(value) is not dict or not value or not set(value).issubset(_ANALYSIS_KEYS):
        raise ValueError("analysis fields are invalid")
    result: dict[str, object] = {}
    for key, item in value.items():
        if item is None:
            raise ValueError("analysis fields are invalid")
        _validate_optional_analysis(item, key)
        result[key] = item
    return result


def submit_analysis(
    value: dict,
    event_key: str,
    analysis: dict,
    now: datetime | None = None,
) -> dict:
    reference_time = now or datetime.now(UTC)
    _aware_datetime(reference_time)
    normalized = _validate_analysis(analysis)
    event = awaiting_analysis_event(value, event_key)
    _active_lease(event, reference_time)
    event.update(normalized)
    event["agent_phase"] = "ready"
    event["agent_lease_until"] = None
    _validate_event(event)
    return event


def discard_analysis(value: dict, event_key: str, now: datetime | None = None) -> None:
    reference_time = now or datetime.now(UTC)
    _aware_datetime(reference_time)
    event = awaiting_analysis_event(value, event_key)
    _active_lease(event, reference_time)
    downloaded = event["downloaded_publication"]
    media_root = None
    if downloaded is not None:
        media_root = str(deserialize_downloaded_publication(downloaded).media_root)
    cleanup_entry = {
        "event_key": event["event_key"],
        "profile_id": event["profile_id"],
        "publication_id": event["publication_id"],
        "media_root": media_root,
        "attempts": 0,
        "last_error": None,
    }
    _validate_cleanup(cleanup_entry)
    candidate = {
        **value,
        "outbox": [item for item in value["outbox"] if item is not event],
        "cleanup": [*value["cleanup"], cleanup_entry],
        "filtered_since_last_heartbeat": value["filtered_since_last_heartbeat"] + 1,
    }
    _validate_state(candidate)
    value["cleanup"].append(cleanup_entry)
    value["outbox"].remove(event)
    value["filtered_since_last_heartbeat"] += 1
    _validate_state(value)


def queue_media_cleanup(
    value: dict,
    event_key: str,
    profile_id: str,
    publication_id: str,
    media_root: str | None,
) -> dict[str, object]:
    _validate_state(value)
    profile_id = _safe_component(profile_id)
    publication_id = _safe_component(publication_id)
    event_key = _safe_token(event_key)
    if event_key != f"{profile_id}:{publication_id}":
        raise _invalid()
    cleanup_entry = {
        "event_key": event_key,
        "profile_id": profile_id,
        "publication_id": publication_id,
        "media_root": media_root,
        "attempts": 0,
        "last_error": None,
    }
    _validate_cleanup(cleanup_entry)
    for item in value["cleanup"]:
        if item["event_key"] == event_key:
            return item
    candidate = {**value, "cleanup": [*value["cleanup"], cleanup_entry]}
    _validate_state(candidate)
    value["cleanup"].append(cleanup_entry)
    return cleanup_entry


def prune_deliveries(value: dict, now: datetime) -> None:
    _validate_state(value)
    _aware_datetime(now)
    cutoff = now - DELIVERY_RETENTION
    value["deliveries"][:] = [
        delivery
        for delivery in value["deliveries"]
        if _parse_aware_datetime(delivery["delivered_at"]) >= cutoff
    ]


def record_delivery(
    value: dict,
    event: dict,
    delivered_at: datetime,
    *,
    text_message_ids: Sequence[str] | None = None,
    media_message_ids: Sequence[str] | None = None,
    cleanup_pending: bool = False,
) -> dict:
    _validate_state(value)
    _aware_datetime(delivered_at)
    _validate_event(event)
    text_ids = list(event["text_message_ids"] if text_message_ids is None else text_message_ids)
    media_ids = list(event["media_message_ids"] if media_message_ids is None else media_message_ids)
    delivery = {
        "event_key": event["event_key"],
        "profile_id": event["profile_id"],
        "publication_id": event["publication_id"],
        "text_message_ids": text_ids,
        "media_message_ids": media_ids,
        "delivered_at": delivered_at.isoformat(),
        "cleanup_pending": cleanup_pending,
    }
    _validate_delivery(delivery)
    value["deliveries"] = [item for item in value["deliveries"] if item["event_key"] != delivery["event_key"]]
    value["deliveries"].append(delivery)
    prune_deliveries(value, delivered_at)
    return delivery


def take_filtered_since_last_heartbeat(value: dict) -> int:
    _validate_state(value)
    filtered = value["filtered_since_last_heartbeat"]
    value["filtered_since_last_heartbeat"] = 0
    return filtered
