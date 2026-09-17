from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import pytest


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

import profile_emoji as helper  # noqa: E402


def _png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (20, 10), (220, 40, 80))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _resolved_image(account: helper.Account) -> helper.ResolvedImage:
    image = helper._canonicalize_image(_png_bytes())
    return helper.ResolvedImage(
        account=account,
        png_bytes=image,
        image_sha256=helper.hashlib.sha256(image).hexdigest(),
        image_source_host="pbs.twimg.com",
    )


def test_normalize_account_accepts_profile_urls_and_handles() -> None:
    x_account = helper.normalize_account("x", "https://www.x.com/Example_1/")
    assert x_account.handle == "Example_1"
    assert x_account.profile_url == "https://x.com/Example_1"

    instagram_account = helper.normalize_account("instagram", "@example.id")
    assert instagram_account.handle == "example.id"
    assert instagram_account.profile_url == "https://www.instagram.com/example.id/"


@pytest.mark.parametrize(
    "platform,value",
    [
        ("x", "https://x.com/example/status/123"),
        ("x", "https://evil.example/example"),
        ("instagram", "https://www.instagram.com/example/p/abc/"),
        ("instagram", "example?query"),
    ],
)
def test_normalize_account_rejects_non_profile_inputs(platform: str, value: str) -> None:
    with pytest.raises(helper.ProfileEmojiError):
        helper.normalize_account(platform, value)


def test_profile_metadata_requires_matching_identity() -> None:
    account = helper.normalize_account("x", "writer")
    page = b'''
        <link rel="canonical" href="https://x.com/someone-else">
        <meta property="og:image" content="https://pbs.twimg.com/avatar.png">
    '''
    with pytest.raises(helper.ProfileEmojiError, match="identity"):
        helper._profile_image_candidates(account, page)


def test_profile_metadata_extracts_image_without_exposing_query() -> None:
    account = helper.normalize_account("x", "writer")
    page = b'''
        <link rel="canonical" href="https://x.com/writer">
        <meta property="og:image" content="https://pbs.twimg.com/avatar.png?sig=private">
    '''
    candidates = helper._profile_image_candidates(account, page)
    assert candidates == ["https://pbs.twimg.com/avatar.png?sig=private"]


def test_canonicalize_image_is_static_circular_png() -> None:
    from PIL import Image

    encoded = helper._canonicalize_image(_png_bytes())
    with Image.open(BytesIO(encoded)) as image:
        assert image.size == (128, 128)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((64, 64))[3] == 255
    assert len(encoded) <= helper.MAX_EMOJI_BYTES


def test_canonicalize_image_rejects_animation() -> None:
    from PIL import Image

    output = BytesIO()
    first = Image.new("RGB", (10, 10), "red")
    second = Image.new("RGB", (10, 10), "blue")
    first.save(output, format="GIF", save_all=True, append_images=[second], duration=100)
    with pytest.raises(helper.ProfileEmojiError, match="animated"):
        helper._canonicalize_image(output.getvalue())


def test_discord_create_sends_static_png_data_uri() -> None:
    import json

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            return b'{"id":"1531672630602498129","name":"writer"}'

    class Opener:
        def __init__(self) -> None:
            self.requests = []

        def open(self, request: object, timeout: int) -> Response:
            self.requests.append((request, timeout))
            return Response()

    opener = Opener()
    client = helper.DiscordClient("token-for-test", opener=opener)
    response = client.create_guild_emoji(helper.DEFAULT_GUILD_ID, "writer", b"png")

    assert response["id"] == "1531672630602498129"
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert timeout == helper.DISCORD_TIMEOUT_SECONDS
    assert request.full_url.endswith(f"/guilds/{helper.DEFAULT_GUILD_ID}/emojis")
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["name"] == "writer"
    assert payload["roles"] == []
    assert payload["image"].startswith("data:image/png;base64,")


def test_resolve_profile_image_uses_profile_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    account = helper.normalize_account("x", "writer")
    image_url = "https://pbs.twimg.com/avatar.png"
    page = (
        b'<link rel="canonical" href="https://x.com/writer">'
        b'<meta property="og:image" content="' + image_url.encode() + b'">'
    )

    def fake_fetch(url: str, **_: object) -> tuple[bytes, str]:
        if url == account.profile_url:
            return page, url
        assert url == image_url
        return _png_bytes(), url

    monkeypatch.setattr(helper, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(helper, "_rsshub_avatar_candidates", lambda _: [])

    resolved = helper.resolve_profile_image(account)
    assert resolved.account == account
    assert resolved.image_source_host == "pbs.twimg.com"
    assert resolved.image_sha256


def test_ensure_returns_existing_without_resolving_or_mutating(monkeypatch: pytest.MonkeyPatch) -> None:
    account = helper.normalize_account("x", "writer")
    existing = {"id": "1531672630602498129", "name": "writer", "animated": False, "managed": False}

    class FakeClient:
        def __init__(self, token: str) -> None:
            assert token == "token-for-test"
            self.created = False

        def list_guild_emojis(self, guild_id: str) -> list[dict[str, object]]:
            assert guild_id == helper.DEFAULT_GUILD_ID
            return [existing]

        def create_guild_emoji(self, *_: object) -> dict[str, object]:
            self.created = True
            raise AssertionError("existing emoji must not be created")

    def fail_resolve(_: helper.Account) -> helper.ResolvedImage:
        raise AssertionError("existing emoji must not download a new image")

    monkeypatch.setattr(helper, "DiscordClient", FakeClient)
    monkeypatch.setattr(helper, "resolve_profile_image", fail_resolve)

    result = helper.ensure(
        account,
        "writer",
        helper.DEFAULT_GUILD_ID,
        apply=True,
        token="token-for-test",
    )
    assert result["action"] == "existing"
    assert result["shortcode"] == ":writer:"
    assert result["discord_markup"] == "<:writer:1531672630602498129>"
    assert result["emoji_id"] == "1531672630602498129"


def test_ensure_dry_run_reports_absent_without_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    account = helper.normalize_account("instagram", "example.id")
    resolved = _resolved_image(account)

    class FakeClient:
        def __init__(self, _: str) -> None:
            self.created = False

        def list_guild_emojis(self, _: str) -> list[dict[str, object]]:
            return []

        def create_guild_emoji(self, *_: object) -> dict[str, object]:
            self.created = True
            raise AssertionError("dry run must not post")

    monkeypatch.setattr(helper, "DiscordClient", FakeClient)
    monkeypatch.setattr(helper, "resolve_profile_image", lambda _: resolved)

    result = helper.ensure(
        account,
        "ig_example_id",
        helper.DEFAULT_GUILD_ID,
        apply=False,
        token="token-for-test",
    )
    assert result["action"] == "would_create"
    assert result["emoji_id"] is None
    assert result["discord_markup"] is None
    assert result["image_sha256"] == resolved.image_sha256


def test_resolve_local_image_reads_and_redacts_the_supplied_path(tmp_path: Path) -> None:
    image_path = tmp_path / "bri.png"
    image_path.write_bytes(_png_bytes())

    resolved = helper.resolve_local_image(str(image_path))

    assert resolved.account is None
    assert resolved.image_source_host == "local-file"
    assert resolved.image_sha256
    assert str(image_path) not in repr(resolved)


def test_ensure_image_apply_creates_absent_emoji(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image_path = tmp_path / "bri.png"
    image_path.write_bytes(_png_bytes())

    class FakeClient:
        def __init__(self, _: str) -> None:
            self.created_payload: tuple[str, str, bytes] | None = None

        def list_guild_emojis(self, _: str) -> list[dict[str, object]]:
            return []

        def create_guild_emoji(self, guild_id: str, name: str, png_bytes: bytes) -> dict[str, object]:
            self.created_payload = (guild_id, name, png_bytes)
            return {"id": "1531673483459821729", "name": name, "animated": False}

    fake_client: FakeClient | None = None

    def make_client(token: str) -> FakeClient:
        nonlocal fake_client
        assert token == "token-for-test"
        fake_client = FakeClient(token)
        return fake_client

    monkeypatch.setattr(helper, "DiscordClient", make_client)
    result = helper.ensure_image(
        str(image_path),
        "bridanareksa",
        helper.DEFAULT_GUILD_ID,
        apply=True,
        token="token-for-test",
    )

    assert fake_client is not None
    assert fake_client.created_payload is not None
    assert fake_client.created_payload[:2] == (helper.DEFAULT_GUILD_ID, "bridanareksa")
    assert result["platform"] == "local"
    assert result["action"] == "created"
    assert result["discord_markup"] == "<:bridanareksa:1531673483459821729>"


def test_ensure_apply_creates_absent_emoji_and_returns_both_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    account = helper.normalize_account("instagram", "example.id")
    resolved = _resolved_image(account)

    class FakeClient:
        def __init__(self, _: str) -> None:
            self.created_payload: tuple[str, str, bytes] | None = None

        def list_guild_emojis(self, _: str) -> list[dict[str, object]]:
            return []

        def create_guild_emoji(self, guild_id: str, name: str, png_bytes: bytes) -> dict[str, object]:
            self.created_payload = (guild_id, name, png_bytes)
            return {"id": "1531673483459821729", "name": name, "animated": False}

    fake_client: FakeClient | None = None

    def make_client(token: str) -> FakeClient:
        nonlocal fake_client
        assert token == "token-for-test"
        fake_client = FakeClient(token)
        return fake_client

    monkeypatch.setattr(helper, "DiscordClient", make_client)
    monkeypatch.setattr(helper, "resolve_profile_image", lambda _: resolved)

    result = helper.ensure(
        account,
        "ig_example_id",
        helper.DEFAULT_GUILD_ID,
        apply=True,
        token="token-for-test",
    )
    assert fake_client is not None
    assert fake_client.created_payload == (
        helper.DEFAULT_GUILD_ID,
        "ig_example_id",
        resolved.png_bytes,
    )
    assert result["action"] == "created"
    assert result["shortcode"] == ":ig_example_id:"
    assert result["discord_markup"] == "<:ig_example_id:1531673483459821729>"
    assert result["emoji_id"] == "1531673483459821729"
