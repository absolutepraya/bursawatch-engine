from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from telegram_source import (
    SOURCE_ID,
    TelegramSourceError,
    capture_image,
    fetch_unseen_messages,
    make_client,
    resolve_source,
    to_source_message,
)


class Raw:
    def __init__(self, message_id: int, *, photo: object | None = None, document: object | None = None) -> None:
        self.id = message_id
        self.date = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
        self.message = f"message {message_id}"
        self.reply_to = None
        self.photo = photo
        self.document = document


class FakeClient:
    def __init__(self, messages: list[Raw] = [], *, image: bytes | None = None, accessible: bool = True) -> None:
        self.messages = messages
        self.image = image
        self.accessible = accessible
        self.iter_kwargs: dict[str, object] | None = None

    async def iter_messages(self, entity: object, **kwargs: object):
        self.iter_kwargs = kwargs
        for message in self.messages:
            yield message

    async def get_entity(self, source_id: int) -> object:
        if not self.accessible:
            raise RuntimeError("not permitted")
        assert source_id == SOURCE_ID
        return object()

    async def get_messages(self, entity: object, ids: int) -> Raw | None:
        return next((message for message in self.messages if message.id == ids), None)

    async def download_media(self, message: Raw, file: object) -> bytes | None:
        return self.image


def raw(message_id: int, **kwargs: object) -> Raw:
    return Raw(message_id, **kwargs)


def test_unseen_messages_are_returned_by_ascending_id() -> None:
    client = FakeClient([raw(103), raw(101), raw(102)])
    messages = asyncio.run(fetch_unseen_messages(client, object(), 100))
    assert [message.message_id for message in messages] == [101, 102, 103]
    assert client.iter_kwargs == {"min_id": 100, "reverse": True}


def test_photo_is_source_media_but_text_document_is_excluded() -> None:
    converted = to_source_message(raw(101, photo=object()))
    document = to_source_message(raw(102, document=object()))
    assert [(item.message_id, item.ordinal) for item in converted.media] == [(101, 0)]
    assert document.media == ()


def test_two_images_keep_source_message_order_despite_raw_order() -> None:
    messages = asyncio.run(fetch_unseen_messages(FakeClient([raw(103, photo=object()), raw(101, photo=object())]), object(), 100))
    assert [(message.message_id, media.ordinal) for message in messages for media in message.media] == [(101, 0), (103, 0)]


def test_capture_image_writes_the_downloaded_source_bytes(tmp_path: Path) -> None:
    path = asyncio.run(capture_image(FakeClient([raw(102, photo=object())], image=b"chart"), object(), 102, 0, tmp_path))
    assert path == tmp_path / "kelas-investasi-102-0.jpg"
    assert path.read_bytes() == b"chart"


def test_capture_image_rejects_empty_download(tmp_path: Path) -> None:
    with pytest.raises(TelegramSourceError, match="image download was empty"):
        asyncio.run(capture_image(FakeClient([raw(102, photo=object())], image=b""), object(), 102, 0, tmp_path))
    assert not list(tmp_path.iterdir())


def test_inaccessible_source_is_sanitized() -> None:
    with pytest.raises(TelegramSourceError, match="source is inaccessible"):
        asyncio.run(resolve_source(FakeClient(accessible=False)))


def test_incomplete_credentials_do_not_expose_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYCOP_SESSION_STRING", "secret-session-content")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_API_HASH", "secret-hash")
    with pytest.raises(TelegramSourceError) as error:
        make_client()
    assert "secret-session-content" not in str(error.value)
    assert "secret-hash" not in str(error.value)
