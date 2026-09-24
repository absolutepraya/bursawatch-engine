from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_plane.validators import ConfigValidationError, validators_from_directories


ROOT = Path(__file__).resolve().parents[2]
X_WATCHER = "bursawatch-x-account-watch"
IG_WATCHER = "bursawatch-ig-account-watch"
WA_WATCHER = "bursawatch-wa-channel-watch"
MARKET_NEWS_WATCHER = "bursawatch-tg-market-news"
SWING_BOARD_WATCHER = "bursawatch-dc-swing-board"
PHINTRACO_WATCHER = "bursawatch-tg-phintraco-swing"
KELAS_INVESTASI_WATCHER = "bursawatch-tg-kelas-investasi-gtw"
STOCKBIT_WATCHER = "bursawatch-stockbit-snips"


@pytest.mark.parametrize(
    ("watcher_id", "directory", "config_file"),
    [
        (X_WATCHER, "cron-x-account-watch/bin", "cron-x-account-watch/config/watches.json"),
        (IG_WATCHER, "cron-ig-account-watch/bin", "cron-ig-account-watch/config/watches.json"),
        (WA_WATCHER, "cron-wa-channel-watch/bin", "cron-wa-channel-watch/config/watches.json"),
    ],
)
def test_validator_reuses_the_watchers_strict_config_schema(watcher_id, directory, config_file):
    validators = validators_from_directories({watcher_id: ROOT / directory})
    config = json.loads((ROOT / config_file).read_text(encoding="utf-8"))

    validators[watcher_id](config)


def test_validator_rejects_invalid_config_without_exposing_process_details():
    validators = validators_from_directories({X_WATCHER: ROOT / "cron-x-account-watch/bin"})

    with pytest.raises(ConfigValidationError, match="watch configuration"):
        validators[X_WATCHER]({"version": 1, "profiles": []})


def test_validator_reuses_the_phintraco_strict_config_schema():
    validators = validators_from_directories(
        {PHINTRACO_WATCHER: ROOT / "cron-tg-phintraco-swing/bin"}
    )
    validators[PHINTRACO_WATCHER](
        {
            "version": 1,
            "source": {
                "telegram_channel_id": 1444713822,
                "telegram_username": "phintraprofits",
            },
            "destinations": {
                "alert_discord_channel_id": "1525102458253217803",
                "heartbeat_discord_channel_id": "1505162000420835388",
            },
        }
    )


def test_validator_reuses_the_kelas_investasi_strict_config_schema():
    validators = validators_from_directories(
        {KELAS_INVESTASI_WATCHER: ROOT / "cron-tg-kelas-investasi-gtw/bin"}
    )
    validators[KELAS_INVESTASI_WATCHER](
        {
            "version": 1,
            "source": {
                "telegram_channel_id": 2142109618,
                "telegram_username": "kelasinvestasiid",
            },
            "destinations": {
                "alert_discord_channel_id": "1525102458253217803",
                "heartbeat_discord_channel_id": "1505162000420835388",
            },
            "additional_prompt_instruction": "Utamakan ringkasan tesis yang sangat ringkas.",
        }
    )


def test_validator_reuses_the_market_news_strict_config_schema():
    validators = validators_from_directories(
        {MARKET_NEWS_WATCHER: ROOT / "cron-tg-market-news/bin"}
    )
    validators[MARKET_NEWS_WATCHER](
        {
            "version": 1,
            "providers": {
                "phintraco": {"telegram_username": "phintasprofits"},
                "tuntun": {"telegram_username": "tuntunsekuritas"},
            },
            "destinations": {
                "id_stocks_news_discord_channel_id": "1525102508714889257",
                "macro_news_discord_channel_id": "1531655369884045382",
                "industry_news_discord_channel_id": "1549418098807930880",
                "heartbeat_discord_channel_id": "1505162000420835388",
            },
            "additional_prompt_instruction": "Utamakan ringkasan yang padat.",
        }
    )


def test_validator_reuses_the_swing_board_strict_config_schema():
    validators = validators_from_directories(
        {SWING_BOARD_WATCHER: ROOT / "cron-dc-swing-board/bin"}
    )

    validators[SWING_BOARD_WATCHER](
        {
            "version": 1,
            "destinations": {
                "heartbeat_discord_channel_id": "1505162000420835388",
            },
        }
    )


def test_validator_reuses_the_stockbit_strict_config_schema():
    validators = validators_from_directories(
        {STOCKBIT_WATCHER: ROOT / "service-bursawatch-control/validator-sources" / STOCKBIT_WATCHER}
    )
    baseline = json.loads(
        (ROOT / "service-bursawatch-control/baseline-configs" / f"{STOCKBIT_WATCHER}.json").read_text(
            encoding="utf-8"
        )
    )

    validators[STOCKBIT_WATCHER](baseline)
    baseline["feeds"][0]["enabled"] = "false"
    with pytest.raises(ConfigValidationError, match="must be boolean"):
        validators[STOCKBIT_WATCHER](baseline)


def test_validator_rejects_an_unregistered_watcher():
    with pytest.raises(ValueError, match="no config validator is defined"):
        validators_from_directories({"bursawatch-unknown": ROOT})
