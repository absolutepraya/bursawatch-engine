from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GtwHeader:
    ticker: str


@dataclass(frozen=True, slots=True)
class SourceMedia:
    message_id: int
    ordinal: int


@dataclass(frozen=True, slots=True)
class SourceMessage:
    message_id: int
    posted_at: datetime
    text: str
    reply_to_message_id: int | None
    media: tuple[SourceMedia, ...]


@dataclass(frozen=True, slots=True)
class PlanSource:
    buy_area: str
    targets: str
    stoploss: str
