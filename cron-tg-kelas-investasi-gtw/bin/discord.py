from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

import config

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

_DISCORD_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DISCORD_DELIVERY_BIN.exists():
    _DISCORD_DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DISCORD_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DISCORD_DELIVERY_BIN))

from bursawatch_discord_delivery import (
    DELIVERY_RECEIPT_WAIT_SECONDS,
    Attachment,
    DeliveryClient,
    DiscordQuery,
    OperationIntent,
    OperationReceipt,
)
from bursawatch_discord_delivery.client import DeliveryClientError
from render import GTW_SOURCE_STATUS, MAX_DISCORD_CHARACTERS, render_event
from swing_format import replace_board_topic_link


# The GTW All feed is part of the chronological Swing feed.  Board delivery
# is a separate owner handoff after this channel delivery succeeds.
DISCORD_CHANNEL_ID = "1525102458253217803"  # #id-stocks-swing
RETRY_INITIAL_SECONDS = 60
RETRY_CAP_SECONDS = 15 * 60
DELIVERY_OWNER_PREFIX = "bursawatch-tg-kelas-investasi-gtw"
DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
DELIVERY_CLIENT_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
NON_TERMINAL_DELIVERY_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


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


def delivery_client_from_environment(*, include_admin: bool = False) -> DeliveryClient:
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", DELIVERY_OWNER_URL)
    token_path = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / DELIVERY_CLIENT_TOKEN_FILE),
        )
    ).expanduser()
    admin_path = None
    if include_admin:
        configured = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured:
            raise DeliveryClientError("admin_credentials_required")
        admin_path = Path(configured).expanduser()
    return DeliveryClient(base_url, token_path, admin_token_file=admin_path)


def operation_key(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("delivery identity requires a nonempty source event and leg")
    normalized = re.sub(
        r"[^A-Za-z0-9:_./-]",
        lambda match: f"_u{ord(match.group()):04x}_",
        f"{event_key}:{leg}",
    )
    key = f"{DELIVERY_OWNER_PREFIX}:{normalized}"
    if len(key) > 200:
        raise ValueError("delivery operation identity is too long")
    return key


def _message_operation(
    content: str,
    channel_id: str,
    event_key: str,
    *,
    leg: str,
    attachments: tuple[Attachment, ...] = (),
) -> OperationIntent:
    if len(content) > MAX_DISCORD_CHARACTERS:
        raise ValueError("Discord text content exceeds 2,000 characters")
    return OperationIntent(
        key=operation_key(event_key, leg),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=attachments,
    )


def _submit_or_lookup(
    operation: OperationIntent,
    client: object,
    *,
    legacy_import_nonce: str | None = None,
) -> OperationReceipt:
    receipt = client.status(operation.key)  # type: ignore[attr-defined]
    from_existing_status = receipt is not None
    if not from_existing_status:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    expected_digest = operation.digest
    if isinstance(receipt, OperationReceipt) and receipt.key == operation.key and receipt.digest != operation.digest:
        if not from_existing_status or legacy_import_nonce is None:
            raise DeliveryClientError("invalid_response")
        imported = replace(
            operation,
            reconcile_before_first_create=True,
            legacy_nonce=legacy_import_nonce,
        )
        if receipt.digest != imported.digest:
            raise DeliveryClientError("invalid_response")
        expected_digest = imported.digest
    if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
        raise DeliveryClientError("invalid_response")
    if receipt.status in NON_TERMINAL_DELIVERY_STATUSES:
        receipt = client.wait(operation.key, DELIVERY_RECEIPT_WAIT_SECONDS)  # type: ignore[attr-defined]
        if not isinstance(receipt, OperationReceipt) or receipt.key != operation.key or receipt.digest != expected_digest:
            raise DeliveryClientError("invalid_response")
    return receipt


def _delivered_message_id(receipt: OperationReceipt, operation: OperationIntent) -> str | None:
    if receipt.status != "delivered" or not isinstance(receipt.receipt, dict):
        return None
    if receipt.receipt.get("channel_id") not in (None, operation.target["channel_id"]):
        raise DeliveryClientError("invalid_response")
    message_id = receipt.receipt.get("message_id")
    return message_id if isinstance(message_id, str) and message_id.isdigit() else None


def _mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def post_text(
    content: str,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    operation_event_key: str | None = None,
    operation_leg: str = "text",
    client: object | None = None,
) -> str | None:
    if len(content) > MAX_DISCORD_CHARACTERS:
        raise ValueError("Discord text content exceeds 2,000 characters")
    if dry_run:
        print(f"would post text channel={channel_id} nonce={nonce_value}")
        return None
    identity = operation_event_key if operation_event_key is not None else nonce_value
    operation = _message_operation(content, channel_id, identity, leg=operation_leg)
    owner = client if client is not None else delivery_client_from_environment()
    try:
        legacy_import_nonce = (
            nonce(operation_event_key, operation_leg)
            if operation_event_key is not None
            else None
        )
        receipt = _submit_or_lookup(
            operation,
            owner,
            legacy_import_nonce=legacy_import_nonce,
        )
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRateLimitError(RETRY_INITIAL_SECONDS) from None
        raise DiscordDeliveryError(str(error)) from None
    message_id = _delivered_message_id(receipt, operation)
    if message_id is None:
        raise DiscordDeliveryError("Discord delivery is still pending")
    return message_id


def post_file(
    path: Path,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    operation_event_key: str | None = None,
    operation_leg: str = "media:0",
    client: object | None = None,
) -> str | None:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("source image file is missing")
    if dry_run:
        print(f"would post file channel={channel_id} path={path} nonce={nonce_value}")
        return None
    attachment = Attachment(path.name, _mime_type(path), path.read_bytes())
    identity = operation_event_key if operation_event_key is not None else nonce_value
    operation = _message_operation(
        "", channel_id, identity, leg=operation_leg, attachments=(attachment,)
    )
    owner = client if client is not None else delivery_client_from_environment()
    try:
        legacy_import_nonce = (
            nonce(operation_event_key, operation_leg)
            if operation_event_key is not None
            else None
        )
        receipt = _submit_or_lookup(
            operation,
            owner,
            legacy_import_nonce=legacy_import_nonce,
        )
    except DeliveryClientError as error:
        if error.category == "rate_limited":
            raise DiscordRateLimitError(RETRY_INITIAL_SECONDS) from None
        raise DiscordDeliveryError(str(error)) from None
    message_id = _delivered_message_id(receipt, operation)
    if message_id is None:
        raise DiscordDeliveryError("Discord delivery is still pending")
    return message_id


def deliver_oldest_ready_event(
    state: dict[str, object],
    now: datetime,
    dry_run: bool | None = None,
    *,
    persist: Callable[[], None] | None = None,
    state_path: Path | None = None,
    media_root: Path | None = None,
    channel_id: str = DISCORD_CHANNEL_ID,
    client: object | None = None,
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
        from render import saved_presentation
        presentation = saved_presentation(event)
        if presentation is not None:
            channel_id = presentation["destination"]
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
            message_id = post_text(
                chunks[index],
                channel_id,
                False,
                nonce(str(event["event_key"]), f"text:{index}"),
                str(event["event_key"]),
                f"text:{index}",
                client,
            )
            if message_id:
                event.setdefault("text_message_ids", []).append(message_id)
            else:
                raise DiscordDeliveryError("Discord text receipt is unavailable")
            event["text_index"] = index + 1
        elif int(event["next_media_index"]) < len(_media(event)):
            index = int(event["next_media_index"])
            path = _media_path(_media(event)[index], media_root)
            message_id = post_file(
                path,
                channel_id,
                False,
                nonce(str(event["event_key"]), f"media:{index}"),
                str(event["event_key"]),
                f"media:{index}",
                client,
            )
            if not message_id:
                raise DiscordDeliveryError("Discord image receipt is unavailable")
            event["next_media_index"] = index + 1
        else:
            return _submit_board_context(state, event, now, dry_run, persist, media_root, channel_id, client)
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
        if event.get("all_delivery_completed_at") is None:
            event["all_delivery_completed_at"] = now.isoformat()
            _persist(persist)
        return _submit_board_context(state, event, now, dry_run, persist, media_root, channel_id, client)
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
    client: object | None = None,
) -> bool:
    """Patch every delivered GTW text chunk that still has the legacy link."""
    if not isinstance(board_url, str) or not board_url:
        return True
    if not isinstance(message_ids, list):
        return False
    if dry_run:
        print(f"would patch board links event={event_key} url={board_url}")
        return True
    owner = client if client is not None else delivery_client_from_environment()
    for index, message_id in enumerate(message_ids):
        if not isinstance(message_id, str) or not message_id:
            return False
        try:
            current = _read_channel_message_content(owner, channel_id, message_id)
            if current is None:
                return False
            updated = replace_board_topic_link(current, board_url)
            if updated == current:
                continue
            operation = OperationIntent(
                key=operation_key(event_key, f"board-link:{index}"),
                kind="channel_message_edit",
                ordering_key=f"channel:{channel_id}",
                target={"channel_id": channel_id, "message_id": message_id},
                payload={"content": updated, "allowed_mentions": {"parse": []}},
            )
            receipt = _submit_or_lookup(operation, owner)
            if receipt.status != "delivered":
                return False
        except DeliveryClientError as error:
            if error.category == "rate_limited":
                raise DiscordRateLimitError(RETRY_INITIAL_SECONDS) from None
            return False
    return True


def _read_channel_message_content(client: object, channel_id: str, message_id: str) -> str | None:
    try:
        target_id = int(message_id)
    except (TypeError, ValueError):
        return None
    cursor = str(target_id + 1)
    while True:
        result = client.query(  # type: ignore[attr-defined]
            DiscordQuery(kind="channel_messages", channel_id=channel_id, before=cursor, limit=100)
        )
        messages = result.get("messages") if isinstance(result, dict) else result
        if not isinstance(messages, list) or not messages:
            return None
        ids: list[int] = []
        for item in messages:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isdigit():
                return None
            ids.append(int(item["id"]))
            if item["id"] == message_id:
                content = item.get("content")
                return content if isinstance(content, str) else None
        oldest = min(ids)
        if oldest <= target_id:
            return None
        next_cursor = str(oldest)
        if next_cursor == cursor:
            return None
        cursor = next_cursor


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
        post_text(
            chunks[index], channel_id, True, nonce(event_key, f"text:{index}"),
            event_key, f"text:{index}",
        )
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
    client: object | None = None,
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
            client=client,
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
