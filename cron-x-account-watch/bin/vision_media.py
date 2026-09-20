from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from models import SourceMedia, SourcePost


MAX_VISION_ASSETS = 8
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 32 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 8
PREPARATION_TIMEOUT_SECONDS = 20
_COMPONENT_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
_POST_ID_RE = re.compile(r"\d+")
_ALLOWED_HOSTS = frozenset({"pbs.twimg.com"})
_IMAGE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class VisionMediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionAsset:
    role: str
    post_id: str
    index: int
    path: Path

    @property
    def label(self) -> str:
        source = "Authored X post" if self.role == "tweet" else "Quoted X post"
        return f"{source} image {self.index + 1}"


@dataclass(frozen=True)
class VisionBundle:
    root: Path
    assets: tuple[VisionAsset, ...]
    unavailable_count: int


def default_root(state_file: Path) -> Path:
    configured = os.environ.get("X_POST_WATCH_VISION_MEDIA_ROOT", "").strip()
    return Path(configured) if configured else state_file.parent / "x-post-watch-vision"


def _safe_component(value: str, pattern: re.Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise VisionMediaError("vision media event identity is invalid")
    return value


def _event_directory(root: Path, profile_id: str, post_id: str) -> Path:
    profile_id = _safe_component(profile_id, _COMPONENT_RE)
    post_id = _safe_component(post_id, _POST_ID_RE)
    root = root.resolve(strict=False)
    candidate = root / profile_id / post_id
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VisionMediaError("vision media path is invalid") from exc
    return resolved


def _ensure_event_directory(root: Path, profile_id: str, post_id: str) -> Path:
    if root.is_symlink():
        raise VisionMediaError("vision media root is invalid")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    directory = _event_directory(root, profile_id, post_id)
    directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.parent.is_symlink():
        raise VisionMediaError("vision media root is invalid")
    if directory.exists() and directory.is_symlink():
        raise VisionMediaError("vision media event directory is invalid")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _clear_directory(directory: Path) -> None:
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise VisionMediaError("vision media event directory is invalid")
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            raise VisionMediaError("vision media event directory is invalid")
        child.unlink()


def cleanup_event(root: Path, profile_id: str, post_id: str) -> None:
    directory = _event_directory(root, profile_id, post_id)
    if not directory.exists():
        return
    _clear_directory(directory)
    directory.rmdir()
    parent = directory.parent
    if parent.exists() and not parent.is_symlink() and not any(parent.iterdir()):
        parent.rmdir()


def _is_supported_source(media: SourceMedia) -> bool:
    if not isinstance(media.url, str):
        return False
    parsed = urlparse(media.url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in _ALLOWED_HOSTS
        and port in {None, 443}
        and not parsed.username
        and not parsed.password
        and bool(parsed.path)
    )


def _candidate_media(post: SourcePost) -> tuple[tuple[str, SourceMedia], ...]:
    candidates: list[tuple[str, SourceMedia]] = []
    seen: set[str] = set()
    for role, collection in (("tweet", post.media), ("quoted_tweet", post.quoted_media)):
        for media in collection:
            if len(candidates) >= MAX_VISION_ASSETS:
                return tuple(candidates)
            if not _is_supported_source(media) or media.url in seen:
                continue
            seen.add(media.url)
            candidates.append((role, media))
    return tuple(candidates)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VisionMediaError("vision image preparation timed out")
    return min(REQUEST_TIMEOUT_SECONDS, remaining)


def _download_image(
    session: requests.Session,
    media: SourceMedia,
    directory: Path,
    ordinal: int,
    total_bytes: int,
    deadline: float,
) -> tuple[Path, int]:
    response = None
    temporary_name: str | None = None
    try:
        response = session.get(
            media.url,
            stream=True,
            timeout=_remaining_timeout(deadline),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise VisionMediaError("vision image download failed")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        suffix = _IMAGE_SUFFIXES.get(content_type)
        if suffix is None:
            raise VisionMediaError("vision image content type is unsupported")
        fd, temporary_name = tempfile.mkstemp(prefix=f"{ordinal}-", suffix=".tmp", dir=directory)
        os.fchmod(fd, 0o600)
        size = 0
        with os.fdopen(fd, "wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if time.monotonic() >= deadline:
                    raise VisionMediaError("vision image preparation timed out")
                size += len(chunk)
                if size > MAX_ASSET_BYTES or total_bytes + size > MAX_EVENT_BYTES:
                    raise VisionMediaError("vision image size limit exceeded")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        final_path = directory / f"{ordinal}{suffix}"
        os.replace(temporary_name, final_path)
        final_path.chmod(0o600)
        return final_path, size
    except (OSError, requests.RequestException) as exc:
        raise VisionMediaError("vision image download failed") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        if response is not None:
            response.close()


def prepare(
    post: SourcePost,
    root: Path,
    session: requests.Session | None = None,
    deadline: float | None = None,
) -> VisionBundle:
    candidates = _candidate_media(post)
    if not candidates:
        return VisionBundle(root.resolve(strict=False), (), 0)
    directory = _ensure_event_directory(root, post.profile_id, post.post_id)
    _clear_directory(directory)
    owns_session = session is None
    client = session or requests.Session()
    client.trust_env = False
    client.proxies.clear()
    assets: list[VisionAsset] = []
    unavailable_count = 0
    total_bytes = 0
    deadline = deadline if deadline is not None else time.monotonic() + PREPARATION_TIMEOUT_SECONDS
    try:
        for ordinal, (role, media) in enumerate(candidates):
            if time.monotonic() >= deadline:
                unavailable_count += len(candidates) - ordinal
                break
            try:
                path, size = _download_image(client, media, directory, ordinal, total_bytes, deadline)
            except VisionMediaError:
                unavailable_count += 1
                continue
            total_bytes += size
            assets.append(VisionAsset(role, post.post_id, media.index, path))
    finally:
        if owns_session:
            client.close()
    return VisionBundle(directory, tuple(assets), unavailable_count)
