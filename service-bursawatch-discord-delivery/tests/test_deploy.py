from __future__ import annotations

import os
from pathlib import Path
import subprocess


PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "deploy.sh"
UNIT = PACKAGE / "deployment/systemd/bursawatch-discord-delivery.service"


def _fake_tools(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log = tmp_path / "deploy-calls.log"
    for name in ("rsync", "ssh"):
        command = fake_bin / name
        command.write_text(
            "#!/bin/sh\n"
            "printf '%s %s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$DEPLOY_TEST_LOG\"\n"
            "cat >/dev/null\n"
        )
        command.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["DEPLOY_TEST_LOG"] = str(log)
    return env, log


def _run(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), command],
        cwd=PACKAGE.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plan_status_and_verify_use_only_read_only_remote_commands(tmp_path: Path) -> None:
    expected_tools = {
        "plan": {"rsync"},
        "status": {"ssh"},
        "verify": {"rsync", "ssh"},
    }

    for command, expected in expected_tools.items():
        env, log = _fake_tools(tmp_path / command)
        result = _run(command, env)
        assert result.returncode == 0, result.stderr
        calls = log.read_text().splitlines()
        assert {line.split(" ", 1)[0] for line in calls} == expected
        assert all("--apply" not in line for line in calls)
        if command in {"plan", "verify"}:
            assert all("-ain" in line for line in calls if line.startswith("rsync "))


def test_mutating_commands_refuse_to_run_without_apply(tmp_path: Path) -> None:
    for command in ("sync", "restart", "release"):
        env, log = _fake_tools(tmp_path / command)
        result = _run(command, env)
        assert result.returncode == 2
        assert "requires the explicit --apply flag" in result.stderr
        assert not log.exists()


def test_apply_commands_require_published_commit_gate() -> None:
    source = SCRIPT.read_text()
    assert '"$repo_root/scripts/require-published-commit"' in source
    for command in ("sync)", "restart)", "release)"):
        start = source.index(command)
        require_apply = source.index('require_apply "${@:2}"', start)
        require_published = source.index("require_published_commit", require_apply)
        assert require_apply < require_published


def test_systemd_unit_is_loopback_only_and_reads_private_environment() -> None:
    source = UNIT.read_text()
    assert "EnvironmentFile=/home/praya/.hermes/bursawatch-discord-delivery.env" in source
    assert "ExecStart=/home/praya/.hermes/bursawatch-discord-delivery/venv/bin/python bin/serve.py" in source
    assert "UMask=0077" in source
    assert "0.0.0.0" not in source
