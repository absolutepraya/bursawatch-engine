from __future__ import annotations

from types import SimpleNamespace

import pytest

import config


def payload() -> dict[str, object]:
    return {
        "version": 1,
        "source": {
            "telegram_channel_id": 2142109618,
            "telegram_username": "kelasinvestasiid",
        },
        "destinations": {
            "alert_discord_channel_id": "1525102458253217803",
            "heartbeat_discord_channel_id": "1505162000420835388",
        },
        "additional_prompt_instruction": "",
    }


def test_default_config_matches_the_established_source_destinations_and_empty_prompt(monkeypatch):
    monkeypatch.delenv("KELAS_INVESTASI_GTW_CONTROL_PLANE_URL", raising=False)

    loaded = config.load_watch_config_for_run()

    assert loaded.revision is None
    assert loaded.config.telegram_channel_id == 2142109618
    assert loaded.config.telegram_username == "kelasinvestasiid"
    assert loaded.config.alert_discord_channel_id == "1525102458253217803"
    assert loaded.config.heartbeat_discord_channel_id == "1505162000420835388"
    assert loaded.config.additional_prompt_instruction == ""


def test_config_rejects_unknown_fields_duplicate_destinations_and_an_unbounded_prompt():
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

    invalid = payload()
    invalid["additional_prompt_instruction"] = "x" * 801
    with pytest.raises(ValueError, match="800"):
        config.load_watch_config_data(invalid)


def test_live_mode_uses_one_validated_frozen_snapshot(monkeypatch):
    live_payload = payload()
    live_payload["source"] = {
        "telegram_channel_id": 2142109999,
        "telegram_username": "kelasinvestasibar",
    }
    live_payload["destinations"] = {
        "alert_discord_channel_id": "1525102458253217804",
        "heartbeat_discord_channel_id": "1505162000420835389",
    }
    live_payload["additional_prompt_instruction"] = "Utamakan ringkasan tesis yang sangat ringkas."
    monkeypatch.setenv("KELAS_INVESTASI_GTW_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setattr(
        config,
        "_fetch_live_config",
        lambda: SimpleNamespace(
            watcher_id="bursawatch-tg-kelas-investasi-gtw",
            revision=9,
            config=live_payload,
        ),
    )

    loaded = config.load_watch_config_for_run()

    assert loaded.revision == 9
    assert loaded.config.telegram_channel_id == 2142109999
    assert loaded.config.additional_prompt_instruction == "Utamakan ringkasan tesis yang sangat ringkas."
    with config.activate_watch_config(loaded.config):
        assert config.active_watch_config() == loaded.config
    assert config.active_watch_config() == config.default_watch_config()
