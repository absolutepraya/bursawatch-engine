#!/usr/bin/env python3
"""Print a filtered, read-only snapshot of Bursawatch production state."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SSH_TARGET = "vps"
REMOTE_CRON_LIST = "/home/praya/.local/bin/hermes cron list --all"
REMOTE_CRON_STATUS = "/home/praya/.local/bin/hermes cron status"
REMOTE_RELEASE_STATUS = "/home/praya/.local/lib/bursawatch-release/bursawatch-release-agent.sh --status"
REMOTE_SCHEDULE_QUERY = r"""
import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

try:
    token = None
    env_path = Path('/home/praya/.hermes/bursawatch-control-plane.env')
    for line in env_path.read_text().splitlines():
        if line.startswith('CONTROL_PLANE_RECONCILER_TOKEN='):
            token = line.partition('=')[2].strip().strip('"').strip("'")
            break
    if not token:
        raise RuntimeError
    request = Request(
        'http://127.0.0.1:9120/v1/internal/schedules',
        headers={'Authorization': f'Bearer {token}'},
    )
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=8) as response:
        schedules = json.load(response)
    if not isinstance(schedules, list):
        raise RuntimeError
    output = []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        key = item.get('runtime_job_key')
        if not isinstance(key, str) or not (key.startswith('bursawatch-') or key == 'cron-stockbit-snips'):
            continue
        schedule = item.get('schedule') if isinstance(item.get('schedule'), dict) else {}
        reconciliation = item.get('reconciliation') if isinstance(item.get('reconciliation'), dict) else {}
        interval = schedule.get('interval_seconds')
        output.append({
            'runtime_job_key': key,
            'schedule': {
                'enabled': schedule.get('enabled'),
                'interval_seconds': interval,
                'revision': schedule.get('revision'),
            },
            'reconciliation': {
                'status': reconciliation.get('status'),
                'applied_revision': reconciliation.get('applied_revision'),
                'effective': reconciliation.get('effective'),
            },
        })
    print(json.dumps(output, sort_keys=True))
except Exception:
    print('control-plane schedule snapshot unavailable', file=sys.stderr)
    sys.exit(1)
"""
JOB_HEADER = re.compile(r"^\s{2}([0-9a-f]{12}) \[([^\]]+)\]\s*$", re.I)
JOB_FIELD = re.compile(r"^\s{4}(Name|Schedule|Skills|Script|Last run):\s*(.*)$")
LAST_RUN_STATE = re.compile(r"\s+(ok|error|failed|running|skipped|never)(?:\s|:|$)", re.I)
SAFE_SSH_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]*$")
INTERVAL_SCHEDULE = re.compile(r"^every\s+(\d+)m$", re.I)
CRON_INTERVALS = {
    "* * * * *": 1,
    "*/1 * * * *": 1,
    "*/10 * * * *": 10,
    "0 * * * *": 60,
}


class SnapshotError(RuntimeError):
    """A snapshot command failed without exposing its captured output."""


def parse_cron_listing(output: str) -> list[dict[str, str | list[str]]]:
    """Extract only Bursawatch jobs and a safe set of scheduler fields."""
    jobs: list[dict[str, str | list[str]]] = []
    current: dict[str, Any] | None = None

    def save() -> None:
        if current is None:
            return
        name = current.get("name", "")
        skills = current.get("skills", [])
        script = current.get("script", "")
        is_bursawatch = (
            name.startswith("bursawatch-")
            or name == "cron-stockbit-snips"
            or any(skill.startswith("bursawatch-") for skill in skills)
            or script.startswith("bursawatch-")
        )
        if not is_bursawatch:
            return
        jobs.append(
            {
                "id": current["id"],
                "state": current["state"],
                "name": name or "unknown",
                "schedule": current.get("schedule", "unknown"),
                "skills": skills,
                "script": script or "unknown",
                "last_run_status": current.get("last_run_status", "unknown"),
            }
        )

    for line in output.splitlines():
        header = JOB_HEADER.match(line)
        if header:
            save()
            current = {
                "id": header.group(1),
                "state": header.group(2).lower(),
                "skills": [],
            }
            continue
        if current is None:
            continue
        field = JOB_FIELD.match(line)
        if not field:
            continue
        key, value = field.groups()
        value = value.strip()
        if key == "Skills":
            current["skills"] = [item.strip() for item in value.split(",") if item.strip()]
        elif key == "Last run":
            status = LAST_RUN_STATE.search(value)
            current["last_run_status"] = status.group(1).lower() if status else "unknown"
        else:
            current[key.lower()] = value
    save()
    return sorted(jobs, key=lambda job: (str(job["name"]), str(job["id"])))


def parse_release_status(output: str) -> dict[str, Any]:
    """Keep only stable release-agent status fields, discarding other JSON."""
    try:
        raw = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SnapshotError("release agent returned an unreadable status response") from exc
    if not isinstance(raw, dict):
        raise SnapshotError("release agent returned an unexpected status response")

    github = raw.get("github_status")
    if not isinstance(github, dict):
        github = {}
    return {
        "last_success_sha": raw.get("last_success_sha"),
        "github_sha": github.get("sha"),
        "github_state": github.get("state"),
        "blocked": raw.get("blocked") is not None,
        "transient": raw.get("transient") is not None,
    }


def parse_cron_status(output: str) -> dict[str, Any]:
    """Return only whether the scheduler gateway is reported running."""
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not first_line:
        raise SnapshotError("Hermes returned an empty scheduler status")
    if re.search(r"\bGateway is running\b", first_line, re.I):
        running: bool | None = True
    elif re.search(r"\bGateway is not running\b", first_line, re.I):
        running = False
    else:
        running = None
    return {"gateway_running": running}


def parse_schedule_catalog(output: str) -> list[dict[str, Any]]:
    """Retain safe desired-schedule and reconciliation fields for Bursawatch."""
    try:
        raw = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SnapshotError("control plane returned an unreadable schedule response") from exc
    if not isinstance(raw, list):
        raise SnapshotError("control plane returned an unexpected schedule response")

    schedules: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        job_key = item.get("runtime_job_key")
        if not isinstance(job_key, str) or not (
            job_key.startswith("bursawatch-") or job_key == "cron-stockbit-snips"
        ):
            continue
        schedule = item.get("schedule")
        reconciliation = item.get("reconciliation")
        if not isinstance(schedule, dict):
            schedule = {}
        if not isinstance(reconciliation, dict):
            reconciliation = {}
        interval_seconds = schedule.get("interval_seconds")
        schedules.append(
            {
                "runtime_job_key": job_key,
                "enabled": schedule.get("enabled"),
                "interval_minutes": interval_seconds // 60
                if type(interval_seconds) is int and interval_seconds % 60 == 0
                else None,
                "revision": schedule.get("revision"),
                "reconciliation_status": reconciliation.get("status"),
                "applied_revision": reconciliation.get("applied_revision"),
                "effective": reconciliation.get("effective"),
            }
        )
    return sorted(schedules, key=lambda item: item["runtime_job_key"])


def _hermes_interval_minutes(schedule: str) -> int | None:
    interval = INTERVAL_SCHEDULE.fullmatch(schedule.strip())
    if interval:
        return int(interval.group(1))
    return CRON_INTERVALS.get(schedule.strip())


def compare_schedule_registry(
    schedules: list[dict[str, Any]], jobs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compare each desired interval job with its exact Hermes registry row."""
    jobs_by_name = {job["name"]: job for job in jobs}
    result: list[dict[str, Any]] = []
    for schedule in schedules:
        job_key = schedule["runtime_job_key"]
        job = jobs_by_name.get(job_key)
        job_state = str(job["state"]) if job else None
        live_interval = _hermes_interval_minutes(str(job["schedule"])) if job else None
        desired_enabled = schedule.get("enabled")
        desired_interval = schedule.get("interval_minutes")
        state_matches = (
            job_state == "active"
            if desired_enabled is True
            else job_state in {"paused", "disabled"}
            if desired_enabled is False
            else False
        )
        result.append(
            {
                **schedule,
                "hermes_state": job_state,
                "hermes_interval_minutes": live_interval,
                "registry_matches_desired": bool(
                    job
                    and state_matches
                    and desired_interval is not None
                    and desired_interval == live_interval
                ),
            }
        )
    return result


def _run(argv: list[str], *, label: str, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotError(f"{label} could not be completed") from exc
    if result.returncode != 0:
        raise SnapshotError(f"{label} failed with exit code {result.returncode}")
    return result.stdout


def _ssh_script(target: str, script: str, *, label: str) -> str:
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                target,
                "python3 -",
            ],
            cwd=ROOT,
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotError(f"{label} could not be completed") from exc
    if result.returncode != 0:
        raise SnapshotError(f"{label} failed with exit code {result.returncode}")
    return result.stdout


def current_main_sha() -> str:
    output = _run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        label="read-only origin/main lookup",
    )
    match = re.match(r"^([0-9a-f]{40})\s+refs/heads/main\s*$", output.strip(), re.I)
    if not match:
        raise SnapshotError("origin/main lookup returned no commit SHA")
    return match.group(1).lower()


def _ssh(target: str, remote_command: str, *, label: str) -> str:
    return _run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            target,
            remote_command,
        ],
        label=label,
        timeout=25,
    )


def collect_snapshot(target: str = DEFAULT_SSH_TARGET) -> dict[str, Any]:
    if not SAFE_SSH_TARGET.fullmatch(target):
        raise SnapshotError("SSH target contains unsupported characters")

    main_sha = current_main_sha()
    release = parse_release_status(
        _ssh(target, REMOTE_RELEASE_STATUS, label="read-only release-agent status")
    )
    scheduler = parse_cron_status(
        _ssh(target, REMOTE_CRON_STATUS, label="read-only Hermes scheduler status")
    )
    jobs = parse_cron_listing(
        _ssh(target, REMOTE_CRON_LIST, label="read-only Hermes cron listing")
    )
    if not jobs:
        raise SnapshotError("Hermes returned no identifiable Bursawatch jobs")
    try:
        catalog = parse_schedule_catalog(
            _ssh_script(
                target,
                REMOTE_SCHEDULE_QUERY,
                label="read-only control-plane schedule lookup",
            )
        )
        schedule_catalog_available = True
    except SnapshotError:
        catalog = []
        schedule_catalog_available = False
    schedules = compare_schedule_registry(catalog, jobs)

    release_sha = release.get("last_success_sha")
    return {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "origin_main_sha": main_sha,
        "release": release,
        "scheduler": scheduler,
        "schedule_catalog_available": schedule_catalog_available,
        "desired_schedules": schedules,
        "release_matches_main": release_sha == main_sha,
        "jobs": jobs,
    }


def render_text(snapshot: dict[str, Any]) -> str:
    release = snapshot["release"]
    jobs = snapshot["jobs"]
    counts: dict[str, int] = {}
    for job in jobs:
        state = str(job["state"])
        counts[state] = counts.get(state, 0) + 1

    lines = [
        f"Bursawatch production snapshot, read-only, {snapshot['checked_at']}",
        f"origin/main: {snapshot['origin_main_sha']}",
        f"Last successful release: {release.get('last_success_sha') or 'unknown'}",
        f"Release CI state: {release.get('github_state') or 'unknown'}",
        f"Release matches origin/main: {'yes' if snapshot['release_matches_main'] else 'no'}",
        f"Release agent blocked: {'yes' if release['blocked'] else 'no'}",
        f"Release agent transient error: {'yes' if release['transient'] else 'no'}",
        "Hermes gateway running: "
        + ("yes" if snapshot["scheduler"]["gateway_running"] else "no")
        if snapshot["scheduler"]["gateway_running"] is not None
        else "Hermes gateway running: unknown",
        f"Hermes jobs: {len(jobs)} total, "
        + ", ".join(f"{count} {state}" for state, count in sorted(counts.items())),
        "",
    ]
    if snapshot["schedule_catalog_available"]:
        desired_schedules = snapshot["desired_schedules"]
        match_count = sum(item["registry_matches_desired"] for item in desired_schedules)
        lines.append(
            f"Desired interval schedules: {match_count}/{len(desired_schedules)} match the live registry"
        )
        for item in desired_schedules:
            desired_state = "active" if item["enabled"] else "paused"
            desired = f"{desired_state}@{item['interval_minutes']}m"
            actual = (
                f"{item['hermes_state']}@{item['hermes_interval_minutes']}m"
                if item["hermes_state"] and item["hermes_interval_minutes"] is not None
                else "missing or unrecognized"
            )
            mark = "match" if item["registry_matches_desired"] else "DRIFT"
            lines.append(
                f"  [{mark}] {item['runtime_job_key']} | desired={desired} "
                f"revision={item['revision']} applied={item['applied_revision']} "
                f"effective={item['effective']} | Hermes={actual}"
            )
        lines.append("")
    else:
        lines.extend(
            [
                "Control-plane desired schedules: unavailable; live Hermes records are still shown.",
                "",
            ]
        )
    for job in jobs:
        skills = ",".join(job["skills"]) or "none"
        lines.append(
            f"[{job['state']}] {job['name']} | {job['schedule']} | "
            f"script={job['script']} | skills={skills} | last={job['last_run_status']}"
        )
    lines.extend(
        [
            "",
            "This snapshot reports scheduler records and release-agent status. It does not verify",
            "runtime checksums or prove a natural source-to-delivery event.",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read and filter current Bursawatch release and Hermes schedule state."
    )
    parser.add_argument(
        "--production",
        action="store_true",
        required=True,
        help="confirm this read-only command will query origin and the VPS",
    )
    parser.add_argument(
        "--ssh-target",
        default=os.environ.get("BURSAWATCH_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="existing SSH alias or target (default: vps)",
    )
    parser.add_argument("--json", action="store_true", help="print the filtered snapshot as JSON")
    args = parser.parse_args(argv)

    try:
        snapshot = collect_snapshot(args.ssh_target)
    except SnapshotError as exc:
        print(f"production snapshot failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(render_text(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
