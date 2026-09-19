from __future__ import annotations

from types import SimpleNamespace

import pytest

import config


def payload() -> dict[str, object]:
    return {
        "version": 1,
        "destinations": {
            "heartbeat_discord_channel_id": "1505162000420835388",
        },
    }


def test_default_config_matches_the_established_heartbeat_destination(monkeypatch):
    monkeypatch.delenv("IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL", raising=False)

    loaded = config.load_board_config_for_run()

    assert loaded.revision is None
    assert loaded.config.heartbeat_discord_channel_id == "1505162000420835388"


def test_config_rejects_unknown_fields_and_invalid_destinations():
    invalid = payload()
    invalid["unknown"] = True
    with pytest.raises(ValueError, match="unsupported"):
        config.load_board_config_data(invalid)

    invalid = payload()
    invalid["destinations"] = {"heartbeat_discord_channel_id": "not-a-discord-id"}
    with pytest.raises(ValueError, match="snowflake"):
        config.load_board_config_data(invalid)


def test_live_mode_uses_one_validated_frozen_snapshot(monkeypatch):
    live_payload = {
        "version": 1,
        "destinations": {
            "heartbeat_discord_channel_id": "1505162000420835389",
        },
    }
    monkeypatch.setenv("IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setattr(
        config,
        "_fetch_live_config",
        lambda: SimpleNamespace(
            watcher_id="bursawatch-dc-swing-board",
            revision=13,
            config=live_payload,
        ),
    )

    loaded = config.load_board_config_for_run()

    assert loaded.revision == 13
    assert loaded.config.heartbeat_discord_channel_id == "1505162000420835389"
