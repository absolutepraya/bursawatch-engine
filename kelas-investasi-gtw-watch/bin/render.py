from __future__ import annotations

from collections.abc import Mapping
import re


TELEGRAM_EMOJI = "<:telegram:1531657996432576618>"
KELAS_INVESTASI_EMOJI = "<:kelasinvestasi:1536570114772574218>"
MAX_DISCORD_CHARACTERS = 2_000
_MARKDOWN_CONTROL = re.compile(r"([\\`*_])")


def render_event(event: Mapping[str, object]) -> list[str]:
    """Render one validated GTW event without exposing source prose verbatim."""
    ticker = _text(event, "ticker")
    title = _escape(_text(event, "title"))
    summary = _render_summary(_text(event, "summary"))
    message_id = _header_message_id(event)
    plan = event.get("plan")
    plan_values = plan if isinstance(plan, Mapping) else {}
    plan_block = (
        "*Plan sumber*\n"
        f"- Buy area: {_escape(_plan_value(plan_values, 'buy_area'))}\n"
        f"- Target: {_escape(_plan_value(plan_values, 'targets'))}\n"
        f"- Stoploss: {_escape(_plan_value(plan_values, 'stoploss'))}\n\n"
        f"[View on Telegram](<https://t.me/kelasinvestasiid/{message_id}>)"
    )
    prefix = f"### {TELEGRAM_EMOJI} {title}\n-# {KELAS_INVESTASI_EMOJI} Kelas Investasi\n\n"
    return _split(prefix, summary, plan_block)


def _split(prefix: str, summary: str, plan_block: str) -> list[str]:
    complete = prefix + summary + "\n\n" + plan_block
    if len(complete) <= MAX_DISCORD_CHARACTERS:
        return [complete]

    # The entire source plan and deep link must remain together. The first
    # message keeps the visible header, later messages continue only summary.
    capacity = MAX_DISCORD_CHARACTERS - len(prefix)
    chunks = _chunks(summary, capacity)
    messages = [prefix + chunks[0]]
    for chunk in chunks[1:-1]:
        messages.append(chunk)
    final = chunks[-1] + "\n\n" + plan_block
    if len(final) > MAX_DISCORD_CHARACTERS:
        raise ValueError("summary leaves no safe Discord space for source plan")
    messages.append(final)
    return messages


def _chunks(value: str, capacity: int) -> list[str]:
    if capacity <= 0:
        raise ValueError("Discord header exceeds message limit")
    chunks: list[str] = []
    remaining = value
    while len(remaining) > capacity:
        boundary = remaining.rfind(" ", 0, capacity + 1)
        if boundary <= 0:
            boundary = capacity
        chunks.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    chunks.append(remaining)
    return chunks


def _render_summary(summary: str) -> str:
    prefix = "*(Ringkasan)* "
    if not summary.startswith(prefix):
        raise ValueError("summary must start with the Ringkasan prefix")
    return prefix + _escape(summary[len(prefix):])


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
    return _MARKDOWN_CONTROL.sub(r"\\\1", value)
