import json
from datetime import UTC
from pathlib import Path

import pytest
import requests

import rsshub
import config as config_module
from models import MediaKind, PublicationKind


@pytest.fixture
def configured_profile():
    return config_module.load_watch_config(
        Path(__file__).parent.parent / "config" / "watches.json"
    ).profiles[0]


def load_fixture(name):
    with open(__file__.replace("test_rsshub.py", "fixtures/" + name), encoding="utf-8") as handle:
        return json.load(handle)


def test_image_caption_strips_media_but_preserves_text_and_links(configured_profile):
    post = rsshub.parse_feed(load_fixture("image-post.json"), configured_profile)[0]
    assert post.publication_id == "media-1001"
    assert post.caption_html == '<p>Caption <a href="https://example.com/report">with a link</a></p>'
    assert [(asset.url, asset.kind, asset.index) for asset in post.media] == [
        ("https://cdn.example/image.jpg", MediaKind.IMAGE, 0),
    ]
    assert post.media[0].kind is MediaKind.IMAGE


def test_carousel_preserves_source_order(configured_profile):
    post = rsshub.parse_feed(load_fixture("carousel-post.json"), configured_profile)[0]
    assert post.kind is PublicationKind.POST
    assert [asset.index for asset in post.media] == [0, 1, 2, 3]
    assert [asset.kind for asset in post.media] == [MediaKind.IMAGE] * 4
    assert [asset.url for asset in post.media] == [f"https://cdn.example/{i}.jpg" for i in range(1, 5)]


def test_reel_is_forwardable_when_reels_are_enabled(configured_profile):
    post = rsshub.parse_feed(load_fixture("reel-post.json"), configured_profile)[0]
    assert post.kind is PublicationKind.REEL
    assert rsshub.is_forwardable(configured_profile, post) is True
    assert [asset.kind for asset in post.media] == [MediaKind.VIDEO, MediaKind.IMAGE]


def test_media_tags_are_removed_without_losing_caption_after_a_reel(configured_profile):
    payload = {"items": [{
        "id": "media-1004", "url": "https://instagram.com/reel/AFTER/",
        "date_published": "2026-08-24T11:00:00Z",
        "content_html": "<video src=\"https://cdn.example/a.mp4\"></video><p>After video</p>",
    }]}
    post = rsshub.parse_feed(payload, configured_profile)[0]
    assert post.caption_html == "<p>After video</p>"


def test_self_closing_video_does_not_hide_following_caption(configured_profile):
    payload = {"items": [{
        "id": "media-1005", "url": "https://instagram.com/reel/SELF/",
        "date_published": "2026-08-24T11:01:00Z",
        "content_html": "<video src=\"https://cdn.example/a.mp4\"/><p>Visible caption</p>",
    }]}
    assert rsshub.parse_feed(payload, configured_profile)[0].caption_html == "<p>Visible caption</p>"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/internal.jpg",
    "https://127.0.0.1/internal.jpg",
    "file:///tmp/image.jpg",
    "javascript:alert(1)",
    "https://cdn.example:8080/image.jpg",
])
def test_media_urls_stay_inside_supported_public_http_boundary(configured_profile, url):
    payload = {"items": [{
        "id": "media-1006", "url": "https://instagram.com/p/URLBOUNDARY/",
        "date_published": "2026-08-24T11:02:00Z", "content_html": f'<img src="{url}">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile) == []


@pytest.mark.parametrize("url", [
    "http://cdn.example/image.jpg",
    "https://cdn.example/image.jpg",
])
def test_public_http_image_urls_are_extracted(configured_profile, url):
    payload = {"items": [{
        "id": "media-1007", "url": "https://instagram.com/p/PUBLICURL/",
        "date_published": "2026-08-24T11:03:00Z", "content_html": f'<img src="{url}">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile)[0].media[0].url == url


def test_unsafe_shortcode_and_naive_timestamp_are_filtered(configured_profile):
    payload = {"items": [
        {"id": "safe", "url": "https://instagram.com/p/../", "date_published": "2026-08-24T11:04:00Z", "content_html": '<img src="https://cdn.example/a.jpg">'},
        {"id": "naive", "url": "https://instagram.com/p/NAIVE/", "date_published": "2026-08-24T11:04:00", "content_html": '<img src="https://cdn.example/a.jpg">'},
    ]}
    assert rsshub.parse_feed(payload, configured_profile) == []


def test_private_and_malformed_publications_are_filtered(configured_profile):
    assert rsshub.parse_feed(load_fixture("private-profile.json"), configured_profile) == []
    assert rsshub.parse_feed(load_fixture("malformed-feed.json"), configured_profile) == []


def test_fetch_uses_one_request_timeout_and_sanitizes_errors(configured_profile):
    class BrokenSession:
        def get(self, *args, **kwargs):
            assert kwargs == {"timeout": 30}
            raise requests.ConnectionError("password=secret response body should not leak")

    with pytest.raises(rsshub.SourceFetchError, match="RSSHub request failed") as error:
        rsshub.fetch_profile_items(configured_profile, BrokenSession())
    assert "secret" not in str(error.value)


def test_fetch_closes_response_and_sanitizes_generic_response_failure(configured_profile):
    class Response:
        def __init__(self): self.closed = False
        def raise_for_status(self): raise RuntimeError("body=secret url=https://private.example")
        def close(self): self.closed = True

    response = Response()
    class Session:
        def get(self, *args, **kwargs): return response

    with pytest.raises(rsshub.SourceFetchError, match="source failed") as error:
        rsshub.fetch_profile_items(configured_profile, Session())
    assert "secret" not in str(error.value)
    assert response.closed is True


def test_fetch_rejects_non_object_or_missing_items(configured_profile):
    class Response:
        def raise_for_status(self): pass
        def json(self): return []

    class Session:
        def get(self, *args, **kwargs): return Response()

    with pytest.raises(rsshub.SourceFetchError, match="items list"):
        rsshub.fetch_profile_items(configured_profile, Session())


def test_after_id_returns_only_newer_feed_entries(configured_profile):
    payload = load_fixture("carousel-post.json")
    payload["items"].append({
        "id": "media-1003", "url": "https://instagram.com/p/NEXT/",
        "date_published": "2026-08-24T10:00:00Z", "content_html": "<img src=\"https://cdn.example/next.jpg\">",
    })
    posts = rsshub.parse_feed(payload, configured_profile, after_id="media-1002")
    assert [post.publication_id for post in posts] == ["media-1003"]
