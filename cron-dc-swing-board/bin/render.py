"""Source-faithful, deterministic cards for the IDX Swing plan board."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from models import Checkpoint, SourceEvent

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "lib-swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "lib-swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from swing_format import (  # noqa: E402
    canonicalize_phintraco_message,
    source_status_emoji,
    space_inline_custom_emojis,
)


WIB = ZoneInfo("Asia/Jakarta")
PHINTRACO_EMOJI = "<:phintraco:1531272488645038091>"
_MARKDOWN = re.compile(r"([\\*_~`|\[\]()])")
_BYLINE = re.compile(r"^-#\s+(.+?)\s*$", re.MULTILINE)
_REASONS = re.compile(r"^\*\*Reasons:\*\*\s*(.+?)\s*$", re.MULTILINE)
_TYPE = re.compile(r"^\*\*Type:\*\*\s*(.+?)\s*$", re.MULTILINE)
_BOARD_FIELD = re.compile(
    r"^\*\*Board:\*\*\s+(?:<#[0-9]+>|<?https://discord\.com/channels/[0-9]+/[0-9]+(?:/[0-9]+)?>?)\s*$\n?",
    re.MULTILINE,
)
MAX_DISCORD_CHARACTERS = 2_000
STATIC_CARD_BUDGET = 1_400


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


def render_source_only_card(title: str, source_url: str | None = None) -> str:
    content = f"### {escape(title)}\n\n**Primary plan:** No Phintraco plan yet"
    return content + (f"\n\n[View source](<{source_url}>)" if source_url else "")


def render_source_reply(event: SourceEvent) -> str:
    """Keep the watcher's All text and source link; media has its own intents."""
    all_content = _BOARD_FIELD.sub("", event.all_content)
    if event.source.casefold() == "phintraco":
        try:
            return canonicalize_phintraco_message(
                all_content,
                source_url=event.source_url,
                published_at=event.published_at,
                source_status=event.source_status,
                include_board=False,
                has_chart=bool(event.media_path),
            )
        except ValueError:
            # Source text that is not the known Phintraco Swing shell, or that
            # cannot fit after adding the canonical fields, remains lossless
            # and is split by render_source_replies below.
            pass
    if event.source.casefold() == "phintraco":
        footer = f"[View in Telegram](<{event.source_url}>)"
        content = all_content.rstrip()
        if content.endswith(footer):
            prefix = content[:-len(footer)].rstrip()
            return f"{prefix}\n\n{footer}"
        if event.source_url not in content:
            return f"{content}\n\n{footer}"
        return content
    urls = (event.source_url,)
    missing = [url for url in urls if url not in all_content]
    return all_content + ("\n\n" + "\n".join(missing) if missing else "")


def render_source_replies(event: SourceEvent) -> tuple[str, ...]:
    """Split every source adapter's content losslessly in Discord-sized order."""
    return split_content(render_source_reply(event))


def discord_length(content: str) -> int:
    return len(content.encode("utf-16-le")) // 2


def split_content(content: str, limit: int = MAX_DISCORD_CHARACTERS) -> tuple[str, ...]:
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


def render_primary_card(
    event: SourceEvent,
    checkpoint: Checkpoint | None = None,
    last_valid_checkpoint: Checkpoint | None = None,
    source_updated_at: datetime | None = None,
) -> str:
    """Render the managed card without adding advice or a redundant source footer."""
    if event.kind != "buy" or event.plan is None:
        raise ValueError("primary cards require a complete buy event")

    static, _ = _primary_static(event)
    source_status = event.source_status or "New setup"
    updated_at = source_updated_at or event.published_at
    lines = [
        static,
        "",
        f"**Source status:** {_excerpt(escape(source_status), 220)} {source_status_emoji(source_status)}",
        f"**Last updated:** {format_wib(updated_at)}",
    ]
    if checkpoint is not None:
        lines.append("")
        if checkpoint.unavailable:
            lines.append("**Market checkpoint:** Market check unavailable")
            if last_valid_checkpoint is not None and not last_valid_checkpoint.unavailable:
                lines.extend(_checkpoint_facts(last_valid_checkpoint, include_state=False))
        else:
            lines.extend(_checkpoint_facts(checkpoint))
    footer = f"[View in Telegram](<{event.source_url}>)"
    lines.extend(["", footer if discord_length(footer) <= 200 else "Full source link in the source reply below"])
    return _excerpt("\n".join(lines), MAX_DISCORD_CHARACTERS)


def primary_card_requires_source_reply(event: SourceEvent) -> bool:
    return _primary_static(event)[1] or discord_length(event.source_url) > 170


def _primary_static(event: SourceEvent) -> tuple[str, bool]:
    # These segments already carry the watcher's transport escaping.
    analyst_name, _ = _source_analyst(event)
    lines = [
        f"### {PHINTRACO_EMOJI} {escape(event.ticker)}: Buy",
        analyst_byline(analyst_name, "Phintraco Sekuritas"),
        "",
    ]
    if source_type := _TYPE.search(event.all_content):
        lines.append(f"**Type:** {escape(space_inline_custom_emojis(source_type.group(1)))}")
    lines.extend([f"**Entry:** {escape(event.plan.entry)}", f"**Stop-loss:** {escape(event.plan.stop_loss)}"])
    targets_start = len(lines)
    for number, target in enumerate(event.plan.targets, start=1):
        lines.append(f"**Target {number}:** {escape(target)}")
    lines.append(f"**Signal date:** {format_wib(event.published_at)}")
    chart = next((line for line in event.all_content.splitlines() if line.startswith("**Chart:**")), None)
    if chart:
        lines.append(chart)

    reasons = _source_reasons(event.all_content)
    complete = "\n".join(lines + (["", f"**Reasons:** {reasons}"] if reasons else []))
    if discord_length(complete) <= STATIC_CARD_BUDGET:
        return complete, False
    core = "\n".join(lines)
    if discord_length(core) > STATIC_CARD_BUDGET - 70:
        compact_targets = "; ".join(f"{number}: {escape(target)}" for number, target in enumerate(event.plan.targets, start=1))
        compact_lines = lines[:targets_start] + [f"**Targets:** {compact_targets}"] + lines[targets_start + len(event.plan.targets):]
        core = "\n".join(compact_lines)
    if discord_length(core) > STATIC_CARD_BUDGET - 70:
        # Extreme source fields stay complete in ordered source replies.
        core = _excerpt(core, STATIC_CARD_BUDGET - 70)
    remaining = STATIC_CARD_BUDGET - discord_length(core) - 15
    return core + ("\n\n**Reasons:** " + _excerpt(reasons, remaining) if reasons else ""), True


def _excerpt(content: str, limit: int) -> str:
    if discord_length(content) <= limit:
        return content
    suffix = "… (full source below)"
    return split_content(content, max(2, limit - discord_length(suffix)))[0].rstrip("\\ \n") + suffix


def render_history(when: str, detail: str) -> str:
    """Render one board-owned material-transition record as a quoted reply."""
    return render_history_replies(when, detail)[0]


def render_history_replies(when: str, detail: str) -> tuple[str, ...]:
    """Render a history record as ordered, Discord-sized quoted replies.

    The timestamp stays on the first reply, while every continuation remains a
    quote.  Splitting the detail instead of truncating it keeps source status
    transitions and close facts lossless while allowing each outbox operation
    to retry independently.
    """
    if not when or not detail:
        raise ValueError("history requires a timestamp and detail")
    normalized_when = when.replace(chr(10), " ")
    normalized_detail = detail.replace(chr(10), " ")
    first_prefix = f"> {normalized_when}\n> "
    continuation_prefix = "> "
    first_budget = MAX_DISCORD_CHARACTERS - discord_length(first_prefix)
    if first_budget < 1:
        raise ValueError("history timestamp exceeds Discord message limit")
    chunks = split_content(normalized_detail, first_budget)
    replies = [first_prefix + chunks[0]]
    replies.extend(continuation_prefix + chunk for chunk in chunks[1:])
    if any(discord_length(reply) > MAX_DISCORD_CHARACTERS for reply in replies):
        raise ValueError("history reply exceeds Discord message limit")
    return tuple(replies)


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
    for line in event.all_content.splitlines():
        source_match = re.search(
            r"\|\s*([^,\n|]+),\s*(?:Investment Advisor|Phintraco Sekuritas)\s*$",
            line,
            re.IGNORECASE,
        )
        if source_match:
            return source_match.group(1).strip(), "Investment Advisor"
    return None, None


def _source_reasons(content: str) -> str | None:
    match = _REASONS.search(content)
    return match.group(1) if match else None


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
