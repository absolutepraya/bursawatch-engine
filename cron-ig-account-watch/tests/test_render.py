from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import discord
import render
from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.models import OperationReceipt
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
    hidden = render.render_publication(
        profile,
        make_post(profile.id, kind=PublicationKind.REEL, caption="<script>reel</script><p>A short market clip</p>"),
    )[0]

    assert "(Reel)" in marked
    assert "(Reel)" not in identified
    assert "(Reel)" in hidden


def test_render_splits_long_unicode_caption_and_keeps_source_link_final(profile):
    caption = "<p>" + ("market insight 😀 " * 500) + "</p>"
    messages = render.render_publication(profile, make_post(profile.id, caption=caption))

    assert len(messages) > 1
    assert all(render.discord_length(message) <= render.DISCORD_LIMIT for message in messages)
    assert messages[0].startswith("### 📸 Beyond thy Fundamental")
    assert sum("### 📸" in message for message in messages) == 1
    assert sum("[View on Instagram]" in message for message in messages) == 1
    assert messages[-1].endswith("[View on Instagram](<https://www.instagram.com/p/DcaLqsggXrE/>)")


def test_render_does_not_render_ocr_automatically(profile):
    post = make_post(profile.id, caption="Caption only")
    rendered = "\n".join(render.render_publication(profile, post, summary="*(Ringkasan)* Caption only"))

    assert "OCR" not in rendered
    assert "Image 1" not in rendered


class FakeDeliveryOwner:
    def __init__(self):
        self.operations = {}
        self.submissions = []
        self.next_error = None

    def status(self, key):
        return self.operations.get(key)

    def submit(self, operation):
        if self.next_error is not None:
            error, self.next_error = self.next_error, None
            raise error
        self.submissions.append(operation)
        receipt = OperationReceipt(
            id=f"operation-{len(self.submissions)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={"channel_id": operation.target["channel_id"], "message_id": "123456789"},
        )
        self.operations[operation.key] = receipt
        return receipt


def _use_delivery_owner(monkeypatch: pytest.MonkeyPatch) -> FakeDeliveryOwner:
    owner = FakeDeliveryOwner()
    monkeypatch.setattr(discord, "delivery_client_from_environment", lambda **_kwargs: owner)
    return owner


def _media_path(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"media bytes")
    return path


def _use_media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(tmp_path))


def test_nonce_is_deterministic_bounded_and_unique_per_leg():
    first = discord.nonce("beyondthefundamental:DcaLqsggXrE", "text:0")
    assert first == discord.nonce("beyondthefundamental:DcaLqsggXrE", "text:0")
    assert len(first) == 24
    assert int(first, 16) >= 0
    assert first != discord.nonce("beyondthefundamental:DcaLqsggXrE", "media:0")


def test_text_and_ordered_media_operations_preserve_names_and_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = _use_delivery_owner(monkeypatch)
    _use_media_root(tmp_path, monkeypatch)
    first = _media_path(tmp_path, "slide-1.jpg")
    second = _media_path(tmp_path, "slide-2.jpg")

    assert discord.post_text("caption", "1531655369884045382", False, discord.nonce("event", "text:0")) == "123456789"
    assert discord.post_media(first, "1531655369884045382", False, discord.nonce("event", "media:0")) == "123456789"
    assert discord.post_media(second, "1531655369884045382", False, discord.nonce("event", "media:1")) == "123456789"
    assert [len(operation.attachments) for operation in owner.submissions] == [0, 1, 1]
    assert [operation.attachments[0].filename for operation in owner.submissions[1:]] == ["slide-1.jpg", "slide-2.jpg"]
    assert [operation.attachments[0].data for operation in owner.submissions[1:]] == [b"media bytes", b"media bytes"]
    assert first.exists() and second.exists()


def test_image_and_video_operations_use_local_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = _use_delivery_owner(monkeypatch)
    _use_media_root(tmp_path, monkeypatch)
    discord.post_media(_media_path(tmp_path, "slide.webp"), "123", False, discord.nonce("event", "media:image"))
    discord.post_media(_media_path(tmp_path, "reel.mp4"), "123", False, discord.nonce("event", "media:video"))

    assert [(operation.attachments[0].filename, operation.attachments[0].mime_type)
            for operation in owner.submissions] == [("slide.webp", "image/webp"), ("reel.mp4", "video/mp4")]


def test_ordered_four_image_operations_preserve_source_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = _use_delivery_owner(monkeypatch)
    _use_media_root(tmp_path, monkeypatch)
    paths = [_media_path(tmp_path, f"slide-{index}.jpg") for index in range(4)]
    for index, path in enumerate(paths):
        assert discord.post_media(path, "123", False, discord.nonce("event", f"media:{index}")) == "123456789"

    assert [operation.attachments[0].filename for operation in owner.submissions] == [
        f"slide-{index}.jpg" for index in range(4)
    ]


def test_media_retry_is_independent_after_text_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = _use_delivery_owner(monkeypatch)
    _use_media_root(tmp_path, monkeypatch)
    source = _media_path(tmp_path, "slide-0.jpg")
    assert discord.post_text("caption", "123", False, discord.nonce("event", "text:0")) == "123456789"
    owner.next_error = DeliveryClientError("rate_limited")
    with pytest.raises(discord.DiscordRetryAfter):
        discord.post_media(source, "123", False, discord.nonce("event", "media:0"))
    assert discord.post_media(source, "123", False, discord.nonce("event", "media:0")) == "123456789"

    assert [len(operation.attachments) for operation in owner.submissions] == [0, 1]


def test_text_limit_uses_utf16_code_units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = _use_delivery_owner(monkeypatch)
    exactly_at_limit = "a" * 1_998 + "😀"
    over_limit = "a" * 1_999 + "😀"

    assert discord.discord_length(exactly_at_limit) == 2_000
    assert discord.post_text(exactly_at_limit, "123", False, discord.nonce("event", "text:limit")) == "123456789"
    with pytest.raises(ValueError, match="2,000"):
        discord.post_text(over_limit, "123", False, discord.nonce("event", "text:over-limit"))
    assert len(owner.submissions) == 1


def test_dry_run_makes_no_owner_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discord, "delivery_client_from_environment", lambda **_kwargs: pytest.fail("owner was called"))
    _use_media_root(tmp_path, monkeypatch)
    path = _media_path(tmp_path, "slide.png")

    assert discord.post_text("text", "123", True, "text-nonce") is None
    assert discord.post_media(path, "123", True, "media-nonce") is None


def test_owner_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch):
    secret = "token-that-must-not-leak"

    class FailingOwner:
        def status(self, _key):
            raise DeliveryClientError("server_error", f"provider body contains {secret}")

    monkeypatch.setattr(discord, "delivery_client_from_environment", lambda **_kwargs: FailingOwner())
    with pytest.raises(discord.DiscordDeliveryError) as error:
        discord.post_text("hello", "123", False, discord.nonce("event", "text:error"))
    assert str(error.value) == "Delivery Owner request failed"
    assert secret not in str(error.value)

    class LimitedOwner:
        def status(self, _key):
            raise DeliveryClientError("rate_limited")

    monkeypatch.setattr(discord, "delivery_client_from_environment", lambda **_kwargs: LimitedOwner())
    with pytest.raises(discord.DiscordRetryAfter) as limited:
        discord.post_text("hello", "123", False, discord.nonce("event", "text:rate-limit"))
    assert limited.value.retry_after == discord.RETRY_FALLBACK_SECONDS
    assert secret not in str(limited.value)


def test_media_path_rejects_symlinks_and_non_local_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_media_root(tmp_path, monkeypatch)
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


def test_media_upload_requires_a_valid_watcher_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _media_path(tmp_path, "source.jpg")
    monkeypatch.delenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", raising=False)
    with pytest.raises(ValueError, match="media root"):
        discord.post_media(source, "123", True, "nonce")

    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_bytes(b"not a directory")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(invalid_root))
    with pytest.raises(ValueError, match="media root"):
        discord.post_media(source, "123", True, "nonce")

    valid_root = tmp_path / "root"
    valid_root.mkdir()
    outside = _media_path(tmp_path, "outside.jpg")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(valid_root))
    with pytest.raises(ValueError, match="outside"):
        discord.post_media(outside, "123", True, "nonce")


def test_upload_temporary_copy_is_removed_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_media_root(tmp_path, monkeypatch)
    source = _media_path(tmp_path, "slide.jpg")

    class FailingOwner:
        def status(self, _key):
            raise DeliveryClientError("network_error")

    monkeypatch.setattr(discord, "delivery_client_from_environment", lambda **_kwargs: FailingOwner())
    with pytest.raises(discord.DiscordDeliveryError, match="Delivery Owner"):
        discord.post_media(source, "123", False, discord.nonce("event", "media:error"))

    assert source.exists()
    assert list(tmp_path.glob(".instagram-post-watch-upload-*")) == []
