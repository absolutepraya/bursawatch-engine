from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from models import MediaKind, Profile, PublicationKind, SourceMedia, SourcePost


class SourceFetchError(RuntimeError):
    pass


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
        if tag not in self._media_tags:
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
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"instagram.com", "www.instagram.com"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] not in {"p", "reel"} or not parts[1]:
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
    seen: set[str] = set()
    media: list[SourceMedia] = []
    for url, media_kind in parser.media:
        if not isinstance(url, str) or not url or url in seen:
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
    return SourcePost(profile.id, _stable_id(item, shortcode), str(item["url"]), published_at, "".join(parser.caption), kind, tuple(media))


def parse_feed(payload: object, profile: Profile, after_id: str | None = None) -> list[SourcePost]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise SourceFetchError("RSSHub response must contain an items list")
    if payload.get("private") is True or isinstance(payload.get("profile"), dict) and payload["profile"].get("is_private") is True:
        return []
    posts: list[SourcePost] = []
    cursor_seen = after_id is None
    for item in payload["items"]:
        post = _parse_item(item, profile)
        if post is None:
            continue
        if not cursor_seen:
            if post.publication_id == after_id:
                cursor_seen = True
            continue
        posts.append(post)
    return posts


def fetch_profile_items(profile: Profile, session: requests.Session | None = None, after_id: str | None = None) -> list[SourcePost]:
    client = session or requests.Session()
    try:
        response = client.get(profile.feed_url, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SourceFetchError("RSSHub request failed") from exc
    except (ValueError, TypeError) as exc:
        raise SourceFetchError("RSSHub returned invalid JSON") from exc
    return parse_feed(payload, profile, after_id)


def is_forwardable(profile: Profile, post: SourcePost) -> bool:
    return (post.kind is PublicationKind.POST and profile.forward_post or post.kind is PublicationKind.REEL and profile.forward_reel) and bool(post.media) and profile.forward_media
