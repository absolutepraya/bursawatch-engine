from __future__ import annotations

import pytest

from control_plane.contract import ConfigSnapshot, ContractError, config_checksum


def test_snapshot_round_trips_with_checksum():
    config = {"version": 1, "profiles": [{"id": "example"}]}
    snapshot = ConfigSnapshot(
        watcher_id="bursawatch-x-account-watch",
        revision=3,
        config_version=1,
        config=config,
        config_sha256=config_checksum(config),
        updated_at="2026-09-19T10:00:00+00:00",
    )

    assert ConfigSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_snapshot_rejects_checksum_mismatch():
    payload = {
        "api_version": 1,
        "watcher_id": "bursawatch-x-account-watch",
        "revision": 1,
        "config_version": 1,
        "config": {"version": 1},
        "config_sha256": "0" * 64,
        "updated_at": "2026-09-19T10:00:00+00:00",
    }

    with pytest.raises(ContractError, match="does not match"):
        ConfigSnapshot.from_dict(payload)


def test_snapshot_rejects_naive_timestamp():
    config = {"version": 1}

    with pytest.raises(ContractError, match="timezone"):
        ConfigSnapshot(
            watcher_id="bursawatch-x-account-watch",
            revision=1,
            config_version=1,
            config=config,
            config_sha256=config_checksum(config),
            updated_at="2026-09-19T10:00:00",
        )
