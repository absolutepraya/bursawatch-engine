from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from typing import Iterable
import xml.etree.ElementTree as ET

import requests

from models import Article, Feed


USER_AGENT = "bursawatch-stockbit-snips/1.0"


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        elif self.ignored == 0 and tag in {"p", "div", "li", "br", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1
        elif self.ignored == 0 and tag in {"p", "div", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored == 0:
            self.parts.append(data)


def visible_text(value: str, limit: int = 12000) -> str:
    parser = _VisibleText()
    parser.feed(value)
    parser.close()
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts))
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()[:limit]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _children(element: ET.Element, name: str) -> Iterable[ET.Element]:
    wanted = name.casefold()
    return (child for child in list(element) if _local_name(child.tag) == wanted)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _first_text(item: ET.Element, *names: str) -> str:
    for name in names:
        for child in _children(item, name):
            value = _text(child)
            if value:
                return value
    return ""


def _published(value: str) -> datetime:
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"RSS publication date is invalid: {value!r}") from error
    if result.tzinfo is None or result.utcoffset() is None:
        result = result.replace(tzinfo=UTC)
    return result


def _media_url(item: ET.Element) -> str | None:
    for child in list(item):
        if _local_name(child.tag) in {"content", "thumbnail", "enclosure"}:
            value = child.attrib.get("url")
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def parse_feed(xml: str, feed: Feed, *, provider_order: bool = False) -> list[Article]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ValueError("Stockbit RSS XML is invalid") from error
    elements = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    articles: list[Article] = []
    for item in elements:
        title = _first_text(item, "title")
        url = _first_text(item, "link")
        if not url:
            for link in _children(item, "link"):
                url = link.attrib.get("href", "")
                if url:
                    break
        guid = _first_text(item, "guid", "id") or url
        pub_date = _first_text(item, "pubdate", "published", "updated")
        if not title or not url or not guid or not pub_date:
            continue
        description = _first_text(item, "encoded", "description", "summary", "content")
        source_text = visible_text(description) or title
        articles.append(
            Article(
                lane=feed.lane,
                lane_label=feed.label,
                guid=guid,
                url=url,
                source_title=visible_text(title, 500),
                source_text=source_text,
                published_at=_published(pub_date),
                media_url=_media_url(item),
            )
        )
    if not provider_order:
        articles.sort(key=lambda item: (item.published_at, item.guid), reverse=True)
    return articles


@dataclass(frozen=True, slots=True)
class FetchResult:
    feed: Feed
    articles: tuple[Article, ...]
    etag: str | None
    last_modified: str | None
    not_modified: bool


def page_url(feed: Feed, page: int) -> str:
    if page < 1:
        raise ValueError("RSS page must be positive")
    return feed.url if page == 1 else f"{feed.url}&page={page}"


def fetch_feed(
    feed: Feed,
    *,
    timeout: float = 20,
    page: int = 1,
    etag: str | None = None,
    last_modified: str | None = None,
    provider_order: bool = False,
) -> FetchResult:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    response = requests.get(page_url(feed, page), headers=headers, timeout=timeout)
    if response.status_code == 304:
        return FetchResult(feed, (), etag, last_modified, True)
    response.raise_for_status()
    return FetchResult(
        feed,
        tuple(parse_feed(response.text, feed, provider_order=provider_order)),
        response.headers.get("ETag") or etag,
        response.headers.get("Last-Modified") or last_modified,
        False,
    )
