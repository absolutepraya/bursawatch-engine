from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .contract import canonical_json_bytes


class ConfigValidationError(ValueError):
    """Raised when an installed watcher schema rejects an operator payload."""


@dataclass(frozen=True)
class ValidatorSpec:
    watcher_id: str
    loader_name: str
    directory_environment_key: str


VALIDATOR_SPECS = {
    "bursawatch-x-account-watch": ValidatorSpec(
        watcher_id="bursawatch-x-account-watch",
        loader_name="load_watch_config_data",
        directory_environment_key="CONTROL_PLANE_X_CONFIG_VALIDATOR_DIR",
    ),
    "bursawatch-ig-account-watch": ValidatorSpec(
        watcher_id="bursawatch-ig-account-watch",
        loader_name="load_watch_config_data",
        directory_environment_key="CONTROL_PLANE_IG_CONFIG_VALIDATOR_DIR",
    ),
    "bursawatch-wa-channel-watch": ValidatorSpec(
        watcher_id="bursawatch-wa-channel-watch",
        loader_name="load_data",
        directory_environment_key="CONTROL_PLANE_WA_CONFIG_VALIDATOR_DIR",
    ),
}


@dataclass(frozen=True)
class IsolatedConfigValidator:
    """Runs a watcher parser in a fresh process to avoid module-name collisions."""

    directory: Path
    loader_name: str
    timeout_seconds: float = 5.0

    def __call__(self, config: dict[str, Any]) -> None:
        payload = canonical_json_bytes(config)
        runner = Path(__file__).with_name("validator_runner.py")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
        }
        try:
            result = subprocess.run(
                [sys.executable, str(runner), str(self.directory), self.loader_name],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                cwd=str(self.directory),
                env=environment,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConfigValidationError("watcher config validation timed out") from exc
        except OSError as exc:
            raise ConfigValidationError("watcher config validator is unavailable") from exc
        if result.returncode == 0:
            return
        message = result.stderr.decode("utf-8", errors="replace").strip().replace("\n", " ")
        if not message:
            message = "configuration was rejected"
        raise ConfigValidationError(message[:500])


def validators_from_directories(
    directories: Mapping[str, Path],
) -> dict[str, Callable[[dict[str, Any]], None]]:
    validators: dict[str, Callable[[dict[str, Any]], None]] = {}
    for watcher_id, directory in directories.items():
        try:
            spec = VALIDATOR_SPECS[watcher_id]
        except KeyError as exc:
            raise ValueError(f"no config validator is defined for {watcher_id}") from exc
        resolved = directory.expanduser().resolve()
        if not (resolved / "config.py").is_file():
            raise ValueError(f"validator directory for {watcher_id} does not contain config.py")
        validators[watcher_id] = IsolatedConfigValidator(resolved, spec.loader_name)
    return validators


def validators_from_environment() -> dict[str, Callable[[dict[str, Any]], None]]:
    directories: dict[str, Path] = {}
    for watcher_id, spec in VALIDATOR_SPECS.items():
        configured = os.environ.get(spec.directory_environment_key, "").strip()
        if configured:
            directories[watcher_id] = Path(configured)
    return validators_from_directories(directories)
