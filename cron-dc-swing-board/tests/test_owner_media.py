from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from conftest import social_event
from discord_forum import DiscordForumClient
from engine import BoardEngine
import media_store
from store import BoardStore


class MediaResponse:
    status_code = 200

    def __init__(self, content=b"\xff\xd8\xffsource image", mime="image/jpeg", redirect=None):
        self.content = content
        self.headers = {"Content-Type": mime}
        if redirect:
            self.status_code = 302
            self.headers["Location"] = redirect

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, **_):
        yield self.content


def source_session(monkeypatch, responses):
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs == {"stream": True, "allow_redirects": False, "timeout": (5, 20)}
            calls.append(url)
            return responses.pop(0)

    monkeypatch.setattr(media_store.requests, "Session", Session)
    return calls


def test_ordered_x_attachments_are_owned_and_retry_without_redownload(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(root))
    downloads = source_session(monkeypatch, [MediaResponse(), MediaResponse()])
    client = Mock(spec=DiscordForumClient)
    client.prepare_payload.side_effect = lambda _op, payload: dict(payload)
    uploads = []

    def execute(op, payload):
        if payload.get("media"):
            path = Path(payload["media"])
            assert path.parent == root and path.is_file()
            assert path.stat().st_mode & 0o777 == 0o600
            uploads.append(payload["media_url"])
            if len(uploads) == 1:
                raise RuntimeError("upload retry")
        if op == "create_thread":
            return {"thread_id": "123", "starter_message_id": "456"}
        return {"message_id": "789"}

    client.execute.side_effect = execute
    owner = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), client)
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    urls = ("https://pbs.twimg.com/media/one.jpg", "https://pbs.twimg.com/media/two.jpg")
    owner.submit(replace(social_event("x:media", "SCMA", "SCMA: source chart"), media_urls=urls), now)
    assert owner.drain(now=now) == 0
    assert uploads == [urls[0]] and downloads == [urls[0]]
    restarted = BoardEngine(BoardStore(owner.store.path), client)
    assert restarted.drain(now=now + timedelta(minutes=1)) == 2
    assert uploads == [urls[0], urls[0], urls[1]]
    assert downloads == list(urls)
    assert owner.store.outbox_health() == {"pending": 0, "failed": 0}


@pytest.mark.parametrize("url", [
    "http://pbs.twimg.com/media/image.jpg", "https://127.0.0.1/private", "https://pbs.twimg.com.evil.test/image.jpg",
    "https://name:password@pbs.twimg.com/media/image.jpg", "https://pbs.twimg.com/media/image.jpg?token=secret",
])
def test_media_url_boundary_rejects_nonpublic_or_authenticated_sources(url):
    with pytest.raises(ValueError, match="public direct X"):
        media_store.validate_media_url(url)


def test_redirect_to_private_host_is_rejected_before_contact(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path))
    calls = source_session(monkeypatch, [MediaResponse(redirect="https://127.0.0.1/private")])
    with pytest.raises(media_store.MediaAcquisitionError):
        media_store.acquire_media("https://pbs.twimg.com/media/one.jpg", "one")
    assert calls == ["https://pbs.twimg.com/media/one.jpg"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("response", [MediaResponse(b"not an image"), MediaResponse(mime="text/html"), MediaResponse(b"\xff\xd8\xff" + b"x" * 30)])
def test_invalid_or_oversized_media_keeps_no_partial_file(tmp_path, monkeypatch, response):
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(media_store, "MAX_MEDIA_BYTES", 20)
    source_session(monkeypatch, [response])
    with pytest.raises(media_store.MediaAcquisitionError):
        media_store.acquire_media("https://pbs.twimg.com/media/one.jpg", "one")
    assert list(tmp_path.iterdir()) == []


def test_no_post_owner_never_downloads_remote_media(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.acquire_media", Mock(side_effect=AssertionError("network forbidden")))
    owner = BoardEngine(BoardStore(tmp_path / "board.sqlite3"), DiscordForumClient(no_post=True))
    now = datetime.fromisoformat("2026-09-21T10:00:00+07:00")
    owner.submit(replace(social_event("x:media", "SCMA", "SCMA: source"), media_urls=("https://pbs.twimg.com/media/one.jpg",)), now)
    assert owner.drain(now=now) == 1
