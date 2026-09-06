#!/usr/bin/env python3
"""Run a local, state-free OCR benchmark over a scratch image directory."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import re
import resource
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from statistics import median
from typing import Sequence


_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from ocr import OCRBackend, OCRBackendUnavailable, OCRResult, OCRStatus, build_backend


IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
DEFAULT_LANGUAGES = ("ind", "eng")
DEFAULT_PREPROCESSING_VERSION = "preprocess-1"
MAX_NOTE_LENGTH = 2000
MAX_METADATA_LENGTH = 200
MAX_MANIFEST_FILES = 512
MIN_MODEL_ARTIFACT_BYTES = 256
FAILED_STATUSES = frozenset({OCRStatus.ERROR, OCRStatus.TIMEOUT, OCRStatus.UNAVAILABLE, OCRStatus.UNCERTAIN})
MAX_SANDBOX_ATTESTATION_BYTES = 8192
PADDLE_SANDBOX_WRAPPER = Path("/usr/bin/unshare")
PADDLE_SANDBOX_ATTESTATION = "unshare-user-network"
PADDLE_SANDBOX_FLAGS = ("-Urn", "--")


class BenchmarkInputError(ValueError):
    """Raised when the supplied scratch input or output cannot be used."""


@dataclass(frozen=True)
class BenchmarkResult:
    report: dict[str, object]
    failed: bool = False


@dataclass(frozen=True)
class PaddleAssetBoundary:
    model_dir: Path
    manifest_path: Path
    allowed_files: frozenset[str]
    initial_snapshot: dict[str, tuple[str, int, str]]
    bindings: dict[str, dict[str, object]]
    verified_runtime: dict[str, str]
    temp_dir: Path


def _peak_rss_bytes() -> int:
    usage = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    if sys.platform == "darwin":
        return int(usage)
    return int(usage * 1024)


def _normalise_languages(values: Sequence[str]) -> tuple[str, ...]:
    languages: list[str] = []
    for value in values:
        for language in value.split(","):
            language = language.strip().lower()
            if language and language not in languages:
                if not re.fullmatch(r"[a-z0-9_-]{1,32}", language):
                    raise BenchmarkInputError("OCR language is invalid")
                languages.append(language)
    if not languages:
        raise BenchmarkInputError("at least one OCR language is required")
    return tuple(languages)


def _safe_label(value: object) -> str:
    label = str(value)
    return label[:MAX_METADATA_LENGTH] if re.fullmatch(r"[A-Za-z0-9_.:+-]{1,200}", label) else "unknown"


def _safe_notes(value: str) -> str:
    notes = re.sub(r"[\x00-\x1f\x7f]", " ", value[: MAX_NOTE_LENGTH * 4])
    notes = re.sub(
        r"(?i)\b(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD)|token|password|secret|api[_-]?key)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^,;\n]+)",
        "[redacted]",
        notes,
    )
    notes = re.sub(r"(?i)\bAuthorization\s*:\s*(?:Basic|Bearer)\s+[^,;\n]+", "[redacted]", notes)
    notes = re.sub(r"(?<![A-Za-z0-9])(?:/[^,;\n]+|[A-Za-z]:[\\/][^,;\n]+|\\\\[^,;\n]+|\.\.?[\\/][^,;\n]+)", "[path-redacted]", notes)
    return re.sub(r"\s+", " ", notes).strip()[:MAX_NOTE_LENGTH]


def _safe_preprocessing_version(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_METADATA_LENGTH:
        raise BenchmarkInputError("preprocessing version is invalid")
    if re.search(r"(?i)\b(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD)|token|password|secret|api[_-]?key)\s*[:=]", value):
        raise BenchmarkInputError("preprocessing version is invalid")
    normalized = re.sub(r"[^A-Za-z0-9_.:+-]", "_", value)
    if not normalized.strip("_."):
        raise BenchmarkInputError("preprocessing version is invalid")
    return normalized[:MAX_METADATA_LENGTH]


def _validate_destination(output: Path) -> Path:
    destination = output.absolute()
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise BenchmarkInputError("output path is invalid")
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        raise BenchmarkInputError("output directory is invalid")
    current = parent
    while True:
        if current.is_symlink():
            raise BenchmarkInputError("output directory is invalid")
        if current.parent == current:
            break
        current = current.parent
    return destination


def _reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            raise BenchmarkInputError("path contains a symlink")


def _safe_manifest_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_METADATA_LENGTH * 4:
        raise BenchmarkInputError("paddle model manifest is invalid")
    if re.search(r"[\x00-\x1f\x7f\\]", value):
        raise BenchmarkInputError("paddle model manifest is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts or not relative.parts:
        raise BenchmarkInputError("paddle model manifest is invalid")
    return relative.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_model_tree(model_dir: Path) -> dict[str, tuple[str, int, str]]:
    snapshot: dict[str, tuple[str, int, str]] = {}
    for path in sorted(model_dir.rglob("*"), key=lambda item: item.relative_to(model_dir).as_posix()):
        relative = path.relative_to(model_dir).as_posix()
        _reject_symlink_ancestors(path)
        if path.is_symlink():
            raise BenchmarkInputError("paddle model tree contains a symlink")
        if path.is_dir():
            snapshot[relative] = ("dir", 0, "")
        elif path.is_file():
            stat = path.stat()
            snapshot[relative] = ("file", stat.st_size, _file_sha256(path))
        else:
            raise BenchmarkInputError("paddle model tree contains an invalid entry")
    return snapshot


def _validate_paddle_manifest(
    model_dir: Path, manifest_path: Path
) -> tuple[
    frozenset[str],
    dict[str, tuple[str, int, str]],
    dict[str, dict[str, object]],
    dict[str, str],
]:
    _reject_symlink_ancestors(model_dir)
    _reject_symlink_ancestors(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_nlink != 1:
        raise BenchmarkInputError("paddle model manifest is invalid")
    try:
        manifest_root = manifest_path.relative_to(model_dir).as_posix()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BenchmarkInputError("paddle model manifest is invalid")
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), dict) or not isinstance(payload.get("verified_runtime"), dict):
        raise BenchmarkInputError("paddle model manifest is invalid")
    verified_runtime = payload["verified_runtime"]
    if verified_runtime.get("sandbox") != "preflight-verified":
        raise BenchmarkInputError("paddle runtime sandbox is not verified")
    if not isinstance(verified_runtime.get("paddle_version"), str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", verified_runtime["paddle_version"]):
        raise BenchmarkInputError("paddle runtime metadata is invalid")
    if not isinstance(verified_runtime.get("paddleocr_version"), str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", verified_runtime["paddleocr_version"]):
        raise BenchmarkInputError("paddle runtime metadata is invalid")
    if not isinstance(verified_runtime.get("constructor_api_sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", verified_runtime["constructor_api_sha256"]):
        raise BenchmarkInputError("paddle runtime metadata is invalid")
    names: list[str] = []
    bindings: dict[str, dict[str, object]] = {}
    for selection_id, model in payload["models"].items():
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", selection_id) or not isinstance(model, dict):
            raise BenchmarkInputError("paddle model manifest is invalid")
        model_root = _safe_manifest_name(model.get("model_dir"))
        artifacts = model.get("artifacts")
        constructor_kwargs = model.get("constructor_kwargs")
        if not isinstance(artifacts, list) or not artifacts or not isinstance(constructor_kwargs, dict) or not constructor_kwargs:
            raise BenchmarkInputError("paddle model manifest is invalid")
        absolute_model_root = model_dir / model_root
        _reject_symlink_ancestors(absolute_model_root)
        if absolute_model_root.is_symlink() or not absolute_model_root.is_dir():
            raise BenchmarkInputError("paddle model directory is missing")
        binding_artifacts: list[dict[str, str]] = []
        binding_kwargs: dict[str, object] = {}
        for key, value in constructor_kwargs.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
                raise BenchmarkInputError("paddle model constructor binding is invalid")
            if key.endswith("_dir"):
                if not isinstance(value, str):
                    raise BenchmarkInputError("paddle model constructor binding is invalid")
                relative_path = _safe_manifest_name(value)
                try:
                    relative_path_obj = PurePosixPath(relative_path)
                    relative_path_obj.relative_to(PurePosixPath(model_root))
                except ValueError as exc:
                    raise BenchmarkInputError("paddle model constructor binding is invalid") from exc
                bound_path = model_dir / relative_path
                _reject_symlink_ancestors(bound_path)
                if bound_path.is_symlink() or not bound_path.is_dir():
                    raise BenchmarkInputError("paddle model constructor binding is invalid")
                binding_kwargs[key] = str(bound_path)
            elif type(value) in {str, bool, int, float}:
                binding_kwargs[key] = value
            else:
                raise BenchmarkInputError("paddle model constructor binding is invalid")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise BenchmarkInputError("paddle model manifest is invalid")
            name = _safe_manifest_name(artifact.get("path"))
            digest = artifact.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise BenchmarkInputError("paddle model manifest is invalid")
            try:
                PurePosixPath(name).relative_to(PurePosixPath(model_root))
            except ValueError as exc:
                raise BenchmarkInputError("paddle model artifact is outside its model directory") from exc
            path = model_dir / name
            _reject_symlink_ancestors(path)
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                raise BenchmarkInputError("paddle model artifact is invalid")
            if path.stat().st_size < MIN_MODEL_ARTIFACT_BYTES or _file_sha256(path).lower() != digest.lower():
                raise BenchmarkInputError("paddle model artifact digest mismatch")
            names.append(name)
            binding_artifacts.append({"path": str(path), "sha256": digest.lower()})
        bindings[selection_id] = {
            "model_dir": str(absolute_model_root),
            "artifacts": binding_artifacts,
            "constructor_kwargs": binding_kwargs,
        }
    if not bindings or len(names) > MAX_MANIFEST_FILES or len(set(names)) != len(names):
        raise BenchmarkInputError("paddle model manifest is invalid")
    names_set = frozenset(names)
    snapshot = _snapshot_model_tree(model_dir)
    allowed_entries = set(names_set) | {manifest_root}
    for name in names_set:
        parent = PurePosixPath(name).parent
        while str(parent) != ".":
            allowed_entries.add(parent.as_posix())
            parent = parent.parent
    if set(snapshot) - allowed_entries:
        raise BenchmarkInputError("paddle model tree has unmanaged files")
    return names_set, snapshot, bindings, {key: str(value) for key, value in verified_runtime.items()}


def _validate_effective_assets(boundary: PaddleAssetBoundary, effective_model_version: str) -> None:
    selection_ids = tuple(part for part in effective_model_version.split("+") if part)
    if not selection_ids or any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", item) for item in selection_ids):
        raise BenchmarkInputError("paddle model selection is invalid")
    for selection_id in selection_ids:
        if selection_id not in boundary.bindings:
            raise BenchmarkInputError("paddle model asset inventory is incomplete")


def _assert_model_tree_unchanged(boundary: PaddleAssetBoundary) -> None:
    current = _snapshot_model_tree(boundary.model_dir)
    if current != boundary.initial_snapshot:
        raise BenchmarkInputError("paddle model tree changed during benchmark")


def _cleanup_paddle_runtime_directory(temp_dir: Path) -> None:
    """Remove only the temporary runtime directory owned by this benchmark."""
    for entry in temp_dir.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _atomic_write_json(output: Path, report: dict[str, object]) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
        temporary_name = None
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, ValueError, TypeError) as exc:
        raise BenchmarkInputError("output path is invalid") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_engine(engine: str) -> str:
    selected = engine.strip().lower()
    if selected == "paddle":
        return "paddleocr"
    if selected in {"tesseract", "paddleocr"}:
        return selected
    raise BenchmarkInputError("unknown OCR engine")


def _has_dot_segment(path: Path) -> bool:
    return any(component in {".", ".."} for component in path.parts)


def _sandbox_path(path: Path, *, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute() or _has_dot_segment(path):
        raise BenchmarkInputError(f"{label} path is invalid")
    _reject_symlink_ancestors(path)
    if path.is_symlink():
        raise BenchmarkInputError(f"{label} path is invalid")
    return path


def _trusted_paddle_sandbox_wrapper() -> Path:
    configured = os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX_WRAPPER", str(PADDLE_SANDBOX_WRAPPER))
    if configured != str(PADDLE_SANDBOX_WRAPPER):
        raise BenchmarkInputError("paddle sandbox wrapper is not allowlisted")
    wrapper = _sandbox_path(PADDLE_SANDBOX_WRAPPER, label="paddle sandbox wrapper")
    try:
        stat = wrapper.stat()
    except OSError as exc:
        raise BenchmarkInputError("paddle sandbox wrapper is unavailable") from exc
    if stat.st_uid != 0 or stat.st_nlink != 1 or stat.st_mode & 0o022 or not os.access(wrapper, os.X_OK):
        raise BenchmarkInputError("paddle sandbox wrapper is not trusted")
    return wrapper


def _argv_sha256(argv: Sequence[str]) -> str:
    encoded = json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _network_namespace(path: str) -> str:
    try:
        value = os.readlink(path)
    except OSError as exc:
        raise BenchmarkInputError("paddle sandbox attestation is unavailable") from exc
    if not re.fullmatch(r"net:\[\d+\]", value):
        raise BenchmarkInputError("paddle sandbox attestation is invalid")
    return value


def _route_entries(path: str) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BenchmarkInputError("paddle sandbox attestation is unavailable") from exc
    if path == "/proc/net/route" and lines:
        lines = lines[1:]
    entries = [line[:256] for line in lines if line.strip()]
    if len(entries) > 16:
        raise BenchmarkInputError("paddle sandbox attestation is invalid")
    return entries


def _route_is_loopback_only(route: str) -> bool:
    fields = route.split()
    return bool(fields) and fields[-1] == "lo"


def _routes_are_loopback_only(routes: object) -> bool:
    return isinstance(routes, list) and len(routes) <= 16 and all(
        isinstance(route, str) and len(route) <= 256 and _route_is_loopback_only(route) for route in routes
    )


def _write_unshare_network_attestation(path: Path, challenge: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}", challenge):
        raise BenchmarkInputError("paddle sandbox challenge is invalid")
    path = _sandbox_path(path, label="paddle sandbox attestation")
    if path.exists():
        raise BenchmarkInputError("paddle sandbox attestation already exists")
    current_namespace = _network_namespace("/proc/self/ns/net")
    host_namespace = _network_namespace("/proc/1/ns/net")
    try:
        interfaces = sorted(name for _index, name in socket.if_nameindex())
    except OSError as exc:
        raise BenchmarkInputError("paddle sandbox attestation is unavailable") from exc
    routes = _route_entries("/proc/net/route")
    ipv6_routes = _route_entries("/proc/net/ipv6_route")
    if (
        current_namespace == host_namespace
        or interfaces != ["lo"]
        or not _routes_are_loopback_only(routes)
        or not _routes_are_loopback_only(ipv6_routes)
    ):
        raise BenchmarkInputError("paddle sandbox network is not private")
    _atomic_write_json(
        path,
        {
            "version": 1,
            "sandbox": PADDLE_SANDBOX_ATTESTATION,
            "challenge": challenge,
            "network_namespace": current_namespace,
            "host_network_namespace": host_namespace,
            "interfaces": interfaces,
            "routes": routes,
            "ipv6_routes": ipv6_routes,
            "argv_sha256": _argv_sha256(sys.argv),
        },
    )


def _read_unshare_network_attestation(path: Path, challenge: str, expected_argv: Sequence[str]) -> None:
    path = _sandbox_path(path, label="paddle sandbox attestation")
    try:
        if path.stat().st_size > MAX_SANDBOX_ATTESTATION_BYTES:
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError("paddle sandbox attestation is invalid") from exc
    if not isinstance(payload, dict):
        raise BenchmarkInputError("paddle sandbox attestation is invalid")
    if set(payload) != {
        "version",
        "sandbox",
        "challenge",
        "network_namespace",
        "host_network_namespace",
        "interfaces",
        "routes",
        "ipv6_routes",
        "argv_sha256",
    }:
        raise BenchmarkInputError("paddle sandbox attestation is invalid")
    if (
        payload["version"] != 1
        or payload["sandbox"] != PADDLE_SANDBOX_ATTESTATION
        or payload["challenge"] != challenge
        or not isinstance(payload["network_namespace"], str)
        or not isinstance(payload["host_network_namespace"], str)
        or payload["network_namespace"] == payload["host_network_namespace"]
        or payload["interfaces"] != ["lo"]
        or not _routes_are_loopback_only(payload["routes"])
        or not _routes_are_loopback_only(payload["ipv6_routes"])
        or payload["argv_sha256"] != _argv_sha256(expected_argv)
    ):
        raise BenchmarkInputError("paddle sandbox attestation is invalid")
    for key in ("network_namespace", "host_network_namespace"):
        if not re.fullmatch(r"net:\[\d+\]", payload[key]):
            raise BenchmarkInputError("paddle sandbox attestation is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", payload["argv_sha256"]):
        raise BenchmarkInputError("paddle sandbox attestation is invalid")


def _build_paddle_sandbox_command(
    *,
    input_dir: Path,
    output: Path,
    attestation: Path,
    challenge: str,
    languages: tuple[str, ...],
    preprocessing_version: str,
    accuracy_notes: str,
) -> list[str]:
    wrapper = _trusted_paddle_sandbox_wrapper()
    input_dir = _sandbox_path(input_dir, label="benchmark input")
    output = _sandbox_path(output, label="benchmark output")
    attestation = _sandbox_path(attestation, label="paddle sandbox attestation")
    script = _sandbox_path(Path(__file__).resolve(), label="benchmark script")
    python = _sandbox_path(Path(sys.executable).resolve(), label="benchmark Python")
    model_dir_value = os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", "")
    model_dir = _sandbox_path(Path(model_dir_value).expanduser(), label="paddle model") if model_dir_value else None
    if model_dir is None or not model_dir.is_dir():
        raise BenchmarkInputError("paddle model directory is invalid")
    if not re.fullmatch(r"[a-f0-9]{32}", challenge):
        raise BenchmarkInputError("paddle sandbox challenge is invalid")
    if output.parent == input_dir or output.parent.is_relative_to(input_dir) or input_dir.is_relative_to(output.parent):
        raise BenchmarkInputError("benchmark input and output paths overlap")
    if output.parent == model_dir or output.parent.is_relative_to(model_dir) or model_dir.is_relative_to(output.parent):
        raise BenchmarkInputError("paddle model and output paths overlap")
    child_arguments = [
        str(script),
        "--input-dir",
        str(input_dir),
        "--output",
        str(output),
        "--engine",
        "paddleocr",
        "--languages",
        *languages,
        "--preprocessing-version",
        preprocessing_version,
        "--accuracy-notes",
        _safe_notes(accuracy_notes),
        "--paddle-sandbox-child",
        "--paddle-sandbox-attestation",
        str(attestation),
        "--paddle-sandbox-challenge",
        challenge,
    ]
    return [
        str(wrapper),
        *PADDLE_SANDBOX_FLAGS,
        str(python),
        *child_arguments,
    ]


def _validate_installed_paddle_runtime(expected: dict[str, str]) -> None:
    try:
        paddle = __import__("paddle")
        paddleocr = __import__("paddleocr")
        from paddleocr import PaddleOCR

        actual = {
            "paddle_version": getattr(paddle, "__version__", ""),
            "paddleocr_version": getattr(paddleocr, "__version__", ""),
            "constructor_api_sha256": hashlib.sha256(str(inspect.signature(PaddleOCR)).encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        raise BenchmarkInputError("paddle runtime metadata is unavailable") from exc
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", value) for value in actual.values()):
        raise BenchmarkInputError("paddle runtime metadata is invalid")
    if any(actual[key] != expected.get(key) for key in actual):
        raise BenchmarkInputError("paddle runtime metadata drifted")


def _run_paddle_benchmark_in_sandbox(
    input_dir: Path,
    output: Path,
    *,
    languages: tuple[str, ...],
    preprocessing_version: str,
    accuracy_notes: str,
) -> BenchmarkResult:
    if os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE") != "1":
        raise BenchmarkInputError("paddleocr requires explicit offline mode")
    challenge = secrets.token_hex(16)
    attestation = output.parent / f".{output.name}.sandbox-{challenge}.json"
    if attestation.exists() or attestation.is_symlink():
        raise BenchmarkInputError("paddle sandbox attestation path is invalid")
    command = _build_paddle_sandbox_command(
        input_dir=input_dir,
        output=output,
        attestation=attestation,
        challenge=challenge,
        languages=languages,
        preprocessing_version=preprocessing_version,
        accuracy_notes=accuracy_notes,
    )
    child_argv = command[command.index("--") + 2 :]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=600)
        if completed.returncode != 0 and not attestation.exists():
            raise BenchmarkInputError("paddle sandbox preflight unavailable: unshare -Urn failed")
        _read_unshare_network_attestation(attestation, challenge, child_argv)
        report = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError("paddle sandbox benchmark failed") from exc
    finally:
        try:
            attestation.unlink(missing_ok=True)
        except OSError:
            pass
    if not isinstance(report, dict) or completed.returncode not in {0, 2}:
        raise BenchmarkInputError("paddle sandbox benchmark failed")
    return BenchmarkResult(report, failed=completed.returncode == 2)


@contextmanager
def _paddle_offline_environment(output_parent: Path) -> PaddleAssetBoundary:
    """Require and scope a manifest-backed, pre-provisioned Paddle model tree."""
    if os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE") != "1":
        raise BenchmarkInputError("paddleocr requires explicit offline mode")
    model_dir_value = os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", "")
    manifest_path_value = os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", "")
    model_dir = Path(model_dir_value).expanduser()
    manifest_path = Path(manifest_path_value).expanduser()
    if (
        not model_dir_value
        or not model_dir.is_absolute()
        or _has_dot_segment(model_dir)
        or model_dir.is_symlink()
        or not model_dir.is_dir()
        or not manifest_path_value
        or not manifest_path.is_absolute()
        or _has_dot_segment(manifest_path)
    ):
        raise BenchmarkInputError("paddleocr model directory is invalid")
    try:
        manifest_path.relative_to(model_dir)
    except ValueError as exc:
        raise BenchmarkInputError("paddle model manifest is outside model directory") from exc
    allowed_files, initial_snapshot, bindings, verified_runtime = _validate_paddle_manifest(model_dir, manifest_path)
    temp_dir = output_parent / ".instagram-post-watch-paddle-tmp"
    if temp_dir.is_symlink() or (temp_dir.exists() and not temp_dir.is_dir()):
        raise BenchmarkInputError("paddle temporary directory is invalid")
    if temp_dir.exists() and any(temp_dir.iterdir()):
        raise BenchmarkInputError("paddle temporary directory is not empty")
    temp_dir.mkdir(exist_ok=True)
    boundary = PaddleAssetBoundary(model_dir, manifest_path, allowed_files, initial_snapshot, bindings, verified_runtime, temp_dir)
    updates = {
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "PADDLE_PDX_OFFLINE": "1",
        "PADDLEOCR_HOME": str(temp_dir),
        "PADDLE_HOME": str(temp_dir),
        "PADDLE_PDX_CACHE_HOME": str(temp_dir),
        "INSTAGRAM_POST_WATCH_PADDLEOCR_HARD_OFFLINE": "1",
        "INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_BINDINGS": json.dumps(bindings, sort_keys=True),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": str(temp_dir),
        "HF_HUB_CACHE": str(temp_dir),
        "TRANSFORMERS_CACHE": str(temp_dir),
        "XDG_CACHE_HOME": str(temp_dir),
        "XDG_CONFIG_HOME": str(temp_dir),
        "XDG_DATA_HOME": str(temp_dir),
        "TMPDIR": str(temp_dir),
        "TEMP": str(temp_dir),
        "TMP": str(temp_dir),
        "HOME": str(temp_dir),
    }
    previous = {key: os.environ.get(key) for key in updates}
    previous_tempdir = tempfile.tempdir
    previous_cwd = Path.cwd()
    os.environ.update(updates)
    tempfile.tempdir = str(temp_dir)
    os.chdir(temp_dir)
    try:
        yield boundary
    finally:
        try:
            _assert_model_tree_unchanged(boundary)
        finally:
            try:
                _cleanup_paddle_runtime_directory(temp_dir)
                temp_dir.rmdir()
            finally:
                tempfile.tempdir = previous_tempdir
                os.chdir(previous_cwd)
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def _effective_backend_metadata(backend: OCRBackend, languages: tuple[str, ...]) -> tuple[str, str, tuple[str, ...]]:
    config_factory = getattr(backend, "runtime_config", None)
    if callable(config_factory):
        config = config_factory(languages)
        model_version = getattr(config, "model_version", None)
        effective_languages = getattr(config, "languages", languages)
        if not isinstance(model_version, str) or not model_version:
            raise BenchmarkInputError("OCR model version is invalid")
        effective_languages = _normalise_languages(effective_languages)
        return _safe_label(backend.engine_id), _safe_label(model_version), effective_languages
    return _safe_label(backend.engine_id), _safe_label(backend.model_version), languages


def _image_paths(input_dir: Path) -> list[Path]:
    if not input_dir.exists() or not input_dir.is_dir() or input_dir.is_symlink():
        raise BenchmarkInputError("input directory is invalid")
    paths = [path for path in input_dir.rglob("*") if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_SUFFIXES]
    paths.sort(key=lambda path: path.relative_to(input_dir).as_posix())
    if not paths:
        raise BenchmarkInputError("input directory contains no supported images")
    return paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError) as exc:
        raise BenchmarkInputError("an input image cannot be read") from exc
    return digest.hexdigest()


def _safe_result(result: OCRResult, backend: OCRBackend, languages: tuple[str, ...]) -> tuple[OCRResult, bool]:
    """Keep injected backends from placing unbounded or sensitive values in output."""
    invalid = not isinstance(result, OCRResult)
    try:
        status = OCRStatus(result.status)
    except (AttributeError, TypeError, ValueError):
        status = OCRStatus.ERROR
        invalid = True
    text = result.text if isinstance(getattr(result, "text", ""), str) else ""
    confidence = getattr(result, "confidence", None)
    if confidence is not None and (not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0 <= confidence <= 1):
        confidence = None
        invalid = True
    if status is OCRStatus.SUCCESS and (not text or confidence is None):
        invalid = True
    if status is OCRStatus.NO_TEXT and (text or confidence is not None):
        invalid = True
    safe = OCRResult(
        status=status,
        text=text[:4000],
        confidence=confidence,
        engine_id=_safe_label(getattr(result, "engine_id", "") or backend.engine_id),
        model_version=_safe_label(getattr(result, "model_version", "") or backend.model_version),
        languages=languages,
    )
    return safe, invalid


def run_benchmark(
    input_dir: Path,
    output: Path,
    engine: str,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGES,
    preprocessing_version: str = DEFAULT_PREPROCESSING_VERSION,
    accuracy_notes: str = "",
    backend: OCRBackend | None = None,
    _sandbox_child: bool = False,
    _sandbox_attestation: Path | None = None,
    _sandbox_challenge: str | None = None,
) -> BenchmarkResult:
    """Benchmark an injected or Task 3 backend without using OCR cache/state."""
    input_dir = Path(input_dir).absolute()
    output = _validate_destination(Path(output))
    engine = _normalize_engine(engine)
    language_set = _normalise_languages(languages)
    preprocessing_version = _safe_preprocessing_version(preprocessing_version)
    if len(accuracy_notes) > MAX_NOTE_LENGTH:
        raise BenchmarkInputError("accuracy notes are too long")
    if engine == "paddleocr" and backend is None and not _sandbox_child:
        _image_paths(input_dir)
        return _run_paddle_benchmark_in_sandbox(
            input_dir,
            output,
            languages=language_set,
            preprocessing_version=preprocessing_version,
            accuracy_notes=accuracy_notes,
        )
    if engine == "paddleocr" and backend is None:
        if _sandbox_attestation is None or _sandbox_challenge is None:
            raise BenchmarkInputError("paddleocr requires a sandbox attestation")
        _write_unshare_network_attestation(_sandbox_attestation, _sandbox_challenge)
    paths = _image_paths(input_dir)
    offline_context = _paddle_offline_environment(output.parent) if backend is None and engine == "paddleocr" else nullcontext()
    started = time.perf_counter()
    images: list[dict[str, object]] = []
    failed = False

    with offline_context as paddle_boundary:
        selected = backend if backend is not None else build_backend(engine)
        engine_id, model_version, effective_languages = _effective_backend_metadata(selected, language_set)
        if paddle_boundary is not None:
            _validate_effective_assets(paddle_boundary, model_version)
            if backend is None:
                _validate_installed_paddle_runtime(paddle_boundary.verified_runtime)
        for path in paths:
            image_started = time.perf_counter()
            try:
                _sha256(path)
            except BenchmarkInputError:
                raise
            try:
                raw_result = selected.extract(path, effective_languages)
                result, invalid = _safe_result(raw_result, selected, effective_languages)
            except OCRBackendUnavailable:
                result, invalid = OCRResult(OCRStatus.UNAVAILABLE, engine_id=engine_id, model_version=model_version, languages=effective_languages), False
            except TimeoutError:
                result, invalid = OCRResult(OCRStatus.TIMEOUT, engine_id=engine_id, model_version=model_version, languages=effective_languages), False
            except Exception:
                result, invalid = OCRResult(OCRStatus.ERROR, engine_id=engine_id, model_version=model_version, languages=effective_languages), False
            failed = failed or invalid or result.status in FAILED_STATUSES
            images.append(
                {
                    "path": path.relative_to(input_dir).as_posix(),
                    "latency_seconds": round(time.perf_counter() - image_started, 6),
                    "status": result.status.value,
                    "character_count": len(result.text),
                    "confidence": result.confidence,
                    "text_recovery": (
                        "complete"
                        if result.status is OCRStatus.SUCCESS and result.text
                        else "partial"
                        if result.text
                        else "none"
                    ),
                }
            )

    latencies = [float(image["latency_seconds"]) for image in images]
    recovery_classes = {"complete": 0, "partial": 0, "none": 0}
    for image in images:
        recovery_classes[image["text_recovery"]] += 1
    assets_with_text = recovery_classes["complete"] + recovery_classes["partial"]
    report = {
        "engine_id": engine_id,
        "model_version": model_version,
        "languages": list(effective_languages),
        "preprocessing_version": preprocessing_version,
        "images": images,
        "total_latency_seconds": round(time.perf_counter() - started, 6),
        "median_latency_seconds": round(float(median(latencies)), 6),
        "peak_rss_bytes": _peak_rss_bytes(),
        "text_recovery": {
            "assets_total": len(images),
            "assets_with_text": assets_with_text,
            "coverage_ratio": round(assets_with_text / len(images), 6),
            "classes": recovery_classes,
        },
        "accuracy_notes": _safe_notes(accuracy_notes),
    }
    _atomic_write_json(output, report)
    return BenchmarkResult(report, failed=failed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine", required=True, choices=("tesseract", "paddle", "paddleocr"))
    parser.add_argument("--languages", nargs="+", default=list(DEFAULT_LANGUAGES), metavar="LANG")
    parser.add_argument("--preprocessing-version", default=DEFAULT_PREPROCESSING_VERSION)
    parser.add_argument("--accuracy-notes", default="")
    parser.add_argument("--paddle-sandbox-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--paddle-sandbox-attestation", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--paddle-sandbox-challenge", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None, *, backend: OCRBackend | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.paddle_sandbox_child and (args.engine != "paddleocr" or backend is not None):
            raise BenchmarkInputError("invalid paddle sandbox child invocation")
        result = run_benchmark(
            args.input_dir,
            args.output,
            args.engine,
            languages=args.languages,
            preprocessing_version=args.preprocessing_version,
            accuracy_notes=args.accuracy_notes,
            backend=backend,
            _sandbox_child=args.paddle_sandbox_child,
            _sandbox_attestation=args.paddle_sandbox_attestation,
            _sandbox_challenge=args.paddle_sandbox_challenge,
        )
    except (BenchmarkInputError, OCRBackendUnavailable, ValueError):
        return 2
    return 2 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
