from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from swing_format import BOARD_MENTION, MAX_DISCORD_CHARACTERS, SwingMessage, escape, render_chunks


TELEGRAM_EMOJI = "<:telegram:1531657996432576618>"
KELAS_INVESTASI_EMOJI = "<:kelasinvestasi:1536570114772574218>"
GTW_SOURCE_STATUS = "Good to watch"


def render_event(event: Mapping[str, object], *, include_board: bool = True) -> list[str]:
    """Render one validated GTW bundle through the shared Swing shell."""
    ticker = _text(event, "ticker")
    title = _text(event, "title")
    summary = _render_summary(_text(event, "summary"))
    message_id = _header_message_id(event)
    source_time = _source_time(event)
    plan = event.get("plan")
    plan_values = plan if isinstance(plan, Mapping) else {}
    plan_lines = (
        f"**Buy area:** {escape(_plan_value(plan_values, 'buy_area'))}",
        f"**Target:** {escape(_plan_value(plan_values, 'targets'))}",
        f"**Stoploss:** {escape(_plan_value(plan_values, 'stoploss'))}",
    )
    body = (summary, "", *plan_lines)
    message = SwingMessage(
        source_emoji=KELAS_INVESTASI_EMOJI,
        title=title,
        analyst_name=None,
        institution="Kelas Investasi GTW",
        body=body,
        source_status=GTW_SOURCE_STATUS if source_time is not None else None,
        updated_at=source_time,
        source_url=f"https://t.me/kelasinvestasiid/{message_id}",
        footer_label="View on Telegram",
        board_url=BOARD_MENTION if source_time is not None else None,
        chart_unavailable=not _has_media(event),
    )
    return list(render_chunks(message, include_board=include_board))


def _render_summary(summary: str) -> str:
    prefix = "*(Ringkasan)* "
    if not summary.startswith(prefix):
        raise ValueError("summary must start with the Ringkasan prefix")
    return prefix + escape(summary[len(prefix):])


def _source_time(event: Mapping[str, object]) -> datetime | None:
    value = event.get("source_published_at")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("source_published_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("source_published_at must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("source_published_at must include a timezone")
    return parsed


def _has_media(event: Mapping[str, object]) -> bool:
    media = event.get("media")
    return isinstance(media, list) and any(isinstance(item, Mapping) for item in media)


def _header_message_id(event: Mapping[str, object]) -> int:
    value = event.get("header_message_id")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("header_message_id must be a positive integer")
    return value


def _text(event: Mapping[str, object], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value.strip()


def _plan_value(plan: Mapping[object, object], field: str) -> str:
    value = plan.get(field, "-")
    return value.strip() if isinstance(value, str) and value.strip() else "-"


def _escape(value: str) -> str:
    """Compatibility helper for callers that used the old module privately."""
    return escape(value)


def _split(prefix: str, summary: str, plan_block: str) -> list[str]:
    """Compatibility splitter retained for existing tests and adapters."""
    complete = prefix + summary + "\n\n" + plan_block
    if len(complete) <= MAX_DISCORD_CHARACTERS:
        return [complete]
    chunks: list[str] = []
    remaining = complete
    while len(remaining) > MAX_DISCORD_CHARACTERS:
        boundary = remaining.rfind(" ", 0, MAX_DISCORD_CHARACTERS)
        if boundary <= 0:
            boundary = MAX_DISCORD_CHARACTERS
        chunks.append(remaining[:boundary + (1 if boundary < len(remaining) and remaining[boundary] == " " else 0)])
        remaining = remaining[boundary + (1 if boundary < len(remaining) and remaining[boundary] == " " else 0):]
    chunks.append(remaining)
    return chunks
