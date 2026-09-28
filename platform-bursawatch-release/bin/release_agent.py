#!/usr/bin/env python3
"""Release eligible Bursawatch main commits from a VPS-local pull agent."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bursawatch_discord_delivery import DeliveryClient, OperationIntent


SHA_RE = re.compile(r"[0-9a-f]{40}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
MANIFEST_FILE = "platform-bursawatch-release/release-manifest.json"
LEGACY_MIGRATION_POLICY_FILE = "service-bursawatch-control/migrations/legacy-release-eligibility.json"
MIGRATION_RELEASE_HEADER_RE = re.compile(
    r"\A\s*--\s*bursawatch-release:\s*(automatic|manual)\s*(?:\r?\n|\Z)",
    re.IGNORECASE,
)
STATE_VERSION = 1
WIB = ZoneInfo("Asia/Jakarta")
KNOWN_HANDLERS = frozenset({"metadata", "manual", "runtime", "control-plane"})


class ReleaseError(RuntimeError):
    """A release cannot proceed safely."""


class TransientReleaseError(ReleaseError):
    """A retry may succeed without an operator change."""


class DeploymentError(ReleaseError):
    """A release began and must stay blocked until an operator resolves it."""


class CommandFailure(DeploymentError):
    """A child process failed with durable, sanitized diagnostic details."""

    def __init__(
        self,
        command: Sequence[str],
        returncode: int | None,
        *,
        stdout: object = "",
        stderr: object = "",
        timed_out: bool = False,
    ) -> None:
        self.command = tuple(command)
        self.returncode = returncode
        self.stdout = _safe_output(stdout)
        self.stderr = _safe_output(stderr)
        self.timed_out = timed_out
        self.signal_number = -returncode if isinstance(returncode, int) and returncode < 0 else None
        self.signal_name: str | None = None
        if self.signal_number is not None:
            try:
                self.signal_name = signal.Signals(self.signal_number).name
            except ValueError:
                self.signal_name = None
        self.details: dict[str, Any] = {
            "command": [_safe_output(argument, limit=500) for argument in self.command],
            "returncode": returncode,
            "signal_number": self.signal_number,
            "signal_name": self.signal_name,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": timed_out,
        }
        if timed_out:
            message = f"release command timed out: {self.command[0]}"
        elif self.signal_name is not None:
            message = (
                f"release command failed: {self.command[0]} "
                f"(exit {returncode}, signal {self.signal_number} {self.signal_name})"
            )
        else:
            message = f"release command failed: {self.command[0]} (exit {returncode})"
        super().__init__(message)

    def add_details(self, **details: Any) -> None:
        self.details.update(details)


class ManualReleaseRequired(ReleaseError):
    """A host-bound release unit requires an explicit operator action."""


@dataclass(frozen=True)
class Settings:
    repository: str
    token: str
    state_root: Path
    branch: str
    runtime_home: Path
    control_plane_runtime: Path
    control_plane_env: Path
    delivery_owner_url: str
    delivery_client_token_file: Path
    heartbeat_channel_id: str
    github_api_url: str
    timeout_seconds: float
    status_token: str | None = None
    status_target_url: str | None = None

    @classmethod
    def from_environment(cls, *, require_token: bool = True) -> "Settings":
        repository = os.environ.get("BURSAWATCH_RELEASE_REPOSITORY", "absolutepraya/bursawatch-engine").strip()
        if not REPOSITORY_RE.fullmatch(repository):
            raise ReleaseError("BURSAWATCH_RELEASE_REPOSITORY must be owner/repository")
        token = os.environ.get("BURSAWATCH_RELEASE_GITHUB_TOKEN", "").strip()
        if require_token and not token:
            raise ReleaseError("BURSAWATCH_RELEASE_GITHUB_TOKEN is required")
        status_token = os.environ.get("BURSAWATCH_RELEASE_STATUS_TOKEN", "").strip() or None
        status_target_url = os.environ.get("BURSAWATCH_RELEASE_STATUS_TARGET_URL", "").strip() or None
        branch = os.environ.get("BURSAWATCH_RELEASE_BRANCH", "main").strip()
        if branch != "main":
            raise ReleaseError("BURSAWATCH_RELEASE_BRANCH must remain main")
        state_root = Path(
            os.environ.get(
                "BURSAWATCH_RELEASE_STATE_ROOT",
                "~/.local/share/bursawatch-release",
            )
        ).expanduser()
        runtime_home = Path(os.environ.get("BURSAWATCH_RELEASE_RUNTIME_HOME", "~/.agents/skills")).expanduser()
        timeout_value = os.environ.get("BURSAWATCH_RELEASE_TIMEOUT_SECONDS", "30")
        try:
            timeout_seconds = float(timeout_value)
        except ValueError as exc:
            raise ReleaseError("BURSAWATCH_RELEASE_TIMEOUT_SECONDS must be a number") from exc
        if not 1 <= timeout_seconds <= 120:
            raise ReleaseError("BURSAWATCH_RELEASE_TIMEOUT_SECONDS must be between 1 and 120")
        return cls(
            repository=repository,
            token=token,
            state_root=state_root,
            branch=branch,
            runtime_home=runtime_home,
            control_plane_runtime=Path(
                os.environ.get(
                    "BURSAWATCH_RELEASE_CONTROL_PLANE_RUNTIME",
                    "~/.hermes/bursawatch-control-plane",
                )
            ).expanduser(),
            control_plane_env=Path(
                os.environ.get(
                    "BURSAWATCH_RELEASE_CONTROL_PLANE_ENV",
                    "~/.hermes/bursawatch-control-plane.env",
                )
            ).expanduser(),
            delivery_owner_url=os.environ.get(
                "BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9140"
            ).rstrip("/"),
            delivery_client_token_file=Path(
                os.environ.get(
                    "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
                    "~/.hermes/secrets/bursawatch-discord-delivery-client-token",
                )
            ).expanduser(),
            heartbeat_channel_id=os.environ.get(
                "BURSAWATCH_RELEASE_HEARTBEAT_CHANNEL_ID", "1505162000420835388"
            ).strip(),
            github_api_url=os.environ.get("BURSAWATCH_RELEASE_GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            timeout_seconds=timeout_seconds,
            status_token=status_token,
            status_target_url=status_target_url,
        )


@dataclass(frozen=True)
class ReleaseUnit:
    identifier: str
    handler: str
    paths: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    runtime: str | None = None
    wrappers: tuple[tuple[str, str], ...] = ()
    verification: str = "checksum-only"


@dataclass(frozen=True)
class ReleaseManifest:
    units: tuple[ReleaseUnit, ...]

    @classmethod
    def load(cls, path: Path) -> "ReleaseManifest":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseError("release manifest could not be read") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ReleaseError("release manifest has an unsupported version")
        raw_units = payload.get("units")
        if not isinstance(raw_units, list) or not raw_units:
            raise ReleaseError("release manifest must contain units")
        units: list[ReleaseUnit] = []
        identifiers: set[str] = set()
        for raw in raw_units:
            if not isinstance(raw, dict):
                raise ReleaseError("release manifest unit must be an object")
            identifier = raw.get("id")
            handler = raw.get("handler")
            paths = raw.get("paths")
            dependencies = raw.get("depends_on", [])
            wrappers = raw.get("wrappers", [])
            runtime = raw.get("runtime")
            verification = raw.get("verification", "checksum-only")
            if (
                not isinstance(identifier, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", identifier)
                or identifier in identifiers
            ):
                raise ReleaseError("release manifest has an invalid or duplicate unit id")
            if handler not in KNOWN_HANDLERS:
                raise ReleaseError(f"release manifest unit {identifier} has an unknown handler")
            if not isinstance(paths, list) or not paths or not all(isinstance(item, str) and item for item in paths):
                raise ReleaseError(f"release manifest unit {identifier} has invalid paths")
            if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                raise ReleaseError(f"release manifest unit {identifier} has invalid dependencies")
            if not isinstance(wrappers, list):
                raise ReleaseError(f"release manifest unit {identifier} has invalid wrappers")
            normalized_wrappers: list[tuple[str, str]] = []
            for wrapper in wrappers:
                if (
                    not isinstance(wrapper, dict)
                    or not isinstance(wrapper.get("source"), str)
                    or not isinstance(wrapper.get("destination"), str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.sh", wrapper["source"])
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.sh", wrapper["destination"])
                ):
                    raise ReleaseError(f"release manifest unit {identifier} has invalid wrappers")
                normalized_wrappers.append((wrapper["source"], wrapper["destination"]))
            if handler == "runtime" and (
                not isinstance(runtime, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", runtime)
            ):
                raise ReleaseError(f"release manifest runtime unit {identifier} has an invalid runtime")
            if handler != "runtime" and (runtime is not None or wrappers):
                raise ReleaseError(f"release manifest non-runtime unit {identifier} has runtime fields")
            if not isinstance(verification, str) or not verification:
                raise ReleaseError(f"release manifest unit {identifier} has invalid verification")
            identifiers.add(identifier)
            units.append(
                ReleaseUnit(
                    identifier=identifier,
                    handler=handler,
                    paths=tuple(paths),
                    dependencies=tuple(dependencies),
                    runtime=runtime,
                    wrappers=tuple(normalized_wrappers),
                    verification=verification,
                )
            )
        known = {unit.identifier for unit in units}
        for unit in units:
            if unit.identifier in unit.dependencies or not set(unit.dependencies) <= known:
                raise ReleaseError(f"release manifest unit {unit.identifier} has an invalid dependency")
        return cls(units=tuple(units))

    def matching_units(self, changed_paths: Sequence[str]) -> tuple[ReleaseUnit, ...]:
        selected: dict[str, ReleaseUnit] = {}
        for changed_path in changed_paths:
            matches = [
                unit
                for unit in self.units
                if any(fnmatch.fnmatchcase(changed_path, pattern) for pattern in unit.paths)
            ]
            if len(matches) != 1:
                raise ReleaseError(
                    "release manifest must map each changed path exactly once: " + changed_path
                )
            selected[matches[0].identifier] = matches[0]
        by_id = {unit.identifier: unit for unit in self.units}
        pending = list(selected.values())
        while pending:
            unit = pending.pop()
            for dependency_id in unit.dependencies:
                dependency = by_id[dependency_id]
                if dependency.identifier not in selected:
                    selected[dependency.identifier] = dependency
                    pending.append(dependency)
        return _topological_order(tuple(selected.values()))


def _topological_order(units: Sequence[ReleaseUnit]) -> tuple[ReleaseUnit, ...]:
    by_id = {unit.identifier: unit for unit in units}
    ordered: list[ReleaseUnit] = []
    active: set[str] = set()
    visited: set[str] = set()

    def visit(unit: ReleaseUnit) -> None:
        if unit.identifier in visited:
            return
        if unit.identifier in active:
            raise ReleaseError("release manifest dependencies contain a cycle")
        active.add(unit.identifier)
        for dependency in unit.dependencies:
            if dependency in by_id:
                visit(by_id[dependency])
        active.remove(unit.identifier)
        visited.add(unit.identifier)
        ordered.append(unit)

    for unit in units:
        visit(unit)
    return tuple(ordered)


class ReleaseStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records = root / "records"
        self.state_path = root / "state.json"

    def initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.records.mkdir(mode=0o700, parents=True, exist_ok=True)

    def read_state(self) -> dict[str, Any]:
        self.initialize()
        if not self.state_path.exists():
            return {
                "version": STATE_VERSION,
                "last_success_sha": None,
                "blocked": None,
                "transient": None,
                "github_status": None,
            }
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseError("release state is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            raise ReleaseError("release state has an unsupported version")
        payload.setdefault("last_success_sha", None)
        payload.setdefault("blocked", None)
        payload.setdefault("transient", None)
        payload.setdefault("github_status", None)
        return payload

    def write_state(self, state: dict[str, Any]) -> None:
        state = dict(state)
        state["version"] = STATE_VERSION
        self._write_json(self.state_path, state)

    def record(self, sha: str, status: str, **details: Any) -> None:
        if not SHA_RE.fullmatch(sha):
            raise ReleaseError("release record SHA is invalid")
        path = self.records / f"{sha}.json"
        history: list[dict[str, Any]] = []
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReleaseError("existing release record is unreadable") from exc
            if (
                not isinstance(existing, dict)
                or existing.get("version") != STATE_VERSION
                or existing.get("sha") != sha
                or not isinstance(existing.get("history", []), list)
            ):
                raise ReleaseError("existing release record has an unsupported format")
            history = existing["history"]
        event = {"status": status, "at": _now().isoformat(), **details}
        history.append(event)
        payload = {
            "version": STATE_VERSION,
            "sha": sha,
            "status": status,
            "updated_at": event["at"],
            "history": history,
            **details,
        }
        self._write_json(path, payload)

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        self.initialize()
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


class GitHubClient:
    RELEASE_STATUS_CONTEXT = "bursawatch/release"
    RELEASE_STATUS_STATES = frozenset({"error", "failure", "pending", "success"})

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def current_main_sha(self) -> str:
        payload = self._request_json(f"/repos/{self.settings.repository}/commits/{self.settings.branch}")
        if not isinstance(payload, dict) or not isinstance(payload.get("sha"), str):
            raise TransientReleaseError("GitHub did not return the current main SHA")
        sha = payload["sha"].lower()
        if not SHA_RE.fullmatch(sha):
            raise TransientReleaseError("GitHub returned an invalid main SHA")
        return sha

    def has_successful_ci(self, sha: str) -> bool:
        query = urlencode({"branch": self.settings.branch, "event": "push", "status": "completed", "per_page": 100})
        payload = self._request_json(f"/repos/{self.settings.repository}/actions/runs?{query}")
        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            raise TransientReleaseError("GitHub did not return workflow runs")
        for run in payload["workflow_runs"]:
            if not isinstance(run, dict):
                continue
            if (
                run.get("head_sha") == sha
                and run.get("name") == "CI"
                and run.get("conclusion") == "success"
            ):
                return True
        return False

    def publish_release_status(
        self,
        sha: str,
        *,
        state: str,
        description: str,
        target_url: str | None = None,
    ) -> bool:
        """Best-effort commit status publication for the external release gate."""
        if not self.settings.status_token:
            return False
        if not SHA_RE.fullmatch(sha) or state not in self.RELEASE_STATUS_STATES:
            return False
        target = target_url or self.settings.status_target_url or f"https://github.com/{self.settings.repository}/commit/{sha}"
        payload = {
            "state": state,
            "target_url": target,
            "description": _safe_reason(description)[:140],
            "context": self.RELEASE_STATUS_CONTEXT,
        }
        try:
            self._request_json(
                f"/repos/{self.settings.repository}/statuses/{sha}",
                method="POST",
                token=self.settings.status_token,
                payload=payload,
            )
        except ReleaseError:
            # GitHub visibility must never turn a safe release outcome into a
            # deployment failure. The durable release record remains canonical.
            return False
        return True

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        token: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> object:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.settings.token if token is None else token}",
            "User-Agent": "bursawatch-release-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.settings.github_api_url + path,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ReleaseError(f"GitHub authorization failed ({exc.code})") from exc
            if exc.code == 404:
                raise ReleaseError("GitHub repository or workflow endpoint was not found") from exc
            raise TransientReleaseError(f"GitHub API returned {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TransientReleaseError("GitHub API request failed") from exc


class GitMirror:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mirror = settings.state_root / "mirror.git"
        self.worktrees = settings.state_root / "worktrees"

    def materialize(self, sha: str) -> Path:
        self.worktrees.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._ensure_mirror()
        self._fetch_main()
        remote_sha = self._git("--git-dir", str(self.mirror), "rev-parse", "refs/remotes/origin/main").strip().lower()
        if remote_sha != sha:
            raise TransientReleaseError("GitHub main SHA and fetched origin/main do not match")
        self._git("--git-dir", str(self.mirror), "cat-file", "-e", f"{sha}^{{commit}}")
        worktree = self.worktrees / sha
        if worktree.exists():
            head = self._git("-C", str(worktree), "rev-parse", "HEAD").strip().lower()
            if head != sha:
                raise ReleaseError("existing release worktree has an unexpected SHA")
            return worktree
        self._git("--git-dir", str(self.mirror), "worktree", "add", "--detach", str(worktree), sha)
        return worktree

    def changed_paths(self, worktree: Path, base_sha: str | None, sha: str) -> list[str]:
        if base_sha:
            if not SHA_RE.fullmatch(base_sha):
                raise ReleaseError("release state has an invalid last successful SHA")
            self._git("--git-dir", str(self.mirror), "cat-file", "-e", f"{base_sha}^{{commit}}")
            output = self._git("-C", str(worktree), "diff", "--name-only", "--no-renames", base_sha, sha, "--")
        else:
            output = self._git("-C", str(worktree), "ls-tree", "-r", "--name-only", sha)
        return sorted({line.strip() for line in output.splitlines() if line.strip()})

    def _ensure_mirror(self) -> None:
        if not self.mirror.exists():
            self.mirror.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._git("init", "--bare", str(self.mirror))
            self._git("--git-dir", str(self.mirror), "remote", "add", "origin", self._origin_url())
            return
        if not self.mirror.is_dir():
            raise ReleaseError("release mirror path is not a directory")
        origin = self._git("--git-dir", str(self.mirror), "remote", "get-url", "origin").strip()
        if origin != self._origin_url():
            raise ReleaseError("release mirror origin does not match the configured repository")

    def _fetch_main(self) -> None:
        try:
            with self._askpass_environment() as environment:
                self._git(
                    "--git-dir",
                    str(self.mirror),
                    "fetch",
                    "--prune",
                    "origin",
                    f"+refs/heads/{self.settings.branch}:refs/remotes/origin/{self.settings.branch}",
                    environment=environment,
                )
        except DeploymentError as exc:
            raise TransientReleaseError("Git fetch failed") from exc

    def _origin_url(self) -> str:
        return f"https://github.com/{self.settings.repository}.git"

    @contextmanager
    def _askpass_environment(self) -> Iterator[dict[str, str]]:
        helpers = self.settings.state_root / "tmp"
        helpers.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=helpers, prefix="git-askpass-", delete=False) as stream:
            helper = Path(stream.name)
            stream.write("#!/bin/sh\n")
            stream.write('case "$1" in\n')
            stream.write('  *Username*) printf "%s\\n" "x-access-token" ;;\n')
            stream.write('  *Password*) printf "%s\\n" "$BURSAWATCH_RELEASE_GITHUB_TOKEN" ;;\n')
            stream.write('  *) exit 1 ;;\n')
            stream.write("esac\n")
        os.chmod(helper, 0o700)
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_ASKPASS": str(helper),
                "GIT_TERMINAL_PROMPT": "0",
                "BURSAWATCH_RELEASE_GITHUB_TOKEN": self.settings.token,
            }
        )
        try:
            yield environment
        finally:
            helper.unlink(missing_ok=True)

    def _git(self, *arguments: str, environment: dict[str, str] | None = None) -> str:
        return _run_command(("git", *arguments), environment=environment, timeout=self.settings.timeout_seconds)


@dataclass
class ReleaseDeployer:
    settings: Settings
    release_sha: str
    checkout: Path
    completed_units: list[str] = field(default_factory=list)

    def deploy(self, unit: ReleaseUnit) -> None:
        if unit.handler == "metadata":
            self.completed_units.append(unit.identifier)
            return
        if unit.handler == "runtime":
            self._deploy_runtime(unit)
        elif unit.handler == "control-plane":
            self._deploy_control_plane(unit)
        else:
            raise DeploymentError(f"release unit has an unsupported deployment handler: {unit.identifier}")
        self.completed_units.append(unit.identifier)

    def _deploy_runtime(self, unit: ReleaseUnit) -> None:
        if unit.runtime is None:
            raise DeploymentError(f"runtime unit missing runtime identity: {unit.identifier}")
        source_root = _single_package_root(unit.paths)
        source = self.checkout / source_root
        target = self.settings.runtime_home / unit.runtime
        if not source.is_dir():
            raise DeploymentError(f"runtime source is missing: {source_root}")
        bin_source = source / "bin"
        if not bin_source.is_dir():
            raise DeploymentError(f"runtime source has no bin directory: {source_root}")
        _sync_tree(bin_source, target / "bin")
        _verify_tree(bin_source, target / "bin")
        config_source = source / "config"
        if config_source.is_dir():
            _sync_tree(config_source, target / "config")
            _verify_tree(config_source, target / "config")
        for document in ("SKILL.md", "CRON.md"):
            source_document = source / document
            if source_document.is_file():
                _sync_file(source_document, target / document, executable=False)
                _verify_file(source_document, target / document)
        scripts_directory = self.settings.runtime_home.parent.parent / ".hermes" / "scripts"
        for source_name, destination_name in unit.wrappers:
            source_wrapper = bin_source / source_name
            if not source_wrapper.is_file():
                raise DeploymentError(f"runtime wrapper is missing: {source_root}/bin/{source_name}")
            target_wrapper = scripts_directory / destination_name
            _sync_file(source_wrapper, target_wrapper, executable=True)
            _verify_file(source_wrapper, target_wrapper)
        self._run_verification(unit.verification)

    def _deploy_control_plane(self, unit: ReleaseUnit) -> None:
        source = self.checkout / "service-bursawatch-control"
        target = self.settings.control_plane_runtime
        for directory in ("baseline-configs", "bin", "migrations", "validator-sources"):
            source_directory = source / directory
            if not source_directory.is_dir():
                raise DeploymentError(f"control-plane source directory is missing: {directory}")
            _sync_tree(source_directory, target / directory)
            _verify_tree(source_directory, target / directory)
        _sync_file(source / "requirements.txt", target / "requirements.txt", executable=False)
        _verify_file(source / "requirements.txt", target / "requirements.txt")
        python = target / "venv/bin/python"
        if not python.is_file() or not os.access(python, os.X_OK):
            raise DeploymentError("control-plane virtual environment is unavailable")
        environment = _read_environment_file(self.settings.control_plane_env)
        if not environment.get("DATABASE_URL"):
            raise DeploymentError("control-plane environment does not provide DATABASE_URL")
        _run_command(
            (str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--requirement", "requirements.txt"),
            cwd=target,
            environment=environment,
            timeout=300,
        )
        _run_command((str(python), "bin/migrate.py"), cwd=target, environment=environment, timeout=120)
        _run_command((str(python), "bin/seed_baseline_configs.py"), cwd=target, environment=environment, timeout=120)
        _run_command(
            ("sudo", "--non-interactive", "/usr/bin/systemctl", "restart", "bursawatch-control-plane.service"),
            timeout=60,
        )
        self._run_verification(unit.verification)

    def _run_verification(self, verification: str) -> None:
        if verification == "checksum-only":
            return
        if verification == "control-plane-health":
            _wait_for_control_plane_health(timeout=self.settings.timeout_seconds)
            return
        specification = _no_post_specification(verification, self.settings.state_root)
        try:
            output = _run_command(specification.command, environment=specification.environment, timeout=300)
            if verification == "stockbit-snips-no-post":
                _verify_stockbit_no_post(output, Path(specification.environment["STOCKBIT_SNIPS_STATE_PATH"]))
            elif verification == "telegram-source-ingest-no-post":
                _verify_telegram_source_ingest_no_post(output)
            elif verification == "x-source-ingest-no-post":
                _verify_x_source_ingest_no_post(output)
            elif verification == "rss-source-ingest-no-post":
                _verify_synthetic_source_ingest_no_post(output, "RSS")
        except CommandFailure as exc:
            exc.add_details(
                verification=verification,
                temporary_path=str(specification.temporary_path),
            )
            raise
        finally:
            shutil.rmtree(specification.temporary_path, ignore_errors=True)


@dataclass(frozen=True)
class NoPostSpecification:
    command: tuple[str, ...]
    environment: dict[str, str]
    temporary_path: Path


def _verify_stockbit_no_post(output: str, state_path: Path) -> None:
    """Require evidence that an isolated Stockbit run loaded live config."""
    failure = DeploymentError("Stockbit no-post did not confirm a successful live config read")
    try:
        lines = output.strip().splitlines()
        result = json.loads(lines[-1]) if lines else None
        state = json.loads(state_path.read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(state["last_heartbeat"])
    except (IndexError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise failure from None
    if (
        not isinstance(result, dict)
        or result.get("wakeAgent") is not False
        or result.get("items") != []
        or not isinstance(result.get("stats"), dict)
        or result["stats"].get("degraded") is not False
        or result["stats"].get("errors") != []
        or not isinstance(state, dict)
        or state.get("version") != 2
        or state.get("articles") != {}
        or timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise failure


def _verify_telegram_source_ingest_no_post(output: str) -> None:
    """Require a synthetic adapter result with explicit no-side-effect claims."""
    _verify_synthetic_source_ingest_no_post(output, "Telegram")


def _verify_x_source_ingest_no_post(output: str) -> None:
    """Require a synthetic adapter result with explicit no-side-effect claims."""
    _verify_synthetic_source_ingest_no_post(output, "X")


def _verify_synthetic_source_ingest_no_post(output: str, platform: str) -> None:
    failure = DeploymentError(f"{platform} source-ingest synthetic verification did not confirm isolation")
    try:
        lines = output.strip().splitlines()
        result = json.loads(lines[-1]) if lines else None
    except (IndexError, ValueError, json.JSONDecodeError):
        raise failure from None
    if (
        not isinstance(result, dict)
        or result.get("outcome") != "synthetic-ok"
        or result.get("network") is not False
        or result.get("secrets") is not False
        or result.get("writes") is not False
        or result.get("events") != 1
        or not isinstance(result.get("content_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", result["content_hash"])
    ):
        raise failure


def _no_post_specification(verification: str, state_root: Path) -> NoPostSpecification:
    temporary = state_root / "no-post" / verification
    temporary.mkdir(mode=0o700, parents=True, exist_ok=True)
    unique = tempfile.mkdtemp(prefix="run-", dir=temporary)
    base = Path(unique)
    home = Path.home()
    scripts = home / ".hermes/scripts"
    environment = dict(os.environ)
    environment["BURSAWATCH_RELEASE_NO_POST_TEMP"] = str(base)
    environment["BURSAWATCH_RELEASE_NO_POST"] = "1"
    if verification == "market-news-no-post":
        environment.update(
            {
                "IDX_MARKET_NEWS_NO_POST": "1",
                "IDX_MARKET_NEWS_STATE_PATH": str(base / "state.json"),
                "IDX_MARKET_NEWS_FORCE_HEARTBEAT": "1",
                "IDX_MARKET_NEWS_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-tg-market-news.sh"),)
    elif verification == "phintraco-no-post":
        environment.update(
            {
                "IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST": "1",
                "IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH": str(base / "state.json"),
                "IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT": "1",
                "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-tg-phintraco-swing.sh"),)
    elif verification == "kelas-no-post":
        environment.update(
            {
                "KELAS_INVESTASI_GTW_NO_POST": "1",
                "KELAS_INVESTASI_GTW_STATE_PATH": str(base / "state.json"),
                "KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT": str(base / "media"),
                "KELAS_INVESTASI_GTW_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-tg-kelas-investasi-gtw.sh"),)
    elif verification == "swing-board-no-post":
        environment.update(
            {
                "IDX_SWING_PLAN_BOARD_NO_POST": "1",
                "IDX_SWING_PLAN_BOARD_STATE_PATH": str(base / "state.sqlite3"),
                "IDX_SWING_PLAN_BOARD_MEDIA_ROOT": str(base / "media"),
                "IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-dc-swing-board.sh"), "drain")
    elif verification == "x-no-post":
        environment.update(
            {
                "X_POST_WATCH_NO_POST": "1",
                "X_POST_WATCH_QUEUE_ONLY": "1",
                "X_POST_WATCH_STATE_PATH": str(base / "state.json"),
                "X_POST_WATCH_VISION_MEDIA_ROOT": str(base / "vision"),
                "X_POST_WATCH_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-x-account-watch-queue.sh"),)
    elif verification == "instagram-no-post":
        environment.update(
            {
                "INSTAGRAM_POST_WATCH_NO_POST": "1",
                "INSTAGRAM_POST_WATCH_STATE_PATH": str(base / "state.json"),
                "INSTAGRAM_POST_WATCH_MEDIA_ROOT": str(base / "media"),
                "INSTAGRAM_POST_WATCH_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-ig-account-watch.sh"),)
    elif verification == "whatsapp-no-post":
        environment.update(
            {
                "WHATSAPP_CHANNEL_WATCH_NO_POST": "1",
                "WHATSAPP_CHANNEL_WATCH_STATE_PATH": str(base / "state.json"),
                "WHATSAPP_CHANNEL_WATCH_QUEUE_DIR": str(base / "queue"),
                "WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL": "",
            }
        )
        command = (str(scripts / "bursawatch-wa-channel-watch.sh"),)
    elif verification == "stockbit-snips-no-post":
        # The wrapper imports the read credentials for its mandatory config GET.
        # Keep this isolated run free of inherited event-spool settings.
        environment.pop("STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH", None)
        environment.update(
            {
                "STOCKBIT_SNIPS_NO_POST": "1",
                "STOCKBIT_SNIPS_STATE_PATH": str(base / "state.json"),
            }
        )
        command = (str(scripts / "bursawatch-stockbit-snips.sh"),)
    elif verification == "telegram-source-ingest-no-post":
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TZ": "Asia/Jakarta",
            "LANG": "C.UTF-8",
            "BURSAWATCH_RELEASE_NO_POST": "1",
            "BURSAWATCH_RELEASE_NO_POST_TEMP": str(base),
        }
        command = (str(scripts / "bursawatch-tg-source-ingest.sh"),)
    elif verification == "x-source-ingest-no-post":
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TZ": "Asia/Jakarta",
            "LANG": "C.UTF-8",
            "BURSAWATCH_RELEASE_NO_POST": "1",
            "BURSAWATCH_RELEASE_NO_POST_TEMP": str(base),
        }
        command = (str(scripts / "bursawatch-x-source-ingest.sh"),)
    elif verification == "rss-source-ingest-no-post":
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TZ": "Asia/Jakarta",
            "LANG": "C.UTF-8",
            "BURSAWATCH_RELEASE_NO_POST": "1",
            "BURSAWATCH_RELEASE_NO_POST_TEMP": str(base),
        }
        command = (str(scripts / "bursawatch-rss-source-ingest.sh"),)
    else:
        raise DeploymentError(f"release manifest references an unknown verification: {verification}")
    return NoPostSpecification(command=command, environment=environment, temporary_path=base)


def _publish_release_status(
    github: object | None,
    store: ReleaseStore,
    durable_state: dict[str, Any],
    sha: str | None,
    *,
    github_state: str,
    description: str,
) -> None:
    if github is None or not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        return
    safe_description = _safe_reason(description)[:140]
    status_record = {
        "sha": sha,
        "state": github_state,
        "description": safe_description,
    }
    if durable_state.get("github_status") == status_record:
        return
    publisher = getattr(github, "publish_release_status", None)
    if not callable(publisher):
        return
    try:
        published = publisher(sha, state=github_state, description=safe_description, target_url=None)
    except Exception:
        # GitHub status is observability only. The local release record and
        # heartbeat remain authoritative when the status endpoint is down.
        return
    if published is False:
        return
    durable_state["github_status"] = status_record
    store.write_state(durable_state)


def release_once(settings: Settings, *, allow_manual: bool = False) -> str:
    store = ReleaseStore(settings.state_root)
    with _release_lock(settings.state_root):
        state = store.read_state()
        candidate_sha: str | None = None
        github: object | None = None
        try:
            github = GitHubClient(settings)
            blocked = state.get("blocked")
            if isinstance(blocked, dict) and blocked.get("sha") is None and not allow_manual:
                return "blocked"
            sha = github.current_main_sha()
            candidate_sha = sha
            if isinstance(blocked, dict) and blocked.get("sha") == sha and not allow_manual:
                _publish_release_status(
                    github,
                    store,
                    state,
                    sha,
                    github_state=blocked.get("github_state", "failure"),
                    description=blocked.get("reason", "release blocked"),
                )
                return "blocked"
            if isinstance(blocked, dict) and blocked.get("sha") != sha:
                state["blocked"] = None
                store.write_state(state)
            if state.get("last_success_sha") == sha:
                return "already-released"
            transient = state.get("transient")
            if _transient_backoff_active(transient, sha):
                attempts = transient.get("attempts", 1) if isinstance(transient, dict) else 1
                reason = transient.get("reason", "retrying release") if isinstance(transient, dict) else "retrying release"
                _publish_release_status(
                    github,
                    store,
                    state,
                    sha,
                    github_state="pending",
                    description=f"retry-{attempts}: {reason}",
                )
                return "backoff"
            if not github.has_successful_ci(sha):
                _publish_release_status(
                    github,
                    store,
                    state,
                    sha,
                    github_state="pending",
                    description="waiting-for-ci",
                )
                return "waiting-for-ci"
            mirror = GitMirror(settings)
            worktree = mirror.materialize(sha)
            changed_paths = mirror.changed_paths(worktree, state.get("last_success_sha"), sha)
            manual_migrations = _changed_manual_migrations(worktree, changed_paths)
            if manual_migrations and not allow_manual:
                reason = "manual migrations require an explicit operations release"
                _block_release(
                    store,
                    state,
                    sha,
                    reason,
                    github_state="pending",
                    changed_paths=changed_paths,
                    manual_migrations=manual_migrations,
                )
                _publish_release_status(
                    github,
                    store,
                    state,
                    sha,
                    github_state="pending",
                    description=reason,
                )
                _send_heartbeat(
                    settings,
                    f"❌ bursawatch-release · {_wib_time()} WIB · blocked manual-migration",
                )
                return "manual-required"
            manifest = ReleaseManifest.load(worktree / MANIFEST_FILE)
            units = manifest.matching_units(changed_paths)
            manual_units = [unit.identifier for unit in units if unit.handler == "manual"]
            if manual_units and not allow_manual:
                reason = "manual release units require an explicit operator action"
                _block_release(
                    store,
                    state,
                    sha,
                    reason,
                    github_state="pending",
                    units=[unit.identifier for unit in units],
                    manual_units=manual_units,
                )
                _publish_release_status(
                    github,
                    store,
                    state,
                    sha,
                    github_state="pending",
                    description=reason,
                )
                _send_heartbeat(settings, f"❌ bursawatch-release · {_wib_time()} WIB · blocked manual={','.join(manual_units)}")
                return "manual-required"
            deployer = ReleaseDeployer(settings=settings, release_sha=sha, checkout=worktree)
            for unit in units:
                if unit.handler != "manual":
                    deployer.deploy(unit)
            state["last_success_sha"] = sha
            state["blocked"] = None
            state["transient"] = None
            store.write_state(state)
            store.record(
                sha,
                "released",
                units=deployer.completed_units,
                manual_migrations=manual_migrations,
                skipped_manual_units=manual_units,
                changed_paths=changed_paths,
            )
            _publish_release_status(
                github,
                store,
                state,
                sha,
                github_state="success",
                description=f"released {len(deployer.completed_units)} units",
            )
            _send_heartbeat(
                settings,
                f"🫀 bursawatch-release · {_wib_time()} WIB · sha={sha[:8]} units={len(deployer.completed_units)}",
            )
            return "released"
        except TransientReleaseError as exc:
            sha = candidate_sha or _best_effort_sha(state)
            failure_count = _record_transient_failure(store, state, sha, str(exc))
            _publish_release_status(
                github,
                store,
                state,
                sha,
                github_state="pending",
                description=f"retry-{failure_count}: {_safe_reason(exc)}",
            )
            _send_heartbeat(
                settings,
                f"🫀 bursawatch-release · {_wib_time()} WIB · retry={failure_count} ⚠️",
            )
            return "transient-failure"
        except (ReleaseError, OSError, subprocess.SubprocessError) as exc:
            sha = candidate_sha or _best_effort_sha(state)
            details = _failure_details(exc)
            _block_release(store, state, sha, _safe_reason(exc), **details)
            _publish_release_status(
                github,
                store,
                state,
                sha,
                github_state="failure",
                description=_safe_reason(exc),
            )
            _send_heartbeat(settings, f"❌ bursawatch-release · {_wib_time()} WIB · blocked")
            return "blocked"


def clear_block(settings: Settings) -> None:
    store = ReleaseStore(settings.state_root)
    with _release_lock(settings.state_root):
        state = store.read_state()
        blocked = state.get("blocked")
        state["blocked"] = None
        state["transient"] = None
        store.write_state(state)
        if isinstance(blocked, dict) and isinstance(blocked.get("sha"), str) and SHA_RE.fullmatch(blocked["sha"]):
            store.record(blocked["sha"], "block-cleared")


def _block_release(
    store: ReleaseStore,
    state: dict[str, Any],
    sha: str | None,
    reason: str,
    github_state: str = "failure",
    **details: Any,
) -> None:
    state["blocked"] = {
        "sha": sha,
        "reason": _safe_reason(reason),
        "github_state": github_state,
        "blocked_at": _now().isoformat(),
    }
    state["transient"] = None
    store.write_state(state)
    if isinstance(sha, str) and SHA_RE.fullmatch(sha):
        store.record(sha, "blocked", reason=_safe_reason(reason), github_state=github_state, **details)


def _record_transient_failure(
    store: ReleaseStore, state: dict[str, Any], sha: str | None, reason: str
) -> int:
    previous = state.get("transient")
    attempts = 1
    if isinstance(previous, dict) and previous.get("sha") == sha:
        attempts = int(previous.get("attempts", 0)) + 1
    delay = min(900, 60 * (2 ** min(attempts - 1, 4)))
    state["transient"] = {
        "sha": sha,
        "attempts": attempts,
        "next_attempt_at": (_now() + timedelta(seconds=delay)).isoformat(),
        "reason": _safe_reason(reason),
    }
    store.write_state(state)
    if isinstance(sha, str) and SHA_RE.fullmatch(sha):
        store.record(sha, "transient-failure", attempts=attempts, retry_after_seconds=delay, reason=_safe_reason(reason))
    return attempts


def _transient_backoff_active(value: object, sha: str) -> bool:
    if not isinstance(value, dict) or value.get("sha") not in {sha, None}:
        return False
    raw = value.get("next_attempt_at")
    if not isinstance(raw, str):
        return False
    try:
        return datetime.fromisoformat(raw) > _now()
    except ValueError:
        return False


@contextmanager
def _release_lock(state_root: Path) -> Iterator[None]:
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = state_root / "release.lock"
    with lock_path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransientReleaseError("another release is already in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _single_package_root(patterns: Sequence[str]) -> Path:
    roots = {pattern.split("/", 1)[0] for pattern in patterns if "/" in pattern}
    if len(roots) != 1:
        raise DeploymentError("runtime unit must have one package root")
    return Path(roots.pop())


def _changed_manual_migrations(worktree: Path, changed_paths: Sequence[str]) -> list[str]:
    migration_paths = [
        path
        for path in changed_paths
        if path.startswith("service-bursawatch-control/migrations/") and path.endswith(".sql")
    ]
    if not migration_paths:
        return []
    policy_path = worktree / LEGACY_MIGRATION_POLICY_FILE
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        legacy = policy["migrations"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseError("legacy migration eligibility registry is unreadable") from exc
    if not isinstance(legacy, dict):
        raise ReleaseError("legacy migration eligibility registry is invalid")
    manual: list[str] = []
    for relative_path in migration_paths:
        name = Path(relative_path).name
        sql = (worktree / relative_path).read_text(encoding="utf-8")
        header = MIGRATION_RELEASE_HEADER_RE.match(sql)
        if header is not None:
            eligibility = header.group(1).lower()
            if name in legacy:
                raise ReleaseError(f"legacy migration must remain headerless: {name}")
        else:
            eligibility = legacy.get(name)
            if eligibility not in {"automatic", "manual"}:
                raise ReleaseError(f"migration release eligibility is missing: {name}")
        if eligibility == "manual":
            manual.append(name)
    return sorted(manual)


def _sync_tree(source: Path, target: Path) -> None:
    _ensure_safe_directory(target)
    target.mkdir(mode=0o750, parents=True, exist_ok=True)
    _run_command(
        (
            "rsync",
            "-a",
            "--checksum",
            "--no-perms",
            "--no-times",
            "--omit-dir-times",
            "--delete",
            "--exclude=__pycache__/",
            "--exclude=*.pyc",
            f"{source}/",
            f"{target}/",
        ),
        timeout=120,
    )


def _sync_file(source: Path, target: Path, *, executable: bool) -> None:
    _ensure_safe_directory(target.parent)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(source, temporary)
    os.chmod(temporary, 0o750 if executable else 0o640)
    os.replace(temporary, target)


def _ensure_safe_directory(path: Path) -> None:
    resolved = path.expanduser().resolve()
    permitted_roots = (
        Path.home().joinpath(".agents/skills").resolve(),
        Path.home().joinpath(".hermes").resolve(),
    )
    if not any(resolved == root or root in resolved.parents for root in permitted_roots):
        raise DeploymentError("release target is outside the approved runtime roots")


def _verify_tree(source: Path, target: Path) -> None:
    for source_file in sorted(source.rglob("*")):
        if source_file.is_symlink():
            raise DeploymentError(f"release source must not contain symlinks: {source_file.name}")
        if source_file.is_file():
            _verify_file(source_file, target / source_file.relative_to(source))


def _verify_file(source: Path, target: Path) -> None:
    if not target.is_file() or _sha256(source) != _sha256(target):
        raise DeploymentError(f"release checksum mismatch: {source.name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_environment_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DeploymentError("control-plane environment file is unavailable")
    environment = dict(os.environ)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise DeploymentError("control-plane environment file has an invalid entry")
        environment[key] = value
    return environment


def _read_json_url(url: str, *, timeout: float) -> object:
    try:
        with urlopen(Request(url, headers={"User-Agent": "bursawatch-release-agent"}), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DeploymentError("control-plane health request failed") from exc


def _wait_for_control_plane_health(*, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: DeploymentError | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeploymentError("control-plane did not become healthy before the release timeout") from last_error
        try:
            payload = _read_json_url(
                "http://127.0.0.1:9120/healthz",
                timeout=min(remaining, 5),
            )
            if payload == {"status": "ok"}:
                return
            last_error = DeploymentError("control-plane loopback health response was unexpected")
        except DeploymentError as exc:
            last_error = exc
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    timeout: float = 120,
) -> str:
    try:
        completed = subprocess.run(
            list(command),
            cwd=None if cwd is None else str(cwd),
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandFailure(
            command,
            None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
        ) from exc
    except OSError as exc:
        raise CommandFailure(command, None, stderr=str(exc)) from exc
    if completed.returncode != 0:
        raise CommandFailure(
            command,
            completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return completed.stdout


def _send_heartbeat(settings: Settings, content: str) -> None:
    try:
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        operation = OperationIntent(
            key=f"bursawatch-release:heartbeat:{content_digest}",
            kind="channel_message_create",
            ordering_key=f"channel:{settings.heartbeat_channel_id}",
            target={"channel_id": settings.heartbeat_channel_id},
            payload={"content": content, "allowed_mentions": {"parse": []}},
        )
        client = DeliveryClient(
            settings.delivery_owner_url,
            settings.delivery_client_token_file,
            timeout_seconds=settings.timeout_seconds,
        )
        client.submit(operation)
    except Exception:
        return


def _best_effort_sha(state: dict[str, Any]) -> str | None:
    blocked = state.get("blocked")
    if isinstance(blocked, dict) and isinstance(blocked.get("sha"), str) and SHA_RE.fullmatch(blocked["sha"]):
        return blocked["sha"]
    previous = state.get("last_success_sha")
    if isinstance(previous, str) and SHA_RE.fullmatch(previous):
        return previous
    return None


def _failure_details(error: BaseException) -> dict[str, Any]:
    if isinstance(error, CommandFailure):
        return dict(error.details)
    return {}


def _safe_output(value: object, *, limit: int = 4000) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = re.sub(r"(?i)\bbearer\s+[^\s]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)\b(token|secret|password|authorization)(\s*[:=]\s*)[^\s]+",
        r"\1\2<redacted>",
        text,
    )
    return text[:limit]


def _safe_reason(value: object) -> str:
    text = " ".join(_safe_output(value).split())
    return text[:300] or "release failure"


def _now() -> datetime:
    return datetime.now(UTC)


def _wib_time() -> str:
    return _now().astimezone(WIB).strftime("%H:%M")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="poll and process one automatic release candidate")
    mode.add_argument(
        "--release-manual",
        action="store_true",
        help="apply reviewed manual migrations and release eligible units alongside host work",
    )
    mode.add_argument("--clear-block", action="store_true", help="clear the current failed release block")
    mode.add_argument("--status", action="store_true", help="print durable release state without contacting GitHub")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_environment(require_token=not (args.status or args.clear_block))
        store = ReleaseStore(settings.state_root)
        if args.status:
            print(json.dumps(store.read_state(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.clear_block:
            clear_block(settings)
            print(json.dumps({"status": "block-cleared"}))
            return 0
        status = release_once(settings, allow_manual=args.release_manual)
        print(json.dumps({"status": status}))
        return {
            "released": 0,
            "already-released": 0,
            "waiting-for-ci": 0,
            "backoff": 0,
            "blocked": 1,
            "manual-required": 1,
            "transient-failure": 1,
        }.get(status, 1)
    except ReleaseError as exc:
        print(f"release refused: {_safe_reason(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
