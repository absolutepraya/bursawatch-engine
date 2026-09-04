from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import requests

from models import DownloadLimits, DownloadedAsset, DownloadedPublication, MediaKind, SourceMedia, SourcePost


class MediaDownloadError(RuntimeError):
    pass


class FrameSamplingError(RuntimeError):
    pass


def _extension(source: SourceMedia, content_type: str) -> str:
    if source.kind is MediaKind.VIDEO:
        return ".mp4"
    return ".png" if "png" in content_type else ".jpg"


def download_publication(post: SourcePost, root: Path, session: requests.Session, limits: DownloadLimits) -> DownloadedPublication:
    media_root = root / post.publication_id
    media_root.mkdir(parents=True, exist_ok=True)
    assets: list[DownloadedAsset] = []
    total = 0
    try:
        for source in post.media:
            try:
                response = session.get(source.url, stream=True, timeout=limits.timeout_seconds)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                expected = "video/" if source.kind is MediaKind.VIDEO else "image/"
                if not content_type.startswith(expected):
                    raise MediaDownloadError("unsupported media content type")
                suffix = _extension(source, content_type)
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
                final_path = media_root / f"{source.index}{suffix}"
                os.replace(temporary_name, final_path)
                assets.append(DownloadedAsset(source, final_path, digest.hexdigest(), size, content_type))
            except MediaDownloadError:
                raise
            except (OSError, requests.RequestException) as exc:
                raise MediaDownloadError("media download failed") from exc
    except Exception:
        for temporary in media_root.glob("*.tmp"):
            temporary.unlink(missing_ok=True)
        for asset in assets:
            asset.path.unlink(missing_ok=True)
        raise
    return DownloadedPublication(tuple(assets), media_root)


def sample_reel_frames(video_path: Path, cover_path: Path, root: Path, max_frames: int, *, runner: Callable[[list[str]], None] | None = None, duration_seconds: float | None = None) -> tuple[DownloadedAsset, ...]:
    if max_frames < 1:
        return ()
    source_cover = SourceMedia(cover_path.as_uri(), MediaKind.IMAGE, 0)
    cover_asset = DownloadedAsset(source_cover, cover_path, hashlib.sha256(cover_path.read_bytes()).hexdigest(), cover_path.stat().st_size, "image/jpeg")
    if max_frames == 1:
        return (cover_asset,)
    run = runner or (lambda command: subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    duration = duration_seconds
    if duration is None:
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)], check=True, capture_output=True, text=True)
            duration = float(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise FrameSamplingError("ffprobe failed") from exc
    frames: list[DownloadedAsset] = [cover_asset]
    frame_root = root / f"{video_path.stem}-frames"
    frame_root.mkdir(parents=True, exist_ok=True)
    try:
        for index in range(1, max_frames):
            output = frame_root / f"{index}.jpg"
            timestamp = duration * index / max_frames
            run(["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1", str(output)])
            data = output.read_bytes()
            frames.append(DownloadedAsset(SourceMedia(output.as_uri(), MediaKind.IMAGE, index), output, hashlib.sha256(data).hexdigest(), len(data), "image/jpeg"))
    except (OSError, subprocess.SubprocessError, FrameSamplingError) as exc:
        for path in frame_root.glob("*"):
            path.unlink(missing_ok=True)
        return (cover_asset,)
    return tuple(frames)


def cleanup_event_media(root: Path, event_id: str) -> None:
    event_root = (root / event_id).resolve()
    root_resolved = root.resolve()
    if event_root.parent != root_resolved or event_root == root_resolved:
        raise ValueError("event directory is outside media root")
    shutil.rmtree(event_root, ignore_errors=True)
