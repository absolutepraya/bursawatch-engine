from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from control_plane_client import (  # noqa: E402
    ConfigSnapshot,
    ControlPlaneContractError,
    ControlPlaneUnavailable,
    fetch_config,
    ControlPlaneReporter,
    ControlPlaneSpoolFull,
    RequestSpool,
)


class FakeResponse:
    def __init__(self, payload: object):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


def payload():
    config = {"version": 1, "profiles": []}
    checksum = hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "api_version": 1,
        "watcher_id": "bursawatch-x-account-watch",
        "revision": 4,
        "config_version": 1,
        "config": config,
        "config_sha256": checksum,
        "updated_at": "2026-09-19T10:00:00+00:00",
    }


def test_fetch_config_validates_snapshot_and_auth_header():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return FakeResponse(payload())

    snapshot = fetch_config(
        "https://control.example.test/",
        "bursawatch-x-account-watch",
        "machine-token",
        timeout=3,
        opener=opener,
    )

    assert isinstance(snapshot, ConfigSnapshot)
    assert snapshot.revision == 4
    assert seen == {
        "url": "https://control.example.test/v1/watchers/bursawatch-x-account-watch/config",
        "auth": "Bearer machine-token",
        "timeout": 3,
    }


def test_fetch_config_rejects_checksum_mismatch():
    invalid = payload()
    invalid["config_sha256"] = "0" * 64

    with pytest.raises(ControlPlaneContractError, match="checksum"):
        fetch_config("https://control.example.test", "bursawatch-x-account-watch", "token", opener=lambda *_args, **_kwargs: FakeResponse(invalid))


def test_fetch_config_requires_token():
    with pytest.raises(ControlPlaneUnavailable, match="token"):
        fetch_config("https://control.example.test", "bursawatch-x-account-watch", "")


class ReporterResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_request_spool_is_atomic_bounded_and_acknowledgeable(tmp_path):
    spool = RequestSpool(tmp_path / "spool", max_bytes=2_000, max_requests=1)

    path = spool.append("POST", "/v1/runs", {"run_id": "one"})
    assert path.stat().st_mode & 0o777 == 0o600
    items = spool.pending()
    assert len(items) == 1
    assert items[0].request_id
    assert items[0].payload == {"run_id": "one"}

    with pytest.raises(ControlPlaneSpoolFull):
        spool.append("POST", "/v1/runs", {"run_id": "two"})

    spool.acknowledge(path)
    assert spool.pending() == []


def test_reporter_queues_and_flushes_run_lifecycle_requests(tmp_path):
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout, json.loads(request.data.decode("utf-8"))))
        return ReporterResponse()

    reporter = ControlPlaneReporter(
        "https://control.example.test",
        "bursawatch-x-account-watch",
        "machine-token",
        timeout=3,
        spool=RequestSpool(tmp_path / "spool"),
        opener=opener,
    )

    run_id = reporter.start_run(4, scheduler_job_id="x-post-source")
    reporter.event(
        run_id,
        "source-fetch-1",
        level="info",
        phase="source",
        event_type="fetch.completed",
        message="  fetched   2 profiles  ",
        attributes={"profiles": 2},
    )
    reporter.finish(run_id, "ok")

    assert reporter.last_error is None
    assert reporter.spool.pending() == []
    assert [item[0].full_url for item in requests] == [
        "https://control.example.test/v1/runs",
        f"https://control.example.test/v1/runs/{run_id}/events",
        f"https://control.example.test/v1/runs/{run_id}/finish",
    ]
    assert all(item[0].get_header("Authorization") == "Bearer machine-token" for item in requests)
    assert requests[1][2]["message"] == "fetched 2 profiles"


def test_reporter_leaves_requests_spooled_when_control_plane_is_unavailable(tmp_path):
    def opener(*_args, **_kwargs):
        raise OSError("offline")

    spool = RequestSpool(tmp_path / "spool")
    reporter = ControlPlaneReporter(
        "https://control.example.test",
        "bursawatch-x-account-watch",
        "machine-token",
        spool=spool,
        opener=opener,
    )

    run_id = reporter.start_run(4)

    assert run_id
    assert reporter.last_error == "control-plane request failed"
    assert len(spool.pending()) == 1


def test_reporter_can_buffer_events_until_run_finishes(tmp_path):
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return ReporterResponse()

    reporter = ControlPlaneReporter(
        "https://control.example.test",
        "bursawatch-x-account-watch",
        "machine-token",
        spool=RequestSpool(tmp_path / "spool"),
        opener=opener,
    )
    run_id = reporter.start_run(1)
    reporter.event(
        run_id,
        "event-1",
        level="info",
        phase="run",
        event_type="run.started",
        message="started",
        flush=False,
    )

    assert len(requests) == 1
    assert len(reporter.spool.pending()) == 1

    reporter.finish(run_id, "ok")

    assert len(requests) == 3
    assert reporter.spool.pending() == []
