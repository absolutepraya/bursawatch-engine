"""Source-faithful, deterministic cards for the IDX Swing plan board."""

from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo

from models import Checkpoint, SourceEvent


WIB = ZoneInfo("Asia/Jakarta")
PHINTRACO_EMOJI = "<:phintraco:1531272488645038091>"
_MARKDOWN = re.compile(r"([\\*_~`|\[\]()>])")
_BYLINE = re.compile(r"^-#\s+(.+?)\s*$", re.MULTILINE)
_REASONS = re.compile(r"^\*\*Reasons:\*\*\s*(.+?)\s*$", re.MULTILINE)


def escape(value: str) -> str:
    """Escape source text when it becomes a board-owned Markdown field."""
    return _MARKDOWN.sub(r"\\\1", value)


def format_wib(value: datetime) -> str:
    """Render an aware timestamp in the board's fixed Indonesian time zone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(WIB).strftime("%-d %b %Y %H:%M WIB")


def analyst_byline(name: str | None, role: str | None) -> str:
    """Render only a source-provided analyst identity, or the firm fallback."""
    return f"-# {escape(name)}, {escape(role)}" if name and role else "-# Phintraco Sekuritas"


def render_source_only_card(title: str) -> str:
    return f"### {escape(title)}\n\n**Primary plan:** No Phintraco plan yet"


def render_primary_card(
    event: SourceEvent,
    checkpoint: Checkpoint | None = None,
    last_valid_checkpoint: Checkpoint | None = None,
) -> str:
    """Render the managed card without adding advice or a redundant source footer."""
    if event.kind != "buy" or event.plan is None:
        raise ValueError("primary cards require a complete buy event")

    name, role = _source_analyst(event)
    lines = [
        f"### {PHINTRACO_EMOJI} {escape(event.ticker)}: Buy",
        analyst_byline(name, role),
        "",
        f"**Entry:** {escape(event.plan.entry)}",
        f"**Stop-loss:** {escape(event.plan.stop_loss)}",
    ]
    for number, target in enumerate(event.plan.targets, start=1):
        lines.append(f"**Target {number}:** {escape(target)}")
    lines.append(f"**Signal date:** {format_wib(event.published_at)}")

    if reasons := _source_reasons(event.all_content):
        lines.extend(["", f"**Reasons:** {reasons}"])

    lines.append(f"**Source status:** {escape(event.source_status or 'New setup')}")
    if checkpoint is not None:
        if checkpoint.unavailable:
            lines.append("**Market checkpoint:** Market check unavailable")
            if last_valid_checkpoint is not None and not last_valid_checkpoint.unavailable:
                lines.extend(_checkpoint_facts(last_valid_checkpoint, include_state=False))
        else:
            lines.extend(_checkpoint_facts(checkpoint))

    lines.extend(["", f"[View in Telegram](<{event.source_url}>)"])
    return "\n".join(lines)


def render_history(when: str, detail: str) -> str:
    """Render one board-owned material-transition record as a fixed two-line quote."""
    if not when or not detail:
        raise ValueError("history requires a timestamp and detail")
    return f"> {when.replace(chr(10), ' ')}\n> {detail.replace(chr(10), ' ')}"


def _source_analyst(event: SourceEvent) -> tuple[str | None, str | None]:
    """Use only an analyst identity retained in source-rendered content."""
    match = _BYLINE.search(event.all_content)
    if match:
        byline = match.group(1)
        if "," in byline:
            name, role = (part.strip() for part in byline.split(",", 1))
            if name and role:
                return name, role
        if byline == "Phintraco Sekuritas":
            return None, None
    return None, None


def _source_reasons(content: str) -> str | None:
    match = _REASONS.search(content)
    return escape(match.group(1)) if match else None


def _checkpoint_facts(checkpoint: Checkpoint, *, include_state: bool = True) -> list[str]:
    """Render a validated market checkpoint's price and observed instant."""
    if checkpoint.unavailable or checkpoint.state is None or checkpoint.close_price is None:
        raise ValueError("market facts require a valid checkpoint")
    facts = [
        f"**Closing price:** Rp{escape(checkpoint.close_price)}",
        f"**Last checked:** {format_wib(datetime.fromisoformat(checkpoint.checked_at))}",
    ]
    if include_state:
        facts.insert(0, f"**Market checkpoint:** {escape(checkpoint.state.value)}")
    return facts
