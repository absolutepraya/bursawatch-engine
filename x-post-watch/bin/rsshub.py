from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from models import PostKind, Profile, SourceMedia, SourcePost


POST_URL_RE = re.compile(r"^https://x\.com/([A-Za-z0-9_]{1,15})/status/(\d+)$")
ARTICLE_URL_RE = re.compile(r"https?://x\.com/i/article/\d+(?:\?\S+)?")
RELATION_TYPES = {"quote", "reply", "repost"}


class SourceFetchError(RuntimeError):
    pass


class _MediaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        candidate = values.get("src") if tag == "img" else values.get("poster") if tag == "video" else None
        if candidate and candidate.startswith("https://"):
            self.urls.append(candidate)


def _post_url(value: object, label: str) -> tuple[str, str]:
    if type(value) is not str:
        raise ValueError(f"{label} URL is missing")
    match = POST_URL_RE.fullmatch(value)
    if not match:
        raise ValueError(f"{label} URL is invalid")
    return value, match.group(2)


def _relations(item: dict[str, object]) -> list[dict[str, object]]:
    extra = item.get("_extra", {})
    if type(extra) is not dict:
        raise ValueError("item _extra must be an object")
    links = extra.get("links", [])
    if type(links) is not list:
        raise ValueError("item _extra.links must be an array")
    relations = []
    for link in links:
        if type(link) is not dict:
            raise ValueError("item relation must be an object")
        if link.get("type") in RELATION_TYPES:
            relations.append(link)
    return relations


def _kind(item: dict[str, object], relations: list[dict[str, object]]) -> tuple[PostKind, str | None]:
    kinds = {relation["type"] for relation in relations}
    if len(kinds) > 1:
        return PostKind.AMBIGUOUS, None
    if not kinds:
        return PostKind.NORMAL, None
    kind = next(iter(kinds))
    if kind == "repost":
        return PostKind.REPOST, None
    if kind == "reply":
        try:
            normalized, _ = _post_url(relations[0].get("url"), "replied-to post")
        except ValueError:
            return PostKind.AMBIGUOUS, None
        return PostKind.REPLY, normalized
    quote_url = relations[0].get("url")
    try:
        normalized, _ = _post_url(quote_url, "quoted post")
    except ValueError:
        return PostKind.AMBIGUOUS, None
    return PostKind.QUOTE, normalized


def _is_article_only(content_html: str) -> bool:
    text = re.sub(r"<[^>]+>", "", content_html).strip()
    # RSSHub prefixes quoted source content with the quoted account's display
    # name, for example "Ricky Ho: https://x.com/i/article/...".
    if not text.startswith(("http://", "https://")):
        text = re.sub(r"^[^:/\n]{1,80}:\s*", "", text)
    return bool(ARTICLE_URL_RE.fullmatch(text))


def _article_url(content_html: str) -> str | None:
    text = re.sub(r"<[^>]+>", "", content_html)
    match = ARTICLE_URL_RE.search(text)
    return match.group(0) if match else None


def _article_label(content_html: str, article_url: str) -> str:
    text = " ".join(re.sub(r"<[^>]+>", " ", content_html).split())
    prefix = text.split(article_url, 1)[0].strip(" :")
    return prefix or "Quoted X Article"


def _media(content_html: str) -> tuple[SourceMedia, ...]:
    parser = _MediaParser()
    parser.feed(content_html)
    seen: set[str] = set()
    return tuple(SourceMedia(url=url, index=index) for index, url in enumerate(url for url in parser.urls if not (url in seen or seen.add(url))))


def _merged_media(*groups: tuple[SourceMedia, ...]) -> tuple[SourceMedia, ...]:
    urls: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for media in group:
            if media.url not in seen:
                seen.add(media.url)
                urls.append(media.url)
    return tuple(SourceMedia(url=url, index=index) for index, url in enumerate(urls))


def _quote_card_media(content_html: str) -> tuple[SourceMedia, ...]:
    match = re.search(r'<div class="rsshub-quote">.*?</div>\s*$', content_html, flags=re.DOTALL)
    return _media(match.group(0)) if match else ()


def _without_quote(content_html: str) -> str:
    return re.sub(r'<div class="rsshub-quote">.*?</div>\s*$', "", content_html, flags=re.DOTALL)


def parse_feed(payload: object, profile: Profile) -> list[SourcePost]:
    if type(payload) is not dict or type(payload.get("items")) is not list:
        raise SourceFetchError("RSSHub X feed returned an invalid JSON feed")
    result: list[SourcePost] = []
    for raw_item in payload["items"][: profile.max_items_per_poll]:
        if type(raw_item) is not dict:
            raise SourceFetchError("RSSHub X feed contains an invalid item")
        try:
            url, post_id = _post_url(raw_item.get("url", raw_item.get("id")), "post")
            content_html = raw_item.get("content_html", raw_item.get("content_text", ""))
            if type(content_html) is not str:
                raise ValueError("post content is invalid")
            published_at = datetime.fromisoformat(str(raw_item["date_published"]).replace("Z", "+00:00"))
            relations = _relations(raw_item)
            kind, quoted_url = _kind(raw_item, relations)
            was_quote = kind is PostKind.QUOTE
            quoted_html = None
            article_quote_media: tuple[SourceMedia, ...] = ()
            quoted_article_url = None
            quoted_article_label = None
            if kind is PostKind.QUOTE:
                quoted_html = relations[0].get("content_html")
                if type(quoted_html) is not str:
                    kind, quoted_url, quoted_html = PostKind.AMBIGUOUS, None, None
                elif _is_article_only(quoted_html):
                    # Retain the Article's cover or preview asset only. Its card
                    # and text must never leak into the authored post rendering.
                    article_quote_media = _merged_media(_media(quoted_html), _quote_card_media(content_html))
                    quoted_article_url = _article_url(quoted_html)
                    quoted_article_label = _article_label(quoted_html, quoted_article_url) if quoted_article_url else None
                    kind, quoted_url, quoted_html = PostKind.NORMAL, None, None
            # Determine whether the author published an Article from their own
            # text only. A quoted Article card must not turn an authored quote
            # into a standalone Article and erase its metadata.
            original_html = _without_quote(content_html) if was_quote else content_html
            if _is_article_only(original_html):
                kind, quoted_url, quoted_html, quoted_article_url, quoted_article_label = PostKind.ARTICLE, None, None, None, None
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceFetchError(f"RSSHub X feed contains an invalid item: {exc}") from exc
        # A quoted X Article is deliberately normalized to an authored normal
        # post.  Its RSSHub quote card must still be removed from the author
        # post before rendering or extracting media.
        result.append(SourcePost(profile.id, post_id, url, published_at, original_html, kind, quoted_url, quoted_html, _media(original_html), article_quote_media or _media(quoted_html or ""), quoted_url, quoted_article_url, quoted_article_label))
    return result


def fetch_profile_items(profile: Profile, session: requests.Session | None = None) -> list[SourcePost]:
    client = session or requests.Session()
    try:
        response = client.get(profile.feed_url, timeout=30)
    except requests.Timeout as exc:
        raise SourceFetchError("RSSHub X feed timed out") from exc
    except requests.RequestException as exc:
        raise SourceFetchError("RSSHub X feed request failed") from exc
    if response.status_code in {401, 403}:
        raise SourceFetchError(f"RSSHub X feed HTTP {response.status_code}: authentication rejected")
    if response.status_code >= 400:
        raise SourceFetchError(f"RSSHub X feed HTTP {response.status_code}")
    try:
        return parse_feed(response.json(), profile)
    except ValueError as exc:
        raise SourceFetchError("RSSHub X feed returned malformed JSON") from exc


def is_forwardable(profile: Profile, post: SourcePost) -> bool:
    return {
        PostKind.NORMAL: profile.forward_normal_post,
        PostKind.QUOTE: profile.forward_quote_post,
        PostKind.REPLY: profile.forward_reply,
        PostKind.REPOST: profile.forward_repost,
        PostKind.ARTICLE: False,
        PostKind.AMBIGUOUS: False,
    }[post.kind]


def is_self_thread_post(profile: Profile, post: SourcePost) -> bool:
    if profile.thread_handling.mode != "self_chain" or post.kind not in {PostKind.QUOTE, PostKind.REPLY}:
        return False
    if not post.related_url:
        return False
    match = POST_URL_RE.fullmatch(post.related_url)
    return bool(match and match.group(1).lower() == profile.handle.lower())
