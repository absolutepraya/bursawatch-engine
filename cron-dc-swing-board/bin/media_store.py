"""Private owner media acquisition for public, direct X attachments."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests


MAX_MEDIA_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 30
_HOSTS = {"pbs.twimg.com", "video.twimg.com"}
_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
          "image/webp": ".webp", "video/mp4": ".mp4"}


class MediaAcquisitionError(RuntimeError):
    """A sanitized, retryable owner attachment failure."""


def validate_media_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in _HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 443} or parsed.fragment
            or not parsed.path.startswith("/") or parsed.path == "/"
            or set(parse_qs(parsed.query)) - {"format", "name", "tag"}):
        raise ValueError("media URL must be a public direct X attachment")
    return value


def media_root() -> Path:
    return Path(os.environ.get("IDX_SWING_PLAN_BOARD_MEDIA_ROOT",
                               str(Path.home() / ".hermes/state/idx-swing-board-media")))


def acquire_media(url: str, operation_key: str) -> Path:
    """Download once into owner storage and reuse it across delivery retries."""
    validate_media_url(url)
    root = media_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(f"{operation_key}\n{url}".encode()).hexdigest()
    for suffix in _TYPES.values():
        candidate = root / f"{key}{suffix}"
        if candidate.is_file() and 0 < candidate.stat().st_size <= MAX_MEDIA_BYTES:
            return candidate
    started = time.monotonic()
    try:
        # Never inherit .netrc, credentials, or environment proxy settings.
        with requests.Session() as session:
            session.trust_env = False
            current = url
            for _ in range(4):
                validate_media_url(current)
                with session.get(current, stream=True, allow_redirects=False, timeout=(5, 20)) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        current = urljoin(current, response.headers.get("Location", ""))
                        continue
                    if response.status_code != 200:
                        raise MediaAcquisitionError("source media download unavailable")
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    suffix = _TYPES.get(mime)
                    length = int(response.headers.get("Content-Length", "0"))
                    if suffix is None or length > MAX_MEDIA_BYTES:
                        raise MediaAcquisitionError("source media exceeds supported limits")
                    descriptor, temporary = tempfile.mkstemp(prefix=f".{key}.", dir=root)
                    try:
                        count = 0
                        header = b""
                        with os.fdopen(descriptor, "wb") as target:
                            for chunk in response.iter_content(chunk_size=64 * 1024):
                                count += len(chunk)
                                if count > MAX_MEDIA_BYTES or time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                                    raise MediaAcquisitionError("source media exceeds supported limits")
                                if len(header) < 16:
                                    header += chunk[:16 - len(header)]
                                target.write(chunk)
                            if not count or not _matches_type(header, suffix):
                                raise MediaAcquisitionError("source media format unavailable")
                            target.flush()
                            os.fsync(target.fileno())
                        destination = root / f"{key}{suffix}"
                        os.replace(temporary, destination)
                        directory = os.open(root, os.O_RDONLY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                        return destination
                    finally:
                        Path(temporary).unlink(missing_ok=True)
            raise MediaAcquisitionError("source media redirect limit reached")
    except (requests.RequestException, OSError, ValueError) as exc:
        raise MediaAcquisitionError("source media acquisition failed") from exc


def _matches_type(header: bytes, suffix: str) -> bool:
    return {".jpg": header.startswith(b"\xff\xd8\xff"),
            ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
            ".gif": header.startswith((b"GIF87a", b"GIF89a")),
            ".webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
            ".mp4": header[4:8] == b"ftyp"}[suffix]
