from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import ipaddress
import re
import socket
import time
from urllib.parse import urlparse

import requests

from models import MediaKind, Profile, PublicationKind, SourceMedia, SourcePost


class SourceFetchError(RuntimeError):
    pass


RSSHUB_REQUEST_TIMEOUT_SECONDS = 75
RSSHUB_REQUEST_ATTEMPTS = 2
RSSHUB_RETRY_DELAY_SECONDS = 1.0


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _safe_component(value: object) -> str | None:
    candidate = str(value).strip() if isinstance(value, (str, int)) else ""
    if not candidate or candidate in {".", ".."} or not _SAFE_COMPONENT.fullmatch(candidate):
        return None
    return candidate


def _parse_url(value: str):
    try:
        return urlparse(value)
    except ValueError:
        return None


def is_supported_media_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 4096:
        return False
    parsed = _parse_url(value)
    if parsed is None:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port not in {None, 80, 443}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not is_public_ip_address(address):
        return False
    return True


def is_public_ip_address(address: ipaddress._BaseAddress) -> bool:
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def is_publicly_resolvable_media_url(value: object) -> bool:
    if not is_supported_media_url(value):
        return False
    parsed = _parse_url(value)
    if parsed is None:
        return False
    hostname = parsed.hostname
    assert hostname is not None
    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not addresses:
        return False
    for address_info in addresses:
        try:
            address = ipaddress.ip_address(address_info[4][0])
        except (IndexError, ValueError):
            return False
        if not is_public_ip_address(address):
            return False
    return True


class _MediaCaptionParser(HTMLParser):
    _media_tags = {"img", "video", "source"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.media: list[tuple[str, MediaKind]] = []
        self.caption: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in self._media_tags:
            if tag == "img" and attrs_dict.get("src"):
                self.media.append((attrs_dict["src"], MediaKind.IMAGE))
            if tag in {"video", "source"} and attrs_dict.get("src"):
                self.media.append((attrs_dict["src"], MediaKind.VIDEO))
            if tag == "video" and attrs_dict.get("poster"):
                self.media.append((attrs_dict["poster"], MediaKind.IMAGE))
            if tag == "video":
                self._skip_depth += 1
            return
        if self._skip_depth:
            return
        self.caption.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "video":
            self.handle_endtag(tag)
        elif tag not in self._media_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag == "video":
                self._skip_depth = 0
            return
        if tag not in self._media_tags:
            self.caption.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.caption.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.caption.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.caption.append(f"&#{name};")


def _publication_url(value: object) -> tuple[PublicationKind, str] | None:
    if not isinstance(value, str):
        return None
    if value != value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    if "?" in value or "#" in value:
        return None
    parsed = _parse_url(value)
    if parsed is None:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"instagram.com", "www.instagram.com"}:
        return None
    if parsed.params:
        return None
    if not parsed.path.startswith("/"):
        return None
    parts = parsed.path.split("/")
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    if len(parts) != 2 or parts[0] not in {"p", "reel"} or _safe_component(parts[1]) is None:
        return None
    return (PublicationKind.REEL if parts[0] == "reel" else PublicationKind.POST, parts[1])


def _stable_id(item: dict, shortcode: str) -> str:
    for key in ("media_id", "instagram_id", "id"):
        value = item.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            candidate = str(value).strip()
            if "cdn" not in candidate.lower() and "/" not in candidate:
                return candidate
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in ("media_id", "instagram_id", "id"):
            value = metadata.get(key)
            if isinstance(value, (str, int)) and str(value).strip() and "/" not in str(value):
                return str(value).strip()
    return shortcode


def _is_private(item: dict) -> bool:
    if item.get("private") is True or item.get("is_private") is True:
        return True
    metadata = item.get("metadata")
    return isinstance(metadata, dict) and (metadata.get("private") is True or metadata.get("is_private") is True)


def _is_truthy_reel_flag(value: object) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().casefold() in {"1", "true", "yes"}


def _is_reel_item(item: dict, media: list[tuple[str, MediaKind]]) -> bool:
    """Recognize clips even when RSSHub gives them a /p/ publication URL."""
    metadata_sources = [item]
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        metadata_sources.append(metadata)
    for source in metadata_sources:
        if _is_truthy_reel_flag(source.get("is_reel")):
            return True
        for key in ("product_type", "type"):
            value = source.get(key)
            if isinstance(value, str) and value.strip().casefold() in {
                "clip",
                "clips",
                "igtv",
                "reel",
                "reels",
                "video",
            }:
                return True
    return any(media_kind is MediaKind.VIDEO for _url, media_kind in media)


def _parse_item(item: object, profile: Profile) -> SourcePost | None:
    if not isinstance(item, dict) or _is_private(item):
        return None
    publication = _publication_url(item.get("url"))
    if publication is None:
        return None
    kind, shortcode = publication
    html = item.get("content_html")
    if not isinstance(html, str):
        title = item.get("title")
        html = title if isinstance(title, str) else ""
    parser = _MediaCaptionParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if _is_reel_item(item, parser.media):
        kind = PublicationKind.REEL
    seen: set[str] = set()
    media: list[SourceMedia] = []
    for url, media_kind in parser.media:
        if not is_supported_media_url(url) or url in seen:
            continue
        seen.add(url)
        media.append(SourceMedia(url, media_kind, len(media)))
    if not media:
        return None
    published = item.get("date_published")
    try:
        published_at = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        return None
    publication_id = _safe_component(_stable_id(item, shortcode))
    if publication_id is None:
        return None
    return SourcePost(profile.id, publication_id, str(item["url"]), published_at, "".join(parser.caption), kind, tuple(media))


def parse_feed(payload: object, profile: Profile, after_id: str | None = None) -> list[SourcePost]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise SourceFetchError("RSSHub response must contain an items list")
    if payload.get("private") is True or isinstance(payload.get("profile"), dict) and payload["profile"].get("is_private") is True:
        return []
    posts: list[SourcePost] = []
    for item in payload["items"]:
        post = _parse_item(item, profile)
        if post is None:
            continue
        posts.append(post)
    if after_id is None:
        return posts
    for index, post in enumerate(posts):
        if post.publication_id == after_id:
            return posts[index + 1:]
    # RSSHub returns one page. If the durable cursor is not on that page,
    # return the page and let durable timestamp/ID comparisons and deduplication
    # decide which entries are new.
    return posts


def fetch_profile_items(profile: Profile, session: requests.Session | None = None, after_id: str | None = None) -> list[SourcePost]:
    client = session or requests.Session()
    payload = None
    for attempt in range(RSSHUB_REQUEST_ATTEMPTS):
        response = None
        try:
            response = client.get(profile.feed_url, timeout=RSSHUB_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            break
        except requests.RequestException as exc:
            if attempt + 1 >= RSSHUB_REQUEST_ATTEMPTS:
                raise SourceFetchError("RSSHub request failed") from exc
        except (ValueError, TypeError) as exc:
            raise SourceFetchError("RSSHub returned invalid JSON") from exc
        except Exception as exc:
            raise SourceFetchError("RSSHub source failed") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        time.sleep(RSSHUB_RETRY_DELAY_SECONDS)
    try:
        return parse_feed(payload, profile, after_id)
    except SourceFetchError:
        raise
    except Exception as exc:
        raise SourceFetchError("RSSHub source failed") from exc


def is_forwardable(profile: Profile, post: SourcePost) -> bool:
    return (post.kind is PublicationKind.POST and profile.forward_post or post.kind is PublicationKind.REEL and profile.forward_reel) and bool(post.media) and profile.forward_media
