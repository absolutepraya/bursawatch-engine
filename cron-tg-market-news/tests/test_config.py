from __future__ import annotations

from types import SimpleNamespace

import pytest

import config


def payload() -> dict[str, object]:
    return {
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
        "additional_prompt_instruction": "",
    }


def test_default_config_matches_established_provider_and_delivery_routes(monkeypatch):
    monkeypatch.delenv("IDX_MARKET_NEWS_CONTROL_PLANE_URL", raising=False)

    loaded = config.load_watch_config_for_run()

    assert loaded.revision is None
    assert loaded.config.phintraco_username == "phintasprofits"
    assert loaded.config.tuntun_username == "tuntunsekuritas"
    assert loaded.config.id_stocks_news_channel_id == "1525102508714889257"
    assert loaded.config.macro_news_channel_id == "1531655369884045382"
    assert loaded.config.industry_news_channel_id == "1549418098807930880"
    assert loaded.config.heartbeat_channel_id == "1505162000420835388"
    assert loaded.config.additional_prompt_instruction == ""


def test_config_rejects_unknown_fields_colliding_routes_and_unbounded_prompt():
    invalid = payload()
    invalid["unknown"] = True
    with pytest.raises(ValueError, match="unsupported"):
        config.load_watch_config_data(invalid)

    invalid = payload()
    invalid["destinations"] = {
        "id_stocks_news_discord_channel_id": "1525102508714889257",
        "macro_news_discord_channel_id": "1525102508714889257",
        "industry_news_discord_channel_id": "1549418098807930880",
        "heartbeat_discord_channel_id": "1505162000420835388",
    }
    with pytest.raises(ValueError, match="must differ"):
        config.load_watch_config_data(invalid)

    invalid = payload()
    invalid["additional_prompt_instruction"] = "x" * 801
    with pytest.raises(ValueError, match="800"):
        config.load_watch_config_data(invalid)


def test_live_mode_uses_one_validated_frozen_snapshot(monkeypatch):
    live_payload = payload()
    live_payload["providers"] = {
        "phintraco": {"telegram_username": "phintracocp"},
        "tuntun": {"telegram_username": "tuntuncontrol"},
    }
    live_payload["destinations"] = {
        "id_stocks_news_discord_channel_id": "1525102508714889258",
        "macro_news_discord_channel_id": "1531655369884045383",
        "industry_news_discord_channel_id": "1549418098807930881",
        "heartbeat_discord_channel_id": "1505162000420835389",
    }
    live_payload["additional_prompt_instruction"] = "Utamakan ringkasan yang padat."
    monkeypatch.setenv("IDX_MARKET_NEWS_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setattr(
        config,
        "_fetch_live_config",
        lambda: SimpleNamespace(
            watcher_id="bursawatch-tg-market-news",
            revision=11,
            config=live_payload,
        ),
    )

    loaded = config.load_watch_config_for_run()

    assert loaded.revision == 11
    assert loaded.config.phintraco_username == "phintracocp"
    assert loaded.config.heartbeat_channel_id == "1505162000420835389"
    assert loaded.config.additional_prompt_instruction == "Utamakan ringkasan yang padat."
    with config.activate_watch_config(loaded.config):
        assert config.active_watch_config() == loaded.config
    assert config.active_watch_config() == config.default_watch_config()
