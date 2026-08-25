from __future__ import annotations

from datetime import datetime

from models import SourceMedia, SourceMessage


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def header(message_id: int, ticker: str, posted_at: str = "2026-08-11T09:00:00+07:00") -> SourceMessage:
    return SourceMessage(
        message_id=message_id,
        posted_at=at(posted_at),
        text=f"Good to watch - {ticker} #GTW",
        reply_to_message_id=None,
        media=(),
    )


def analysis(
    message_id: int,
    text: str = "Buy area: 605-630\nTP 1: 655\nStoploss: <573",
    posted_at: str = "2026-08-11T09:00:00+07:00",
    *,
    media: tuple[SourceMedia, ...] = (),
    parent: int | None = None,
) -> SourceMessage:
    return SourceMessage(
        message_id=message_id,
        posted_at=at(posted_at),
        text=text,
        reply_to_message_id=parent,
        media=media,
    )


def image(message_id: int, ordinal: int = 0) -> SourceMedia:
    return SourceMedia(message_id=message_id, ordinal=ordinal)



def reply(message_id: int, text: str, parent: int, posted_at: str = "2026-08-11T10:00:00+07:00") -> SourceMessage:
    return analysis(message_id, text, posted_at, parent=parent)
