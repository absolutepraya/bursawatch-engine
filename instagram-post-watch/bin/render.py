from __future__ import annotations

import re
from html.parser import HTMLParser

from models import Profile, PublicationKind, SourcePost


DISCORD_LIMIT = 2_000
MAX_CAPTION_HTML = 32_000
MAX_DISPLAY_NAME = 256
MAX_TITLE = 120

_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+")
_REEL_RE = re.compile(r"\breels?\b", re.IGNORECASE)
_MARKDOWN_SPECIALS_RE = re.compile(r"([\\`*_[\]~|<>])")


def _safe_prefix(value: str, limit: int) -> str:
    """Return a bounded prefix without cutting an explicit UTF-16 pair."""
    if len(value) <= limit:
        return value
    cut = limit
    if cut and cut < len(value):
        previous = ord(value[cut - 1])
        current = ord(value[cut])
        if 0xD800 <= previous <= 0xDBFF and 0xDC00 <= current <= 0xDFFF:
            cut -= 1
    return value[:cut]


def _escape_caption_text(value: str) -> str:
    """Escape caption text so source data cannot create Discord Markdown."""
    return _MARKDOWN_SPECIALS_RE.sub(r"\\\1", value)


class _CaptionParser(HTMLParser):
    """Extract bounded plain caption text from RSSHub HTML."""

    _IGNORED_TAGS = {"script", "style", "template", "svg"}
    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "main",
        "p",
        "section",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self._BLOCK_TAGS or tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if tag in self._BLOCK_TAGS or tag in {"li", "ul", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(_escape_caption_text(data))


def markdown(caption_html: str) -> str:
    """Convert untrusted RSSHub caption HTML to bounded safe Markdown text."""
    if not isinstance(caption_html, str):
        raise ValueError("Instagram caption is invalid")
    parser = _CaptionParser()
    parser.feed(_safe_prefix(caption_html, MAX_CAPTION_HTML))
    parser.close()
    value = "".join(parser.parts)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _escape_heading(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return _safe_prefix(_escape_caption_text(value), limit).strip()


def _reel_marker_needed(post: SourcePost, *, body: str, title: str | None) -> bool:
    if post.kind is not PublicationKind.REEL:
        return False
    return not any(_REEL_RE.search(value) for value in (body, title or "", post.caption_html))


def _cut_at_boundary(value: str, limit: int) -> int:
    if len(value) <= limit:
        return len(value)
    candidates = (
        value.rfind("\n\n", 0, limit + 1),
        value.rfind("\n", 0, limit + 1),
        value.rfind(" ", 0, limit + 1),
    )
    cut = next((candidate for candidate in candidates if candidate > 0), limit)
    if cut and cut < len(value):
        previous = ord(value[cut - 1])
        current = ord(value[cut])
        if 0xD800 <= previous <= 0xDBFF and 0xDC00 <= current <= 0xDFFF:
            cut -= 1
    return max(1, cut)


def _split_body(body: str, first_limit: int, footer: str) -> list[str]:
    """Split body text while reserving space for the final source link."""
    if first_limit <= 0 or len(footer) + 2 >= DISCORD_LIMIT:
        raise ValueError("Instagram source link exceeds Discord message limit")
    remaining = body.strip()
    messages: list[str] = []
    first = True
    while remaining:
        prefix_length = DISCORD_LIMIT - first_limit if first else 0
        available = first_limit if first else DISCORD_LIMIT
        final_size = len(remaining) + 2 + len(footer)
        if final_size <= available:
            messages.append(remaining)
            break
        cut = _cut_at_boundary(remaining, available)
        messages.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
        first = False
        if prefix_length < 0:
            raise ValueError("Instagram heading exceeds Discord message limit")
    return messages

def render_publication(
    profile: Profile,
    post: SourcePost,
    summary: str | None = None,
    title: str | None = None,
) -> list[str]:
    """Render accepted analysis or the source caption, followed by its link."""
    if not isinstance(profile, Profile) or not isinstance(post, SourcePost):
        raise ValueError("Instagram publication is invalid")

    display_name = _escape_heading(profile.display_name, MAX_DISPLAY_NAME)
    accepted_title = _escape_heading(title, MAX_TITLE) if title is not None else ""
    if summary is not None and summary.strip():
        body = summary.strip()
    else:
        body = markdown(post.caption_html)

    heading_text = accepted_title or display_name
    if _reel_marker_needed(post, body=body, title=accepted_title or None):
        heading_text = f"{heading_text} (Reel)"
    platform = profile.platform_emoji.strip()
    account = profile.emoji.strip()
    if not platform:
        raise ValueError("Instagram platform emoji is invalid")
    account_part = f"{account} " if account else ""
    heading = f"### {platform} {heading_text}\n-# {account_part}{display_name}" if accepted_title else f"### {platform} {account_part}{heading_text}"
    footer = f"[View on Instagram](<{post.url}>)"
    if not body:
        message = f"{heading}\n\n{footer}"
        if len(message) > DISCORD_LIMIT:
            raise ValueError("Instagram heading exceeds Discord message limit")
        return [message]

    first_limit = DISCORD_LIMIT - len(heading) - 2
    body_chunks = _split_body(body, first_limit, footer)
    messages = [f"{heading}\n\n{body_chunks[0]}"]
    messages.extend(body_chunks[1:])
    messages[-1] = f"{messages[-1]}\n\n{footer}"
    if any(len(message) > DISCORD_LIMIT for message in messages):
        raise ValueError("Instagram publication exceeds Discord message limit")
    return messages
