from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Iterator
from zoneinfo import ZoneInfo

import requests

import agent_protocol
import config
import discord
import media
import ocr
import render
import rsshub
import state
import vision_gate
from models import (
    DownloadLimits,
    DownloadedAsset,
    DownloadedPublication,
    FailedAsset,
    MediaKind,
    Profile,
    PublicationKind,
    SourceMedia,
    SourcePost,
)
from ocr import OCRResult, OCRStatus


WIB = ZoneInfo("Asia/Jakarta")
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
WATCHER_HEARTBEAT_NAME = "instagram-post"
OWNER_MENTION = "<@443342168434933760>"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "watches.json"
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.json"
DEFAULT_MEDIA_ROOT = Path(__file__).resolve().parent.parent / "state" / "media"
DEFAULT_OCR_CACHE_ROOT = Path(__file__).resolve().parent.parent / "state" / "ocr-cache"
MAX_REASON_CHARACTERS = 180
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(?:token|password|secret|cookie|authorization|session)\s*[:=]\s*[^\s,;]+"
)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])(?:~|/(?:Users|home|tmp|var|private|opt|srv|etc))[^\s,;]*")


@dataclass
class RunStats:
    fetched: int = 0
    filtered: int = 0
    queued: int = 0
    ocr: int = 0
    vision_fallback: int = 0
    delivered: int = 0
    errors: int = 0
    degraded: bool = False
    needs_attention: bool = False
    reasons: list[str] = field(default_factory=list)

    def note_error(self, reason: str, *, count: int = 1) -> None:
        self.degraded = True
        self.needs_attention = True
        self.errors += max(1, count)
        safe = _sanitize_reason(reason)
        if safe and safe not in self.reasons:
            self.reasons.append(safe)

    def note_media_failure(self, profile: Profile) -> None:
        self.note_error(f"{profile.handle}: media asset unavailable")

    def note_ocr_failure(self, profile: Profile) -> None:
        self.note_error(f"{profile.handle}: OCR degraded")

    def tokens(self) -> str:
        return (
            f"{self.fetched} fetched · {self.filtered} filtered · {self.queued} queued · "
            f"{self.ocr} OCR · {self.vision_fallback} vision fallback · "
            f"{self.delivered} delivered · {self.errors} errors"
        )


def _sanitize_reason(reason: object) -> str:
    value = " ".join(str(reason).split())
    value = _SENSITIVE_VALUE_RE.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>", value)
    value = _URL_RE.sub("<external source>", value)
    value = _ABSOLUTE_PATH_RE.sub("<local path>", value)
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return value[:MAX_REASON_CHARACTERS].strip()


def state_path() -> Path:
    return Path(os.environ.get("INSTAGRAM_POST_WATCH_STATE_PATH", str(DEFAULT_STATE_PATH)))


def config_path() -> Path:
    return Path(os.environ.get("INSTAGRAM_POST_WATCH_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))


def media_root_path() -> Path:
    configured = os.environ.get("INSTAGRAM_POST_WATCH_MEDIA_ROOT")
    if configured:
        return Path(configured)
    if os.environ.get("INSTAGRAM_POST_WATCH_STATE_PATH"):
        return state_path().parent / "media"
    return DEFAULT_MEDIA_ROOT


def ocr_cache_path() -> Path:
    configured = os.environ.get("INSTAGRAM_POST_WATCH_OCR_CACHE_PATH")
    if configured:
        return Path(configured)
    if os.environ.get("INSTAGRAM_POST_WATCH_STATE_PATH"):
        return state_path().parent / "ocr-cache"
    return DEFAULT_OCR_CACHE_ROOT


def _ensure_media_root() -> Path:
    root = media_root_path()
    if not root.is_absolute() or root == Path(root.anchor) or any(part in {".", ".."} for part in root.parts):
        raise ValueError("watcher media root is invalid")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("watcher media root is invalid")
    # agent_protocol validates the same root when it closes the wake payload.
    os.environ["INSTAGRAM_POST_WATCH_MEDIA_ROOT"] = str(root)
    return root


def _no_post(dry_run: bool | None) -> bool:
    return bool(dry_run) or os.environ.get("INSTAGRAM_POST_WATCH_NO_POST") == "1"


@contextmanager
def _process_lock(storage: Path, *, blocking: bool) -> Iterator[bool]:
    storage.parent.mkdir(parents=True, exist_ok=True)
    lock_path = storage.parent / "run.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle, flags)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def format_heartbeat(now: datetime, stats: RunStats) -> str:
    suffix = f" · {stats.reasons[0]}" if stats.reasons else ""
    attention = f" {OWNER_MENTION}" if stats.degraded or stats.needs_attention else ""
    warning = " ⚠️" if stats.degraded else ""
    return (
        f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · "
        f"{stats.tokens()}{suffix}{attention}{warning}"
    )


def format_fatal(now: datetime, reason: object) -> str:
    failure = _sanitize_reason(reason)
    return f"❌ {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {failure} {OWNER_MENTION}"


def _next_deliverable_index(value: dict, profiles: dict[str, Profile], now: datetime) -> int | None:
    for index, event in enumerate(value["outbox"]):
        profile = profiles.get(event["profile_id"])
        if profile is None:
            continue
        if not state.is_ready(event, now):
            continue
        if profile.uses_llm and event.get("agent_phase") != "ready":
            continue
        return index
    return None


def _target_channel(profile: Profile, event: dict) -> str:
    if not profile.enable_llm_routing:
        return profile.discord_channels[0].channel_id
    route = event.get("route")
    if not isinstance(route, str):
        raise ValueError("analysis route is unavailable")
    return profile.channel_for(route).channel_id


def _source_media_by_index(post: SourcePost, downloaded: DownloadedPublication) -> tuple[DownloadedAsset, ...]:
    expected = {item.index: item.kind for item in post.media}
    selected: dict[int, DownloadedAsset] = {}
    for asset in sorted(downloaded.assets, key=lambda item: item.source.index):
        if asset.source.index in expected and asset.source.kind is expected[asset.source.index]:
            if asset.source.index in selected:
                raise ValueError("source media indexes are duplicated")
            selected[asset.source.index] = asset
    if set(selected) != set(expected):
        raise ValueError("source media is unavailable")
    return tuple(selected[index] for index in sorted(expected))


def _cleanup_entry(event: dict, media_root: str | None) -> dict[str, object]:
    return {
        "event_key": event["event_key"],
        "profile_id": event["profile_id"],
        "publication_id": event["publication_id"],
        "media_root": media_root,
        "attempts": 0,
        "last_error": None,
    }


def _delivery_media_root(event: dict) -> str | None:
    raw = event.get("downloaded_publication")
    if raw is None:
        return None
    try:
        return str(state.deserialize_downloaded_publication(raw).media_root)
    except ValueError:
        return None


def _retry_media_cleanup(value: dict, storage: Path, stats: RunStats, *, no_post: bool) -> None:
    if no_post:
        return
    changed = False
    for item in list(value["cleanup"]):
        media_root = item.get("media_root")
        try:
            if media_root is not None:
                root = Path(str(media_root))
                media.cleanup_event_media(root.parent, str(item["publication_id"]))
            value["cleanup"].remove(item)
            for delivery in value["deliveries"]:
                if delivery["event_key"] == item["event_key"]:
                    delivery["cleanup_pending"] = False
            changed = True
        except Exception:
            item["attempts"] = int(item.get("attempts", 0)) + 1
            item["last_error"] = "media cleanup failed"
            stats.note_error("media cleanup failed")
            changed = True
    if changed:
        state.save_state(storage, value)


def _retry_cleanup(value: dict, dry_run: bool, storage: Path, stats: RunStats) -> None:
    """Compatibility-shaped helper for the X watcher delivery pattern."""
    _retry_media_cleanup(value, storage, stats, no_post=dry_run)


def _finalize_delivery(
    value: dict,
    event_index: int,
    storage: Path,
    stats: RunStats,
    now: datetime,
) -> bool:
    event = value["outbox"][event_index]
    media_root = _delivery_media_root(event)
    state.record_delivery(
        value,
        event,
        now,
        text_message_ids=event["text_message_ids"],
        media_message_ids=event["media_message_ids"],
        cleanup_pending=media_root is not None,
    )
    value["outbox"].pop(event_index)
    if media_root is not None:
        value["cleanup"].append(_cleanup_entry(event, media_root))
    state.save_state(storage, value)
    stats.delivered += 1
    return True


def _deliver(
    value: dict,
    profiles: dict[str, Profile],
    event_index: int,
    dry_run: bool,
    storage: Path,
    stats: RunStats,
    now: datetime | None = None,
) -> bool:
    if dry_run:
        return False
    now = now or datetime.now(WIB)
    event = value["outbox"][event_index]
    profile = profiles[event["profile_id"]]
    post = state.deserialize_post(event["post"])
    downloaded_raw = event.get("downloaded_publication")
    if downloaded_raw is None:
        event["last_error"] = "downloaded media is unavailable"
        stats.note_error("downloaded media is unavailable")
        state.save_state(storage, value)
        return False
    downloaded = state.deserialize_downloaded_publication(downloaded_raw)
    channel_id = _target_channel(profile, event)
    messages = render.render_publication(
        profile,
        post,
        event.get("summary") if profile.enable_llm_summary else None,
        event.get("title") if profile.enable_llm_title else None,
    )
    try:
        if event["text_index"] < len(messages):
            index = event["text_index"]
            message_id = discord.post_text(
                messages[index],
                channel_id,
                False,
                discord.nonce(event["event_key"], f"text:{index}"),
            )
            if message_id is not None:
                event["text_message_ids"].append(message_id)
            event["text_index"] += 1
            state.save_state(storage, value)
            return True

        original_assets = _source_media_by_index(post, downloaded)
        if profile.forward_media and event["media_index"] < len(original_assets):
            index = event["media_index"]
            asset = original_assets[index]
            message_id = discord.post_media(
                asset.path,
                channel_id,
                False,
                discord.nonce(event["event_key"], f"media:{index}"),
            )
            if message_id is not None:
                event["media_message_ids"].append(message_id)
            event["media_index"] += 1
            state.save_state(storage, value)
            return True

        return _finalize_delivery(value, event_index, storage, stats, now)
    except Exception:
        event["last_error"] = "Discord delivery failed"
        stats.note_error("Discord delivery failed")
        state.save_state(storage, value)
        return False


def _drain_deliveries(
    value: dict,
    profiles: dict[str, Profile],
    storage: Path,
    stats: RunStats,
    now: datetime,
    *,
    limit: int | None = None,
) -> None:
    completed = 0
    while limit is None or completed < limit:
        event_index = _next_deliverable_index(value, profiles, now)
        if event_index is None:
            return
        before = len(value["outbox"])
        if not _deliver(value, profiles, event_index, False, storage, stats, now):
            return
        if len(value["outbox"]) < before:
            completed += 1


def _asset_with_index(asset: DownloadedAsset, index: int) -> DownloadedAsset:
    source = SourceMedia(asset.source.url, asset.source.kind, index)
    return DownloadedAsset(source, asset.path, asset.sha256, asset.size_bytes, asset.content_type)


def _failed_with_index(asset: FailedAsset, index: int) -> FailedAsset:
    source = SourceMedia(asset.source.url, asset.source.kind, index)
    return FailedAsset(source, asset.reason)


def _reel_analysis_assets(
    post: SourcePost,
    downloaded: DownloadedPublication,
    profile: Profile,
    stats: RunStats,
) -> DownloadedPublication:
    if post.kind is not PublicationKind.REEL:
        return downloaded
    source_assets = list(downloaded.assets)
    failed_assets = list(downloaded.failed_assets)
    videos = [asset for asset in source_assets if asset.source.kind is MediaKind.VIDEO]
    covers = [asset for asset in source_assets if asset.source.kind is MediaKind.IMAGE]
    offset = max(
        [asset.source.index for asset in source_assets]
        + [asset.source.index for asset in failed_assets]
        + [-1]
    ) + 1
    if not videos or not covers:
        failed_assets.append(FailedAsset(SourceMedia("analysis-frame://missing", MediaKind.IMAGE, offset), "frame_sampling_failed"))
        stats.note_error(f"{profile.handle}: reel frame sampling failed")
        return DownloadedPublication(tuple(source_assets), downloaded.media_root, tuple(failed_assets))
    try:
        sampled, sampled_failures = media.sample_reel_frames_observed(
            videos[0].path,
            covers[0].path,
            downloaded.media_root,
            profile.max_reel_frames,
        )
    except Exception:
        sampled, sampled_failures = (), (FailedAsset(SourceMedia("analysis-frame://sampled", MediaKind.IMAGE, 0), "frame_sampling_failed"),)
    # The sampler returns the cover first. The source cover is already present,
    # so only additional frames become persisted analysis assets.
    frames = [asset for asset in sampled if asset.path != covers[0].path]
    for frame in frames:
        source_assets.append(_asset_with_index(frame, offset))
        offset += 1
    for failed in sampled_failures:
        failed_assets.append(_failed_with_index(failed, offset))
        offset += 1
    if sampled_failures:
        stats.note_error(f"{profile.handle}: reel frame sampling failed")
    return DownloadedPublication(tuple(source_assets), downloaded.media_root, tuple(failed_assets))


def _backend_identity(backend: object, attribute: str) -> str:
    value = getattr(backend, attribute, "")
    try:
        value = value() if callable(value) else value
    except Exception:
        value = ""
    return value if isinstance(value, str) else ""


def _ocr_failure(backend: object, profile: Profile, status: OCRStatus) -> OCRResult:
    return OCRResult(
        status=status,
        engine_id=_backend_identity(backend, "engine_id"),
        model_version=_backend_identity(backend, "model_version"),
        languages=profile.ocr_languages,
        error="ocr backend failed",
    )


def _prepare_event(
    post: SourcePost,
    profile: Profile,
    media_root: Path,
    cache_root: Path,
    backend: object,
    stats: RunStats,
) -> dict[str, object]:
    session = requests.Session()
    try:
        downloaded = media.download_publication(
            post,
            media_root,
            session,
            DownloadLimits(),
            allow_partial=True,
        )
    finally:
        session.close()
    if not isinstance(downloaded, DownloadedPublication):
        raise ValueError("media preparation returned an invalid publication")
    source_indexes = {item.index for item in post.media}
    failed_source_assets = tuple(
        failed for failed in downloaded.failed_assets if failed.source.index in source_indexes
    )
    if failed_source_assets:
        stats.note_media_failure(profile)
        try:
            media.cleanup_event_media(downloaded.media_root.parent, downloaded.media_root.name)
        except Exception:
            stats.note_error(f"{profile.handle}: media cleanup failed")
        raise ValueError("source media preparation failed")
    if downloaded.failed_assets:
        stats.note_media_failure(profile)
    downloaded = _reel_analysis_assets(post, downloaded, profile, stats)
    image_assets = tuple(
        sorted(
            (asset for asset in downloaded.assets if asset.source.kind is MediaKind.IMAGE),
            key=lambda asset: asset.source.index,
        )
    )
    results: list[OCRResult] = []
    for asset in image_assets:
        stats.ocr += 1
        try:
            result = ocr.extract_cached(asset, cache_root, backend, profile.ocr_languages)
            if not isinstance(result, OCRResult):
                result = _ocr_failure(backend, profile, OCRStatus.ERROR)
        except TimeoutError:
            result = _ocr_failure(backend, profile, OCRStatus.TIMEOUT)
        except Exception:
            result = _ocr_failure(backend, profile, OCRStatus.ERROR)
        if result.status in {OCRStatus.ERROR, OCRStatus.TIMEOUT, OCRStatus.UNAVAILABLE, OCRStatus.UNCERTAIN}:
            stats.note_ocr_failure(profile)
        results.append(result)
    bounded_results = ocr.bound_publication_results(tuple(results))
    decision = vision_gate.decide_vision_mode(
        agent_protocol.caption_text(post),
        image_assets,
        bounded_results,
        profile,
        failed_assets=downloaded.failed_assets,
    )
    if decision.mode is not vision_gate.VisionMode.TEXT_ONLY:
        stats.vision_fallback += 1
    return {
        "post": post,
        "downloaded_publication": downloaded,
        "ocr_results": bounded_results,
        "vision_decision": decision,
    }


def _advance_filtered_cursor(value: dict, profile: Profile, posts: list[SourcePost]) -> None:
    if not posts:
        return
    newest = max(posts, key=lambda post: (post.published_at, post.publication_id))
    record = value["profiles"].get(profile.id)
    if record is None:
        value["profiles"][profile.id] = {
            "cursor": newest.publication_id,
            "cursor_published_at": newest.published_at.isoformat(),
        }
        return
    current_time = None
    if record.get("cursor_published_at"):
        try:
            current_time = datetime.fromisoformat(record["cursor_published_at"])
        except (TypeError, ValueError):
            current_time = None
    if record.get("cursor") is None or current_time is None or (newest.published_at, newest.publication_id) > (current_time, str(record.get("cursor"))):
        record["cursor"] = newest.publication_id
        record["cursor_published_at"] = newest.published_at.isoformat()


def _profile_posts(profile: Profile, value: dict, stats: RunStats) -> tuple[list[SourcePost], list[SourcePost]]:
    record = value["profiles"].get(profile.id) or {}
    cursor = record.get("cursor") if isinstance(record, dict) else None
    posts = rsshub.fetch_profile_items(profile, after_id=cursor)
    if not posts:
        stats.note_error(f"{profile.handle}: empty source feed")
        return [], []
    stats.fetched += len(posts)
    ordered = sorted(posts, key=lambda post: (post.published_at, post.publication_id))
    limited = ordered[: profile.max_items_per_poll]
    eligible: list[SourcePost] = []
    for post in limited:
        if rsshub.is_forwardable(profile, post):
            eligible.append(post)
        else:
            stats.filtered += 1
    if len(limited) < len(posts):
        stats.filtered += len(posts) - len(limited)
    return eligible, limited


def _ocr_backend_for_run() -> object:
    return ocr.build_backend(os.environ.get("INSTAGRAM_POST_WATCH_OCR_ENGINE"))


def _claim_agent(
    value: dict,
    profiles: dict[str, Profile],
    storage: Path,
    now: datetime,
    stats: RunStats,
) -> dict[str, object]:
    event = state.claim_oldest_agent(value, profiles, now)
    if event is None:
        state.save_state(storage, value)
        return agent_protocol.build_wake_payload(None)
    state.save_state(storage, value)
    try:
        item = agent_protocol.agent_item(profiles[event["profile_id"]], event)
        return agent_protocol.build_wake_payload(item)
    except Exception:
        event["agent_phase"] = "pending"
        event["agent_lease_until"] = None
        stats.note_error("agent payload preparation failed")
        state.save_state(storage, value)
        return agent_protocol.build_wake_payload(None)


def run(now: datetime | None = None, dry_run: bool | None = None) -> dict[str, object]:
    now = now or datetime.now(WIB)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scan time must be timezone-aware")
    no_post = _no_post(dry_run)
    storage = state_path()
    stats = RunStats()
    try:
        with _process_lock(storage, blocking=False) as acquired:
            if not acquired:
                return agent_protocol.build_wake_payload(None)
            root = _ensure_media_root()
            cache_root = ocr_cache_path()
            watches = config.load_watch_config(config_path())
            value = state.load_state(storage)
            state.prune_deliveries(value, now)
            stats.filtered = state.take_filtered_since_last_heartbeat(value)
            profiles = {profile.id: profile for profile in watches.profiles}
            backend: object | None = None
            for profile in watches.profiles:
                if not profile.enabled:
                    continue
                try:
                    posts, source_posts = _profile_posts(profile, value, stats)
                    if not source_posts:
                        continue
                    if not posts:
                        _advance_filtered_cursor(value, profile, source_posts)
                        state.save_state(storage, value)
                        continue
                    profile_record = value["profiles"].get(profile.id)
                    if profile_record is None or profile_record.get("cursor") is None:
                        state.observe_publications(
                            value,
                            profile,
                            posts,
                            now,
                            lambda _post: {},
                        )
                        _advance_filtered_cursor(value, profile, source_posts)
                        state.save_state(storage, value)
                        continue
                    if backend is None:
                        backend = _ocr_backend_for_run()
                    prepare = lambda post, profile=profile: _prepare_event(
                        post,
                        profile,
                        root,
                        cache_root,
                        backend,
                        stats,
                    )
                    queued = state.observe_publications(value, profile, posts, now, prepare)
                    stats.queued += queued
                    _advance_filtered_cursor(value, profile, source_posts)
                    state.save_state(storage, value)
                except rsshub.SourceFetchError:
                    stats.note_error(f"{profile.handle}: RSSHub source unavailable")
                    state.save_state(storage, value)
                except Exception:
                    stats.note_error(f"{profile.handle}: media/OCR preparation failed")
                    state.save_state(storage, value)

            if not no_post:
                _retry_media_cleanup(value, storage, stats, no_post=False)
                _drain_deliveries(value, profiles, storage, stats, now)
                _retry_media_cleanup(value, storage, stats, no_post=False)
                try:
                    discord.post_text(
                        format_heartbeat(now, stats),
                        HEARTBEAT_CHANNEL_ID,
                        False,
                        discord.nonce("heartbeat", now.astimezone(WIB).strftime("%Y%m%d%H%M")),
                    )
                except Exception:
                    stats.note_error("Discord heartbeat delivery failed")
                return _claim_agent(value, profiles, storage, now, stats)

            state.save_state(storage, value)
            return agent_protocol.build_wake_payload(None)
    except Exception as exc:
        if not no_post:
            try:
                discord.post_text(
                    format_fatal(now, "watcher execution failed"),
                    HEARTBEAT_CHANNEL_ID,
                    False,
                    discord.nonce("fatal", now.astimezone(WIB).strftime("%Y%m%d%H%M")),
                )
            except Exception:
                pass
        raise RuntimeError(_sanitize_reason(exc)) from exc


def _analysis_ocr_text(event: dict) -> str:
    texts: list[str] = []
    for raw in event.get("ocr_results", []):
        try:
            result = state.deserialize_ocr_result(raw)
        except ValueError:
            continue
        if result.text:
            texts.append(result.text)
    return "\n".join(texts)


def submit_analysis_payload(payload: object, dry_run: bool | None = None) -> dict[str, object]:
    if type(payload) is not dict or not isinstance(payload.get("event_key"), str):
        raise ValueError("analysis submission requires an event_key")
    no_post = _no_post(dry_run)
    storage = state_path()
    with _process_lock(storage, blocking=True) as acquired:
        if not acquired:
            raise RuntimeError("watcher lock is unavailable")
        root = _ensure_media_root()
        del root
        watches = config.load_watch_config(config_path())
        value = state.load_state(storage)
        profiles = {profile.id: profile for profile in watches.profiles}
        event_key = payload["event_key"]
        profile_id = event_key.partition(":")[0]
        profile = profiles.get(profile_id)
        if profile is None or not profile.uses_llm:
            raise ValueError("analysis profile is not enabled")
        analysis = agent_protocol.validate_submission(profile, payload)
        event = state.awaiting_analysis_event(value, analysis["event_key"])
        post = state.deserialize_post(event["post"])
        ocr_text = _analysis_ocr_text(event)
        promotional = agent_protocol.is_promotional(post, ocr_text)
        irrelevant = analysis.get("is_relevant") is False
        if promotional or irrelevant:
            if irrelevant and not promotional and agent_protocol.requires_relevance(post, ocr_text):
                raise ValueError("direct market disclosure must be relevant")
            state.discard_analysis(value, analysis["event_key"], datetime.now(WIB))
            state.save_state(storage, value)
            stats = RunStats()
            _retry_media_cleanup(value, storage, stats, no_post=no_post)
            return {"submitted": True, "ignored": True, "delivered": 0}

        state.submit_analysis(
            value,
            analysis["event_key"],
            {key: item for key, item in analysis.items() if key != "event_key"},
            datetime.now(WIB),
        )
        state.save_state(storage, value)
        stats = RunStats()
        if not no_post:
            _drain_deliveries(value, profiles, storage, stats, datetime.now(WIB), limit=1)
            _retry_media_cleanup(value, storage, stats, no_post=False)
        else:
            state.save_state(storage, value)
        return {"submitted": True, "ignored": False, "delivered": stats.delivered}


def _main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    submit = subparsers.add_parser("submit-analysis")
    submit.add_argument("--json", required=True, dest="payload")
    arguments = parser.parse_args()
    try:
        if arguments.command == "submit-analysis":
            result = submit_analysis_payload(json.loads(arguments.payload))
        else:
            result = run()
    except Exception as exc:
        print(json.dumps({"wakeAgent": False, "error": _sanitize_reason(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
