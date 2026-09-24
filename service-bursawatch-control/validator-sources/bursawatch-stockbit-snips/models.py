from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re


class Route(StrEnum):
    ID_STOCKS_NEWS = "id_stocks_news"
    MACRO_NEWS = "macro_news"
    EXCLUDE = "exclude"


class FeedLane(StrEnum):
    STOCKBIT_COMMENTARY = "stockbit_commentary"
    UNBOXING = "unboxing"
    UNBOXING_IPO = "unboxing_ipo"
    AI_REPORTS = "ai_reports_stockbit"


@dataclass(frozen=True, slots=True)
class Feed:
    lane: FeedLane
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class StockbitFeedSetting:
    lane: FeedLane
    enabled: bool


@dataclass(frozen=True, slots=True)
class StockbitWatchConfig:
    feeds: tuple[StockbitFeedSetting, ...]
    id_stocks_news_channel_id: str
    macro_news_channel_id: str
    additional_prompt_instruction: str


@dataclass(frozen=True, slots=True)
class Article:
    lane: FeedLane
    lane_label: str
    guid: str
    url: str
    source_title: str
    source_text: str
    published_at: datetime
    media_url: str | None = None

    @property
    def key(self) -> str:
        safe_guid = re.sub(r"[^A-Za-z0-9._:-]+", "_", self.guid).strip("_")
        return f"stockbit:{self.lane.value}:{safe_guid or 'article'}"

    def to_payload(self) -> dict[str, object]:
        return {
            "lane": self.lane.value,
            "lane_label": self.lane_label,
            "guid": self.guid,
            "url": self.url,
            "source_title": self.source_title,
            "source_text": self.source_text,
            "published_at": self.published_at.isoformat(),
            "media_url": self.media_url,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "Article":
        if not isinstance(payload, dict):
            raise ValueError("article payload must be an object")
        try:
            article = cls(
                lane=FeedLane(payload["lane"]),
                lane_label=payload["lane_label"],
                guid=payload["guid"],
                url=payload["url"],
                source_title=payload["source_title"],
                source_text=payload["source_text"],
                published_at=datetime.fromisoformat(payload["published_at"]),
                media_url=payload.get("media_url"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("article payload is invalid") from error
        if article.published_at.tzinfo is None or article.published_at.utcoffset() is None:
            raise ValueError("article published_at must be timezone-aware")
        if not all(isinstance(value, str) and value.strip() for value in (article.guid, article.url, article.source_title, article.source_text)):
            raise ValueError("article text fields must be nonempty")
        return article


@dataclass(frozen=True, slots=True)
class Analysis:
    candidate_key: str
    ticker: str
    title: str
    summary: str
    material_facts: tuple[str, ...]
    dedupe_facts: tuple[str, ...]
    eligible: bool
    route: Route
    source_evidence: str
