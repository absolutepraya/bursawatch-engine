from __future__ import annotations

from pathlib import Path as _NewsPath
import sys as _news_sys
_news_bin = _NewsPath(__file__).resolve().parents[2] / "lib-news-format" / "bin"
if not _news_bin.is_dir():
    _news_bin = _NewsPath.home() / ".agents/skills/lib-news-format/bin"
if str(_news_bin) not in _news_sys.path:
    _news_sys.path.insert(0, str(_news_bin))
import news_format

import re
from zoneinfo import ZoneInfo

from classification import extract_source_status, is_technical_review
from models import ChannelEvent, ChannelProfile


DISCORD_LIMIT = 2_000
WIB = ZoneInfo("Asia/Jakarta")
BOARD_URL = "https://discord.com/channels/940285152335110204/1548273399069933720"
BOARD_MENTION = "<#1548273399069933720>"
SENTIMENT_KINDS = {"Bullish": "up", "Bearish": "down", "Sideways": "hold"}


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


def _format_wib(value) -> str:
    local = value.astimezone(WIB)
    return f"{local.day} {local:%b %Y %H:%M} WIB"


def _fallback_sentiment(event: ChannelEvent) -> str | None:
    """Support old leased records while new submissions carry sentiment."""
    status = extract_source_status(event.text)
    if status is None:
        return None
    return {"up": "Bullish", "down": "Bearish", "hold": "Sideways"}.get(status.kind)


def _swing_post(
    profile: ChannelProfile,
    event: ChannelEvent,
    *,
    title: str | None,
    reasons: str | None,
    sentiment: str | None,
    board_url: str | None,
) -> str:
    label = sentiment or _fallback_sentiment(event)
    if label not in SENTIMENT_KINDS:
        raise ValueError("BRI Swing rendering requires Bullish, Bearish, or Sideways sentiment")
    if board_url is not None and not board_url.startswith("https://discord.com/channels/"):
        raise ValueError("board_url must be a Discord channel or topic URL")
    clean_reasons = (reasons or event.text or "*(Tidak ada alasan dari sumber)*").strip()
    clean_reasons = re.sub(r"^\*\(Ringkasan\)\*\s*", "", clean_reasons).strip()
    label_prefix = r"^(?:\*\*Reasons:\*\*|Reasons:)\s*"
    while re.match(label_prefix, clean_reasons, flags=re.IGNORECASE):
        clean_reasons = re.sub(label_prefix, "", clean_reasons, count=1, flags=re.IGNORECASE).strip()
    clean_reasons = " ".join(clean_reasons.split())
    emoji = profile.status_emojis.for_kind(SENTIMENT_KINDS[label]) or ""
    heading = f"### {profile.emoji} {_safe_name(title or profile.display_name)}"
    board = board_url or BOARD_MENTION
    lines = [
        heading,
        f"-# {_safe_name(profile.display_name)}",
        "",
        f"**Sentiment:** {label} {emoji}".rstrip(),
        f"**Sentiment date:** {_format_wib(event.published_at)}",
        "",
        f"**Reasons:** {clean_reasons}",
        "",
        f"**Last updated:** {_format_wib(event.published_at)}",
        f"**Board:** {board}",
        "",
        f"[View on WhatsApp](<{profile.channel_url}>)",
    ]
    return "\n".join(lines)


def render_post(
    profile: ChannelProfile,
    event: ChannelEvent,
    *,
    title: str | None = None,
    summary: str | None = None,
    route: str | None = None,
    sentiment: str | None = None,
    board_url: str | None = None,
    source_chart_unavailable: bool = False,
) -> list[str]:
    if source_chart_unavailable and is_technical_review(event.text):
        heading = f"### {profile.emoji} {_safe_name(title or profile.display_name)}"
        return _split(
            f"{heading}\n\n{event.text.strip()}\n\nSource chart unavailable\n\n[View on WhatsApp Channel](<{profile.channel_url}>)",
            DISCORD_LIMIT,
        )
    if route == "id_stocks_swing" and is_technical_review(event.text):
        return _split(
            _swing_post(
                profile,
                event,
                title=title,
                reasons=summary,
                sentiment=sentiment,
                board_url=board_url,
            ),
            DISCORD_LIMIT,
        )
    heading = f"### {profile.emoji} {_safe_name(title or profile.display_name)}"
    body = (summary or event.text or "*(Media tanpa caption)*").strip()
    return _split(f"{heading}\n\n{body}\n\n[View on WhatsApp Channel](<{profile.channel_url}>)", DISCORD_LIMIT)


def freeze_news(profile, event, items):
    return news_format.validate_cards(news_format.freeze_cards(
        items, lambda item: f"### {profile.emoji} {_safe_name(item.get('title') or profile.display_name)}\n-# {_safe_name(profile.display_name)}", profile.channel_url, "WhatsApp Channel", target_for=lambda item: profile.channel_for(item["route"]).channel_id))
