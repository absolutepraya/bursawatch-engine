from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_plane.validators import ConfigValidationError, validators_from_directories


ROOT = Path(__file__).resolve().parents[2]
X_WATCHER = "bursawatch-x-account-watch"
IG_WATCHER = "bursawatch-ig-account-watch"
WA_WATCHER = "bursawatch-wa-channel-watch"
PHINTRACO_WATCHER = "bursawatch-tg-phintraco-swing"


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


def test_validator_rejects_an_unregistered_watcher():
    with pytest.raises(ValueError, match="no config validator is defined"):
        validators_from_directories({"bursawatch-unknown": ROOT})
