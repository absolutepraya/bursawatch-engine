from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from io import BytesIO
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import observe


RUNTIME_NAMES = {"bursawatch-tg-source-ingest", "bursawatch-x-account-watch"}
EXPECTED_RUNTIME_JOB_IDS = {
    "bursawatch-tg-source-ingest": "bursawatch-tg-source-ingest",
    "bursawatch-tg-market-news-watchdog": "bursawatch-tg-market-news-watchdog",
    "bursawatch-dc-swing-board-lifecycle": "bursawatch-dc-swing-board-lifecycle",
    "bursawatch-x-account-watch": "bursawatch-x-account-watch-source",
    "bursawatch-x-account-watch-queue": "bursawatch-x-account-watch-queue-worker",
    "bursawatch-ig-account-watch": "bursawatch-ig-account-watch-source",
    "bursawatch-tg-phintraco-swing": "bursawatch-tg-phintraco-swing",
    "bursawatch-dc-swing-board-close": "bursawatch-dc-swing-board-close",
    "bursawatch-dc-swing-board-retry": "bursawatch-dc-swing-board-retry",
    "bursawatch-tg-market-news": "bursawatch-tg-market-news",
    "bursawatch-tg-kelas-investasi-gtw": "bursawatch-tg-kelas-investasi-gtw",
    "bursawatch-wa-channel-watch": "bursawatch-wa-channel-watch",
    "cron-stockbit-snips": "bursawatch-stockbit-snips",
}


def write_registry(path: Path, jobs: list[dict[str, object]]) -> bytes:
    payload = json.dumps({"jobs": jobs}).encode("utf-8")
    path.write_bytes(payload)
    return payload


def job(name: str, *, schedule: dict[str, object], **extra: object) -> dict[str, object]:
    return {
        "id": "6a0b4f895b07",
        "name": name,
        "enabled": True,
        "schedule": schedule,
        **extra,
    }


def test_reads_exact_interval_and_fixed_job_schedules(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1}),
            job("bursawatch-x-account-watch", schedule={"kind": "fixed", "expr": "*/10 * * * *"}),
        ],
    )

    rows = observe.read_observed_jobs(registry, RUNTIME_NAMES)

    assert rows == [
        {
            "runtime_job_key": "bursawatch-tg-source-ingest",
            "enabled": True,
            "schedule": {"kind": "interval", "minutes": 1},
            "last_execution": {"at": None, "status": None},
        },
        {
            "runtime_job_key": "bursawatch-x-account-watch",
            "enabled": True,
            "schedule": {"kind": "cron", "expr": "*/10 * * * *"},
            "last_execution": {"at": None, "status": None},
        },
    ]


def test_full_runtime_job_map_matches_declared_job_ids_and_requires_every_name(tmp_path: Path):
    assert observe.RUNTIME_JOB_IDS == EXPECTED_RUNTIME_JOB_IDS
    registry = tmp_path / "jobs.json"
    write_registry(
        registry,
        [
            job(name, schedule={"kind": "interval", "minutes": 1})
            for name in sorted(EXPECTED_RUNTIME_JOB_IDS)
        ],
    )

    rows = observe.read_observed_jobs(registry, set(EXPECTED_RUNTIME_JOB_IDS))

    assert {row["runtime_job_key"] for row in rows} == set(EXPECTED_RUNTIME_JOB_IDS)
    assert observe.RUNTIME_JOB_IDS["cron-stockbit-snips"] == "bursawatch-stockbit-snips"


def test_duplicate_runtime_name_blocks_report(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1}),
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 2}),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )

    with pytest.raises(observe.ObserverError, match="duplicate"):
        observe.read_observed_jobs(registry, RUNTIME_NAMES)


def test_missing_runtime_name_blocks_report(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(registry, [job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1})])

    with pytest.raises(observe.ObserverError, match="missing"):
        observe.read_observed_jobs(registry, RUNTIME_NAMES)


def test_registry_read_has_no_file_writes(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    before = write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1}),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )

    observe.read_observed_jobs(registry, RUNTIME_NAMES)

    assert registry.read_bytes() == before


def test_observer_never_invokes_cli(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1}),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )
    with patch.object(subprocess, "run") as cli:
        observe.read_observed_jobs(registry, RUNTIME_NAMES)
    cli.assert_not_called()


def test_parser_redacts_unapproved_registry_fields(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(
        registry,
        [
            job(
                "bursawatch-tg-source-ingest",
                schedule={"kind": "interval", "minutes": 1},
                last_run_at="2026-09-29T12:00:00+07:00",
                last_status="ok",
                last_run_status="failed",
                last_run_error="Authorization: Bearer secret-value /private/path",
                command="/private/path with token=secret-value",
            ),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )

    rows = observe.read_observed_jobs(registry, RUNTIME_NAMES)
    serialized = json.dumps(rows)

    assert rows[0]["last_execution"] == {"at": "2026-09-29T05:00:00Z", "status": "success"}
    assert "secret-value" not in serialized
    assert "/private/path" not in serialized
    assert "command" not in serialized
    assert "last_run_error" not in serialized


def test_reporter_posts_only_frozen_observation_fields():
    row = {
        "runtime_job_key": "bursawatch-x-account-watch-queue",
        "enabled": False,
        "schedule": {"kind": "cron", "expr": "*/10 * * * *"},
        "last_execution": {"at": "2026-09-29T05:00:00Z", "status": "failed"},
    }
    captured: list[dict[str, object]] = []

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://control.example.test/v1/internal/observations"
        assert request.method == "POST"
        assert timeout == 15
        assert request.get_header("Authorization") == "Bearer test-token"
        captured.append(json.loads(request.data.decode("utf-8")))
        return BytesIO(b'{"ok":true}')

    with patch.object(observe, "urlopen", side_effect=fake_urlopen):
        observe.report_observations("https://control.example.test", "test-token", [row])

    assert len(captured) == 1
    payload = captured[0]
    assert set(payload) == {"api_version", "identity_kind", "identity_id", "observed_at", "status", "evidence"}
    assert payload["api_version"] == 1
    assert payload["identity_kind"] == "job"
    assert payload["identity_id"] == "bursawatch-x-account-watch-queue-worker"
    assert payload["status"] == "disabled"
    assert payload["evidence"] == {
        "runtime_job_key": "bursawatch-x-account-watch-queue",
        "enabled": False,
        "schedule": {"kind": "cron", "expr": "*/10 * * * *"},
        "last_execution": {"at": "2026-09-29T05:00:00Z", "status": "failed"},
    }


def test_release_manifest_keeps_host_package_manual():
    manifest_path = ROOT.parent / "platform-bursawatch-release" / "release-manifest.json"
    units = json.loads(manifest_path.read_text(encoding="utf-8"))["units"]
    unit = next(item for item in units if item["id"] == "platform-bursawatch-observer")

    assert unit["handler"] == "manual"
    assert unit["paths"] == ["platform-bursawatch-observer/**"]


def test_invalid_json_and_invalid_schedule_fail_closed(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    registry.write_text("{oops", encoding="utf-8")
    with pytest.raises(observe.ObserverError, match="JSON"):
        observe.read_observed_jobs(registry, RUNTIME_NAMES)

    write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 0}),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )
    with pytest.raises(observe.ObserverError, match="schedule"):
        observe.read_observed_jobs(registry, RUNTIME_NAMES)

    write_registry(
        registry,
        [
            job("bursawatch-tg-source-ingest", schedule={"kind": "interval", "minutes": 1}),
            job("bursawatch-x-account-watch", schedule={"kind": "cron", "expr": "run /tmp/script"}),
            job(["malformed-name"], schedule={"kind": "cron", "expr": "*/10 * * * *"}),
        ],
    )
    with pytest.raises(observe.ObserverError, match="fixed schedule"):
        observe.read_observed_jobs(registry, RUNTIME_NAMES)
