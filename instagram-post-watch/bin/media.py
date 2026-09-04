from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
import socket
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import requests
import urllib3
from urllib3.util import connection as urllib3_connection

from models import DownloadLimits, DownloadedAsset, DownloadedPublication, MediaKind, SourceMedia, SourcePost
from rsshub import is_public_ip_address, is_publicly_resolvable_media_url, is_supported_media_url


class MediaDownloadError(RuntimeError):
    def __init__(self, message: str, *, cleanup_failed: bool = False):
        super().__init__(message)
        self.cleanup_failed = cleanup_failed


class FrameSamplingError(RuntimeError):
    def __init__(self, message: str, *, cleanup_failed: bool = False):
        super().__init__(message)
        self.cleanup_failed = cleanup_failed


class MediaCleanupError(RuntimeError):
    pass


def _connection_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise urllib3.exceptions.NameResolutionError(host, None, exc) from exc
    addresses: list[str] = []
    for record in records:
        try:
            address = ipaddress.ip_address(record[4][0])
        except (IndexError, ValueError):
            continue
        if not is_public_ip_address(address):
            continue
        if record[4][0] not in addresses:
            addresses.append(record[4][0])
    if not addresses:
        raise urllib3.exceptions.NewConnectionError(None, "media connection address rejected")
    return tuple(addresses)


class _PinnedHTTPSConnection(urllib3.connection.HTTPSConnection):
    def _new_conn(self):
        last_error = None
        for address in _connection_public_addresses(self.host, self.port):
            try:
                # Connect to the validated IP while the inherited HTTPS connect keeps self.host for SNI and Host verification.
                return urllib3_connection.create_connection(
                    (address, self.port),
                    self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise urllib3.exceptions.NewConnectionError(None, "media connection failed") from last_error


class _PinnedHTTPSConnectionPool(urllib3.connectionpool.HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedHTTPSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3.PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)
        self.poolmanager.pool_classes_by_scheme["https"] = _PinnedHTTPSConnectionPool


def _ensure_connection_policy(session: requests.Session) -> None:
    if not getattr(session, "_instagram_pinned_https", False):
        session.trust_env = False
        session.proxies.clear()
        session.mount("https://", _PinnedHTTPSAdapter())
        session._instagram_pinned_https = True


_CONTENT_TYPES = {
    (MediaKind.IMAGE, "image/jpeg"): ".jpg",
    (MediaKind.IMAGE, "image/png"): ".png",
    (MediaKind.IMAGE, "image/webp"): ".webp",
    (MediaKind.IMAGE, "image/gif"): ".gif",
    (MediaKind.VIDEO, "video/mp4"): ".mp4",
    (MediaKind.VIDEO, "video/webm"): ".webm",
    (MediaKind.VIDEO, "video/quicktime"): ".mov",
}


def _best_effort_unlink(paths) -> bool:
    failed = False
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            failed = True
    return failed


def _best_effort_cleanup(directory: Path, patterns: tuple[str, ...], extra_paths=()) -> bool:
    failed = False
    paths = list(extra_paths)
    for pattern in patterns:
        try:
            paths.extend(directory.glob(pattern))
        except Exception:
            failed = True
    return _best_effort_unlink(paths) or failed


def _managed_regular_file(path: Path, root: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FrameSamplingError("managed media file is invalid")
    root_resolved = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FrameSamplingError("managed media file is outside root") from exc
    return resolved


def download_publication(post: SourcePost, root: Path, session: requests.Session, limits: DownloadLimits) -> DownloadedPublication:
    root_resolved = root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", post.publication_id) or post.publication_id in {".", ".."}:
        raise MediaDownloadError("unsafe publication identifier")
    media_candidate = root_resolved / post.publication_id
    if media_candidate.is_symlink():
        raise MediaDownloadError("unsafe publication identifier")
    media_root = media_candidate.resolve()
    if media_root.parent != root_resolved:
        raise MediaDownloadError("unsafe publication identifier")
    try:
        media_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise MediaDownloadError("media directory creation failed") from exc
    assets: list[DownloadedAsset] = []
    total = 0
    try:
        if isinstance(session, requests.Session):
            _ensure_connection_policy(session)
        for source in post.media:
            if not is_supported_media_url(source.url):
                raise MediaDownloadError("unsupported media URL")
            if not isinstance(source.index, int) or source.index < 0:
                raise MediaDownloadError("unsafe media index")
            response = None
            try:
                if not is_publicly_resolvable_media_url(source.url):
                    raise MediaDownloadError("unsupported media URL")
                response = session.get(source.url, stream=True, timeout=limits.timeout_seconds, allow_redirects=False)
                response.raise_for_status()
                if 300 <= getattr(response, "status_code", 200) < 400:
                    raise MediaDownloadError("media redirects are not supported")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                suffix = _CONTENT_TYPES.get((source.kind, content_type))
                if suffix is None:
                    raise MediaDownloadError("unsupported media content type")
                fd, temporary_name = tempfile.mkstemp(prefix=f"{source.index}-", suffix=".tmp", dir=media_root)
                digest = hashlib.sha256()
                size = 0
                with os.fdopen(fd, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        total += len(chunk)
                        if size > limits.max_asset_bytes:
                            raise MediaDownloadError("asset size limit exceeded")
                        if total > limits.max_publication_bytes:
                            raise MediaDownloadError("publication size limit exceeded")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                final_path = (media_root / f"{source.index}{suffix}").resolve()
                if final_path.parent != media_root:
                    raise MediaDownloadError("unsafe media path")
                os.replace(temporary_name, final_path)
                assets.append(DownloadedAsset(source, final_path, digest.hexdigest(), size, content_type))
            except MediaDownloadError:
                raise
            except Exception as exc:
                raise MediaDownloadError("media download failed") from exc
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
    except MediaDownloadError as exc:
        cleanup_failed = _best_effort_cleanup(media_root, ("*.tmp",), [asset.path for asset in assets])
        exc.cleanup_failed = exc.cleanup_failed or cleanup_failed
        raise
    except Exception as exc:
        cleanup_failed = _best_effort_cleanup(media_root, ("*.tmp",), [asset.path for asset in assets])
        raise MediaDownloadError("media download failed", cleanup_failed=cleanup_failed) from exc
    return DownloadedPublication(tuple(assets), media_root)


def sample_reel_frames(video_path: Path, cover_path: Path, root: Path, max_frames: int, *, runner: Callable[[list[str]], None] | None = None, duration_seconds: float | None = None) -> tuple[DownloadedAsset, ...]:
    if max_frames < 1:
        return ()
    root_resolved = root.resolve()
    video_path = _managed_regular_file(video_path, root_resolved)
    cover_path = _managed_regular_file(cover_path, root_resolved)
    try:
        source_cover = SourceMedia(cover_path.as_uri(), MediaKind.IMAGE, 0)
        cover_data = cover_path.read_bytes()
        cover_asset = DownloadedAsset(source_cover, cover_path, hashlib.sha256(cover_data).hexdigest(), len(cover_data), "image/jpeg")
    except Exception as exc:
        raise FrameSamplingError("cover preparation failed") from exc
    if max_frames == 1:
        return (cover_asset,)
    run = runner or (lambda command: subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    duration = duration_seconds
    if duration is None:
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)], check=True, capture_output=True, text=True)
            duration = float(result.stdout.strip())
        except Exception as exc:
            raise FrameSamplingError("ffprobe failed") from exc
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise FrameSamplingError("invalid reel duration")
    frames: list[DownloadedAsset] = [cover_asset]
    frame_candidate = root_resolved / f"{video_path.stem}-frames"
    if frame_candidate.is_symlink():
        raise FrameSamplingError("managed frame directory is invalid")
    frame_root = frame_candidate.resolve()
    if frame_root.parent != root_resolved:
        raise FrameSamplingError("managed frame directory is outside root")
    try:
        frame_root.mkdir(parents=True, exist_ok=True)
        for index in range(1, max_frames):
            output_candidate = frame_root / f"{index}.jpg"
            if output_candidate.is_symlink() or output_candidate.exists() and not output_candidate.is_file():
                raise FrameSamplingError("managed frame output is invalid")
            output = output_candidate.resolve()
            if output.parent != frame_root:
                raise FrameSamplingError("managed frame output is outside root")
            timestamp = duration * index / max_frames
            run(["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1", str(output)])
            data = output.read_bytes()
            frames.append(DownloadedAsset(SourceMedia(output.as_uri(), MediaKind.IMAGE, index), output, hashlib.sha256(data).hexdigest(), len(data), "image/jpeg"))
    except Exception as exc:
        # The original downloaded video is the deliverable fallback. Sampling only creates analysis artifacts.
        cleanup_failed = _best_effort_cleanup(frame_root, ("*",))
        raise FrameSamplingError("frame sampling failed", cleanup_failed=cleanup_failed) from exc
    return tuple(frames)


def cleanup_event_media(root: Path, event_id: str) -> None:
    root_resolved = root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", event_id) or event_id in {".", ".."}:
        raise ValueError("event directory is outside media root")
    event_candidate = root_resolved / event_id
    if event_candidate.is_symlink():
        raise MediaCleanupError("event media cleanup failed")
    event_root = event_candidate.resolve()
    if event_root.parent != root_resolved or event_root == root_resolved:
        raise ValueError("event directory is outside media root")
    try:
        shutil.rmtree(event_root)
    except FileNotFoundError:
        return
    except Exception as exc:
        raise MediaCleanupError("event media cleanup failed") from exc
