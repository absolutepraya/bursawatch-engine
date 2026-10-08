#!/usr/bin/env python3
"""Resolve profile pictures and safely ensure static Discord profile emojis."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_HERE = Path(__file__).resolve()
_DELIVERY_BIN = _HERE.parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    # Source checkout: .agents/skills/profile-emoji/bin sits four levels below the repo root.
    _DELIVERY_BIN = _HERE.parents[4] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))
from bursawatch_discord_delivery import DeliveryClient, DeliveryClientError  # noqa: E402


DEFAULT_GUILD_ID = "940285152335110204"
DISCORD_TIMEOUT_SECONDS = 30
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_IMAGE_INPUT_BYTES = 10 * 1024 * 1024
MAX_EMOJI_BYTES = 256 * 1024
EMOJI_SIZE = 128
MAX_REDIRECTS = 4
USER_AGENT = "profile-emoji/1.0 (+https://github.com/absolutepraya/Hermes)"

DISCORD_ID_RE = re.compile(r"^\d{17,20}$")
EMOJI_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
X_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

PROFILE_HOSTS = {
    "x": frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"}),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
}
RSSHUB_PORTS = {"x": 1200, "instagram": 1200}
AVATAR_KEYS = frozenset(
    {
        "avatar",
        "avatar_url",
        "icon",
        "profile_image_url",
        "profile_pic_url",
        "profile_picture",
        "profile_picture_url",
    }
)
AVATAR_CONTAINERS = frozenset(
    {"author", "authors", "creator", "owner", "profile", "user"}
)


class ProfileEmojiError(RuntimeError):
    """A safe, user-facing failure without provider bodies or credentials."""


@dataclass(frozen=True)
class Account:
    platform: str
    handle: str
    profile_url: str


@dataclass(frozen=True)
class ResolvedImage:
    account: Account | None
    png_bytes: bytes
    image_sha256: str
    image_source_host: str


class ProfileMetaParser(HTMLParser):
    """Collect only profile identity and image metadata from a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_values: list[str] = []
        self.identity_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content")
            if not content:
                return
            if key in {"og:image", "twitter:image", "twitter:image:src"}:
                self.image_values.append(content)
            elif key in {"og:url", "twitter:url"}:
                self.identity_values.append(content)
        elif tag_name == "link":
            rel = {
                part.strip().lower()
                for part in (attributes.get("rel") or "").split()
            }
            href = attributes.get("href")
            if "canonical" in rel and href:
                self.identity_values.append(href)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, msg: str, headers: Any, new_url: str):
        return None


def _normalize_platform(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"x", "twitter"}:
        return "x"
    if normalized in {"ig", "instagram"}:
        return "instagram"
    raise ProfileEmojiError("platform must be x or instagram")


def _profile_handle_from_url(platform: str, value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ProfileEmojiError("profile URL is malformed") from exc
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
        raise ProfileEmojiError("profile URL must use HTTPS without credentials")
    if parsed.query or parsed.fragment:
        raise ProfileEmojiError("profile URL must not contain a query or fragment")
    try:
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ProfileEmojiError("profile URL has an invalid port") from exc
    if port not in {None, 443} or hostname not in PROFILE_HOSTS[platform]:
        raise ProfileEmojiError("profile URL host is not supported for this platform")

    path = parsed.path
    if not path or "%" in path:
        raise ProfileEmojiError("profile URL must contain one plain profile handle")
    path = path.rstrip("/")
    parts = path.split("/")
    if len(parts) != 2 or not parts[1]:
        raise ProfileEmojiError("profile URL must point to one profile handle")
    handle = unquote(parts[1])
    pattern = X_HANDLE_RE if platform == "x" else INSTAGRAM_HANDLE_RE
    if not pattern.fullmatch(handle):
        raise ProfileEmojiError("profile URL contains an invalid profile handle")
    return handle


def normalize_account(platform: str, value: str) -> Account:
    normalized_platform = _normalize_platform(platform)
    candidate = value.strip()
    if not candidate:
        raise ProfileEmojiError("account is required")

    if "://" in candidate:
        handle = _profile_handle_from_url(normalized_platform, candidate)
    else:
        if candidate.startswith("@"):  # Handles are accepted with a display prefix.
            candidate = candidate[1:]
        if "/" in candidate or "?" in candidate or "#" in candidate:
            raise ProfileEmojiError("bare account must be a handle, not a URL")
        pattern = X_HANDLE_RE if normalized_platform == "x" else INSTAGRAM_HANDLE_RE
        if not pattern.fullmatch(candidate):
            raise ProfileEmojiError("account contains an invalid profile handle")
        handle = candidate

    if normalized_platform == "x":
        profile_url = f"https://x.com/{handle}"
    else:
        profile_url = f"https://www.instagram.com/{handle}/"
    return Account(normalized_platform, handle, profile_url)


def validate_emoji_name(value: str) -> str:
    if not isinstance(value, str) or not EMOJI_NAME_RE.fullmatch(value):
        raise ProfileEmojiError(
            "emoji name must contain only ASCII letters, digits, or underscores and be 1 to 32 characters"
        )
    return value


def _default_emoji_name(account: Account, profile_id: str | None) -> str:
    if profile_id is not None:
        if not PROFILE_ID_RE.fullmatch(profile_id):
            raise ProfileEmojiError("profile ID must use the reviewed lowercase ID format")
        return validate_emoji_name(profile_id)
    prefix = "x" if account.platform == "x" else "ig"
    handle = re.sub(r"[^A-Za-z0-9_]", "_", account.handle).lower()
    return validate_emoji_name(f"{prefix}_{handle}")


def resolve_emoji_name(account: Account, emoji_name: str | None, profile_id: str | None) -> str:
    if emoji_name is not None:
        return validate_emoji_name(emoji_name)
    return _default_emoji_name(account, profile_id)


def _validate_https_url(value: str, *, allowed_hosts: frozenset[str] | None = None) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise ProfileEmojiError("source URL is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ProfileEmojiError("source URL is malformed") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ProfileEmojiError("source URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ProfileEmojiError("source URL must not contain credentials")
    if parsed.fragment:
        raise ProfileEmojiError("source URL must not contain a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProfileEmojiError("source URL has an invalid port") from exc
    if port not in {None, 443}:
        raise ProfileEmojiError("source URL must use the default HTTPS port")
    host = parsed.hostname.lower().rstrip(".")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ProfileEmojiError("source URL host is not trusted")
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def _assert_public_host(host: str, port: int) -> None:
    normalized = host.lower().rstrip(".")
    if normalized in {"localhost", "localhost.localdomain"}:
        raise ProfileEmojiError("source host is not public")
    try:
        addresses = [ipaddress.ip_address(normalized)]
    except ValueError:
        try:
            records = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ProfileEmojiError("source host could not be resolved") from exc
        addresses = []
        for record in records:
            try:
                addresses.append(ipaddress.ip_address(record[4][0]))
            except (IndexError, ValueError):
                continue
    if not addresses or any(not address.is_global for address in addresses):
        raise ProfileEmojiError("source host is not public")


def _assert_fetch_url(
    value: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
    allow_local: bool = False,
) -> str:
    if allow_local:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port not in RSSHUB_PORTS.values()
            or parsed.username
            or parsed.password
        ):
            raise ProfileEmojiError("local source URL is not allowed")
        return value
    normalized = _validate_https_url(value, allowed_hosts=allowed_hosts)
    parsed = urlsplit(normalized)
    _assert_public_host(parsed.hostname or "", parsed.port or 443)
    return normalized


def _read_limited(response: Any, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ProfileEmojiError("source response is too large")
    return data


def fetch_bytes(
    url: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
    allow_local: bool = False,
    limit: int,
) -> tuple[bytes, str]:
    """Fetch a bounded response while validating every manually followed URL."""

    current = url
    opener = build_opener(_NoRedirectHandler())
    for _ in range(MAX_REDIRECTS + 1):
        current = _assert_fetch_url(
            current,
            allowed_hosts=allowed_hosts,
            allow_local=allow_local,
        )
        request = Request(current, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with opener.open(request, timeout=DISCORD_TIMEOUT_SECONDS) as response:
                status = int(getattr(response, "status", 200))
                if 300 <= status < 400:
                    location = response.headers.get("Location")
                    if not location:
                        raise ProfileEmojiError("source redirect has no location")
                    current = urljoin(current, location)
                    continue
                if status != 200:
                    raise ProfileEmojiError(f"source request failed with HTTP {status}")
                return _read_limited(response, limit), current
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                location = exc.headers.get("Location")
                if location:
                    current = urljoin(current, location)
                    continue
                raise ProfileEmojiError("source redirect has no location") from exc
            raise ProfileEmojiError(f"source request failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise ProfileEmojiError("source request failed") from exc
        except TimeoutError as exc:
            raise ProfileEmojiError("source request timed out") from exc
    raise ProfileEmojiError("source redirect limit exceeded")


def _profile_identity_matches(account: Account, value: str) -> bool:
    try:
        return normalize_account(account.platform, unescape(value)).handle.casefold() == account.handle.casefold()
    except ProfileEmojiError:
        return False


def _profile_image_candidates(account: Account, page: bytes) -> list[str]:
    parser = ProfileMetaParser()
    parser.feed(page.decode("utf-8", errors="replace"))
    if parser.identity_values and not any(
        _profile_identity_matches(account, urljoin(account.profile_url, identity))
        for identity in parser.identity_values
    ):
        raise ProfileEmojiError("profile page identity does not match the requested account")

    candidates: list[str] = []
    for value in parser.image_values:
        candidate = urljoin(account.profile_url, unescape(value).strip())
        try:
            normalized = _validate_https_url(candidate)
        except ProfileEmojiError:
            continue
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _avatar_urls(value: Any, *, depth: int = 0, container: bool = True) -> list[str]:
    if depth > 5:
        return []
    candidates: list[str] = []

    def add(candidate: Any) -> None:
        if not isinstance(candidate, str) or not candidate.startswith("https://"):
            return
        try:
            normalized = _validate_https_url(candidate)
        except ProfileEmojiError:
            return
        if normalized not in candidates:
            candidates.append(normalized)

    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in AVATAR_KEYS:
                add(child)
            elif normalized_key in AVATAR_CONTAINERS:
                candidates.extend(_avatar_urls(child, depth=depth + 1, container=True))
    elif isinstance(value, list) and container:
        for child in value[:20]:
            candidates.extend(_avatar_urls(child, depth=depth + 1, container=True))
    return list(dict.fromkeys(candidates))


def _rsshub_avatar_candidates(account: Account) -> list[str]:
    port = RSSHUB_PORTS[account.platform]
    path_platform = "twitter" if account.platform == "x" else "instagram/2"
    route = f"http://127.0.0.1:{port}/{path_platform}/user/{quote(account.handle, safe='._')}?format=json"
    try:
        body, _ = fetch_bytes(
            route,
            allowed_hosts=frozenset({"127.0.0.1"}),
            allow_local=True,
            limit=MAX_HTML_BYTES,
        )
        payload = json.loads(body.decode("utf-8"))
    except (ProfileEmojiError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    # RSSHub's top-level icon and author avatar are the only accepted fallback
    # fields. Generic post media is intentionally not searched.
    candidates: list[str] = []
    if isinstance(payload, dict):
        for key in ("icon", "avatar", "avatar_url"):
            value = payload.get(key)
            if isinstance(value, str):
                candidates.extend(_avatar_urls({key: value}))
        for key in ("author", "authors", "creator", "owner", "profile", "user"):
            candidates.extend(_avatar_urls(payload.get(key)))
    return list(dict.fromkeys(candidates))


def _canonicalize_image(data: bytes) -> bytes:
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise ProfileEmojiError("Pillow is required on the helper runtime") from exc

    if not data or len(data) > MAX_IMAGE_INPUT_BYTES:
        raise ProfileEmojiError("profile image is too large")

    Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        from io import BytesIO

        with Image.open(BytesIO(data)) as source:
            if getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                raise ProfileEmojiError("animated profile images are not supported")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except ProfileEmojiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProfileEmojiError("profile image is not a supported static image") from exc

    width, height = image.size
    if width < 1 or height < 1:
        raise ProfileEmojiError("profile image has invalid dimensions")
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    square = image.crop((left, top, left + side, top + side)).resize(
        (EMOJI_SIZE, EMOJI_SIZE),
        Image.Resampling.LANCZOS,
    )
    mask = Image.new("L", (EMOJI_SIZE, EMOJI_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, EMOJI_SIZE - 1, EMOJI_SIZE - 1), fill=255)
    alpha = ImageChops.multiply(square.getchannel("A"), mask)
    square.putalpha(alpha)

    output = BytesIO()
    square.save(output, format="PNG", optimize=True)
    encoded = output.getvalue()
    if len(encoded) > MAX_EMOJI_BYTES:
        raise ProfileEmojiError("cropped profile image exceeds Discord's 256 KiB limit")
    return encoded


def resolve_profile_image(account: Account) -> ResolvedImage:
    candidates: list[str] = []
    try:
        page, _ = fetch_bytes(
            account.profile_url,
            allowed_hosts=PROFILE_HOSTS[account.platform],
            limit=MAX_HTML_BYTES,
        )
        candidates.extend(_profile_image_candidates(account, page))
    except ProfileEmojiError:
        pass

    candidates.extend(_rsshub_avatar_candidates(account))
    candidates = list(dict.fromkeys(candidates))
    for candidate in candidates:
        try:
            image_data, final_url = fetch_bytes(candidate, limit=MAX_IMAGE_INPUT_BYTES)
            png_bytes = _canonicalize_image(image_data)
            host = (urlsplit(final_url).hostname or "").lower().rstrip(".")
            if not host:
                continue
            return ResolvedImage(
                account=account,
                png_bytes=png_bytes,
                image_sha256=hashlib.sha256(png_bytes).hexdigest(),
                image_source_host=host,
            )
        except ProfileEmojiError:
            continue
    raise ProfileEmojiError(
        f"could not resolve a trusted profile image for {account.platform}/{account.handle}"
    )


def resolve_local_image(path: str) -> ResolvedImage:
    image_path = Path(path)
    try:
        if not image_path.is_file():
            raise ProfileEmojiError("local image path is not a file")
        with image_path.open("rb") as source:
            image_data = source.read(MAX_IMAGE_INPUT_BYTES + 1)
    except ProfileEmojiError:
        raise
    except OSError as exc:
        raise ProfileEmojiError("local image could not be read") from exc

    png_bytes = _canonicalize_image(image_data)
    return ResolvedImage(
        account=None,
        png_bytes=png_bytes,
        image_sha256=hashlib.sha256(png_bytes).hexdigest(),
        image_source_host="local-file",
    )


def _validate_guild_id(value: str) -> str:
    if not DISCORD_ID_RE.fullmatch(value):
        raise ProfileEmojiError("guild ID must be a 17 to 20 digit Discord ID")
    return value


def _validate_emoji_id(value: Any) -> str:
    candidate = str(value) if isinstance(value, (str, int)) else ""
    if not DISCORD_ID_RE.fullmatch(candidate):
        raise ProfileEmojiError("Discord returned an invalid emoji ID")
    return candidate


class EmojiDeliveryClient:
    """Use only the loopback Delivery Owner for Discord emoji access."""

    def __init__(self) -> None:
        try:
            self._client = DeliveryClient(
                os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9140"),
                Path(os.environ.get(
                    "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
                    str(Path.home() / ".hermes/secrets/bursawatch-discord-delivery-client-token"),
                )),
                emoji_token_file=Path(os.environ.get(
                    "BURSAWATCH_DISCORD_DELIVERY_EMOJI_TOKEN_FILE",
                    str(Path.home() / ".hermes/secrets/bursawatch-discord-delivery-emoji-token"),
                )),
            )
        except DeliveryClientError as exc:
            raise ProfileEmojiError(str(exc)) from None

    def list_guild_emojis(self, guild_id: str) -> list[dict[str, Any]]:
        try:
            return self._client.list_guild_emojis(guild_id)
        except DeliveryClientError as exc:
            raise ProfileEmojiError(str(exc)) from None

    def create_guild_emoji(self, guild_id: str, name: str, png_bytes: bytes) -> dict[str, Any]:
        try:
            receipt = self._client.create_guild_emoji(guild_id, name, png_bytes)
            if receipt.status != "delivered":
                receipt = self._client.wait(receipt.key, DISCORD_TIMEOUT_SECONDS)
        except DeliveryClientError as exc:
            raise ProfileEmojiError(str(exc)) from None
        if receipt.status != "delivered" or not receipt.receipt:
            raise ProfileEmojiError(f"emoji creation is {receipt.status}; retry ensure after Delivery Owner resolves it")
        return {"name": name, "id": receipt.receipt.get("emoji_id")}


def _result_base(account: Account | None, name: str) -> dict[str, Any]:
    return {
        "platform": account.platform if account else "local",
        "account": account.handle if account else None,
        "profile_url": account.profile_url if account else None,
        "emoji_name": name,
        "shortcode": f":{name}:",
        "discord_markup": None,
        "emoji_id": None,
        "source_url": account.profile_url if account else None,
        "image_source_host": None,
        "image_sha256": None,
        "image_size_bytes": None,
        "action": None,
    }


def _apply_image_fields(result: dict[str, Any], image: ResolvedImage) -> None:
    result["image_source_host"] = image.image_source_host
    result["image_sha256"] = image.image_sha256
    result["image_size_bytes"] = len(image.png_bytes)


def _result_for_existing(result: dict[str, Any], emoji: dict[str, Any]) -> dict[str, Any]:
    if emoji.get("managed"):
        raise ProfileEmojiError("an integration-managed emoji already uses this name")
    if emoji.get("animated"):
        raise ProfileEmojiError("an animated emoji already uses this name")
    emoji_id = _validate_emoji_id(emoji.get("id"))
    result["emoji_id"] = emoji_id
    result["discord_markup"] = f"<:{result['emoji_name']}:{emoji_id}>"
    result["action"] = "existing"
    return result


def prepare(account: Account, name: str) -> dict[str, Any]:
    image = resolve_profile_image(account)
    result = _result_base(account, name)
    _apply_image_fields(result, image)
    result["action"] = "prepared"
    return result


def ensure(
    account: Account,
    name: str,
    guild_id: str,
    *,
    apply: bool,
) -> dict[str, Any]:
    client = EmojiDeliveryClient()
    result = _result_base(account, name)
    matching = [emoji for emoji in client.list_guild_emojis(guild_id) if emoji.get("name") == name]
    if len(matching) > 1:
        raise ProfileEmojiError("multiple Discord emojis use the requested name")
    if matching:
        return _result_for_existing(result, matching[0])

    image = resolve_profile_image(account)
    _apply_image_fields(result, image)
    if not apply:
        result["action"] = "would_create"
        return result

    created = client.create_guild_emoji(guild_id, name, image.png_bytes)
    if created.get("name") not in {None, name}:
        raise ProfileEmojiError("Discord returned an emoji with an unexpected name")
    emoji_id = _validate_emoji_id(created.get("id"))
    result["emoji_id"] = emoji_id
    result["discord_markup"] = f"<:{name}:{emoji_id}>"
    result["action"] = "created"
    return result


def ensure_image(
    image_path: str,
    name: str,
    guild_id: str,
    *,
    apply: bool,
) -> dict[str, Any]:
    client = EmojiDeliveryClient()
    result = _result_base(None, name)
    matching = [emoji for emoji in client.list_guild_emojis(guild_id) if emoji.get("name") == name]
    if len(matching) > 1:
        raise ProfileEmojiError("multiple Discord emojis use the requested name")
    if matching:
        return _result_for_existing(result, matching[0])

    image = resolve_local_image(image_path)
    _apply_image_fields(result, image)
    if not apply:
        result["action"] = "would_create"
        return result

    created = client.create_guild_emoji(guild_id, name, image.png_bytes)
    if created.get("name") not in {None, name}:
        raise ProfileEmojiError("Discord returned an emoji with an unexpected name")
    emoji_id = _validate_emoji_id(created.get("id"))
    result["emoji_id"] = emoji_id
    result["discord_markup"] = f"<:{name}:{emoji_id}>"
    result["action"] = "created"
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--platform", required=True, choices=("x", "instagram"))
        subparser.add_argument("--account", required=True, help="profile URL or handle")
        subparser.add_argument("--emoji-name")
        subparser.add_argument("--profile-id", help="stable reviewed watcher ID")
        subparser.add_argument("--json", action="store_true", help="emit one JSON result")

    prepare_parser = subparsers.add_parser("prepare", help="resolve and crop without contacting Discord")
    add_common(prepare_parser)

    ensure_parser = subparsers.add_parser("ensure", help="return or create a guild emoji")
    add_common(ensure_parser)
    ensure_parser.add_argument("--guild-id", default=DEFAULT_GUILD_ID)
    ensure_parser.add_argument(
        "--apply",
        action="store_true",
        help="create the emoji when absent; existing emojis are always returned unchanged",
    )

    image_parser = subparsers.add_parser(
        "ensure-image", help="return or create an emoji from an explicitly supplied local image"
    )
    image_parser.add_argument("--image-path", required=True)
    image_parser.add_argument("--emoji-name", required=True)
    image_parser.add_argument("--guild-id", default=DEFAULT_GUILD_ID)
    image_parser.add_argument(
        "--apply",
        action="store_true",
        help="create the emoji when absent; existing emojis are always returned unchanged",
    )
    image_parser.add_argument("--json", action="store_true", help="emit one JSON result")
    return parser


def _print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    print(f"action: {result['action']}")
    print(f"shortcode: {result['shortcode']}")
    print(f"discord_markup: {result['discord_markup'] or '(not created)'}")
    print(f"emoji_id: {result['emoji_id'] or '(none)'}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "ensure-image":
            guild_id = _validate_guild_id(args.guild_id)
            name = validate_emoji_name(args.emoji_name)
            result = ensure_image(args.image_path, name, guild_id, apply=args.apply)
        else:
            account = normalize_account(args.platform, args.account)
            name = resolve_emoji_name(account, args.emoji_name, args.profile_id)
            if args.command == "prepare":
                result = prepare(account, name)
            else:
                guild_id = _validate_guild_id(args.guild_id)
                result = ensure(account, name, guild_id, apply=args.apply)
        _print_result(result, args.json)
        return 0
    except ProfileEmojiError as exc:
        print(f"profile-emoji: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("profile-emoji: could not write the requested output", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
