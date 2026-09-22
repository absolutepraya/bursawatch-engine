"""Future-ready BRI Danareksa adapter for the shared cash-Swing shell.

The WhatsApp watcher does not import this module yet. It defines the reviewed
normalized contract so a later live integration cannot invent a second format.
"""

from __future__ import annotations

from datetime import datetime

from swing_format import SwingMessage


BRI_DANAREKSA_EMOJI = "<:bridanareksa:1551797903927025797>"


def build_message(
    *,
    ticker: str,
    title: str,
    body: tuple[str, ...],
    source_status: str | None,
    published_at: datetime | None,
    source_url: str,
    analyst_name: str | None = None,
    chart_unavailable: bool = False,
) -> SwingMessage:
    """Build a BRI message without changing the live WhatsApp watcher."""
    return SwingMessage(
        source_emoji=BRI_DANAREKSA_EMOJI,
        title=f"{ticker}: {title}",
        analyst_name=analyst_name,
        institution="BRI Danareksa",
        body=body,
        source_status=source_status,
        updated_at=published_at,
        source_url=source_url,
        footer_label="View on WhatsApp",
        chart_unavailable=chart_unavailable,
    )
