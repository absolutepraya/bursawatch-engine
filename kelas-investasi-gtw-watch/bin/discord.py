from __future__ import annotations

import hashlib
import json
import os
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from render import MAX_DISCORD_CHARACTERS, render_event


DISCORD_API = "https://discord.com/api/v10"
DISCORD_TIMEOUT_SECONDS = 30
DISCORD_CHANNEL_ID = "1525102508714889257"
RETRY_INITIAL_SECONDS = 60
RETRY_CAP_SECONDS = 15 * 60


class DiscordRateLimitError(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        super().__init__("Discord rate limited")
        self.retry_after = retry_after


def nonce(event_key: str, leg: str) -> str:
    """Return the stable Discord nonce for exactly one durable delivery leg."""
    value = f"kelas-investasi-gtw-watch:{event_key}:{leg}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def post_text(content: str, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if len(content) > MAX_DISCORD_CHARACTERS:
        raise ValueError("Discord text content exceeds 2,000 characters")
    if dry_run:
        print(f"would post text channel={channel_id} nonce={nonce_value}")
        return None
    response = _post(channel_id, json={"content": content, "nonce": nonce_value})
    return _message_id(response)


def post_file(path: Path, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("source image file is missing")
    if dry_run:
        print(f"would post file channel={channel_id} path={path} nonce={nonce_value}")
        return None
    with path.open("rb") as source:
        response = _post(
            channel_id,
            data={"payload_json": json.dumps({"nonce": nonce_value})},
            files={"files[0]": (path.name, source)},
        )
    return _message_id(response)


def deliver_oldest_ready_event(
    state: dict[str, object],
    now: datetime,
    dry_run: bool | None = None,
    *,
    persist: Callable[[], None] | None = None,
    state_path: Path | None = None,
    media_root: Path | None = None,
) -> bool:
    """Deliver at most one durable leg, or print all pending legs in no-post mode.

    The two indices are the delivery cursor: text chunks are exhausted before
    media is considered, and each index advances only after Discord accepts
    that exact nonce.
    """
    # Task 6 calls this directly, so delivery owns the no-post resolution and
    # the immediate persistence hook rather than depending on a later scan.
    if dry_run is None:
        dry_run = os.environ.get("KELAS_INVESTASI_GTW_NO_POST") == "1"
    if persist is not None and state_path is not None:
        raise ValueError("provide either persist or state_path")
    if state_path is not None:
        from state import save_state

        persist = lambda: save_state(state_path, state)
    media_root = (media_root or _configured_media_root(state_path)).resolve()
    event = _oldest_deliverable_event(state)
    if event is None:
        return False
    if _retry_is_not_due(event, now):
        return False

    try:
        chunks = render_event(event)
    except Exception:
        _record_failure(event, now, RuntimeError("invalid delivery event"), None)
        _persist(persist)
        return False
    if not _valid_cursor(event, chunks):
        _record_failure(event, now, RuntimeError("invalid delivery cursor"), None)
        _persist(persist)
        return False
    if dry_run:
        _print_intended(event, chunks, media_root)
        return False

    try:
        if int(event["text_index"]) < len(chunks):
            index = int(event["text_index"])
            post_text(chunks[index], DISCORD_CHANNEL_ID, False, nonce(str(event["event_key"]), f"text:{index}"))
            event["text_index"] = index + 1
        elif int(event["next_media_index"]) < len(_media(event)):
            index = int(event["next_media_index"])
            path = _media_path(_media(event)[index], media_root)
            post_file(path, DISCORD_CHANNEL_ID, False, nonce(str(event["event_key"]), f"media:{index}"))
            event["next_media_index"] = index + 1
        else:
            _remove_event(state, event)
            _persist(persist)
            return True
    except DiscordRateLimitError as error:
        _record_failure(event, now, error, error.retry_after)
        _persist(persist)
        return False
    except Exception as error:
        _record_failure(event, now, error, None)
        _persist(persist)
        return False

    _clear_failure(event)
    if _complete(event, chunks):
        _remove_event(state, event)
    _persist(persist)
    return True


def _post(channel_id: str, **kwargs: Any) -> requests.Response:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Discord bot token is not configured")
    try:
        response = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            timeout=DISCORD_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as error:
        raise RuntimeError("Discord request failed") from error
    if response.status_code == 429:
        raise DiscordRateLimitError(_retry_after(response))
    if not response.ok:
        raise RuntimeError(f"Discord API returned HTTP {response.status_code}: {_response_error(response)}")
    return response


def _retry_after(response: requests.Response) -> float:
    try:
        payload = response.json()
        value = payload.get("retry_after") if isinstance(payload, dict) else None
        seconds = float(value)
    except (TypeError, ValueError, requests.RequestException):
        seconds = 0.0
    return seconds if math.isfinite(seconds) and seconds > 0 else RETRY_INITIAL_SECONDS


def _message_id(response: requests.Response) -> str:
    try:
        payload = response.json()
    except requests.RequestException as error:
        raise RuntimeError("Discord API returned an invalid response") from error
    value = payload.get("id") if isinstance(payload, dict) else None
    return str(value) if value is not None else ""


def _response_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except requests.RequestException:
        return "request was rejected"
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return _sanitize(payload["message"])
    return "request was rejected"


def _oldest_deliverable_event(state: Mapping[str, object]) -> dict[str, object] | None:
    outbox = state.get("outbox")
    if not isinstance(outbox, list):
        return None
    for item in outbox:
        if isinstance(item, dict) and item.get("agent_phase") in ("ready", "delivering") and isinstance(item.get("title"), str) and isinstance(item.get("summary"), str):
            return item
    return None


def _retry_is_not_due(event: Mapping[str, object], now: datetime) -> bool:
    value = event.get("next_attempt_at")
    return isinstance(value, str) and datetime.fromisoformat(value) > now


def _media(event: Mapping[str, object]) -> list[object]:
    value = event.get("media")
    return value if isinstance(value, list) else []


def _media_path(item: object, media_root: Path) -> Path:
    if isinstance(item, Mapping):
        value = item.get("path")
        if isinstance(value, str) and value:
            path = Path(value).resolve()
            try:
                path.relative_to(media_root)
            except ValueError as error:
                raise FileNotFoundError("captured source media is unavailable") from error
            if path.is_file() and path.stat().st_size > 0 and _is_image(path):
                return path
    raise FileNotFoundError("captured source media is unavailable")


def _print_intended(event: Mapping[str, object], chunks: list[str], media_root: Path) -> None:
    event_key = str(event["event_key"])
    for index in range(int(event["text_index"]), len(chunks)):
        post_text(chunks[index], DISCORD_CHANNEL_ID, True, nonce(event_key, f"text:{index}"))
    for index in range(int(event["next_media_index"]), len(_media(event))):
        item = _media(event)[index]
        try:
            path = _media_path(item, media_root)
        except FileNotFoundError:
            path = Path("<missing-source-image>")
        print(f"would post file channel={DISCORD_CHANNEL_ID} path={path} nonce={nonce(event_key, f'media:{index}')}")


def _record_failure(event: dict[str, object], now: datetime, error: BaseException, retry_after: float | None) -> None:
    attempts = int(event["attempts"]) + 1
    delay = retry_after if retry_after is not None else min(RETRY_INITIAL_SECONDS * (2 ** (attempts - 1)), RETRY_CAP_SECONDS)
    event["attempts"] = attempts
    event["next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
    event["last_error"] = _sanitize(error)


def _clear_failure(event: dict[str, object]) -> None:
    event["attempts"] = 0
    event["next_attempt_at"] = None
    event["last_error"] = None


def _complete(event: Mapping[str, object], chunks: list[str]) -> bool:
    return int(event["text_index"]) == len(chunks) and int(event["next_media_index"]) == len(_media(event))


def _remove_event(state: dict[str, object], event: dict[str, object]) -> None:
    outbox = state.get("outbox")
    if isinstance(outbox, list):
        outbox.remove(event)


def _sanitize(error: BaseException) -> str:
    # Persisted state is operationally visible. Never retain provider bodies,
    # paths, tokens, or arbitrary exception strings there.
    if isinstance(error, DiscordRateLimitError):
        return "Discord rate limited"
    if isinstance(error, FileNotFoundError):
        return "captured source media is unavailable"
    if "cursor" in str(error).lower():
        return "delivery cursor is invalid"
    if "event" in str(error).lower():
        return "delivery event is invalid"
    return "Discord delivery failed"


def _persist(persist: object) -> None:
    if persist is not None:
        persist()  # type: ignore[operator]


def _configured_media_root(state_path: Path | None = None) -> Path:
    configured = os.environ.get("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT")
    if configured:
        return Path(configured)
    return state_path.parent / "media" if state_path is not None else Path("state/media")


def _valid_cursor(event: Mapping[str, object], chunks: list[str]) -> bool:
    text_index = event.get("text_index")
    media_index = event.get("next_media_index")
    return (
        isinstance(text_index, int)
        and not isinstance(text_index, bool)
        and 0 <= text_index <= len(chunks)
        and isinstance(media_index, int)
        and not isinstance(media_index, bool)
        and 0 <= media_index <= len(_media(event))
    )


def _is_image(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            header = source.read(16)
    except OSError:
        return False
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or header.startswith((b"GIF87a", b"GIF89a"))
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )
