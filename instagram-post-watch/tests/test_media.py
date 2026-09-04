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
        self.closed = False

    def raise_for_status(self): pass

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


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
    responses = [FakeResponse([b"two"]), FakeResponse([b"one"])]
    session = FakeSession(responses)
    downloaded = media.download_publication(post(sources), tmp_path, session, DownloadLimits())
    assert [asset.source.index for asset in downloaded.assets] == [1, 0]
    assert downloaded.assets[0].sha256 == hashlib.sha256(b"two").hexdigest()
    assert all(asset.path.is_file() and ".tmp" not in asset.path.name for asset in downloaded.assets)
    assert all(response.closed for response in responses)


def test_oversized_asset_has_no_partial_final_file(tmp_path):
    source = SourceMedia("https://cdn/large.jpg", MediaKind.IMAGE, 0)
    session = FakeSession([FakeResponse([b"1234", b"5678"])])
    with pytest.raises(media.MediaDownloadError, match="asset size limit"):
        media.download_publication(post([source]), tmp_path, session, DownloadLimits(max_asset_bytes=5))
    event_dir = tmp_path / "event-1"
    assert not list(event_dir.glob("*.jpg"))
    assert not list(event_dir.glob("*.tmp"))


def test_publication_size_limit_removes_prior_assets_and_closes_all_responses(tmp_path):
    sources = [SourceMedia("https://cdn/one.jpg", MediaKind.IMAGE, 0), SourceMedia("https://cdn/two.jpg", MediaKind.IMAGE, 1)]
    responses = [FakeResponse([b"1234"]), FakeResponse([b"5678"])]
    with pytest.raises(media.MediaDownloadError, match="publication size limit"):
        media.download_publication(post(sources), tmp_path, FakeSession(responses), DownloadLimits(max_publication_bytes=5))
    assert all(response.closed for response in responses)
    assert not list((tmp_path / "event-1").glob("*"))


def test_rejects_non_media_content_type(tmp_path):
    source = SourceMedia("https://cdn/file", MediaKind.IMAGE, 0)
    with pytest.raises(media.MediaDownloadError, match="content type"):
        media.download_publication(post([source]), tmp_path, FakeSession([FakeResponse([b"x"], "text/html")]), DownloadLimits())


def test_video_content_type_gets_matching_extension(tmp_path):
    source = SourceMedia("https://cdn/file.webm", MediaKind.VIDEO, 0)
    downloaded = media.download_publication(post([source]), tmp_path, FakeSession([FakeResponse([b"x"], "video/webm")]), DownloadLimits())
    assert downloaded.assets[0].path.suffix == ".webm"


@pytest.mark.parametrize("url", ["file:///tmp/x.jpg", "http://127.0.0.1/x.jpg", "javascript:alert(1)"])
def test_download_rejects_unsafe_media_url_without_request(tmp_path, url):
    source = SourceMedia(url, MediaKind.IMAGE, 0)
    with pytest.raises(media.MediaDownloadError, match="unsupported media URL"):
        media.download_publication(post([source]), tmp_path, FakeSession([]), DownloadLimits())


@pytest.mark.parametrize("publication_id", ["..", "../escape", "nested/name", "\\escape"])
def test_download_rejects_event_id_traversal(tmp_path, publication_id):
    unsafe = SourcePost("profile", publication_id, "https://instagram.com/p/ABC/", datetime.now(UTC), "", PublicationKind.POST, ())
    with pytest.raises(media.MediaDownloadError, match="unsafe publication identifier"):
        media.download_publication(unsafe, tmp_path, FakeSession([]), DownloadLimits())


def test_download_rejects_event_directory_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "event-1").symlink_to(outside, target_is_directory=True)
    source = SourceMedia("https://cdn/file.jpg", MediaKind.IMAGE, 0)
    with pytest.raises(media.MediaDownloadError, match="unsafe publication identifier"):
        media.download_publication(post([source]), tmp_path, FakeSession([]), DownloadLimits())


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


def test_sampling_failure_is_sanitized_and_preserves_video(tmp_path):
    video = tmp_path / "reel.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")

    def runner(command):
        raise media.FrameSamplingError("ffmpeg failed")

    with pytest.raises(media.FrameSamplingError, match="frame sampling failed") as error:
        media.sample_reel_frames(video, cover, tmp_path, 5, runner=runner, duration_seconds=12.0)
    assert "ffmpeg failed" not in str(error.value)
    assert video.exists()


def test_invalid_ffprobe_duration_is_degraded_with_sanitized_error(tmp_path, monkeypatch):
    video = tmp_path / "reel.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")

    class Result:
        stdout = "nan"

    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(media.FrameSamplingError, match="invalid reel duration"):
        media.sample_reel_frames(video, cover, tmp_path, 5)


def test_sampling_ffprobe_failure_is_sanitized(tmp_path, monkeypatch):
    video = tmp_path / "reel.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret command output")))
    with pytest.raises(media.FrameSamplingError, match="ffprobe failed") as error:
        media.sample_reel_frames(video, cover, tmp_path, 5)
    assert "secret" not in str(error.value)


def test_cleanup_removes_only_managed_event_directory(tmp_path):
    keep = tmp_path / "keep.txt"
    keep.write_text("keep")
    event = tmp_path / "event-1"
    event.mkdir()
    (event / "media.jpg").write_bytes(b"x")
    media.cleanup_event_media(tmp_path, "event-1")
    assert keep.exists()
    assert not event.exists()


def test_cleanup_failure_is_visible_and_sanitized(tmp_path, monkeypatch):
    event = tmp_path / "event-1"
    event.mkdir()
    monkeypatch.setattr(media.shutil, "rmtree", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("secret path")))
    with pytest.raises(media.MediaCleanupError, match="cleanup failed") as error:
        media.cleanup_event_media(tmp_path, "event-1")
    assert "secret" not in str(error.value)
