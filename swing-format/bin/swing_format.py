"""Provider-neutral rendering for cash-equity Swing source messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")
BOARD_URL = "https://discord.com/channels/940285152335110204/1548273399069933720"
UP_EMOJI = "<:up:1531285100346740766>"
DOWN_EMOJI = "<:down:1531285063986053200>"
GREEN_EMOJI = "<:green:1531274822221434911>"
GREY_EMOJI = "<:grey:1531279158913536182>"
RED_EMOJI = "<:red:1531274756853202974>"
HOLD_EMOJI = "<:hold:1531284248235868333>"
MAX_DISCORD_CHARACTERS = 2_000

_MARKDOWN = re.compile(r"([\\*_~`|\[\]])")
_STOP = re.compile(r"\bstop[- ]?loss\b|\bcut loss\b|\bstopped out\b", re.IGNORECASE)
_TARGET = re.compile(r"\b(?:target|tp)\b.*\b(?:achieved|hit|reached)\b|\ball targets\b", re.IGNORECASE)
_ACTIVE = re.compile(r"\b(?:hold|on track|on support|sideways|neutral)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SwingField:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class SwingMessage:
    """Normalized input consumed by every cash-Swing provider adapter."""

    source_emoji: str
    title: str
    analyst_name: str | None
    institution: str
    body: tuple[str, ...]
    source_status: str | None
    updated_at: datetime | None
    source_url: str | None
    footer_label: str
    board_url: str | None = BOARD_URL
    fields: tuple[SwingField, ...] = ()
    chart_unavailable: bool = False


def escape(value: str) -> str:
    """Escape source values before inserting them into Markdown fields."""
    return _MARKDOWN.sub(r"\\\1", str(value))


def format_wib(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    local = value.astimezone(WIB)
    return f"{local.day} {local:%b %Y %H:%M} WIB"


def byline(analyst_name: str | None, institution: str) -> str:
    institution = _required_text(institution, "institution")
    if analyst_name and analyst_name.strip():
        return f"-# {escape(analyst_name.strip())}, {escape(institution)}"
    return f"-# {escape(institution)}"


def source_status_emoji(status: str) -> str:
    """Map one factual source status to exactly one inline marker."""
    value = _required_text(status, "source status")
    if _STOP.search(value):
        return RED_EMOJI
    if _TARGET.search(value):
        return GREEN_EMOJI
    if _ACTIVE.search(value):
        return HOLD_EMOJI
    return GREY_EMOJI


def render_message(message: SwingMessage, *, include_board: bool = False) -> str:
    """Render one complete message, preserving provider-specific body fields."""
    title = _required_text(message.title, "title")
    institution = _required_text(message.institution, "institution")
    if not message.source_emoji.strip():
        raise ValueError("source emoji must be non-empty")
    lines = [f"### {message.source_emoji} {escape(title)}", byline(message.analyst_name, institution), ""]

    for field in message.fields:
        label = _required_text(field.label, "field label")
        lines.append(f"**{escape(label)}:** {escape(field.value)}")
    lines.extend(message.body)
    if message.chart_unavailable:
        lines.append("**Chart:** Unavailable from source")

    if message.source_status is not None:
        status = _required_text(message.source_status, "source status")
        if message.updated_at is None:
            raise ValueError("source status requires updated_at")
        if lines[-1] != "":
            lines.append("")
        lines.append(f"**Source status:** {escape(status)} {source_status_emoji(status)}")
        lines.append(f"**Last updated:** {format_wib(message.updated_at)}")
        if include_board and message.board_url:
            lines.append(f"**Board:** <{message.board_url}>")
    elif include_board and message.board_url:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"**Board:** <{message.board_url}>")

    if message.source_url:
        label = _required_text(message.footer_label, "footer label")
        if lines[-1] != "":
            lines.append("")
        lines.append(f"[{escape(label)}](<{message.source_url}>)")
    rendered = "\n".join(lines)
    if discord_length(rendered) > MAX_DISCORD_CHARACTERS:
        raise ValueError("Swing message exceeds Discord's 2,000-character limit")
    return rendered


def render_chunks(message: SwingMessage, *, include_board: bool = False) -> tuple[str, ...]:
    """Render and split a long provider message without dropping source text."""
    rendered = render_message_unbounded(message, include_board=include_board)
    return split_content(rendered)


def render_message_unbounded(message: SwingMessage, *, include_board: bool = False) -> str:
    """Internal form used by chunking adapters before the Discord limit check."""
    title = _required_text(message.title, "title")
    institution = _required_text(message.institution, "institution")
    if not message.source_emoji.strip():
        raise ValueError("source emoji must be non-empty")
    lines = [f"### {message.source_emoji} {escape(title)}", byline(message.analyst_name, institution), ""]
    for field in message.fields:
        label = _required_text(field.label, "field label")
        lines.append(f"**{escape(label)}:** {escape(field.value)}")
    lines.extend(message.body)
    if message.chart_unavailable:
        lines.append("**Chart:** Unavailable from source")
    if message.source_status is not None:
        status = _required_text(message.source_status, "source status")
        if message.updated_at is None:
            raise ValueError("source status requires updated_at")
        if lines[-1] != "":
            lines.append("")
        lines.append(f"**Source status:** {escape(status)} {source_status_emoji(status)}")
        lines.append(f"**Last updated:** {format_wib(message.updated_at)}")
        if include_board and message.board_url:
            lines.append(f"**Board:** <{message.board_url}>")
    elif include_board and message.board_url:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"**Board:** <{message.board_url}>")
    if message.source_url:
        label = _required_text(message.footer_label, "footer label")
        if lines[-1] != "":
            lines.append("")
        lines.append(f"[{escape(label)}](<{message.source_url}>)")
    return "\n".join(lines)


def discord_length(content: str) -> int:
    return len(content.encode("utf-16-le")) // 2


def split_content(content: str, limit: int = MAX_DISCORD_CHARACTERS) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("split limit must be positive")
    chunks: list[str] = []
    remaining = content
    while discord_length(remaining) > limit:
        units = 0
        boundary = 0
        for char in remaining:
            units += 2 if ord(char) > 0xFFFF else 1
            if units > limit:
                break
            boundary += 1
        whitespace = max(remaining.rfind(" ", 0, boundary), remaining.rfind("\n", 0, boundary))
        if whitespace > 0:
            boundary = whitespace + 1
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    chunks.append(remaining)
    return tuple(chunks)


def fields(*items: tuple[str, str]) -> tuple[SwingField, ...]:
    return tuple(SwingField(label, value) for label, value in items)


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()
