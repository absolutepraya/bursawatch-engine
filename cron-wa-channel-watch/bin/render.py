from __future__ import annotations

import re
from zoneinfo import ZoneInfo

from classification import extract_source_status, is_technical_review
from models import ChannelEvent, ChannelProfile


DISCORD_LIMIT = 2_000
WIB = ZoneInfo("Asia/Jakarta")


def _split(value: str, limit: int) -> list[str]:
    value = value.strip()
    if not value:
        return []
    parts: list[str] = []
    while len(value) > limit:
        cut = max(value.rfind("\n\n", 0, limit + 1), value.rfind("\n", 0, limit + 1), value.rfind(" ", 0, limit + 1))
        cut = cut if cut > 0 else limit
        parts.append(value[:cut].rstrip())
        value = value[cut:].lstrip()
    parts.append(value)
    return parts


def _safe_name(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


def _has_source_chart(event: ChannelEvent) -> bool:
    # Media paths are transient, untrusted bridge metadata. Delivery validates
    # an archive-owned copy before it ever posts a technical chart.
    return any(media.kind == "image" for media in event.media)


def _source_footer(profile: ChannelProfile, event: ChannelEvent, *, route: str | None = None) -> str:
    status = extract_source_status(event.text)
    technical = is_technical_review(event.text)
    swing_technical = route == "id_stocks_swing" and technical
    if (status is None or not swing_technical) and not technical:
        return f"[View on WhatsApp Channel](<{profile.channel_url}>)"

    lines: list[str] = []
    if status is not None and swing_technical:
        emoji = profile.status_emojis.for_kind(status.kind) or ""
        lines.append(f"Status: {status.label}{emoji}")
        local = event.published_at.astimezone(WIB)
        lines.append(f"Status date: {local:%a, %b} {local.day} {local.year}, {local:%H:%M} WIB")
    lines.append(f"Source: [{_safe_name(profile.display_name)}](<{profile.channel_url}>)")
    if technical:
        chart = "Attached below" if _has_source_chart(event) else "Unavailable from source"
        lines.append(f"Chart: {chart}")
    return "\n".join(lines)


def render_post(
    profile: ChannelProfile,
    event: ChannelEvent,
    *,
    title: str | None = None,
    summary: str | None = None,
    route: str | None = None,
) -> list[str]:
    heading = f"### {profile.emoji} {_safe_name(title or profile.display_name)}"
    body = (summary or event.text or "*(Media tanpa caption)*").strip()
    source = _source_footer(profile, event, route=route)
    return _split(f"{heading}\n\n{body}\n\n{source}", DISCORD_LIMIT)
