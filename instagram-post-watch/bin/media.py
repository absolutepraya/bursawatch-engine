from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import requests

from models import DownloadLimits, DownloadedAsset, DownloadedPublication, MediaKind, SourceMedia, SourcePost
from rsshub import is_supported_media_url


class MediaDownloadError(RuntimeError):
    pass


class FrameSamplingError(RuntimeError):
    pass


class MediaCleanupError(RuntimeError):
    pass


_CONTENT_TYPES = {
    (MediaKind.IMAGE, "image/jpeg"): ".jpg",
    (MediaKind.IMAGE, "image/png"): ".png",
    (MediaKind.IMAGE, "image/webp"): ".webp",
    (MediaKind.IMAGE, "image/gif"): ".gif",
    (MediaKind.VIDEO, "video/mp4"): ".mp4",
    (MediaKind.VIDEO, "video/webm"): ".webm",
    (MediaKind.VIDEO, "video/quicktime"): ".mov",
}


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
        for source in post.media:
            if not is_supported_media_url(source.url):
                raise MediaDownloadError("unsupported media URL")
            if not isinstance(source.index, int) or source.index < 0:
                raise MediaDownloadError("unsafe media index")
            response = None
            try:
                response = session.get(source.url, stream=True, timeout=limits.timeout_seconds)
                response.raise_for_status()
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
    except MediaDownloadError:
        for temporary in media_root.glob("*.tmp"):
            temporary.unlink(missing_ok=True)
        for asset in assets:
            asset.path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        for temporary in media_root.glob("*.tmp"):
            temporary.unlink(missing_ok=True)
        for asset in assets:
            asset.path.unlink(missing_ok=True)
        raise MediaDownloadError("media download failed") from exc
    return DownloadedPublication(tuple(assets), media_root)


def sample_reel_frames(video_path: Path, cover_path: Path, root: Path, max_frames: int, *, runner: Callable[[list[str]], None] | None = None, duration_seconds: float | None = None) -> tuple[DownloadedAsset, ...]:
    if max_frames < 1:
        return ()
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
    frame_root = root / f"{video_path.stem}-frames"
    try:
        frame_root.mkdir(parents=True, exist_ok=True)
        for index in range(1, max_frames):
            output = frame_root / f"{index}.jpg"
            timestamp = duration * index / max_frames
            run(["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1", str(output)])
            data = output.read_bytes()
            frames.append(DownloadedAsset(SourceMedia(output.as_uri(), MediaKind.IMAGE, index), output, hashlib.sha256(data).hexdigest(), len(data), "image/jpeg"))
    except Exception as exc:
        for path in frame_root.glob("*"):
            path.unlink(missing_ok=True)
        raise FrameSamplingError("frame sampling failed") from exc
    return tuple(frames)


def cleanup_event_media(root: Path, event_id: str) -> None:
    event_root = (root / event_id).resolve()
    root_resolved = root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", event_id) or event_id in {".", ".."}:
        raise ValueError("event directory is outside media root")
    if event_root.parent != root_resolved or event_root == root_resolved:
        raise ValueError("event directory is outside media root")
    try:
        shutil.rmtree(event_root)
    except FileNotFoundError:
        return
    except Exception as exc:
        raise MediaCleanupError("event media cleanup failed") from exc
