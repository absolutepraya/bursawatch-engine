"""Profile metadata inputs and safe avatar URL resolution."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
import re
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_AVATAR_URL_LENGTH = 2_048
MAX_RESPONSE_BYTES = 1 * 1024 * 1024
DEFAULT_RSSHub_BASE_URL = "http://127.0.0.1:1200"
DEFAULT_TIMEOUT_SECONDS = 10
USER_AGENT = "bursawatch-control-plane/1.0"

PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
X_PROFILE_HOSTS = frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"})
INSTAGRAM_PROFILE_HOSTS = frozenset({"instagram.com", "www.instagram.com"})
X_AVATAR_HOSTS = frozenset({"pbs.twimg.com", "abs.twimg.com", "ton.twimg.com"})
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


class AvatarResolutionError(RuntimeError):
    """A safe, user-facing failure without provider response bodies."""


@dataclass(frozen=True)
class ProfileMetadataInput:
    profile_id: str
    handle: str
    display_name: str
    profile_url: str
    enabled: bool


@dataclass(frozen=True)
class AvatarResolution:
    url: str
    source: str


class AvatarResolver(Protocol):
    def resolve(self, profile: ProfileMetadataInput) -> AvatarResolution: ...


def _profile_id(value: object) -> str:
    if type(value) is not str or not PROFILE_ID_RE.fullmatch(value):
        raise ValueError("profile id must use lowercase letters, digits, _ or -")
    return value


def validate_profile_id(value: object) -> str:
    return _profile_id(value)


def profile_inputs_from_config(config: dict[str, Any]) -> list[ProfileMetadataInput]:
    """Extract complete display-safe profile identities from a validated config."""

    raw_profiles = config.get("profiles", [])
    if raw_profiles is None or type(raw_profiles) is not list:
        return []

    profiles: list[ProfileMetadataInput] = []
    seen: set[str] = set()
    for raw_profile in raw_profiles:
        if type(raw_profile) is not dict:
            continue
        required = {"id", "handle", "display_name", "profile_url", "enabled"}
        if not required.issubset(raw_profile):
            continue
        try:
            profile_id = _profile_id(raw_profile.get("id"))
        except ValueError:
            continue
        enabled = raw_profile.get("enabled")
        if type(enabled) is not bool:
            continue
        handle = raw_profile.get("handle")
        display_name = raw_profile.get("display_name")
        profile_url = raw_profile.get("profile_url")
        if not all(type(value) is str and value.strip() for value in (handle, display_name, profile_url)):
            continue
        if profile_id in seen:
            raise ValueError("profile ids must be unique")
        seen.add(profile_id)
        profiles.append(
            ProfileMetadataInput(
                profile_id=profile_id,
                handle=handle.strip(),
                display_name=display_name.strip(),
                profile_url=profile_url.strip(),
                enabled=enabled,
            )
        )
    return profiles


def normalize_manual_avatar_url(value: object) -> str:
    """Validate a durable HTTPS avatar URL supplied by an admin."""

    if type(value) is not str or not value.strip() or len(value) > MAX_AVATAR_URL_LENGTH:
        raise ValueError("avatar URL must be non-empty text of at most 2048 characters")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("avatar URL is malformed") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ValueError("avatar URL must be HTTPS without credentials, fragments, or custom ports")
    return urlunsplit(("https", parsed.hostname.lower().rstrip("."), parsed.path, parsed.query, ""))


def _platform(profile_url: str) -> str:
    try:
        parsed = urlsplit(profile_url)
    except ValueError as exc:
        raise AvatarResolutionError("profile URL is malformed") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if host in X_PROFILE_HOSTS:
        return "x"
    if host in INSTAGRAM_PROFILE_HOSTS:
        return "instagram"
    raise AvatarResolutionError("profile URL host is not supported")


def _trusted_avatar_url(value: object, platform: str) -> str | None:
    if type(value) is not str or not value.strip() or len(value) > MAX_AVATAR_URL_LENGTH:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in {None, 443}
    ):
        return None
    host = parsed.hostname.lower().rstrip(".")
    if platform == "x":
        allowed = host in X_AVATAR_HOSTS
    else:
        allowed = host == "cdninstagram.com" or host.endswith(".cdninstagram.com") or host.endswith(".fbcdn.net")
    if not allowed:
        return None
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


class _ProfileMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.identities: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content")
            if not content:
                return
            if key in {"og:image", "twitter:image", "twitter:image:src"}:
                self.images.append(content)
            elif key in {"og:url", "twitter:url"}:
                self.identities.append(content)
        elif tag_name == "link":
            rel = {part.strip().lower() for part in (attributes.get("rel") or "").split()}
            href = attributes.get("href")
            if "canonical" in rel and href:
                self.identities.append(href)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, msg: str, headers: Any, new_url: str):
        return None


def _profile_identity_matches(profile: ProfileMetadataInput, value: str) -> bool:
    try:
        parsed = urlsplit(unquote(value))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    expected_hosts = X_PROFILE_HOSTS if _platform(profile.profile_url) == "x" else INSTAGRAM_PROFILE_HOSTS
    path_parts = [part for part in parsed.path.split("/") if part]
    return host in expected_hosts and len(path_parts) == 1 and path_parts[0].casefold() == profile.handle.casefold()


def _profile_page_candidates(profile: ProfileMetadataInput, body: bytes) -> list[str]:
    parser = _ProfileMetaParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    if parser.identities and not any(_profile_identity_matches(profile, value) for value in parser.identities):
        raise AvatarResolutionError("profile page identity does not match the requested account")

    result: list[str] = []
    platform = _platform(profile.profile_url)
    for value in parser.images:
        candidate = urljoin(profile.profile_url, value.strip())
        normalized = _trusted_avatar_url(candidate, platform)
        if normalized is not None and normalized not in result:
            result.append(normalized)
    return result


def _rsshub_avatar_candidates(payload: object, platform: str) -> list[tuple[str, str]]:
    if type(payload) is not dict:
        return []
    candidates: list[tuple[str, str]] = []

    def add(value: object, source: str) -> None:
        normalized = _trusted_avatar_url(value, platform)
        if normalized is not None and (normalized, source) not in candidates:
            candidates.append((normalized, source))

    def visit(value: object, source: str, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).lower()
                if normalized_key in AVATAR_KEYS:
                    add(child, source)
                elif normalized_key in AVATAR_CONTAINERS:
                    visit(child, "rsshub_author", depth + 1)
        elif isinstance(value, list):
            for child in value[:20]:
                visit(child, source, depth + 1)

    for key in ("icon", "avatar", "avatar_url"):
        add(payload.get(key), "rsshub_icon")
    for key in ("author", "authors", "creator", "owner", "profile", "user"):
        visit(payload.get(key), "rsshub_author")
    return candidates


FetchBytes = Callable[[str, int, str], bytes]


class RssHubAvatarResolver:
    """Resolve only trusted provider avatar URLs, never image bytes."""

    def __init__(
        self,
        base_url: str = DEFAULT_RSSHub_BASE_URL,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        fetch_bytes: FetchBytes | None = None,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("avatar resolver timeout must be between 0 and 60 seconds")
        self.timeout_seconds = timeout_seconds
        self._fetch_bytes = fetch_bytes or self._fetch

    @classmethod
    def from_environment(cls) -> "RssHubAvatarResolver":
        raw_timeout = os.environ.get("CONTROL_PLANE_AVATAR_FETCH_TIMEOUT_SECONDS", "10").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise RuntimeError("CONTROL_PLANE_AVATAR_FETCH_TIMEOUT_SECONDS must be numeric") from exc
        return cls(
            os.environ.get("CONTROL_PLANE_RSSHUB_BASE_URL", DEFAULT_RSSHub_BASE_URL),
            timeout_seconds=timeout,
        )

    @staticmethod
    def _validate_base_url(value: str) -> str:
        try:
            parsed = urlsplit(value.strip().rstrip("/"))
            port = parsed.port
        except ValueError as exc:
            raise ValueError("RSSHub base URL is malformed") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or port not in {None, 80, 443, 1200}
        ):
            raise ValueError("RSSHub base URL must be HTTP(S), credential-free, and use a standard port")
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", ""))

    def _fetch(self, url: str, limit: int, accept: str) -> bytes:
        opener = build_opener(_NoRedirectHandler())
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise AvatarResolutionError(f"avatar source request failed with HTTP {status}")
                body = response.read(limit + 1)
        except HTTPError as exc:
            raise AvatarResolutionError(f"avatar source request failed with HTTP {exc.code}") from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise AvatarResolutionError("avatar source request failed") from exc
        if len(body) > limit:
            raise AvatarResolutionError("avatar source response is too large")
        return body

    def _rsshub_payload(self, profile: ProfileMetadataInput) -> object:
        platform = _platform(profile.profile_url)
        path_platform = "twitter" if platform == "x" else "instagram/2"
        route = (
            f"{self.base_url}/{path_platform}/user/"
            f"{quote(profile.handle, safe='._')}?format=json"
        )
        try:
            body = self._fetch_bytes(route, MAX_RESPONSE_BYTES, "application/json")
            return json.loads(body.decode("utf-8"))
        except (AvatarResolutionError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _profile_page_payload(self, profile: ProfileMetadataInput) -> bytes | None:
        try:
            return self._fetch_bytes(profile.profile_url, MAX_RESPONSE_BYTES, "text/html")
        except AvatarResolutionError:
            return None

    def resolve(self, profile: ProfileMetadataInput) -> AvatarResolution:
        platform = _platform(profile.profile_url)
        for url, source in _rsshub_avatar_candidates(self._rsshub_payload(profile), platform):
            return AvatarResolution(url=url, source=source)

        page = self._profile_page_payload(profile)
        if page is not None:
            for url in _profile_page_candidates(profile, page):
                return AvatarResolution(url=url, source="profile_page_meta")

        raise AvatarResolutionError("could not resolve a trusted profile avatar")
