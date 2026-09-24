from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from models import Feed, FeedLane, StockbitFeedSetting, StockbitWatchConfig


STOCKBIT_EMOJI = "<:stockbit:1552220036557578311>"
GREY_EMOJI = "<:grey:1531279158913536182>"
GREEN_EMOJI = "<:green:1531274822221434911>"
RED_EMOJI = "<:red:1531274756853202974>"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
ID_STOCKS_NEWS_CHANNEL_ID = "1525102508714889257"
MACRO_NEWS_CHANNEL_ID = "1531655369884045382"
WATCHER_NAME = "stockbit-snips"
WATCHER_ID = "bursawatch-stockbit-snips"

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
CONFIG_VERSION = 1
STOCKBIT_LANES = tuple(feed.lane for feed in FEEDS)
_DISCORD_ID_RE = re.compile(r"[0-9]{17,20}")


def _expect_object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def load_watch_config_data(raw: object) -> StockbitWatchConfig:
    root = _expect_object(raw, "watch configuration")
    if set(root) != {
        "version",
        "feeds",
        "destinations",
        "additional_prompt_instruction",
    }:
        raise ValueError("watch configuration has an invalid shape")
    if type(root["version"]) is not int or root["version"] != CONFIG_VERSION:
        raise ValueError("watch configuration version must be 1")
    if type(root["feeds"]) is not list or len(root["feeds"]) != len(STOCKBIT_LANES):
        raise ValueError("watch configuration must contain all four Stockbit lanes")
    parsed_feeds = []
    for row in root["feeds"]:
        if type(row) is not dict or set(row) != {"id", "enabled"}:
            raise ValueError("each Stockbit feed must contain only id and enabled")
        lane_id = row["id"]
        if type(lane_id) is not str or lane_id not in {lane.value for lane in STOCKBIT_LANES}:
            raise ValueError("Stockbit feed ID is unsupported")
        if type(row["enabled"]) is not bool:
            raise ValueError("Stockbit feed enabled must be boolean")
        parsed_feeds.append(StockbitFeedSetting(FeedLane(lane_id), row["enabled"]))
    if {feed.lane for feed in parsed_feeds} != set(STOCKBIT_LANES):
        raise ValueError("Stockbit feed IDs must be unique and complete")
    destinations = root["destinations"]
    expected_destinations = {
        "id_stocks_news_channel_id",
        "macro_news_channel_id",
    }
    if type(destinations) is not dict or set(destinations) != expected_destinations:
        raise ValueError("Stockbit destinations have an invalid shape")
    for key in expected_destinations:
        value = destinations[key]
        if type(value) is not str or _DISCORD_ID_RE.fullmatch(value) is None:
            raise ValueError(f"{key} must be a Discord snowflake")
    issuer_channel = destinations["id_stocks_news_channel_id"]
    macro_channel = destinations["macro_news_channel_id"]
    if issuer_channel == macro_channel:
        raise ValueError("Stockbit destinations must differ")
    instruction = root["additional_prompt_instruction"]
    if type(instruction) is not str:
        raise ValueError("additional_prompt_instruction must be text")
    instruction = " ".join(instruction.split())
    if len(instruction) > 800:
        raise ValueError("additional_prompt_instruction must be at most 800 characters")
    return StockbitWatchConfig(
        feeds=tuple(parsed_feeds),
        id_stocks_news_channel_id=issuer_channel,
        macro_news_channel_id=macro_channel,
        additional_prompt_instruction=instruction,
    )


@dataclass(frozen=True, slots=True)
class LoadedStockbitConfig:
    config: StockbitWatchConfig
    revision: int


def _fetch_live_config():
    from control_plane_client import fetch_config, live_config_settings

    settings = live_config_settings("STOCKBIT_SNIPS")
    if settings is None:
        raise ValueError("Stockbit control-plane URL is missing")
    base_url, watcher_id, token, timeout = settings
    if watcher_id != WATCHER_ID or not token:
        raise ValueError("Stockbit control-plane settings are invalid")
    return fetch_config(base_url, watcher_id, token, timeout=timeout)


def load_watch_config_for_run() -> LoadedStockbitConfig:
    """Fetch and validate one mandatory live configuration snapshot."""
    try:
        snapshot = _fetch_live_config()
        if snapshot.watcher_id != WATCHER_ID:
            raise ValueError("Stockbit control-plane returned the wrong watcher")
        if type(snapshot.revision) is not int or snapshot.revision < 1:
            raise ValueError("Stockbit control-plane revision is invalid")
        if type(snapshot.config_version) is not int or snapshot.config_version != CONFIG_VERSION:
            raise ValueError("Stockbit control-plane config version is invalid")
        parsed = load_watch_config_data(snapshot.config)
        return LoadedStockbitConfig(config=parsed, revision=snapshot.revision)
    except Exception:
        raise ValueError("Stockbit live configuration is unavailable or invalid") from None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    state_path: Path
    no_post: bool
    request_timeout: float
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
        heartbeat_channel_id=os.environ.get("STOCKBIT_SNIPS_HEARTBEAT_CHANNEL_ID", HEARTBEAT_CHANNEL_ID),
        id_stocks_news_channel_id=os.environ.get("STOCKBIT_SNIPS_ID_STOCKS_NEWS_CHANNEL_ID", ID_STOCKS_NEWS_CHANNEL_ID),
        macro_news_channel_id=os.environ.get("STOCKBIT_SNIPS_MACRO_NEWS_CHANNEL_ID", MACRO_NEWS_CHANNEL_ID),
    )
