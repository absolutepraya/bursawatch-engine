from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from models import SourceMedia, SourceMessage


SOURCE_ID = 2142109618


class TelegramSourceError(RuntimeError):
    """A Telegram source operation failed without exposing credentials."""


def make_client() -> Any:
    """Create the shared-PolyCop Telethon client from required environment values."""
    session = os.environ.get("POLYCOP_SESSION_STRING")
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not session or not api_id or not api_hash:
        raise TelegramSourceError("Telegram credentials are incomplete")
    try:
        numeric_api_id = int(api_id)
    except ValueError as error:
        raise TelegramSourceError("Telegram credentials are incomplete") from error
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        return TelegramClient(StringSession(session), numeric_api_id, api_hash)
    except Exception as error:
        raise TelegramSourceError("Telegram client could not be initialized") from error


async def resolve_source(client: Any) -> Any:
    try:
        dialogs = await client.get_dialogs()
    except Exception as error:
        raise TelegramSourceError("Telegram source is inaccessible") from error
    for dialog in dialogs:
        entity = getattr(dialog, "entity", None)
        if getattr(entity, "id", None) == SOURCE_ID:
            return entity
    raise TelegramSourceError("Telegram source is inaccessible")


async def latest_message_id(client: Any, entity: Any) -> int | None:
    try:
        message = await client.get_messages(entity, limit=1)
    except Exception as error:
        raise TelegramSourceError("Telegram source could not be read") from error
    if isinstance(message, list):
        message = message[0] if message else None
    return _message_id(message) if message is not None else None


async def fetch_unseen_messages(client: Any, entity: Any, min_id: int) -> list[SourceMessage]:
    try:
        raw_messages = [message async for message in client.iter_messages(entity, min_id=min_id, reverse=True)]
    except Exception as error:
        raise TelegramSourceError("Telegram source could not be read") from error
    return [to_source_message(message) for message in sorted(raw_messages, key=_message_id)]


def to_source_message(message: Any) -> SourceMessage:
    message_id = _message_id(message)
    posted_at = getattr(message, "date", None)
    if posted_at is None:
        raise TelegramSourceError("Telegram message is missing its timestamp")
    reply_to = getattr(message, "reply_to", None)
    reply_to_message_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
    text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
    media = (SourceMedia(message_id=message_id, ordinal=0),) if getattr(message, "photo", None) is not None else ()
    return SourceMessage(message_id, posted_at, str(text), reply_to_message_id, media)


async def capture_image(client: Any, entity: Any, message_id: int, ordinal: int, destination: Path) -> Path:
    try:
        message = await client.get_messages(entity, ids=message_id)
    except Exception as error:
        raise TelegramSourceError("Telegram source image is inaccessible") from error
    if message is None or getattr(message, "photo", None) is None:
        raise TelegramSourceError("Telegram source image is inaccessible")
    try:
        payload = await client.download_media(message, file=bytes)
    except Exception as error:
        raise TelegramSourceError("Telegram image download failed") from error
    if not isinstance(payload, bytes) or not payload:
        raise TelegramSourceError("Telegram image download was empty")
    path = Path(destination) / f"kelas-investasi-{message_id}-{ordinal}.jpg"
    _atomic_write(path, payload)
    return path


def _message_id(message: Any) -> int:
    value = getattr(message, "id", None)
    if not isinstance(value, int):
        raise TelegramSourceError("Telegram message is missing its ID")
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
