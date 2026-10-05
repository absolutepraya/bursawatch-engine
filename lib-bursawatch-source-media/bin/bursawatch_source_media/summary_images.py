"""Optional, verified local image context. Never classifies, invokes models or sends."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Literal

from .client import SourceMediaClient
from .models import MediaDownload


@dataclass(frozen=True)
class SummaryImageRef:
    ref: str
    sha256: str
    size_bytes: int
    content_type: str
    association: str
    index: int


@dataclass(frozen=True)
class PreparedSummaryImage:
    asset_id: str
    path: Path
    sha256: str
    association: str
    index: int


@dataclass(frozen=True)
class SummaryImageBundle:
    status: Literal["ready", "partial", "unavailable"]
    assets: tuple[PreparedSummaryImage, ...]
    unavailable_count: int


@dataclass(frozen=True)
class SummaryImageLimits:
    max_assets: int = 4
    per_asset_bytes: int = 8 * 1024 * 1024
    total_bytes: int = 25 * 1024 * 1024
    request_seconds: float = 8.0
    preparation_seconds: float = 20.0

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in
               (self.max_assets, self.per_asset_bytes, self.total_bytes)):
            raise ValueError("invalid optional image limits")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value <= 0 for value in
               (self.request_seconds, self.preparation_seconds)):
            raise ValueError("invalid optional image limits")


_SLOTS = threading.BoundedSemaphore(4)
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def _directory(root: Path, binding: str, *, create: bool) -> Path:
    if not isinstance(binding, str) or not binding or root.is_symlink():
        raise ValueError("invalid optional image root")
    root = root.absolute()
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError("invalid optional image root")
    directory = root / hashlib.sha256(binding.encode()).hexdigest()
    if directory.is_symlink():
        raise ValueError("invalid optional image directory")
    if create:
        root.chmod(0o700)
        directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.is_dir() or directory.stat().st_uid != os.getuid():
            raise ValueError("invalid optional image directory")
        directory.chmod(0o700)
    return directory


def _download(client: SourceMediaClient, ref: str, maximum: int, seconds: float) -> MediaDownload | None:
    if seconds <= 0 or not _SLOTS.acquire(blocking=False):
        return None
    ready = threading.Event()
    result: list[MediaDownload] = []

    def worker() -> None:
        try:
            result.append(client.download(ref, max_bytes=maximum, timeout_seconds=seconds))
        except Exception:
            pass  # Optional context never exposes raw service failures.
        finally:
            _SLOTS.release()
            ready.set()

    try:
        threading.Thread(target=worker, daemon=True).start()
    except RuntimeError:
        _SLOTS.release()
        return None
    return result[0] if ready.wait(seconds) and result else None


def _verified(ref: SummaryImageRef, download: MediaDownload | None) -> bool:
    if not isinstance(download, MediaDownload) or not isinstance(download.data, bytes):
        return False
    data = download.data
    signatures = {
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    return (download.kind == "image" and download.content_type == ref.content_type
            and len(data) == ref.size_bytes and download.sha256 == ref.sha256
            and hashlib.sha256(data).hexdigest() == ref.sha256
            and signatures.get(ref.content_type, False))


def prepare_summary_images(
    refs: tuple[SummaryImageRef, ...], *, client: SourceMediaClient, root: Path,
    binding: str, limits: SummaryImageLimits = SummaryImageLimits(),
) -> SummaryImageBundle:
    """Prepare only requested original image refs, with bounded time/bytes/workers."""
    assets: list[PreparedSummaryImage] = []
    deadline = time.monotonic() + limits.preparation_seconds
    used = 0
    try:
        directory = _directory(Path(root), binding, create=True)
        for ordinal, ref in enumerate(refs[:limits.max_assets]):
            if (not isinstance(ref, SummaryImageRef) or not isinstance(ref.ref, str)
                    or not isinstance(ref.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", ref.sha256)
                    or type(ref.size_bytes) is not int or ref.size_bytes <= 0
                    or ref.size_bytes > min(limits.per_asset_bytes, limits.total_bytes - used)
                    or ref.content_type not in _EXTENSIONS or not isinstance(ref.association, str)
                    or type(ref.index) is not int or ref.index < 0):
                continue
            remaining = min(limits.request_seconds, deadline - time.monotonic())
            if remaining <= 0:
                break
            # Charge attempted reads as well as successful assets to the byte budget.
            maximum = ref.size_bytes
            used += ref.size_bytes
            downloaded = _download(client, ref.ref, maximum, remaining)
            if time.monotonic() >= deadline or not _verified(ref, downloaded):
                continue
            assert downloaded is not None
            asset_id = f"{ordinal}-{ref.sha256}"
            path = directory / (asset_id + _EXTENSIONS[ref.content_type])
            if path.is_symlink():
                continue
            fd, temporary = tempfile.mkstemp(dir=directory, prefix=".summary-")
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(downloaded.data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            assets.append(PreparedSummaryImage(asset_id, path, ref.sha256, ref.association, ref.index))
    except (OSError, ValueError):
        pass
    unavailable = len(refs) - len(assets)
    status = "unavailable" if not assets else "partial" if unavailable else "ready"
    return SummaryImageBundle(status, tuple(assets), unavailable)


def cleanup_summary_images(root: Path, binding: str) -> None:
    """Remove only this private binding's temporary analysis assets."""
    try:
        directory = _directory(Path(root), binding, create=False)
        if directory.is_dir():
            shutil.rmtree(directory)
    except (OSError, ValueError):
        pass


def record_summary_expiry(root: Path, binding: str, expires_at: float) -> None:
    """Retain the claim's deadline beside its temporary assets, never in owner state."""
    if not math.isfinite(expires_at):
        raise ValueError("invalid optional image expiry")
    directory = _directory(root, binding, create=False)
    descriptor, temporary = tempfile.mkstemp(prefix=".expiry-", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(str(expires_at))
        os.replace(temporary, directory / ".expires-at")
    finally:
        Path(temporary).unlink(missing_ok=True)


def expire_summary_images(root: Path, now: float) -> None:
    """Opportunistically discard expired private bundles, preserving active ones."""
    try:
        root = Path(root).absolute()
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
            return
        for directory in root.iterdir():
            if (re.fullmatch(r"[0-9a-f]{64}", directory.name) is None
                    or directory.is_symlink() or not directory.is_dir()
                    or directory.stat().st_uid != os.getuid()):
                continue
            expiry = directory / ".expires-at"
            if (expiry.is_symlink() or not expiry.is_file() or expiry.stat().st_size > 64
                    or expiry.stat().st_uid != os.getuid()):
                continue
            try:
                deadline = float(expiry.read_text())
            except (OSError, ValueError):
                continue
            if math.isfinite(deadline) and deadline <= now:
                shutil.rmtree(directory)
    except (OSError, ValueError):
        pass
