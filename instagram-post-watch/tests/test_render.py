from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import discord
import render
from config import load_watch_config
from models import MediaKind, PublicationKind, SourceMedia, SourcePost


@pytest.fixture
def profile(config_path: Path):
    return load_watch_config(config_path).profiles[0]


def make_post(
    profile_id: str,
    *,
    caption: str = "Caption text",
    kind: PublicationKind = PublicationKind.POST,
    shortcode: str = "DcaLqsggXrE",
    media: tuple[SourceMedia, ...] = (),
) -> SourcePost:
    return SourcePost(
        profile_id=profile_id,
        publication_id=shortcode,
        url=f"https://www.instagram.com/p/{shortcode}/",
        published_at=datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        caption_html=caption,
        kind=kind,
        media=media,
    )


def test_render_default_heading_omits_empty_account_emoji(profile):
    rendered = render.render_publication(profile, make_post(profile.id))[0]

    assert rendered.startswith("### 📸 Beyond thy Fundamental")
    assert "-#" not in rendered
    assert "[View on Instagram](<https://www.instagram.com/p/DcaLqsggXrE/>)" in rendered


def test_render_title_and_accepted_summary(profile):
    rendered = render.render_publication(
        profile,
        make_post(profile.id, caption="Raw caption"),
        summary="*(Ringkasan)* Ringkasan tervalidasi.",
        title="Pasar global dan likuiditas",
    )[0]

    assert rendered.startswith("### 📸 Pasar global dan likuiditas\n-# Beyond thy Fundamental")
    assert "*(Ringkasan)* Ringkasan tervalidasi." in rendered
    assert "Raw caption" not in rendered


def test_render_caption_escapes_html_and_markdown_without_rendering_links(profile):
    post = make_post(
        profile.id,
        caption=(
            "<p>Hello <strong>world</strong> [not a link] <a href='https://evil.example'>click</a></p>"
            "<script>DISCORD_BOT_TOKEN=secret</script>"
        ),
    )
    rendered = render.render_publication(profile, post)[0]

    assert "Hello world" in rendered
    assert r"\[not a link\]" in rendered
    assert "https://evil.example" not in rendered
    assert "DISCORD_BOT_TOKEN" not in rendered
    assert "<strong>" not in rendered


def test_render_reel_marker_is_added_only_when_not_already_identified(profile):
    reel = make_post(profile.id, kind=PublicationKind.REEL, caption="A short market clip")
    marked = render.render_publication(profile, reel)[0]
    identified = render.render_publication(profile, make_post(profile.id, kind=PublicationKind.REEL, caption="Our Reel on rates"))[0]

    assert "(Reel)" in marked
    assert "(Reel)" not in identified


def test_render_splits_long_unicode_caption_and_keeps_source_link_final(profile):
    caption = "<p>" + ("market insight 😀 " * 500) + "</p>"
    messages = render.render_publication(profile, make_post(profile.id, caption=caption))

    assert len(messages) > 1
    assert all(len(message) <= render.DISCORD_LIMIT for message in messages)
    assert messages[0].startswith("### 📸 Beyond thy Fundamental")
    assert sum("### 📸" in message for message in messages) == 1
    assert sum("[View on Instagram]" in message for message in messages) == 1
    assert messages[-1].endswith("[View on Instagram](<https://www.instagram.com/p/DcaLqsggXrE/>)")


def test_render_does_not_render_ocr_automatically(profile):
    post = make_post(profile.id, caption="Caption only")
    rendered = "\n".join(render.render_publication(profile, post, summary="*(Ringkasan)* Caption only"))

    assert "OCR" not in rendered
    assert "Image 1" not in rendered


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"id": "123456789"}

    def json(self):
        return self._payload


def _media_path(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"media bytes")
    return path


def test_nonce_is_deterministic_prefixed_and_unique_per_leg():
    first = discord.nonce("beyondthefundamental:DcaLqsggXrE", "text:0")
    assert first == discord.nonce("beyondthefundamental:DcaLqsggXrE", "text:0")
    assert first.startswith("instagram-post-watch:")
    assert first != discord.nonce("beyondthefundamental:DcaLqsggXrE", "media:0")


def test_text_and_ordered_media_uploads_use_module_apis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str, str | None]] = []

    def fake_post(url, *, headers, json=None, files=None, timeout):
        assert url.endswith("/channels/1531655369884045382/messages")
        assert headers["Authorization"] == "Bot test-token"
        assert timeout == 30
        if json is not None:
            calls.append(("text", json["nonce"], json["content"]))
        else:
            assert files is not None
            upload = files["files[0]"]
            calls.append(("media", upload[0], None))
            assert upload[1].read() == b"media bytes"
        return FakeResponse()

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setattr(discord.requests, "post", fake_post)
    first = _media_path(tmp_path, "slide-1.jpg")
    second = _media_path(tmp_path, "slide-2.jpg")

    assert discord.post_text("caption", "1531655369884045382", False, discord.nonce("event", "text:0")) == "123456789"
    assert discord.post_media(first, "1531655369884045382", False, discord.nonce("event", "media:0")) == "123456789"
    assert discord.post_media(second, "1531655369884045382", False, discord.nonce("event", "media:1")) == "123456789"
    assert [call[0] for call in calls] == ["text", "media", "media"]
    assert [call[1] for call in calls[1:]] == ["slide-1.jpg", "slide-2.jpg"]
    assert first.exists() and second.exists()


def test_image_and_video_uploads_use_local_files_and_multipart_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    observed: list[tuple[str, str]] = []

    def fake_post(_url, *, headers, json=None, files=None, timeout):
        assert json is None
        assert headers["Authorization"] == "Bot token"
        assert timeout == 30
        assert files is not None
        media = files["files[0]"]
        observed.append((media[0], media[2]))
        assert files["payload_json"][1].startswith('{"nonce":')
        return FakeResponse()

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(discord.requests, "post", fake_post)
    discord.post_media(_media_path(tmp_path, "slide.webp"), "123", False, "nonce-image")
    discord.post_media(_media_path(tmp_path, "reel.mp4"), "123", False, "nonce-video")

    assert observed == [("slide.webp", "image/webp"), ("reel.mp4", "video/mp4")]


def test_dry_run_makes_no_http_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: pytest.fail("HTTP was called"))
    path = _media_path(tmp_path, "slide.png")

    assert discord.post_text("text", "123", True, "text-nonce") is None
    assert discord.post_media(path, "123", True, "media-nonce") is None


def test_status_and_429_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch):
    secret = "token-that-must-not-leak"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", secret)

    class ErrorResponse(FakeResponse):
        text = f"provider body contains {secret}"

    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: ErrorResponse(500, {"message": "secret body"}))
    with pytest.raises(discord.DiscordDeliveryError) as error:
        discord.post_text("hello", "123", False, "nonce")
    assert "Discord HTTP 500" == str(error.value)
    assert secret not in str(error.value)
    assert "secret body" not in str(error.value)

    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: FakeResponse(429, {"retry_after": 4.5}))
    with pytest.raises(discord.DiscordRetryAfter) as limited:
        discord.post_text("hello", "123", False, "nonce")
    assert limited.value.retry_after == 4.5
    assert secret not in str(limited.value)


def test_media_path_rejects_symlinks_and_non_local_urls(tmp_path: Path):
    source = _media_path(tmp_path, "source.jpg")
    link = tmp_path / "link.jpg"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(ValueError, match="media path"):
        discord.post_media(link, "123", True, "nonce")
    with pytest.raises(ValueError, match="media path"):
        discord.post_media(Path("https://cdn.example/image.jpg"), "123", True, "nonce")


def test_upload_temporary_copy_is_removed_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    source = _media_path(tmp_path, "slide.jpg")

    def fail_post(*args, **kwargs):
        raise requests.ConnectionError("provider body token")

    monkeypatch.setattr(discord.requests, "post", fail_post)
    with pytest.raises(discord.DiscordDeliveryError, match="request failed"):
        discord.post_media(source, "123", False, "nonce")

    assert source.exists()
    assert list(tmp_path.glob(".instagram-post-watch-upload-*")) == []
