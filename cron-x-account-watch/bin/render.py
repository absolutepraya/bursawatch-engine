from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import sys

from models import Profile, SourcePost


_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from swing_format import BOARD_MENTION, format_wib  # noqa: E402


DISCORD_LIMIT = 2000
QUOTED_TEXT_LIMIT = 100
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+")
SOURCE_URL_RE = re.compile(r"https?://[^\s<>()]+")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"p", "div", "br"}:
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "strong":
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a":
            self.href = values.get("href")

    def handle_endtag(self, tag):
        if tag == "strong":
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a" and self.href:
            self.parts.append(f" (<{self.href}>)")
            self.href = None

    def handle_data(self, data):
        self.parts.append(re.sub(r"([`~|])", r"\\\1", data))


def markdown(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def strip_emojis(value: str) -> str:
    """Remove emoji glyphs from a writer name while preserving its text."""
    return re.sub(r"\s+", " ", EMOJI_RE.sub("", value)).strip()


def _split_plain(value: str, limit: int) -> list[str]:
    """Split only source text, never a Markdown link or quote block we add."""
    value = value.strip()
    if not value:
        return []
    result: list[str] = []
    while len(value) > limit:
        candidates = (value.rfind("\n\n", 0, limit + 1), value.rfind("\n", 0, limit + 1), value.rfind(" ", 0, limit + 1))
        cut = next((candidate for candidate in candidates if candidate > 0), limit)
        result.append(value[:cut].rstrip())
        value = value[cut:].lstrip()
    return result + [value]


def _append_text(prefix: str, text: str) -> list[str]:
    limit = DISCORD_LIMIT - len(prefix)
    if limit <= 0:
        raise ValueError("Discord heading exceeds its message limit")
    chunks = _split_plain(text, limit)
    if not chunks:
        return [prefix.rstrip()]
    return [prefix + chunks[0], *_split_plain("\n\n".join(chunks[1:]), DISCORD_LIMIT)]


def _append_atomic(messages: list[str], value: str, separator: str) -> None:
    """Keep links and quote blocks whole, placing them in a new message if needed."""
    if len(value) > DISCORD_LIMIT:
        raise ValueError("atomic Discord section exceeds its message limit")
    if len(messages[-1]) + len(separator) + len(value) <= DISCORD_LIMIT:
        messages[-1] += separator + value
    else:
        messages.append(value)


def _truncate(value: str, limit: int = QUOTED_TEXT_LIMIT) -> str:
    if len(value) <= limit:
        return value
    cut = value.rfind(" ", 0, limit)
    return value[:cut if cut > 0 else limit].rstrip() + "..."


def _quoted_text(content_html: str) -> str:
    """Keep the first cited source link clickable without exposing its raw URL."""
    quoted = markdown(content_html) or "Quoted post text unavailable"
    match = SOURCE_URL_RE.search(quoted)
    if not match:
        return _truncate(quoted)
    source_url = match.group(0).rstrip(".,;:!?")
    prefix = quoted[:match.start()].rstrip()
    # HTML anchors become `label (<url>)` in markdown(). Remove the orphaned
    # opening parenthesis when the URL becomes its own Discord anchor.
    if prefix.endswith("("):
        prefix = prefix[:-1].rstrip()
    return f"{_truncate(prefix)} [Read source](<{source_url}>)".strip()


def _quoted_block(content_html: str, quoted_url: str) -> str:
    quoted = _quoted_text(content_html)
    name, separator, content = quoted.partition(":")
    if not separator or not name.strip():
        name, content = "Quoted post", quoted
    lines = [f"> **{name.strip()}**"]
    content_lines = content.strip().splitlines()
    for line in content_lines:
        if not line.strip():
            lines.append("> \u200b")
        else:
            lines.append(f"> {line}")
    lines.append(f"> [View quoted on X](<{quoted_url}>)")
    return "\n".join(lines)


def _article_block(label: str | None, article_url: str) -> str:
    safe_label = re.sub(r"([`~|*_])", r"\\\1", " ".join((label or "Quoted X Article").split()))
    return f"> **{safe_label}**\n> *(Article)*\n> [Read Article on X](<{article_url}>)"


def _thread_text(thread_posts: tuple[SourcePost, ...]) -> str:
    parts = [markdown(post.content_html) or "*(No text)*" for post in thread_posts]
    return "\n\n".join(parts)


def render_post(
    profile: Profile,
    post: SourcePost,
    summary: str | None = None,
    title: str | None = None,
    thread_posts: tuple[SourcePost, ...] | None = None,
    updated_tweet: bool = False,
    *,
    include_board: bool = False,
    include_status_date: bool = False,
    status_date: datetime | None = None,
) -> list[str]:
    writer_name = strip_emojis(profile.display_name)
    byline = f"{writer_name} (Updated Tweet)" if updated_tweet else writer_name
    heading = f"### {profile.twitter_emoji} {title}\n-# {profile.emoji} {byline}" if title else f"### {profile.twitter_emoji}{profile.emoji} {byline}"
    prefix = f"{heading}\n\n"
    rendered_status_date = status_date if status_date is not None else post.published_at
    if summary is not None:
        messages = _append_text(prefix, summary.strip())
        if include_status_date:
            _append_atomic(messages, f"**Status date:** {format_wib(rendered_status_date)}", "\n\n")
        if include_board:
            _append_atomic(messages, f"**Board:** {BOARD_MENTION}", "\n")
        _append_atomic(messages, f"[View on X](<{post.url}>)", "\n\n")
        if profile.show_quoted_post:
            if post.quoted_content_html:
                _append_atomic(messages, _quoted_block(post.quoted_content_html, post.quoted_url or post.url), "\n")
            if post.quoted_article_url:
                _append_atomic(messages, _article_block(post.quoted_article_label, post.quoted_article_url), "\n")
        return messages
    messages = _append_text(prefix, _thread_text(thread_posts or (post,)))
    if include_status_date:
        _append_atomic(messages, f"**Status date:** {format_wib(rendered_status_date)}", "\n\n")
    if include_board:
        _append_atomic(messages, f"**Board:** {BOARD_MENTION}", "\n")
    _append_atomic(messages, f"[View on X](<{post.url}>)", "\n\n" if include_board else " ")
    if profile.show_quoted_post:
        if post.quoted_content_html:
            _append_atomic(messages, _quoted_block(post.quoted_content_html, post.quoted_url or post.url), "\n")
        if post.quoted_article_url:
            _append_atomic(messages, _article_block(post.quoted_article_label, post.quoted_article_url), "\n")
    return messages
