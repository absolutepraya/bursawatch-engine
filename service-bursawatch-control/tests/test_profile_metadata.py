from __future__ import annotations

import json

import pytest

from control_plane.profile_metadata import (
    AvatarResolution,
    ProfileMetadataInput,
    RssHubAvatarResolver,
    normalize_manual_avatar_url,
    profile_inputs_from_config,
)
from control_plane.store import InMemoryStore


def profile() -> ProfileMetadataInput:
    return ProfileMetadataInput(
        profile_id="kutekians",
        handle="Kutekians",
        display_name="Kutekians",
        profile_url="https://x.com/Kutekians",
        enabled=True,
    )


def test_rsshub_icon_is_preferred_and_only_the_url_is_returned():
    calls: list[tuple[str, str]] = []

    def fetch(url: str, _limit: int, accept: str) -> bytes:
        calls.append((url, accept))
        return json.dumps(
            {
                "icon": "https://pbs.twimg.com/profile_images/123/avatar.jpg?name=large",
                "items": [{"content_html": "this must not be inspected"}],
            }
        ).encode()

    resolver = RssHubAvatarResolver(fetch_bytes=fetch)

    result = resolver.resolve(profile())

    assert result == AvatarResolution(
        url="https://pbs.twimg.com/profile_images/123/avatar.jpg?name=large",
        source="rsshub_icon",
    )
    assert calls == [("http://127.0.0.1:1200/twitter/user/Kutekians?format=json", "application/json")]


def test_rsshub_author_avatar_is_the_fallback_when_icon_is_not_trusted():
    def fetch(_url: str, _limit: int, _accept: str) -> bytes:
        return json.dumps(
            {
                "icon": "https://example.invalid/not-an-avatar.png",
                "authors": [{"name": "Kutekians", "avatar": "https://pbs.twimg.com/profile_images/456/avatar.jpg"}],
            }
        ).encode()

    result = RssHubAvatarResolver(fetch_bytes=fetch).resolve(profile())

    assert result.url == "https://pbs.twimg.com/profile_images/456/avatar.jpg"
    assert result.source == "rsshub_author"


def test_profile_page_metadata_is_a_fallback_after_rsshub_failure():
    def fetch(url: str, _limit: int, _accept: str) -> bytes:
        if "twitter/user" in url:
            return b"{}"
        return (
            b'<link rel="canonical" href="https://x.com/Kutekians">'
            b'<meta property="og:image" content="https://pbs.twimg.com/profile_images/789/avatar.jpg">'
        )

    result = RssHubAvatarResolver(fetch_bytes=fetch).resolve(profile())

    assert result == AvatarResolution(
        url="https://pbs.twimg.com/profile_images/789/avatar.jpg",
        source="profile_page_meta",
    )


def test_avatar_url_validation_rejects_non_https_and_credentials():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_manual_avatar_url("http://pbs.twimg.com/avatar.jpg")
    with pytest.raises(ValueError, match="credentials"):
        normalize_manual_avatar_url("https://user:pass@pbs.twimg.com/avatar.jpg")


def test_profile_metadata_keeps_old_avatar_on_refresh_failure_and_clears_it_on_identity_change():
    store = InMemoryStore()
    store.seed_config("bursawatch-x-account-watch", 1, {"version": 1, "profiles": []})
    records = store.sync_profile_metadata("bursawatch-x-account-watch", [profile()])
    assert records[0].avatar_url is None

    updated = store.record_profile_avatar_success(
        "bursawatch-x-account-watch",
        "kutekians",
        "https://pbs.twimg.com/profile_images/123/avatar.jpg",
        "rsshub_icon",
        "Kutekians",
        "https://x.com/Kutekians",
    )
    failed = store.record_profile_avatar_failure(
        "bursawatch-x-account-watch",
        "kutekians",
        "RSSHub unavailable",
        "Kutekians",
        "https://x.com/Kutekians",
    )
    assert failed.avatar_url == updated.avatar_url
    assert failed.last_error == "RSSHub unavailable"

    changed = store.sync_profile_metadata(
        "bursawatch-x-account-watch",
        [
            ProfileMetadataInput(
                profile_id="kutekians",
                handle="DifferentHandle",
                display_name="Kutekians",
                profile_url="https://x.com/DifferentHandle",
                enabled=True,
            )
        ],
    )[0]
    assert changed.avatar_url is None
    assert changed.last_success_at is None
