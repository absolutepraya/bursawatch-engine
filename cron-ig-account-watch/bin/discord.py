from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

import requests


API = "https://discord.com/api/v10"
DISCORD_TIMEOUT_SECONDS = 30
DISCORD_LIMIT = 2_000
MAX_MEDIA_PATH_CHARACTERS = 4_096
MAX_MEDIA_BYTES = 25 * 1024 * 1024
RETRY_FALLBACK_SECONDS = 60.0
RETRY_MAX_SECONDS = 15 * 60.0

_ALLOWED_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}


class DiscordDeliveryError(RuntimeError):
    """A Discord delivery failure with no provider body or secret details."""


class DiscordRetryAfter(DiscordDeliveryError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__("Discord rate limited")


def discord_length(value: str) -> int:
    """Return Discord's UTF-16 code-unit length for a text value."""
    if not isinstance(value, str):
        raise TypeError("Discord content must be text")
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


def nonce(event_key: str, leg: str) -> str:
    """Return one deterministic nonce for one durable Instagram delivery leg."""
    if not isinstance(event_key, str) or not isinstance(leg, str):
        raise ValueError("Discord nonce inputs are invalid")
    digest = hashlib.sha256(f"instagram-post-watch:{event_key}:{leg}".encode("utf-8")).hexdigest()[:24]
    return digest


def _token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise DiscordDeliveryError("Discord bot token is unavailable")
    return token


def _retry_after(response: Any) -> float:
    try:
        payload = response.json()
        value = payload.get("retry_after") if isinstance(payload, dict) else None
        seconds = float(value)
    except (AttributeError, TypeError, ValueError, requests.RequestException):
        seconds = RETRY_FALLBACK_SECONDS
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = RETRY_FALLBACK_SECONDS
    return min(seconds, RETRY_MAX_SECONDS)


def _message_id(response: Any) -> str:
    try:
        payload = response.json()
    except (AttributeError, ValueError, requests.RequestException) as exc:
        raise DiscordDeliveryError("Discord returned an invalid message response") from exc
    value = payload.get("id") if isinstance(payload, dict) else None
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and value and len(value) <= 128 and not any(ord(char) < 32 for char in value):
        return value
    raise DiscordDeliveryError("Discord returned an invalid message response")


def _request(channel_id: str, *, json_payload: dict[str, object] | None = None, files: dict[str, object] | None = None) -> str:
    try:
        response = requests.post(
            f"{API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {_token()}"},
            json=json_payload,
            files=files,
            timeout=DISCORD_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise DiscordDeliveryError("Discord request failed") from exc
    status = getattr(response, "status_code", None)
    if status == 429:
        raise DiscordRetryAfter(_retry_after(response))
    if not isinstance(status, int) or not 200 <= status < 300:
        safe_status = status if isinstance(status, int) else "unknown"
        raise DiscordDeliveryError(f"Discord HTTP {safe_status}")
    return _message_id(response)


def post_text(content: str, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if not isinstance(content, str) or discord_length(content) > DISCORD_LIMIT:
        raise ValueError("Discord text content exceeds 2,000 characters")
    if dry_run:
        print(f"[dry-run] Discord text channel={channel_id} nonce={nonce_value}")
        return None
    return _request(
        channel_id,
        json_payload={
            "content": content,
            "nonce": nonce_value,
            "allowed_mentions": {"parse": []},
        },
    )


def _lstat_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise ValueError("Discord media path is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("Discord media path is invalid")


def _validated_media_root() -> Path:
    configured_root = os.environ.get("INSTAGRAM_POST_WATCH_MEDIA_ROOT")
    if not configured_root:
        raise ValueError("Discord media root is unavailable")
    root = Path(configured_root)
    if (
        not root.is_absolute()
        or root == Path(root.anchor)
        or len(configured_root) > MAX_MEDIA_PATH_CHARACTERS
        or "\x00" in configured_root
        or "://" in configured_root
        or any(part in {".", ".."} for part in configured_root.split(os.sep))
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise ValueError("Discord media root is invalid")
    try:
        _lstat_components(root)
        mode = os.lstat(root).st_mode
        if not stat.S_ISDIR(mode):
            raise ValueError("Discord media root is invalid")
        return root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Discord media root is invalid") from exc


def _validated_media_path(path: Path) -> tuple[Path, str]:
    root = _validated_media_root()
    if not isinstance(path, Path):
        path = Path(path)
    path_text = str(path)
    if (
        not path.is_absolute()
        or not path_text
        or len(path_text) > MAX_MEDIA_PATH_CHARACTERS
        or "\x00" in path_text
        or "://" in path_text
        or any(part in {".", ".."} for part in path_text.split(os.sep))
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("Discord media path is invalid")
    _lstat_components(path)
    try:
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("Discord media path is invalid")
        resolved = path.resolve(strict=True)
        size = resolved.stat().st_size
    except (OSError, RuntimeError) as exc:
        raise ValueError("Discord media path is unavailable") from exc
    if size <= 0 or size > MAX_MEDIA_BYTES:
        raise ValueError("Discord media size is invalid")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Discord media path is outside the watcher media root") from exc

    media_type = mimetypes.guess_type(resolved.name)[0]
    if media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("Discord media type is unsupported")
    return resolved, media_type


def _temporary_upload_copy(source: Path) -> Path:
    temporary: Path | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".instagram-post-watch-upload-",
            suffix=source.suffix,
            dir=source.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        with handle, source.open("rb") as original:
            shutil.copyfileobj(original, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except (OSError, ValueError) as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise DiscordDeliveryError("Discord media staging failed") from exc


def post_media(path: Path, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    source, content_type = _validated_media_path(path)
    if dry_run:
        print(f"[dry-run] Discord media channel={channel_id} nonce={nonce_value}")
        return None

    temporary: Path | None = None
    try:
        temporary = _temporary_upload_copy(source)
        with temporary.open("rb") as content:
            return _request(
                channel_id,
                json_payload=None,
                files={
                    "files[0]": (source.name, content, content_type),
                    "payload_json": (
                        None,
                        json.dumps({"nonce": nonce_value, "allowed_mentions": {"parse": []}}),
                        "application/json",
                    ),
                },
            )
    except DiscordDeliveryError:
        raise
    except (OSError, ValueError) as exc:
        raise DiscordDeliveryError("Discord media upload failed") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
