from __future__ import annotations

import hashlib
from io import BytesIO
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
    SourceCatalogClient,
    SourceCatalogConflict,
)


def catalog_config():
    return {"selected_securities": [], "people_org": [], "endpoints": [], "publisher_defaults": [], "endpoint_overrides": []}


def catalog_revision():
    config = catalog_config()
    checksum = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {"revision": 2, "config": config, "sha256": checksum, "actor_id": "admin", "updated_at": "2026-09-24T00:00:00+00:00"}


def effective_catalog():
    return {"revision": 2, "updated_at": "2026-09-24T00:00:00+00:00", "selected_securities": [], "subscriptions": [{"endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "platform": "telegram", "address": "phintraprofits", "provider_id": "1444713822", "credential_ref": None, "capability_id": "trading_plans", "pipeline": "swing_plan", "enabled": True, "verification_status": "verified", "settings": {}, "source": "publisher_default"}]}


def catalog_body():
    return {"securities": [], "institutions": [{"id": "phintraco", "name": "Phintraco Sekuritas", "tier": 1, "asset_ref": None}], "people_org": [], "endpoints": [{"id": "telegram:phintraprofits", "publisher_id": "phintraco", "platform": "telegram", "address": "phintraprofits", "provider_id": "1444713822", "credential_ref": None, "system_owned": True, "verified": True}], "capabilities": [{"id": "trading_plans", "label": "Trading Plans", "pipeline": "swing_plan", "version": 1}], "compatibility": [{"endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans"}], "config": catalog_revision()}


def test_source_catalog_client_reads_effective_and_puts_expected_revision_without_spooling():

    seen = []

    def opener(request, timeout):
        seen.append((request.get_method(), request.full_url, request.get_header("Authorization"), request.data))
        body = effective_catalog() if request.get_method() == "GET" else catalog_revision()
        return BytesIO(json.dumps(body).encode())

    client = SourceCatalogClient("https://control.example.test", "token", opener=opener)
    assert client.get_effective()["revision"] == 2
    assert client.put_config(1, catalog_config())["revision"] == 2
    assert seen[0][:3] == ("GET", "https://control.example.test/v1/source-catalog/effective", "Bearer token")
    assert seen[1][0] == "PUT"
    assert json.loads(seen[1][3])["expected_revision"] == 1


def test_source_catalog_client_accepts_complete_registry_response():
    client = SourceCatalogClient("https://control.example.test", "token", opener=lambda *_args, **_kwargs: BytesIO(json.dumps(catalog_body()).encode()))
    assert client.get_catalog()["endpoints"][0]["provider_id"] == "1444713822"


@pytest.mark.parametrize("change", [
    lambda body: body.update(revision={"value": 2}),
    lambda body: body.pop("subscriptions"),
    lambda body: body.update(subscriptions={}),
    lambda body: body["subscriptions"][0].pop("address"),
    lambda body: body["subscriptions"][0].update(enabled=1),
])
def test_source_catalog_client_rejects_malformed_effective_snapshots(change):
    body = effective_catalog()
    change(body)
    client = SourceCatalogClient("https://control.example.test", "token", opener=lambda *_args, **_kwargs: BytesIO(json.dumps(body).encode()))
    with pytest.raises(ControlPlaneContractError):
        client.get_effective()


@pytest.mark.parametrize("change", [
    lambda body: body.update(revision={"value": 2}),
    lambda body: body.pop("config"),
    lambda body: body["config"].update(endpoints={}),
    lambda body: body.update(sha256=7),
    lambda body: body.update(sha256="0" * 64),
])
def test_source_catalog_client_rejects_malformed_write_responses(change):
    body = catalog_revision()
    change(body)
    client = SourceCatalogClient("https://control.example.test", "token", opener=lambda *_args, **_kwargs: BytesIO(json.dumps(body).encode()))
    with pytest.raises(ControlPlaneContractError):
        client.put_config(1, catalog_config())


@pytest.mark.parametrize("change", [
    lambda body: body.pop("capabilities"),
    lambda body: body["endpoints"][0].update(provider_id=123),
    lambda body: body["institutions"][0].update(tier=True),
    lambda body: body["config"].update(revision={"value": 2}),
])
def test_source_catalog_client_rejects_malformed_registry_responses(change):
    body = catalog_body()
    change(body)
    client = SourceCatalogClient("https://control.example.test", "token", opener=lambda *_args, **_kwargs: BytesIO(json.dumps(body).encode()))
    with pytest.raises(ControlPlaneContractError):
        client.get_catalog()


def test_source_catalog_client_exposes_revision_conflict():
    from urllib.error import HTTPError

    def opener(request, timeout):
        raise HTTPError(request.full_url, 409, "conflict", {}, None)

    with pytest.raises(SourceCatalogConflict):
        SourceCatalogClient("https://control.example.test", "token", opener=opener).put_config(1, {})


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
