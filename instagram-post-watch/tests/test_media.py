import hashlib
from pathlib import Path

import pytest
import requests

import media
from models import DownloadLimits, MediaKind, SourceMedia, SourcePost, PublicationKind
from datetime import datetime, UTC


class FakeResponse:
    def __init__(self, chunks, content_type="image/jpeg"):
        self.chunks = chunks
        self.headers = {"content-type": content_type}

    def raise_for_status(self): pass

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def iter_content(self, chunk_size):
        yield from self.chunks


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def post(media_items):
    return SourcePost("profile", "event-1", "https://instagram.com/p/ABC/", datetime.now(UTC), "", PublicationKind.POST, tuple(media_items))


def test_downloads_in_source_order_hashes_and_uses_atomic_final_files(tmp_path):
    sources = [SourceMedia("https://cdn/2.jpg", MediaKind.IMAGE, 1), SourceMedia("https://cdn/1.jpg", MediaKind.IMAGE, 0)]
    session = FakeSession([FakeResponse([b"two"]), FakeResponse([b"one"])])
    downloaded = media.download_publication(post(sources), tmp_path, session, DownloadLimits())
    assert [asset.source.index for asset in downloaded.assets] == [1, 0]
    assert downloaded.assets[0].sha256 == hashlib.sha256(b"two").hexdigest()
    assert all(asset.path.is_file() and ".tmp" not in asset.path.name for asset in downloaded.assets)


def test_oversized_asset_has_no_partial_final_file(tmp_path):
    source = SourceMedia("https://cdn/large.jpg", MediaKind.IMAGE, 0)
    session = FakeSession([FakeResponse([b"1234", b"5678"])])
    with pytest.raises(media.MediaDownloadError, match="asset size limit"):
        media.download_publication(post([source]), tmp_path, session, DownloadLimits(max_asset_bytes=5))
    event_dir = tmp_path / "event-1"
    assert not list(event_dir.glob("*.jpg"))
    assert not list(event_dir.glob("*.tmp"))


def test_rejects_non_media_content_type(tmp_path):
    source = SourceMedia("https://cdn/file", MediaKind.IMAGE, 0)
    with pytest.raises(media.MediaDownloadError, match="content type"):
        media.download_publication(post([source]), tmp_path, FakeSession([FakeResponse([b"x"], "text/html")]), DownloadLimits())


def test_download_timeout_is_sanitized_and_leaves_no_final_file(tmp_path):
    source = SourceMedia("https://cdn/timeout.jpg", MediaKind.IMAGE, 0)

    class TimeoutSession:
        def get(self, url, **kwargs):
            assert kwargs["timeout"] == 30
            raise requests.Timeout("secret origin details")

    with pytest.raises(media.MediaDownloadError, match="media download failed") as error:
        media.download_publication(post([source]), tmp_path, TimeoutSession(), DownloadLimits())
    assert "secret" not in str(error.value)


def test_reel_sampling_includes_cover_and_at_most_cap(tmp_path):
    video = tmp_path / "reel.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    calls = []

    def runner(command):
        calls.append(command)
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"frame")

    frames = media.sample_reel_frames(video, cover, tmp_path, 5, runner=runner, duration_seconds=12.0)
    assert len(frames) == 5
    assert frames[0].path == cover
    assert all(asset.source.kind is MediaKind.IMAGE for asset in frames)
    assert len(calls) == 4


def test_sampling_failure_preserves_video_and_returns_cover(tmp_path):
    video = tmp_path / "reel.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")

    def runner(command):
        raise media.FrameSamplingError("ffmpeg failed")

    frames = media.sample_reel_frames(video, cover, tmp_path, 5, runner=runner, duration_seconds=12.0)
    assert len(frames) == 1
    assert video.exists()


def test_cleanup_removes_only_managed_event_directory(tmp_path):
    keep = tmp_path / "keep.txt"
    keep.write_text("keep")
    event = tmp_path / "event-1"
    event.mkdir()
    (event / "media.jpg").write_bytes(b"x")
    media.cleanup_event_media(tmp_path, "event-1")
    assert keep.exists()
    assert not event.exists()
