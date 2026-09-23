from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from models import Feed, FeedLane


STOCKBIT_EMOJI = "<:stockbit:1552220036557578311>"
GREY_EMOJI = "<:grey:1531279158913536182>"
GREEN_EMOJI = "<:green:1531274822221434911>"
RED_EMOJI = "<:red:1531274756853202974>"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
ID_STOCKS_NEWS_CHANNEL_ID = "1525102508714889257"
MACRO_NEWS_CHANNEL_ID = "1531655369884045382"
WATCHER_NAME = "stockbit-snips"

FEEDS = (
    Feed(
        FeedLane.STOCKBIT_COMMENTARY,
        "Stockbit Commentary",
        "https://snips.stockbit.com/stockbit-research?format=rss",
    ),
    Feed(
        FeedLane.UNBOXING,
        "Unboxing",
        "https://snips.stockbit.com/unboxing?format=rss",
    ),
    Feed(
        FeedLane.UNBOXING_IPO,
        "Unboxing IPO",
        "https://snips.stockbit.com/unboxing-ipo?format=rss",
    ),
    Feed(
        FeedLane.AI_REPORTS,
        "AI Reports Stockbit",
        "https://snips.stockbit.com/ai-reports-stockbit?format=rss",
    ),
)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    state_path: Path
    no_post: bool
    request_timeout: float
    discord_token: str | None
    heartbeat_channel_id: str
    id_stocks_news_channel_id: str
    macro_news_channel_id: str


def runtime() -> RuntimeConfig:
    state_value = os.environ.get(
        "STOCKBIT_SNIPS_STATE_PATH",
        str(Path.home() / ".hermes" / "state" / "stockbit-snips.json"),
    )
    timeout_value = os.environ.get("STOCKBIT_SNIPS_REQUEST_TIMEOUT", "20")
    try:
        timeout = float(timeout_value)
    except ValueError as error:
        raise ValueError("STOCKBIT_SNIPS_REQUEST_TIMEOUT must be numeric") from error
    if timeout <= 0:
        raise ValueError("STOCKBIT_SNIPS_REQUEST_TIMEOUT must be positive")
    return RuntimeConfig(
        state_path=Path(state_value).expanduser(),
        no_post=os.environ.get("STOCKBIT_SNIPS_NO_POST") == "1",
        request_timeout=timeout,
        discord_token=os.environ.get("DISCORD_BOT_TOKEN"),
        heartbeat_channel_id=os.environ.get("STOCKBIT_SNIPS_HEARTBEAT_CHANNEL_ID", HEARTBEAT_CHANNEL_ID),
        id_stocks_news_channel_id=os.environ.get("STOCKBIT_SNIPS_ID_STOCKS_NEWS_CHANNEL_ID", ID_STOCKS_NEWS_CHANNEL_ID),
        macro_news_channel_id=os.environ.get("STOCKBIT_SNIPS_MACRO_NEWS_CHANNEL_ID", MACRO_NEWS_CHANNEL_ID),
    )
