from __future__ import annotations

import os
from pathlib import Path
import subprocess


WRAPPER = Path(__file__).resolve().parents[1] / "bin/bursawatch-stockbit-snips.sh"
CONTROL_KEYS = (
    "STOCKBIT_SNIPS_CONTROL_PLANE_URL",
    "STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID",
    "STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN",
    "STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS",
)


def _run_wrapper(tmp_path: Path, *, install_client: bool) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    home = tmp_path / "home"
    hermes = home / ".hermes"
    hermes.mkdir(parents=True)
    values = {
        "STOCKBIT_SNIPS_CONTROL_PLANE_URL": "https://synthetic.example.invalid/private-config",
        "STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID": "bursawatch-stockbit-snips",
        "STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN": "synthetic-secret-token",
        "STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS": "13",
    }
    (hermes / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in values.items())
        + "\nSTOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH=/forbidden/spool\n",
        encoding="utf-8",
    )
    client_dir = home / ".agents/skills/lib-bursawatch-control/bin"
    if install_client:
        client_dir.mkdir(parents=True)
        (client_dir / "control_plane_client.py").write_text("# synthetic sentinel\n", encoding="utf-8")
    capture = tmp_path / "capture.env"
    python_stub = tmp_path / "python-stub"
    python_stub.write_text('#!/bin/sh\nenv > "$WRAPPER_CAPTURE_PATH"\n', encoding="utf-8")
    python_stub.chmod(0o700)
    runtime = tmp_path / "synthetic-scan.py"
    runtime.write_text("# synthetic runtime\n", encoding="utf-8")
    release_temp = tmp_path / "release"
    release_temp.mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("STOCKBIT_SNIPS_")}
    environment.update({
        "HOME": str(home),
        "STOCKBIT_SNIPS_PY": str(python_stub),
        "STOCKBIT_SNIPS_BIN": str(runtime),
        "STOCKBIT_SNIPS_NO_POST": "1",
        "STOCKBIT_SNIPS_STATE_PATH": str(release_temp / "state.json"),
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(release_temp),
        "WRAPPER_CAPTURE_PATH": str(capture),
        "STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH": "/inherited/forbidden/spool",
    })
    result = subprocess.run(["bash", str(WRAPPER)], env=environment, capture_output=True, text=True, check=False)
    return result, capture, release_temp


def test_wrapper_imports_only_allowed_control_plane_settings_into_isolated_no_post(tmp_path: Path) -> None:
    result, capture, release_temp = _run_wrapper(tmp_path, install_client=True)
    assert result.returncode == 0
    child = dict(line.split("=", 1) for line in capture.read_text(encoding="utf-8").splitlines() if "=" in line)
    assert child["STOCKBIT_SNIPS_CONTROL_PLANE_URL"] == "https://synthetic.example.invalid/private-config"
    assert child["STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID"] == "bursawatch-stockbit-snips"
    assert child["STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN"] == "synthetic-secret-token"
    assert child["STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS"] == "13"
    assert "STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH" not in child
    assert str(tmp_path / "home/.agents/skills/lib-bursawatch-control/bin") in child["PYTHONPATH"].split(":")
    assert str(tmp_path / "home/.agents/skills/lib-bursawatch-discord-delivery/bin") in child["PYTHONPATH"].split(":")
    assert "DISCORD_BOT_TOKEN" not in child
    assert child["STOCKBIT_SNIPS_STATE_PATH"] == str(release_temp / "state.json")
    assert (release_temp / "bursawatch-stockbit-snips.log").exists()
    logs = result.stdout + result.stderr + (release_temp / "bursawatch-stockbit-snips.log").read_text(encoding="utf-8")
    assert "https://synthetic.example.invalid/private-config" not in logs
    assert "synthetic-secret-token" not in logs


def test_wrapper_fails_safely_before_python_when_shared_client_is_missing(tmp_path: Path) -> None:
    result, capture, release_temp = _run_wrapper(tmp_path, install_client=False)
    assert result.returncode != 0
    assert not capture.exists()
    logs = result.stdout + result.stderr
    if (release_temp / "bursawatch-stockbit-snips.log").exists():
        logs += (release_temp / "bursawatch-stockbit-snips.log").read_text(encoding="utf-8")
    assert "control-plane" in logs.lower()
    assert "https://synthetic.example.invalid/private-config" not in logs
    assert "synthetic-secret-token" not in logs
