import json
import socket
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


@pytest.mark.parametrize("metadata", [
    {"product_type": "clips"},
    {"product_type": "igtv"},
    {"type": "reel"},
    {"is_reel": True},
])
def test_reel_metadata_promotes_p_url_to_reel(configured_profile, metadata):
    payload = {"items": [{
        "id": "metadata-reel",
        "url": "https://instagram.com/p/METADATAREEL/",
        "date_published": "2026-08-24T10:00:00Z",
        "content_html": '<p>Video publication</p><video src="https://cdn.example/reel.mp4"></video>',
        **metadata,
    }]}

    posts = rsshub.parse_feed(payload, configured_profile)

    assert posts[0].kind is PublicationKind.REEL


def test_video_media_promotes_p_url_to_reel_without_metadata(configured_profile):
    payload = {"items": [{
        "id": "video-p-reel",
        "url": "https://instagram.com/p/VIDEOPREEL/",
        "date_published": "2026-08-24T10:00:00Z",
        "content_html": '<p>Video publication</p><video src="https://cdn.example/reel.mp4"></video>',
    }]}

    assert rsshub.parse_feed(payload, configured_profile)[0].kind is PublicationKind.REEL


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


def test_http_image_urls_are_rejected(configured_profile):
    payload = {"items": [{
        "id": "media-1007", "url": "https://instagram.com/p/PUBLICURL/",
        "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="http://cdn.example/image.jpg">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile) == []


def test_duplicate_publication_path_separators_are_rejected(configured_profile):
    payload = {"items": [{
        "id": "media-1008", "url": "https://instagram.com/p//DUPLICATE//",
        "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="https://cdn.example/image.jpg">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile) == []


@pytest.mark.parametrize("url", [
    "https://instagram.com/p/CANONICAL/?",
    "https://instagram.com/p/CANONICAL/#",
])
def test_empty_query_or_fragment_delimiters_are_rejected(configured_profile, url):
    payload = {"items": [{
        "id": "media-1009", "url": url,
        "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="https://cdn.example/image.jpg">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile) == []


@pytest.mark.parametrize("url", [
    "https://instagram.com/p/CANONICAL;param",
    "https://instagram.com/p/CANONICAL/;param",
    " https://instagram.com/p/CANONICAL/",
    "https://instagram.com/p/CANONICAL/ ",
    "\thttps://instagram.com/p/CANONICAL/",
    "https://instagram.com/p/CANONICAL/\n",
    "https://instagram.com/p/CANONICAL/\x7f",
])
def test_publication_url_params_and_control_whitespace_are_rejected(configured_profile, url):
    payload = {"items": [{
        "id": "media-1010", "url": url,
        "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="https://cdn.example/image.jpg">',
    }]}
    assert rsshub.parse_feed(payload, configured_profile) == []


def test_malformed_bracketed_publication_url_is_filtered_without_losing_valid_item(configured_profile):
    payload = {"items": [
        {"id": "bad-publication", "url": "https://[instagram.com/p/BAD/", "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="https://cdn.example/bad.jpg">'},
        {"id": "valid-publication", "url": "https://instagram.com/p/VALIDBRACKET/", "date_published": "2026-08-24T11:04:00Z", "content_html": '<img src="https://cdn.example/valid.jpg">'},
    ]}
    posts = rsshub.parse_feed(payload, configured_profile)
    assert [post.publication_id for post in posts] == ["valid-publication"]


def test_malformed_bracketed_media_url_is_filtered_without_losing_valid_items(configured_profile):
    payload = {"items": [
        {
            "id": "mixed-media",
            "url": "https://instagram.com/p/MIXEDMEDIA/",
            "date_published": "2026-08-24T11:03:00Z",
            "content_html": '<img src="https://[bad"><img src="https://cdn.example/valid.jpg">',
        },
        {"id": "valid-publication", "url": "https://instagram.com/p/VALIDMEDIA/", "date_published": "2026-08-24T11:04:00Z", "content_html": '<img src="https://cdn.example/next.jpg">'},
    ]}
    posts = rsshub.parse_feed(payload, configured_profile)
    assert [post.publication_id for post in posts] == ["mixed-media", "valid-publication"]
    assert [asset.url for asset in posts[0].media] == ["https://cdn.example/valid.jpg"]


def test_canonical_publication_urls_are_preserved(configured_profile):
    payload = {"items": [
        {"id": "media-1011", "url": "https://instagram.com/p/CANONICAL/", "date_published": "2026-08-24T11:03:00Z", "content_html": '<img src="https://cdn.example/image.jpg">'},
        {"id": "media-1012", "url": "https://www.instagram.com/reel/REELCODE", "date_published": "2026-08-24T11:04:00Z", "content_html": '<video src="https://cdn.example/video.mp4"></video>'},
    ]}
    posts = rsshub.parse_feed(payload, configured_profile)
    assert [(post.kind, post.url) for post in posts] == [
        (PublicationKind.POST, "https://instagram.com/p/CANONICAL/"),
        (PublicationKind.REEL, "https://www.instagram.com/reel/REELCODE"),
    ]


@pytest.mark.parametrize("address", ["100.64.0.1", "10.0.0.1", "169.254.0.1", "240.0.0.1", "224.0.0.1"])
def test_public_resolver_requires_global_unicast_addresses(monkeypatch, address):
    monkeypatch.setattr(
        rsshub.socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))],
    )
    assert rsshub.is_publicly_resolvable_media_url("https://cdn.example/image.jpg") is False


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


def test_after_id_missing_from_page_returns_the_page_for_durable_filtering(configured_profile):
    payload = load_fixture("carousel-post.json")

    posts = rsshub.parse_feed(payload, configured_profile, after_id="cursor-not-on-page")

    assert [post.publication_id for post in posts] == ["media-1002"]
