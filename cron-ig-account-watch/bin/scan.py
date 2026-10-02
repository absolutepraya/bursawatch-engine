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
import publication_projection
import render
import rsshub
import source_work_routes
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


try:
    from control_plane_runtime import ControlPlaneRun
except ModuleNotFoundError:
    class ControlPlaneRun:
        @classmethod
        def begin(cls, *_args, **_kwargs):
            return cls()

        def event(self, *_args, **_kwargs):
            pass

        def finish(self, *_args, **_kwargs):
            pass


WIB = ZoneInfo("Asia/Jakarta")
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
WATCHER_HEARTBEAT_NAME = "instagram-post"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "watches.json"
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.json"
DEFAULT_MEDIA_ROOT = Path(__file__).resolve().parent.parent / "state" / "media"
DEFAULT_OCR_CACHE_ROOT = Path(__file__).resolve().parent.parent / "state" / "ocr-cache"
MAX_REASON_CHARACTERS = 180
MAX_DELIVERY_LEGS_PER_INVOCATION = 20
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
    delivery_legs: int = 0
    owner_pending: int = 0
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
            self.reasons.insert(0, safe)

    def note_media_failure(self, profile: Profile) -> None:
        self.note_error(f"{profile.handle}: media asset unavailable")

    def note_ocr_failure(self, profile: Profile) -> None:
        self.note_error(f"{profile.handle}: OCR degraded")

    def tokens(self) -> str:
        return (
            f"{self.fetched} fetched · {self.filtered} filtered · {self.queued} queued · "
            f"{self.ocr} OCR · {self.vision_fallback} vision fallback · "
            f"{self.delivered} delivered · {self.delivery_legs} delivery legs · "
            f"{self.errors} errors · owner pending {self.owner_pending}"
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


def _resolved_path(path: Path) -> Path:
    return Path(os.path.expanduser(os.path.abspath(str(path)))).resolve(strict=False)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_no_post_isolation() -> None:
    state_raw = os.environ.get("INSTAGRAM_POST_WATCH_STATE_PATH")
    media_raw = os.environ.get("INSTAGRAM_POST_WATCH_MEDIA_ROOT")
    if not state_raw or not media_raw:
        raise ValueError("no-post requires explicit isolated state and media paths")

    raw_state = Path(state_raw).expanduser()
    raw_media = Path(media_raw).expanduser()
    if not raw_state.is_absolute() or not raw_media.is_absolute():
        raise ValueError("no-post paths must be absolute")
    configured_state = _resolved_path(raw_state)
    configured_media = _resolved_path(raw_media)
    if configured_state == configured_media:
        raise ValueError("no-post state and media paths must be distinct")

    actual_state = _resolved_path(state_path())
    actual_media = _resolved_path(media_root_path())
    if configured_state != actual_state or configured_media != actual_media:
        raise ValueError("no-post paths must match the isolated watcher paths")

    live_root = _resolved_path(DEFAULT_STATE_PATH.parent)
    if _path_is_within(configured_state, live_root) or _path_is_within(configured_media, live_root):
        raise ValueError("no-post paths must not use the live watcher state root")
    cache_root = _resolved_path(ocr_cache_path())
    if _path_is_within(cache_root, live_root):
        raise ValueError("no-post OCR cache must not use the live watcher state root")


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
    warning = " ⚠️" if stats.degraded else ""
    return (
        f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · "
        f"{stats.tokens()}{suffix}{warning}"
    )


def format_fatal(now: datetime, reason: object) -> str:
    failure = _sanitize_reason(reason)
    return f"❌ {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {failure}"


def _post_heartbeat(now: datetime, stats: RunStats) -> None:
    try:
        discord.post_text(
            format_heartbeat(now, stats),
            HEARTBEAT_CHANNEL_ID,
            False,
            discord.nonce("heartbeat", now.astimezone(WIB).strftime("%Y%m%d%H%M")),
        )
    except discord.DeliveryOwnerPending:
        stats.owner_pending += 1
    except Exception:
        stats.note_error("Discord heartbeat delivery failed")


def _post_fatal(now: datetime, reason: object) -> None:
    try:
        discord.post_text(
            format_fatal(now, reason),
            HEARTBEAT_CHANNEL_ID,
            False,
            discord.nonce("fatal", now.astimezone(WIB).strftime("%Y%m%d%H%M")),
        )
    except Exception:
        pass


def _post_degraded_heartbeat(now: datetime, reason: object) -> None:
    stats = RunStats()
    stats.note_error(str(reason))
    _post_heartbeat(now, stats)


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
    return profile.channel_for(agent_protocol.validate_route(profile, route)).channel_id


def _source_media_by_index(post: SourcePost, downloaded: DownloadedPublication) -> tuple[DownloadedAsset, ...]:
    # Sampled reel frames are analysis-only. All returned assets are original
    # source assets; delivery applies its one-image limit separately.
    state.validate_source_media_coverage(post, downloaded)
    expected_sources = tuple(post.media)
    expected = {item.index: item for item in expected_sources}
    failed = {item.source.index: item for item in downloaded.failed_assets}
    selected: dict[int, DownloadedAsset] = {}
    for asset in sorted(downloaded.assets, key=lambda item: item.source.index):
        expected_source = expected.get(asset.source.index)
        if expected_source is None:
            continue
        if (
            asset.source.kind is not expected_source.kind
            or asset.source.locator_digest != expected_source.locator_digest
        ):
            raise ValueError("source media identity mismatch")
        if asset.source.index in selected:
            raise ValueError("source media indexes are duplicated")
        selected[asset.source.index] = asset
    for index, expected_source in expected.items():
        if index in selected:
            continue
        failed_source = failed.get(index)
        if failed_source is None:
            raise ValueError("source media is unavailable")
        if (
            failed_source.source.kind is not expected_source.kind
            or failed_source.source.locator_digest != expected_source.locator_digest
        ):
            raise ValueError("source media identity mismatch")
    return tuple(selected[index] for index in sorted(selected))


def _delivery_media(post: SourcePost, downloaded: DownloadedPublication) -> tuple[DownloadedAsset, ...]:
    source_assets = _source_media_by_index(post, downloaded)
    if not source_assets:
        return ()
    first_image = next(
        (asset for asset in source_assets if asset.source.kind is MediaKind.IMAGE),
        None,
    )
    return (first_image or source_assets[0],)


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
        event_key = item["event_key"]
        if any(event.get("event_key") == event_key for event in value["outbox"]):
            # A retry may have recreated this event's media before cleanup was
            # attempted. The active outbox owns that directory now.
            continue
        delivery = next(
            (entry for entry in value["deliveries"] if entry.get("event_key") == event_key),
            None,
        )
        if delivery is not None and not delivery.get("cleanup_pending", False):
            # A stale duplicate cleanup entry must not delete media owned by a
            # completed delivery whose cleanup is already settled.
            value["cleanup"].remove(item)
            changed = True
            continue
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
    profile: Profile,
) -> bool:
    event = value["outbox"][event_index]
    if source_work_routes.read(storage, event["event_key"]) is not None:
        source_work_routes.record_terminal(storage, event["event_key"], "delivered")
    media_root = _delivery_media_root(event)
    state.record_delivery(
        value,
        event,
        now,
        text_message_ids=event["text_message_ids"],
        media_message_ids=event["media_message_ids"],
        cleanup_pending=media_root is not None,
    )
    try:
        publication_projection.record_intent(value, event, profile, now)
    except Exception:
        # Preserve an explicit coverage gap without repeating confirmed sends.
        publication_projection.record_blocked(value, event, now)
    if media_root is not None:
        state.queue_media_cleanup(
            value,
            event["event_key"],
            event["profile_id"],
            event["publication_id"],
            media_root,
        )
    value["outbox"].pop(event_index)
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
    try:
        profile = profiles[event["profile_id"]]
        post = state.deserialize_post(event["post"])
        downloaded_raw = event.get("downloaded_publication")
        if downloaded_raw is None:
            raise ValueError("downloaded media is unavailable")
        downloaded = state.deserialize_downloaded_publication(downloaded_raw)
        channel_id = _target_channel(profile, event)
        messages = render.render_publication(
            profile,
            post,
            event.get("summary") if profile.enable_llm_summary else None,
            event.get("title") if profile.enable_llm_title else None,
        )
        cards = event.get("news_cards")
        targets = None
        if cards is not None:
            render.news_format.validate_cards(cards)
            messages = [message for card in cards for message in card["messages"]]
            targets = [card["destination"] for card in cards for message in card["messages"]]
            channel_id = targets[0]
        if event["text_index"] < len(messages):
            index = event["text_index"]
            stats.delivery_legs += 1
            message_id = discord.post_text(
                messages[index],
                targets[index] if targets else channel_id,
                False,
                discord.nonce(event["event_key"], f"text:{index}"),
            )
            if message_id is not None:
                event["text_message_ids"].append(message_id)
            event["text_index"] += 1
            state.save_state(storage, value)
            return True

        original_assets = _delivery_media(post, downloaded)
        if profile.forward_media and event["media_index"] < len(original_assets):
            index = event["media_index"]
            asset = original_assets[index]
            stats.delivery_legs += 1
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

        return _finalize_delivery(value, event_index, storage, stats, now, profile)
    except Exception as error:
        if isinstance(error, discord.DeliveryOwnerPending):
            event["last_error"] = "Delivery Owner accepted pending work"
            stats.owner_pending += 1
            try:
                state.save_state(storage, value)
            except Exception:
                stats.note_error("delivery failure state persistence failed")
            return False
        event["last_error"] = "Discord delivery failed"
        stats.note_error("Discord delivery failed")
        try:
            state.save_state(storage, value)
        except Exception:
            stats.note_error("delivery failure state persistence failed")
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
        if stats.delivery_legs >= MAX_DELIVERY_LEGS_PER_INVOCATION:
            if _next_deliverable_index(value, profiles, now) is not None:
                stats.note_error(
                    f"delivery backlog remains after {MAX_DELIVERY_LEGS_PER_INVOCATION} legs"
                )
            return


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
    return _prepare_downloaded_event(post, profile, downloaded, cache_root, backend, stats)


def _prepare_downloaded_event(
    post: SourcePost,
    profile: Profile,
    downloaded: DownloadedPublication,
    cache_root: Path,
    backend: object,
    stats: RunStats,
) -> dict[str, object]:
    """Apply the watcher OCR and vision flow to already durable originals."""
    if not isinstance(downloaded, DownloadedPublication):
        raise ValueError("media preparation returned an invalid publication")
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


def _profile_posts(
    profile: Profile,
    value: dict,
    stats: RunStats,
) -> tuple[list[SourcePost], list[SourcePost], list[SourcePost]]:
    record = value["profiles"].get(profile.id) or {}
    cursor = record.get("cursor") if isinstance(record, dict) else None
    posts = rsshub.fetch_profile_items(profile, after_id=cursor)
    if not posts:
        stats.note_error(f"{profile.handle}: empty source feed")
        return [], [], []
    stats.fetched += len(posts)
    ordered = sorted(posts, key=lambda post: (post.published_at, post.publication_id))
    fresh = list(state.publications_after_cursor(value, profile.id, ordered))
    limited = fresh[: profile.max_items_per_poll]
    eligible: list[SourcePost] = []
    for post in limited:
        if rsshub.is_forwardable(profile, post):
            eligible.append(post)
        else:
            stats.filtered += 1
    if len(limited) < len(fresh):
        stats.filtered += len(fresh) - len(limited)
    return eligible, limited, ordered


def _ocr_backend_for_run() -> object:
    return ocr.build_backend(os.environ.get("INSTAGRAM_POST_WATCH_OCR_ENGINE"))


def _queue_prepared_cleanup(
    value: dict,
    profile: Profile,
    prepared_roots: dict[str, Path],
    storage: Path,
    stats: RunStats,
) -> None:
    if not prepared_roots:
        return
    changed = False
    for publication_id, media_root in prepared_roots.items():
        try:
            state.queue_media_cleanup(
                value,
                f"{profile.id}:{publication_id}",
                profile.id,
                publication_id,
                str(media_root),
            )
            changed = True
        except Exception:
            stats.note_error(f"{profile.handle}: media cleanup queue failed")
    if changed:
        try:
            state.save_state(storage, value)
        except Exception:
            stats.note_error("cleanup queue persistence failed")


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


def _note_reclaimed_agent_leases(value: dict, now: datetime, stats: RunStats) -> None:
    reclaimed = 0
    for event in value.get("outbox", []):
        if event.get("agent_phase") != "awaiting_agent":
            continue
        raw_lease = event.get("agent_lease_until")
        expired = raw_lease is None
        if isinstance(raw_lease, str):
            try:
                lease = datetime.fromisoformat(raw_lease)
            except ValueError:
                expired = True
            else:
                expired = lease <= now
        if expired:
            reclaimed += 1
    if reclaimed:
        stats.note_error(f"reclaimed {reclaimed} expired agent lease(s)")


def run(now: datetime | None = None, dry_run: bool | None = None) -> dict[str, object]:
    now = now or datetime.now(WIB)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scan time must be timezone-aware")
    no_post = _no_post(dry_run)
    if no_post:
        _require_no_post_isolation()
    storage = state_path()
    stats = RunStats()
    control_run: ControlPlaneRun | None = None
    try:
        with _process_lock(storage, blocking=False) as acquired:
            if not acquired:
                return agent_protocol.build_wake_payload(None)
            root = _ensure_media_root()
            cache_root = ocr_cache_path()
            loaded_config = config.load_watch_config_for_run(config_path())
            watches = loaded_config.config
            control_run = ControlPlaneRun.begin(
                "INSTAGRAM_POST_WATCH",
                loaded_config.revision,
                scheduler_job_id="instagram-post",
            )
            control_run.event(
                "run-started",
                level="info",
                phase="lifecycle",
                event_type="run.started",
                message="Instagram watcher run started",
                attributes={"config_revision": loaded_config.revision, "no_post": no_post},
            )
            value = state.load_state(storage)
            state.prune_deliveries(value, now)
            stats.filtered = state.take_filtered_since_last_heartbeat(value)
            profiles = {profile.id: profile for profile in watches.profiles}
            _retry_media_cleanup(value, storage, stats, no_post=no_post)
            backend: object | None = None
            for profile in watches.profiles:
                if not profile.enabled:
                    continue
                prepared_roots: dict[str, Path] = {}
                try:
                    posts, limited_source_posts, complete_source_posts = _profile_posts(profile, value, stats)
                    profile_record = value["profiles"].get(profile.id)
                    first_observation = profile_record is None or profile_record.get("cursor") is None
                    if first_observation:
                        # Initialization consumes the complete fetched feed. The
                        # poll cap must never turn an initial snapshot into a
                        # delayed historical backfill.
                        state.observe_publications(
                            value,
                            profile,
                            [],
                            now,
                            lambda _post: {},
                        )
                        _advance_filtered_cursor(value, profile, complete_source_posts)
                        state.save_state(storage, value)
                        control_run.event(
                            f"source-poll-{profile.id}",
                            level="info",
                            phase="source",
                            event_type="source.poll.completed",
                            message=f"{profile.id}: source poll initialized future-only cursor",
                            attributes={
                                "profile_id": profile.id,
                                "source_items": len(complete_source_posts),
                                "fresh_items": len(limited_source_posts),
                                "eligible_items": 0,
                                "queued": 0,
                                "initialized": True,
                            },
                        )
                        continue
                    if not limited_source_posts:
                        control_run.event(
                            f"source-poll-{profile.id}",
                            level="info",
                            phase="source",
                            event_type="source.poll.completed",
                            message=f"{profile.id}: source poll completed",
                            attributes={
                                "profile_id": profile.id,
                                "source_items": len(complete_source_posts),
                                "fresh_items": 0,
                                "eligible_items": 0,
                                "queued": 0,
                                "initialized": False,
                            },
                        )
                        continue
                    if not posts:
                        _advance_filtered_cursor(value, profile, limited_source_posts)
                        state.save_state(storage, value)
                        control_run.event(
                            f"source-poll-{profile.id}",
                            level="info",
                            phase="source",
                            event_type="source.poll.completed",
                            message=f"{profile.id}: source poll completed",
                            attributes={
                                "profile_id": profile.id,
                                "source_items": len(complete_source_posts),
                                "fresh_items": len(limited_source_posts),
                                "eligible_items": 0,
                                "queued": 0,
                                "initialized": False,
                            },
                        )
                        continue
                    if backend is None:
                        backend = _ocr_backend_for_run()
                    def prepare(post: SourcePost, profile: Profile = profile) -> dict[str, object]:
                        prepared_roots[post.publication_id] = root / post.publication_id
                        prepared = _prepare_event(
                            post,
                            profile,
                            root,
                            cache_root,
                            backend,
                            stats,
                        )
                        downloaded = prepared.get("downloaded_publication")
                        if isinstance(downloaded, DownloadedPublication):
                            prepared_roots[post.publication_id] = downloaded.media_root
                        return prepared
                    queued = state.observe_publications(value, profile, posts, now, prepare)
                    stats.queued += queued
                    _advance_filtered_cursor(value, profile, limited_source_posts)
                    state.save_state(storage, value)
                    control_run.event(
                        f"source-poll-{profile.id}",
                        level="info",
                        phase="source",
                        event_type="source.poll.completed",
                        message=f"{profile.id}: source poll completed",
                        attributes={
                            "profile_id": profile.id,
                            "source_items": len(complete_source_posts),
                            "fresh_items": len(limited_source_posts),
                            "eligible_items": len(posts),
                            "queued": queued,
                            "initialized": False,
                        },
                    )
                except rsshub.SourceFetchError:
                    stats.note_error(f"{profile.handle}: RSSHub source unavailable")
                    state.save_state(storage, value)
                    control_run.event(
                        f"source-poll-{profile.id}",
                        level="warning",
                        phase="source",
                        event_type="source.poll.failed",
                        message=f"{profile.id}: RSSHub source unavailable",
                        attributes={"profile_id": profile.id},
                    )
                except Exception:
                    _queue_prepared_cleanup(value, profile, prepared_roots, storage, stats)
                    stats.note_error(f"{profile.handle}: media/OCR preparation failed")
                    state.save_state(storage, value)
                    control_run.event(
                        f"source-poll-{profile.id}",
                        level="warning",
                        phase="source",
                        event_type="source.preparation.failed",
                        message=f"{profile.id}: media or OCR preparation failed",
                        attributes={"profile_id": profile.id},
                    )

            if not no_post:
                _drain_deliveries(value, profiles, storage, stats, now)
                projection = publication_projection.drain(value, now)
                if projection["pending"]:
                    stats.note_error("Published Feed projection pending")
                state.save_state(storage, value)
                _retry_media_cleanup(value, storage, stats, no_post=False)
                _note_reclaimed_agent_leases(value, now, stats)
                _post_heartbeat(now, stats)
                result = _claim_agent(value, profiles, storage, now, stats)
            else:
                state.save_state(storage, value)
                result = agent_protocol.build_wake_payload(None)

            control_run.event(
                "delivery-drain-completed",
                level="warning" if stats.degraded else "info",
                phase="delivery",
                event_type="delivery.drain.completed",
                message="Instagram delivery drain completed",
                attributes={
                    "delivered": stats.delivered,
                    "delivery_legs": stats.delivery_legs,
                    "no_post": no_post,
                    "errors": stats.errors,
                },
            )
            if result.get("wakeAgent"):
                control_run.event(
                    "agent-wake-requested",
                    level="info",
                    phase="agent",
                    event_type="agent.wake.requested",
                    message="Instagram publication claimed for agent analysis",
                )

            control_run.event(
                "run-completed",
                level="warning" if stats.degraded else "info",
                phase="lifecycle",
                event_type="run.completed",
                message="Instagram watcher run completed",
                attributes={
                    "fetched": stats.fetched,
                    "filtered": stats.filtered,
                    "queued": stats.queued,
                    "ocr": stats.ocr,
                    "vision_fallback": stats.vision_fallback,
                    "delivered": stats.delivered,
                    "delivery_legs": stats.delivery_legs,
                    "errors": stats.errors,
                    "degraded": stats.degraded,
                    "reasons": stats.reasons[:10],
                },
            )
            control_run.finish("degraded" if stats.degraded else "ok")
            return result
    except Exception as exc:
        if control_run is not None:
            reason = _sanitize_reason(exc)
            control_run.event(
                "run-failed",
                level="fatal",
                phase="lifecycle",
                event_type="run.failed",
                message="Instagram watcher run failed",
                attributes={"error": reason},
            )
            control_run.finish("failed", reason)
        if not no_post:
            _post_fatal(now, exc)
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


def _preserve_analysis_failure(
    value: dict | None,
    event: dict | None,
    storage: Path,
) -> None:
    if value is None or event is None:
        return
    if event.get("last_error") is None:
        event["last_error"] = "analysis submission failed"
    try:
        state.save_state(storage, value)
    except Exception:
        pass


def submit_analysis_payload(payload: object, dry_run: bool | None = None) -> dict[str, object]:
    no_post = _no_post(dry_run)
    now = datetime.now(WIB)
    if no_post:
        _require_no_post_isolation()
    if type(payload) is not dict or not isinstance(payload.get("event_key"), str):
        reason = "analysis submission requires an event_key"
        if not no_post:
            _post_degraded_heartbeat(now, reason)
        raise ValueError(reason)
    storage = state_path()
    value: dict | None = None
    event: dict | None = None
    control_run: ControlPlaneRun | None = None
    try:
        with _process_lock(storage, blocking=True) as acquired:
            if not acquired:
                raise RuntimeError("watcher lock is unavailable")
            root = _ensure_media_root()
            del root
            loaded_config = config.load_watch_config_for_run(config_path())
            watches = loaded_config.config
            control_run = ControlPlaneRun.begin(
                "INSTAGRAM_POST_WATCH",
                loaded_config.revision,
                scheduler_job_id="instagram-post",
                trigger="agent_submission",
            )
            control_run.event(
                "agent-submission-started",
                level="info",
                phase="agent",
                event_type="agent.submission.started",
                message="Instagram agent submission started",
                attributes={"no_post": no_post},
            )
            value = state.load_state(storage)
            profiles = {profile.id: profile for profile in watches.profiles}
            event_key = payload["event_key"]
            profile_id = event_key.partition(":")[0]
            profile = profiles.get(profile_id)
            if profile is None or not profile.uses_llm:
                raise ValueError("analysis profile is not enabled")
            event = state.awaiting_analysis_event(value, event_key)
            analysis = agent_protocol.validate_submission(profile, payload)
            post = state.deserialize_post(event["post"])
            ocr_text = _analysis_ocr_text(event)
            irrelevant = analysis.get("is_relevant") is False
            if irrelevant:
                if source_work_routes.read(storage, event_key) is not None:
                    source_work_routes.record_terminal(storage, event_key, "irrelevant")
                state.discard_analysis(value, analysis["event_key"], now)
                state.save_state(storage, value)
                stats = RunStats()
                _retry_media_cleanup(value, storage, stats, no_post=no_post)
                if stats.degraded and not no_post:
                    _post_heartbeat(now, stats)
                control_run.event(
                    "agent-submission-accepted",
                    level="info",
                    phase="agent",
                    event_type="agent.submission.accepted",
                    message="Instagram agent submission accepted as irrelevant",
                    attributes={"is_relevant": False, "delivered": 0},
                )
                control_run.finish("degraded" if stats.degraded else "ok")
                return {"submitted": True, "ignored": True, "delivered": 0}

            # Source Catalog subscriptions select delivery routes after the
            # usual relevance and route classification. A truthful relevant
            # publication for an unsubscribed route has its own no-match
            # outcome; it is never mislabeled irrelevant or delivered there.
            news_items = analysis.pop("news_items", None)
            allowed_routes = source_work_routes.allowed_routes(storage, event_key)
            if news_items is not None and allowed_routes is not None:
                news_items = [item for item in news_items if item["route"] in allowed_routes]
                if news_items:
                    analysis.update(news_items[0])
            if news_items == []:
                analysis["route"] = "route_not_subscribed"
            if allowed_routes is not None and analysis.get("route") not in allowed_routes:
                source_work_routes.record_terminal(storage, event_key, "route_not_subscribed", analysis["route"])
                state.discard_analysis(value, analysis["event_key"], now)
                state.save_state(storage, value)
                stats = RunStats()
                _retry_media_cleanup(value, storage, stats, no_post=no_post)
                if stats.degraded and not no_post:
                    _post_heartbeat(now, stats)
                control_run.event(
                    "agent-submission-route-not-subscribed",
                    level="info",
                    phase="agent",
                    event_type="agent.submission.route_not_subscribed",
                    message="Instagram publication route is not subscribed",
                    attributes={"route": analysis["route"], "delivered": 0},
                )
                control_run.finish("degraded" if stats.degraded else "ok")
                return {"submitted": True, "ignored": True, "delivered": 0, "outcome": "route_not_subscribed"}

            state.submit_analysis(
                value,
                analysis["event_key"],
                {key: item for key, item in analysis.items() if key != "event_key"},
                now,
            )
            if profile.enable_llm_summary:
                event["news_cards"] = render.freeze_news(profile, post, news_items or [{"title": analysis.get("title") or profile.display_name, "summary": analysis["summary"], "route": analysis.get("route") or profile.discord_channels[0].key}])
            state.save_state(storage, value)
            stats = RunStats()
            if not no_post:
                _drain_deliveries(value, profiles, storage, stats, now, limit=1)
                _retry_media_cleanup(value, storage, stats, no_post=False)
                if stats.degraded:
                    _post_heartbeat(now, stats)
            else:
                state.save_state(storage, value)
            control_run.event(
                "agent-submission-accepted",
                level="info",
                phase="agent",
                event_type="agent.submission.accepted",
                message="Instagram agent submission accepted",
                attributes={"is_relevant": True, "delivered": stats.delivered},
            )
            control_run.event(
                "agent-delivery-drain-completed",
                level="warning" if stats.degraded else "info",
                phase="delivery",
                event_type="delivery.drain.completed",
                message="Instagram agent delivery drain completed",
                attributes={
                    "delivered": stats.delivered,
                    "delivery_legs": stats.delivery_legs,
                    "errors": stats.errors,
                },
            )
            control_run.finish("degraded" if stats.degraded else "ok")
            return {"submitted": True, "ignored": False, "delivered": stats.delivered}
    except Exception as exc:
        _preserve_analysis_failure(value, event, storage)
        if control_run is not None:
            reason = _sanitize_reason(exc)
            rejected = isinstance(exc, ValueError)
            control_run.event(
                "agent-submission-rejected" if rejected else "agent-submission-failed",
                level="warning" if rejected else "fatal",
                phase="agent",
                event_type="agent.submission.rejected" if rejected else "agent.submission.failed",
                message="Instagram agent submission rejected" if rejected else "Instagram agent submission failed",
                attributes={"reason" if rejected else "error": reason},
            )
            control_run.finish("degraded" if rejected else "failed", reason)
        if not no_post:
            _post_degraded_heartbeat(now, f"analysis submission failed: {_sanitize_reason(exc)}")
        raise


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
