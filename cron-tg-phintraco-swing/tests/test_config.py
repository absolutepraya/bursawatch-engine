from __future__ import annotations

from types import SimpleNamespace

import pytest

import config


def payload() -> dict[str, object]:
    return {
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


def test_default_config_matches_the_established_source_and_destinations(monkeypatch):
    monkeypatch.delenv("IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL", raising=False)

    loaded = config.load_watch_config_for_run()

    assert loaded.revision is None
    assert loaded.config.telegram_channel_id == 1444713822
    assert loaded.config.telegram_username == "phintraprofits"
    assert loaded.config.alert_discord_channel_id == "1525102458253217803"
    assert loaded.config.heartbeat_discord_channel_id == "1505162000420835388"


def test_config_rejects_unknown_fields_and_duplicate_destinations():
    invalid = payload()
    invalid["unknown"] = True
    with pytest.raises(ValueError, match="only"):
        config.load_watch_config_data(invalid)

    invalid = payload()
    invalid["destinations"] = {
        "alert_discord_channel_id": "1525102458253217803",
        "heartbeat_discord_channel_id": "1525102458253217803",
    }
    with pytest.raises(ValueError, match="must differ"):
        config.load_watch_config_data(invalid)


def test_live_mode_uses_one_validated_frozen_snapshot(monkeypatch):
    live_payload = payload()
    live_payload["source"] = {
        "telegram_channel_id": 1444713999,
        "telegram_username": "phintraconew",
    }
    monkeypatch.setenv("IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setattr(
        config,
        "_fetch_live_config",
        lambda: SimpleNamespace(
            watcher_id="bursawatch-tg-phintraco-swing",
            revision=7,
            config=live_payload,
        ),
    )

    loaded = config.load_watch_config_for_run()

    assert loaded.revision == 7
    assert loaded.config.telegram_channel_id == 1444713999
    with config.activate_watch_config(loaded.config):
        assert config.active_watch_config() == loaded.config
    assert config.active_watch_config() == config.default_watch_config()
