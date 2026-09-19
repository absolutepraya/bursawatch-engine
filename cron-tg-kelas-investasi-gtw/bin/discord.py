from __future__ import annotations

import hashlib
import json
import os
import math
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

import requests

import config

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from render import GTW_SOURCE_STATUS, MAX_DISCORD_CHARACTERS, render_event
from swing_format import replace_board_topic_link


DISCORD_API = "https://discord.com/api/v10"
DISCORD_TIMEOUT_SECONDS = 30
# The GTW All feed is part of the chronological Swing feed.  Board delivery
# is a separate owner handoff after this channel delivery succeeds.
DISCORD_CHANNEL_ID = "1525102458253217803"  # #id-stocks-swing
RETRY_INITIAL_SECONDS = 60
RETRY_CAP_SECONDS = 15 * 60


class DiscordDeliveryError(RuntimeError):
    """A Discord delivery operation failed with a safe public reason."""


class DiscordRateLimitError(DiscordDeliveryError):
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
    channel_id: str = DISCORD_CHANNEL_ID,
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
        _print_intended(event, chunks, media_root, channel_id)
        return False

    try:
        if int(event["text_index"]) < len(chunks):
            index = int(event["text_index"])
            message_id = post_text(chunks[index], channel_id, False, nonce(str(event["event_key"]), f"text:{index}"))
            if message_id:
                event.setdefault("text_message_ids", []).append(message_id)
            event["text_index"] = index + 1
        elif int(event["next_media_index"]) < len(_media(event)):
            index = int(event["next_media_index"])
            path = _media_path(_media(event)[index], media_root)
            post_file(path, channel_id, False, nonce(str(event["event_key"]), f"media:{index}"))
            event["next_media_index"] = index + 1
        else:
            return _submit_board_context(state, event, now, dry_run, persist, media_root, channel_id)
    except DiscordRateLimitError as error:
        _record_failure(event, now, error, error.retry_after)
        _persist(persist)
        return False
    except Exception as error:
        _record_failure(event, now, error, None)
        _persist(persist)
        return False

    _clear_failure(event)
    _persist(persist)
    if _complete(event, chunks):
        return _submit_board_context(state, event, now, dry_run, persist, media_root, channel_id)
    return True


def board_payload(event: Mapping[str, object], media: Path | None = None) -> dict[str, object] | None:
    """Project a completed GTW bundle as source-only board context."""
    source_text = event.get("source_text")
    if not isinstance(source_text, str) or not source_text.splitlines():
        raise ValueError("board source text is invalid")
    source_title = source_text.splitlines()[0]
    if not source_title.strip():
        raise ValueError("board source title is invalid")
    published_at = event.get("source_published_at")
    if published_at is None:
        return None
    if not isinstance(published_at, str) or not published_at:
        raise ValueError("board source time is invalid")
    header_message_id = event.get("header_message_id")
    ticker = event.get("ticker")
    if not isinstance(header_message_id, int) or isinstance(header_message_id, bool) or header_message_id < 1:
        raise ValueError("board source message is invalid")
    if not isinstance(ticker, str) or not ticker:
        raise ValueError("board source ticker is invalid")
    return {
        "event_key": f"kelas-investasi:{event['event_key']}",
        "source": "kelas-investasi",
        "kind": "social",
        "ticker": ticker,
        "published_at": published_at,
        "source_url": f"https://t.me/{config.active_watch_config().telegram_username}/{header_message_id}",
        "all_content": "\n\n".join(render_event(event, include_board=False)),
        "source_title": source_title,
        "source_status": GTW_SOURCE_STATUS,
        "plan": None,
        "media_path": str(media) if media is not None else None,
        "media_urls": [],
    }


def submit_board_event(payload: Mapping[str, object], media: Path | None, dry_run: bool) -> bool:
    if dry_run:
        print(f"would submit board source event event={payload['event_key']}")
        return True
    submission = {**payload, "media_path": str(media) if media is not None else None}
    wrapper = os.environ.get(
        "IDX_SWING_PLAN_BOARD_WRAPPER",
        str(Path.home() / ".hermes" / "scripts" / "bursawatch-dc-swing-board.sh"),
    )
    try:
        completed = subprocess.run(
            [wrapper, "submit-source-event", "--stdin"],
            input=json.dumps(submission, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    try:
        acknowledgement = json.loads(completed.stdout.strip())
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(acknowledgement, dict)
        or set(acknowledgement) not in ({"accepted"}, {"accepted", "board_url"}, {"accepted", "board_url", "board_pending"})
        or type(acknowledgement.get("accepted")) is not bool
        or acknowledgement["accepted"] is not True
    ):
        return False
    board_url = acknowledgement.get("board_url")
    if board_url is not None and (type(board_url) is not str or not board_url):
        return False
    board_pending = acknowledgement.get("board_pending", False)
    if type(board_pending) is not bool:
        return False
    if isinstance(payload, dict):
        payload["_board_url"] = board_url
        payload["_board_pending"] = board_pending
    return True


def edit_board_links(
    message_ids: object,
    board_url: object,
    dry_run: bool,
    event_key: str,
    *,
    channel_id: str = DISCORD_CHANNEL_ID,
) -> bool:
    """Patch every delivered GTW text chunk that still has the legacy link."""
    if not isinstance(board_url, str) or not board_url:
        return True
    if not isinstance(message_ids, list):
        return False
    if dry_run:
        print(f"would patch board links event={event_key} url={board_url}")
        return True
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return False
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    for message_id in message_ids:
        if not isinstance(message_id, str) or not message_id:
            return False
        try:
            response = requests.get(
                f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}",
                headers=headers,
                timeout=DISCORD_TIMEOUT_SECONDS,
            )
            if response.status_code == 429:
                raise DiscordRateLimitError(_retry_after(response))
            if response.status_code != 200:
                return False
            current = response.json().get("content")
            if not isinstance(current, str):
                return False
            updated = replace_board_topic_link(current, board_url)
            if updated == current:
                continue
            response = requests.patch(
                f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}",
                headers=headers,
                json={"content": updated, "allowed_mentions": {"parse": []}},
                timeout=DISCORD_TIMEOUT_SECONDS,
            )
            if response.status_code == 429:
                raise DiscordRateLimitError(_retry_after(response))
            if response.status_code != 200:
                return False
        except requests.RequestException:
            return False
    return True


def _post(channel_id: str, **kwargs: Any) -> requests.Response:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise DiscordDeliveryError("Discord bot token is not configured")
    try:
        response = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            timeout=DISCORD_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as error:
        raise DiscordDeliveryError("Discord request failed") from error
    if response.status_code == 429:
        raise DiscordRateLimitError(_retry_after(response))
    if not response.ok:
        raise DiscordDeliveryError("Discord API request was rejected")
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
        raise DiscordDeliveryError("Discord API returned an invalid response") from error
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
    ready = [item for item in outbox if isinstance(item, dict)
             and item.get("agent_phase") in ("ready", "delivering")
             and isinstance(item.get("title"), str) and isinstance(item.get("summary"), str)]
    # Board backoff never occupies the head of the All text/image queue.
    return next((item for item in ready if not _complete_for_board(item)), ready[0] if ready else None)


def _retry_is_not_due(event: Mapping[str, object], now: datetime) -> bool:
    if _complete_for_board(event):
        value = event.get("board_next_attempt_at")
        return isinstance(value, str) and datetime.fromisoformat(value) > now
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


def _print_intended(
    event: Mapping[str, object],
    chunks: list[str],
    media_root: Path,
    channel_id: str,
) -> None:
    event_key = str(event["event_key"])
    for index in range(int(event["text_index"]), len(chunks)):
        post_text(chunks[index], channel_id, True, nonce(event_key, f"text:{index}"))
    for index in range(int(event["next_media_index"]), len(_media(event))):
        item = _media(event)[index]
        try:
            path = _media_path(item, media_root)
        except FileNotFoundError:
            path = Path("<missing-source-image>")
        print(f"would post file channel={channel_id} path={path} nonce={nonce(event_key, f'media:{index}')}")


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


def _submit_board_context(
    state: dict[str, object],
    event: dict[str, object],
    now: datetime,
    dry_run: bool,
    persist: Callable[[], None] | None,
    media_root: Path,
    channel_id: str,
) -> bool:
    # Keep board handoffs in source order while the All queue is independent.
    for earlier in state.get("outbox", []):
        if earlier is event:
            break
        if isinstance(earlier, dict) and _complete_for_board(earlier):
            return True
    try:
        payload = board_payload(event)
        if payload is None:
            _remove_event(state, event)
            _persist(persist)
            return True
        media = _board_media(event, media_root)
        payload = board_payload(event, media)
        if payload is None:
            raise ValueError("board source time is invalid")
        accepted = submit_board_event(payload, media, dry_run)
        if accepted and payload.get("_board_pending"):
            accepted = False
        if accepted and not edit_board_links(
            event.get("text_message_ids", []),
            payload.get("_board_url"),
            dry_run,
            str(event["event_key"]),
            channel_id=channel_id,
        ):
            accepted = False
    except Exception:
        accepted = False
    if not accepted:
        _record_board_failure(event, now)
        _persist(persist)
        # A completed All event may fail its handoff while other All events
        # still have immediately useful delivery work.
        next_event = _oldest_deliverable_event(state)
        return next_event is not None and not _complete_for_board(next_event)
    _clear_board_failure(event)
    _remove_event(state, event)
    _persist(persist)
    return True


def _board_media(event: Mapping[str, object], media_root: Path) -> Path | None:
    media = _media(event)
    if not media:
        return None
    return _media_path(media[0], media_root)


def _record_board_failure(event: dict[str, object], now: datetime) -> None:
    attempts = int(event["board_attempts"]) + 1
    delay = min(RETRY_INITIAL_SECONDS * (2 ** (attempts - 1)), RETRY_CAP_SECONDS)
    event["board_attempts"] = attempts
    event["board_next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
    event["board_last_error"] = "board source event was not accepted"


def _clear_board_failure(event: dict[str, object]) -> None:
    event["board_attempts"] = 0
    event["board_next_attempt_at"] = None
    event["board_last_error"] = None


def _complete_for_board(event: Mapping[str, object]) -> bool:
    try:
        return _complete(event, render_event(event))
    except Exception:
        return False


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
    if isinstance(error, DiscordDeliveryError):
        return str(error)
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
