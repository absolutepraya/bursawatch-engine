from datetime import UTC, datetime

from models import PostKind, SourceMedia, SourcePost
import vision_media


class Response:
    def __init__(self, status_code: int, content: bytes, content_type: str = "image/jpeg"):
        self.status_code = status_code
        self._content = content
        self.headers = {"content-type": content_type}
        self.closed = False

    def iter_content(self, chunk_size: int):
        assert chunk_size == 64 * 1024
        yield self._content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses: Response):
        self.responses = list(responses)
        self.urls: list[str] = []
        self.trust_env = True
        self.proxies = {"https": "http://should-not-be-used"}

    def get(self, url: str, *, stream: bool, timeout: int, allow_redirects: bool):
        assert stream is True
        assert 0 < timeout <= vision_media.REQUEST_TIMEOUT_SECONDS
        assert allow_redirects is False
        self.urls.append(url)
        return self.responses.pop(0)


def post() -> SourcePost:
    return SourcePost(
        "kutekians",
        "102",
        "https://x.com/Kutekians/status/102",
        datetime.now(UTC),
        "Author text",
        PostKind.QUOTE,
        "https://x.com/other/status/101",
        "Quoted text",
        (SourceMedia("https://pbs.twimg.com/media/authored.jpg?format=jpg&name=large", 0),),
        (SourceMedia("https://pbs.twimg.com/media/quoted.png?format=png&name=large", 0),),
    )


def test_prepare_downloads_authored_and_quoted_images_to_private_event_directory(tmp_path):
    session = Session(Response(200, b"authored", "image/jpeg"), Response(200, b"quoted", "image/png"))

    bundle = vision_media.prepare(post(), tmp_path / "vision", session)

    assert session.trust_env is False
    assert session.proxies == {}
    assert session.urls == [
        "https://pbs.twimg.com/media/authored.jpg?format=jpg&name=large",
        "https://pbs.twimg.com/media/quoted.png?format=png&name=large",
    ]
    assert [asset.role for asset in bundle.assets] == ["tweet", "quoted_tweet"]
    assert [asset.label for asset in bundle.assets] == ["Authored X post image 1", "Quoted X post image 1"]
    assert [asset.path.read_bytes() for asset in bundle.assets] == [b"authored", b"quoted"]
    assert all(asset.path.parent == bundle.root for asset in bundle.assets)
    assert bundle.unavailable_count == 0


def test_prepare_skips_unsupported_or_unavailable_images_without_blocking_other_vision(tmp_path):
    source = post()
    source = SourcePost(
        source.profile_id,
        source.post_id,
        source.url,
        source.published_at,
        source.content_html,
        source.kind,
        source.quoted_url,
        source.quoted_content_html,
        (SourceMedia("https://img.example/not-allowed.jpg", 0),),
        (SourceMedia("https://pbs.twimg.com/media/quoted.jpg", 0),),
    )
    session = Session(Response(200, b"quoted", "image/jpeg"))

    bundle = vision_media.prepare(source, tmp_path / "vision", session)

    assert session.urls == ["https://pbs.twimg.com/media/quoted.jpg"]
    assert [asset.role for asset in bundle.assets] == ["quoted_tweet"]
    assert bundle.unavailable_count == 0


def test_prepare_skips_tweet_video_urls_without_marking_the_image_bundle_degraded(tmp_path):
    source = post()
    source = SourcePost(
        source.profile_id,
        source.post_id,
        source.url,
        source.published_at,
        source.content_html,
        source.kind,
        source.quoted_url,
        source.quoted_content_html,
        (SourceMedia("https://video.twimg.com/ext_tw_video/123/video.mp4", 0),),
        (SourceMedia("https://pbs.twimg.com/media/quoted.jpg", 0),),
    )
    session = Session(Response(200, b"quoted", "image/jpeg"))

    bundle = vision_media.prepare(source, tmp_path / "vision", session)

    assert session.urls == ["https://pbs.twimg.com/media/quoted.jpg"]
    assert [asset.role for asset in bundle.assets] == ["quoted_tweet"]
    assert bundle.unavailable_count == 0


def test_prepare_keeps_successful_image_when_another_download_fails(tmp_path):
    session = Session(Response(404, b"missing"), Response(200, b"quoted", "image/jpeg"))

    bundle = vision_media.prepare(post(), tmp_path / "vision", session)

    assert [asset.role for asset in bundle.assets] == ["quoted_tweet"]
    assert bundle.unavailable_count == 1


def test_cleanup_event_removes_only_its_private_cache(tmp_path):
    root = tmp_path / "vision"
    session = Session(Response(200, b"authored"), Response(200, b"quoted"))
    bundle = vision_media.prepare(post(), root, session)
    unrelated = root / "other" / "100"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.jpg").write_bytes(b"keep")

    vision_media.cleanup_event(root, "kutekians", "102")

    assert not bundle.root.exists()
    assert (unrelated / "keep.jpg").read_bytes() == b"keep"
