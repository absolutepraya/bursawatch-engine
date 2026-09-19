from __future__ import annotations

from dataclasses import dataclass
import os

import pytest

import config


@dataclass(frozen=True)
class Snapshot:
    watcher_id: str
    revision: int
    config: dict


def test_static_config_remains_default(config_path, monkeypatch):
    monkeypatch.delenv("X_POST_WATCH_CONTROL_PLANE_URL", raising=False)
    loaded = config.load_watch_config_for_run(config_path)

    assert loaded.revision is None
    assert loaded.config.profiles[0].id == "kutekians"


def test_live_config_is_validated_and_returns_revision(config_path, profile_payload, monkeypatch):
    monkeypatch.setenv("X_POST_WATCH_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setenv("X_POST_WATCH_CONTROL_PLANE_WATCHER_ID", "bursawatch-x-account-watch")
    monkeypatch.setattr(
        config,
        "_fetch_live_config",
        lambda: Snapshot(
            watcher_id="bursawatch-x-account-watch",
            revision=17,
            config={"version": 1, "profiles": [profile_payload]},
        ),
    )

    loaded = config.load_watch_config_for_run()

    assert loaded.revision == 17
    assert loaded.config.profiles[0].handle == "Kutekians"


def test_live_config_does_not_fall_back_to_static_file(config_path, monkeypatch):
    monkeypatch.setenv("X_POST_WATCH_CONTROL_PLANE_URL", "https://control.example.test")
    monkeypatch.setenv("X_POST_WATCH_CONTROL_PLANE_WATCHER_ID", "bursawatch-x-account-watch")

    def fail_fetch():
        raise RuntimeError("control-plane unavailable")

    monkeypatch.setattr(config, "_fetch_live_config", fail_fetch)

    with pytest.raises(RuntimeError, match="control-plane unavailable"):
        config.load_watch_config_for_run()
