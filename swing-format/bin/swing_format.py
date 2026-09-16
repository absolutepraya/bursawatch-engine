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
_CUSTOM_EMOJI = re.compile(r"<:[A-Za-z0-9_]+:\d+>")
_FIELD = re.compile(r"^\*\*(?P<label>[^*]+):\*\*\s*(?P<value>.*)$")
_HEADER = re.compile(
    r"^###\s+(?P<emoji><:[^>]+>)\s+"
    r"(?:(?P<legacy_action>BUY|HOLD|REMINDER)\s*:\s*\*\*(?P<legacy_ticker>[A-Z][A-Z0-9]{1,9})\*\*|"
    r"(?P<ticker>[A-Z][A-Z0-9]{1,9})\s*:\s*(?P<action>Buy|Hold|Reminder))\s*$",
    re.IGNORECASE,
)
_SOURCE_URL = re.compile(r"https?://t\.me/[^\s>)]+", re.IGNORECASE)
_ANALYST = re.compile(
    r"(?:\|\s*|-#\s+)(?P<name>[^,\n|]+),\s*(?:Investment Advisor|Phintraco Sekuritas)\s*$",
    re.IGNORECASE,
)
_WIB_DATE_DAY_MONTH = re.compile(
    r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-z]{3})\s+(?P<year>\d{4})(?:,)?\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+WIB$",
    re.IGNORECASE,
)
_WIB_DATE_MONTH_DAY = re.compile(
    r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(?P<month>[A-Za-z]{3})\s+"
    r"(?P<day>\d{1,2})\s+(?P<year>\d{4})(?:,)?\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+WIB$",
    re.IGNORECASE,
)
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


def space_inline_custom_emojis(value: str) -> str:
    """Keep inline custom emoji markers visually separated from preceding text."""
    return re.sub(r"(?<=\S)(?=<:[A-Za-z0-9_]+:\d+>)", " ", str(value))


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
        lines.append(f"**{escape(label)}:** {escape(space_inline_custom_emojis(field.value))}")
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
        lines.append(f"**{escape(label)}:** {escape(space_inline_custom_emojis(field.value))}")
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


def canonicalize_phintraco_message(
    content: str,
    *,
    source_url: str | None = None,
    published_at: datetime | None = None,
    source_status: str | None = None,
    include_board: bool = False,
    has_chart: bool = False,
) -> str:
    """Rewrite a legacy Phintraco message through the shared Swing shell.

    The migration is intentionally source-faithful: values are read from the
    already-published message, while the title, byline, factual status, dates,
    footer, and spacing are normalized to the current contract.
    """
    raw = str(content or "").strip()
    header = _HEADER.match(raw.splitlines()[0] if raw else "")
    if header is None:
        raise ValueError("legacy Phintraco message header is invalid")
    ticker = (header.group("legacy_ticker") or header.group("ticker") or "").upper()
    action = (header.group("legacy_action") or header.group("action") or "").casefold()
    kind = {"buy": "buy", "hold": "status", "reminder": "reminder"}.get(action)
    if kind is None:
        raise ValueError("legacy Phintraco message action is invalid")

    parsed: dict[str, str] = {}
    analyst_name: str | None = None
    found_url: str | None = None
    for line in raw.splitlines():
        match = _FIELD.match(line.strip())
        if match:
            parsed[match.group("label").strip().casefold()] = match.group("value").strip()
        if found_url is None:
            url_match = _SOURCE_URL.search(line)
            if url_match:
                found_url = url_match.group(0).rstrip(".,")
        analyst_match = _ANALYST.search(line.strip())
        if analyst_match:
            analyst_name = analyst_match.group("name").strip()

    url = source_url or found_url
    if not url:
        raise ValueError("legacy Phintraco message source URL is missing")
    updated_at = _parse_wib_date(
        parsed.get("last updated")
        or parsed.get("signal date")
        or parsed.get("status date")
        or parsed.get("reminder date")
    ) or published_at
    if updated_at is None:
        raise ValueError("legacy Phintraco message timestamp is missing")

    status = source_status or parsed.get("source status")
    if not status:
        status = parsed.get("outcome") if kind == "reminder" else parsed.get("status")
    if not status:
        status = "New setup" if kind == "buy" else "Hold"
    status = _strip_inline_custom_emojis(status)

    labels: tuple[str, ...]
    if kind == "buy":
        labels = ("type", "entry", "stop-loss", "target", "signal date")
    elif kind == "status":
        labels = ("entry", "stop-loss", "target")
    else:
        labels = ("target",)
    message_fields: list[tuple[str, str]] = []
    for key, value in parsed.items():
        if key not in labels and not (key.startswith("target ") and "target" in labels):
            continue
        if key in {"status date", "reminder date", "source status", "status", "outcome"}:
            continue
        label = {
            "stop-loss": "Stop-loss",
            "signal date": "Signal date",
        }.get(key, key.title())
        normalized_value = (
            space_inline_custom_emojis(value)
            if key == "type"
            else format_wib(updated_at)
            if key == "signal date"
            else _strip_inline_custom_emojis(value)
        )
        message_fields.append((label, normalized_value))
    message_fields = _ordered_fields(message_fields)

    body: tuple[str, ...] = ()
    if reason := parsed.get("reasons"):
        body = ("", f"**Reasons:** {escape(reason)}")
    emoji = header.group("emoji")
    message = SwingMessage(
        source_emoji=emoji,
        title=f"{ticker}: {'Buy' if kind == 'buy' else 'Hold' if kind == 'status' else 'Reminder'}",
        analyst_name=analyst_name,
        institution="Phintraco Sekuritas",
        fields=fields(*message_fields),
        body=body,
        source_status=status,
        updated_at=updated_at,
        source_url=url,
        footer_label="View in Telegram",
        chart_unavailable=kind == "buy" and not has_chart,
        board_url=BOARD_URL if include_board else None,
    )
    return render_message_unbounded(message, include_board=include_board)


def _ordered_fields(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    order = {"Type": 0, "Entry": 1, "Stop-loss": 2, "Target": 3, "Signal Date": 99}
    return sorted(values, key=lambda item: (order.get(item[0], 3 if item[0].startswith("Target ") else 98), item[0]))


def _strip_inline_custom_emojis(value: str) -> str:
    return _CUSTOM_EMOJI.sub("", value).strip()


def _parse_wib_date(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = " ".join(value.replace(",", " ").split())
    match = _WIB_DATE_DAY_MONTH.match(normalized) or _WIB_DATE_MONTH_DAY.match(normalized)
    if not match:
        return None
    try:
        month = datetime.strptime(match.group("month"), "%b").month
        return datetime(
            int(match.group("year")), month, int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")), tzinfo=WIB,
        )
    except ValueError:
        return None


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()
