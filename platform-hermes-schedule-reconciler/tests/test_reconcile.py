from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import reconcile


def schedule_payload(*, revision: int = 1, enabled: bool = True, interval_seconds: int = 60) -> dict[str, object]:
    return {
        "api_version": 1,
        "job_id": "bursawatch-tg-market-news",
        "revision": revision,
        "enabled": enabled,
        "interval_seconds": interval_seconds,
        "timezone": "Asia/Jakarta",
        "schedule_sha256": reconcile.schedule_checksum(enabled, interval_seconds, "Asia/Jakarta"),
        "updated_at": "2026-09-19T10:00:00+00:00",
    }


def desired_job(*, revision: int = 1, enabled: bool = True, interval_seconds: int = 60) -> dict[str, object]:
    return {
        "job_id": "bursawatch-tg-market-news",
        "watcher_id": "bursawatch-tg-market-news",
        "display_name": "Telegram Market News",
        "runtime_job_key": "bursawatch-tg-market-news",
        "schedule_kind": "interval",
        "min_interval_seconds": 60,
        "max_interval_seconds": 3600,
        "schedule": schedule_payload(
            revision=revision,
            enabled=enabled,
            interval_seconds=interval_seconds,
        ),
        "reconciliation": {
            "status": "pending",
            "applied_revision": None,
            "last_error": None,
            "effective": False,
        },
    }


class Response:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self.payload


class FakeControlPlane:
    def __init__(self, jobs: list[dict[str, object]], *, stale_on_report: bool = False) -> None:
        self.jobs = jobs
        self.stale_on_report = stale_on_report
        self.reports: list[dict[str, object]] = []

    def __call__(self, request, timeout: float):
        assert timeout == 15
        parsed = urlparse(request.full_url)
        if request.get_method() == "GET":
            assert parsed.path == "/v1/internal/schedules"
            return Response(self.jobs)
        if self.stale_on_report:
            raise HTTPError(request.full_url, 409, "conflict", None, BytesIO())
        self.reports.append(json.loads(request.data.decode("utf-8")))
        return Response({"ok": True})


def write_registry(path: Path, *, enabled: bool = True, minutes: int = 1) -> None:
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "6a0b4f895b07",
                        "name": "bursawatch-tg-market-news",
                        "enabled": enabled,
                        "schedule": {"kind": "interval", "minutes": minutes},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def write_legacy_cron_registry(path: Path, *, enabled: bool, expression: str) -> None:
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "6a0b4f895b07",
                        "name": "bursawatch-tg-market-news",
                        "enabled": enabled,
                        "schedule": {"kind": "cron", "expr": expression},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def settings(registry: Path, *, dry_run: bool = False) -> reconcile.Settings:
    return reconcile.Settings(
        control_plane_url="https://control.example.test",
        token="reconciler-token",
        jobs_path=registry,
        hermes_cli="/usr/local/bin/hermes",
        timeout_seconds=15,
        dry_run=dry_run,
    )


def test_dry_run_plans_exact_interval_and_pause_without_cli_or_report(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(registry, enabled=True, minutes=1)
    api = FakeControlPlane([desired_job(enabled=False, interval_seconds=120)])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)

    outcomes = reconcile.reconcile_all(
        settings(registry, dry_run=True),
        client,
        command_runner=lambda *_args, **_kwargs: pytest.fail("dry run invoked Hermes CLI"),
    )

    assert [outcome.to_dict() for outcome in outcomes] == [
        {
            "job_id": "bursawatch-tg-market-news",
            "revision": 1,
            "status": "planned",
            "actions": ["edit schedule to every 2m", "pause job"],
        }
    ]
    assert api.reports == []


def test_reconciler_edits_then_pauses_reloads_registry_and_reports_applied(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(registry, enabled=True, minutes=1)
    api = FakeControlPlane([desired_job(enabled=False, interval_seconds=120)])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)
    commands: list[list[str]] = []

    def runner(command: list[str], timeout: float) -> None:
        commands.append(command)
        payload = json.loads(registry.read_text(encoding="utf-8"))
        job = payload["jobs"][0]
        if command[2] == "edit":
            assert command == [
                "/usr/local/bin/hermes",
                "cron",
                "edit",
                "6a0b4f895b07",
                "--schedule",
                "every 2m",
            ]
            job["schedule"] = {"kind": "interval", "minutes": 2}
        elif command[2] == "pause":
            job["enabled"] = False
        else:
            pytest.fail(f"unexpected command: {command}")
        registry.write_text(json.dumps(payload), encoding="utf-8")

    outcomes = reconcile.reconcile_all(settings(registry), client, command_runner=runner)

    assert commands == [
        ["/usr/local/bin/hermes", "cron", "edit", "6a0b4f895b07", "--schedule", "every 2m"],
        ["/usr/local/bin/hermes", "cron", "pause", "6a0b4f895b07"],
    ]
    assert outcomes[0].status == "applied"
    assert api.reports == [{"revision": 1, "status": "applied"}]
    assert json.loads(registry.read_text(encoding="utf-8"))["jobs"][0] == {
        "id": "6a0b4f895b07",
        "name": "bursawatch-tg-market-news",
        "enabled": False,
        "schedule": {"kind": "interval", "minutes": 2},
    }


@pytest.mark.parametrize(
    ("interval_seconds", "expression"),
    [
        (60, "* * * * *"),
        (600, "*/10 * * * *"),
        (3600, "0 * * * *"),
    ],
)
def test_reconciler_preserves_exact_legacy_cron_baselines(
    tmp_path: Path,
    interval_seconds: int,
    expression: str,
):
    registry = tmp_path / "jobs.json"
    write_legacy_cron_registry(registry, enabled=False, expression=expression)
    api = FakeControlPlane([desired_job(enabled=False, interval_seconds=interval_seconds)])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)

    outcomes = reconcile.reconcile_all(
        settings(registry),
        client,
        command_runner=lambda *_args, **_kwargs: pytest.fail("legacy baseline invoked Hermes CLI"),
    )

    assert outcomes == [
        reconcile.Outcome(
            job_id="bursawatch-tg-market-news",
            revision=1,
            status="applied",
            actions=[],
        )
    ]
    assert api.reports == [{"revision": 1, "status": "applied"}]


def test_reconciler_reports_sanitized_cli_failures_without_leaking_credentials_or_paths(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(registry, enabled=True, minutes=1)
    api = FakeControlPlane([desired_job(interval_seconds=120)])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)

    def subprocess_runner(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            17,
            command,
            stderr="token=top-secret https://private.example.test/api /tmp/private-state",
        )

    def runner(command: list[str], timeout: float) -> None:
        reconcile.run_hermes_cli(command, timeout, runner=subprocess_runner)

    outcomes = reconcile.reconcile_all(settings(registry), client, command_runner=runner)

    assert outcomes[0].status == "error"
    assert api.reports[0]["status"] == "error"
    error = api.reports[0]["error"]
    assert "top-secret" not in error
    assert "private.example" not in error
    assert "/tmp/private-state" not in error
    assert "<redacted>" in error
    assert "<url>" in error
    assert "<path>" in error


def test_stale_report_is_not_retried_or_marked_effective(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    write_registry(registry, enabled=True, minutes=1)
    api = FakeControlPlane([desired_job()], stale_on_report=True)
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)

    outcomes = reconcile.reconcile_all(settings(registry), client)

    assert outcomes == [
        reconcile.Outcome(
            job_id="bursawatch-tg-market-news",
            revision=1,
            status="stale",
            actions=[],
        )
    ]


def test_contract_rejects_schedule_checksum_or_wrong_timezone():
    checksum_mismatch = desired_job()
    checksum_mismatch["schedule"]["schedule_sha256"] = "0" * 64
    with pytest.raises(reconcile.ContractError, match="checksum"):
        reconcile.parse_desired_schedule(checksum_mismatch)

    wrong_timezone = desired_job()
    wrong_timezone["schedule"]["timezone"] = "UTC"
    wrong_timezone["schedule"]["schedule_sha256"] = reconcile.schedule_checksum(True, 60, "UTC")
    with pytest.raises(reconcile.ContractError, match="Asia/Jakarta"):
        reconcile.parse_desired_schedule(wrong_timezone)


def test_telegram_source_existing_legacy_cron_matches_without_edit(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    registry.write_text(json.dumps({"jobs": [{
        "id": "source-job-id",
        "name": "bursawatch-tg-source-ingest",
        "enabled": True,
        "schedule": {"kind": "cron", "expr": "* * * * *"},
    }]}), encoding="utf-8")
    job = desired_job()
    job["job_id"] = "bursawatch-tg-source-ingest"
    job["watcher_id"] = None
    job["runtime_job_key"] = "bursawatch-tg-source-ingest"
    job["schedule"]["job_id"] = "bursawatch-tg-source-ingest"
    api = FakeControlPlane([job])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)

    outcomes = reconcile.reconcile_all(
        settings(registry), client,
        command_runner=lambda *_args, **_kwargs: pytest.fail("matching schedule invoked Hermes CLI"),
    )

    assert outcomes == [reconcile.Outcome("bursawatch-tg-source-ingest", 1, "applied", [])]
    assert api.reports == [{"revision": 1, "status": "applied"}]


def test_unexpected_runtime_key_refuses_edit(tmp_path: Path):
    registry = tmp_path / "jobs.json"
    registry.write_text(json.dumps({"jobs": [{
        "id": "unrelated-id",
        "name": "unrelated-job",
        "enabled": True,
        "schedule": {"kind": "interval", "minutes": 2},
    }]}), encoding="utf-8")
    job = desired_job(interval_seconds=120)
    job["runtime_job_key"] = "unrelated-job"
    api = FakeControlPlane([job])
    client = reconcile.ControlPlaneClient("https://control.example.test", "reconciler-token", 15, opener=api)
    commands: list[list[str]] = []

    with pytest.raises(reconcile.ContractError, match="runtime job key"):
        reconcile.reconcile_all(
            settings(registry), client,
            command_runner=lambda command, _timeout: commands.append(command),
        )
    assert commands == []
    assert api.reports == []


def test_declared_job_bounds_and_fixed_job_are_enforced():
    telegram = desired_job(interval_seconds=7200)
    telegram["job_id"] = "bursawatch-tg-source-ingest"
    telegram["watcher_id"] = None
    telegram["runtime_job_key"] = "bursawatch-tg-source-ingest"
    telegram["schedule"]["job_id"] = "bursawatch-tg-source-ingest"
    telegram["schedule"]["schedule_sha256"] = reconcile.schedule_checksum(True, 7200, "Asia/Jakarta")
    with pytest.raises(reconcile.ContractError, match="interval bounds"):
        reconcile.parse_desired_schedule(telegram)

    fixed = desired_job()
    fixed["job_id"] = "bursawatch-dc-swing-board-close"
    fixed["runtime_job_key"] = "bursawatch-dc-swing-board-close"
    fixed["schedule_kind"] = "fixed"
    fixed["schedule"]["job_id"] = "bursawatch-dc-swing-board-close"
    with pytest.raises(reconcile.ContractError, match="non-interval"):
        reconcile.parse_desired_schedule(fixed)


def test_wrapper_has_valid_bash_syntax():
    wrapper = Path(__file__).resolve().parents[1] / "bin/bursawatch-hermes-schedule-reconciler.sh"
    completed = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr


def test_systemd_timer_runs_the_reconciler_separately_from_hermes_cron():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "deployment/systemd/bursawatch-schedule-reconciler.service").read_text(encoding="utf-8")
    timer = (root / "deployment/systemd/bursawatch-schedule-reconciler.timer").read_text(encoding="utf-8")

    assert "EnvironmentFile=/home/praya/.hermes/.env" in unit
    assert "bursawatch-hermes-schedule-reconciler.sh" in unit
    assert "OnUnitActiveSec=1m" in timer
    assert "Unit=bursawatch-schedule-reconciler.service" in timer
