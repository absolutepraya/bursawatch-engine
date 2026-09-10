from __future__ import annotations

import re

from models import ChannelEvent, ChannelProfile


DISCORD_LIMIT = 2_000


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


def render_post(profile: ChannelProfile, event: ChannelEvent, *, title: str | None = None, summary: str | None = None) -> list[str]:
    heading = f"### 📣 {_safe_name(title or profile.display_name)}\n-# {_safe_name(profile.display_name)}"
    body = (summary or event.text or "*(Media tanpa caption)*").strip()
    source = f"[View on WhatsApp Channel](<{profile.channel_url}>)"
    return _split(f"{heading}\n\n{body}\n\n{source}", DISCORD_LIMIT)
