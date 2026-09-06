from __future__ import annotations

import json
import hashlib
import inspect
import os
import socket
import sys
import tempfile
import types
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import benchmark_ocr
import ocr


class FakeBackend:
    engine_id = "fake"
    model_version = "test-1"

    def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
        return ocr.OCRResult(ocr.OCRStatus.SUCCESS, path.stem, 0.91)


class FalseyBackend(FakeBackend):
    def __bool__(self) -> bool:
        return False


class ProvisionedPaddleBackend(FakeBackend):
    engine_id = "paddleocr"
    model_version = "PP-OCRv5-id+PP-OCRv5-en"


class StatusBackend(FakeBackend):
    def __init__(self, status: ocr.OCRStatus):
        self.status = status

    def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
        return ocr.OCRResult(self.status)


def provision_paddle_assets(model_dir: Path) -> Path:
    models = {}
    for selection in ("PP-OCRv5-id", "PP-OCRv5-en"):
        asset_dir = model_dir / selection
        asset_dir.mkdir(parents=True)
        asset = asset_dir / "model.bin"
        asset.write_bytes((selection.encode() * 512)[:2048])
        models[selection] = {
            "model_dir": selection,
            "constructor_kwargs": {"model_dir": selection},
            "artifacts": [{"path": f"{selection}/model.bin", "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()}],
        }
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "verified_runtime": {
                    "sandbox": "preflight-verified",
                    "paddle_version": "3.0.0-preflight",
                    "paddleocr_version": "3.7.0-preflight",
                    "constructor_api_sha256": "a" * 64,
                },
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def configure_paddle(monkeypatch: pytest.MonkeyPatch, model_dir: Path, manifest: Path) -> None:
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX", "preflight-verified")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(manifest))


def run_provisioned_paddle_child(
    monkeypatch: pytest.MonkeyPatch,
    input_dir: Path,
    output: Path,
    *,
    engine: str = "paddleocr",
):
    monkeypatch.setattr(benchmark_ocr, "_write_unshare_network_attestation", lambda path, challenge: None)
    monkeypatch.setattr(benchmark_ocr, "_validate_installed_paddle_runtime", lambda expected: None)
    return benchmark_ocr.run_benchmark(
        input_dir,
        output,
        engine,
        _sandbox_child=True,
        _sandbox_attestation=output.parent / "attestation.json",
        _sandbox_challenge="a" * 32,
    )


def test_benchmark_is_lexical_and_reports_relative_paths(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "b.jpg").write_bytes(b"b")
    (input_dir / "a.png").write_bytes(b"a")
    output = tmp_path / "report.json"

    result = benchmark_ocr.run_benchmark(
        input_dir,
        output,
        "tesseract",
        backend=FakeBackend(),
        accuracy_notes="manual token=hidden /private/image.jpg",
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert result.failed is False
    assert [image["path"] for image in report["images"]] == ["a.png", "b.jpg"]
    assert all("/" not in image["path"] for image in report["images"])
    assert report["accuracy_notes"] == "manual [redacted]"
    assert report["languages"] == ["ind", "eng"]
    assert report["images"][0]["character_count"] == 1
    assert report["images"][0]["confidence"] == 0.91
    assert report["images"][0]["latency_seconds"] >= 0
    assert report["total_latency_seconds"] >= 0
    assert report["median_latency_seconds"] >= 0
    assert report["images"][0]["text_recovery"] == "complete"
    assert report["text_recovery"] == {
        "assets_total": 2,
        "assets_with_text": 2,
        "coverage_ratio": 1.0,
        "classes": {"complete": 2, "partial": 0, "none": 0},
    }
    assert report["peak_rss_bytes"] > 0


def test_unavailable_backend_returns_nonzero_and_sanitized_report(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    output = tmp_path / "report.json"

    class Unavailable(FakeBackend):
        def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
            raise ocr.OCRBackendUnavailable("/secret/tesseract --token=hidden")

    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(output), "--engine", "tesseract"],
        backend=Unavailable(),
    ) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["images"][0]["status"] == "unavailable"
    assert "/secret" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("status", [ocr.OCRStatus.ERROR, ocr.OCRStatus.TIMEOUT])
def test_backend_failure_status_writes_report_and_returns_nonzero(tmp_path: Path, status: ocr.OCRStatus):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    output = tmp_path / "report.json"

    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(output), "--engine", "tesseract"],
        backend=StatusBackend(status),
    ) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["images"]) == 1
    assert report["images"][0]["status"] == status.value


def test_invalid_ocr_result_preserves_entry_and_fails(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    output = tmp_path / "report.json"

    class Invalid(FakeBackend):
        def extract(self, path: Path, languages: tuple[str, ...]):
            return ocr.OCRResult(ocr.OCRStatus.SUCCESS, "text", confidence="bad")

    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(output), "--engine", "tesseract"], backend=Invalid()
    ) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["images"][0]["status"] == "success"


def test_falsey_injected_backend_is_used(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    result = benchmark_ocr.run_benchmark(input_dir, tmp_path / "report.json", "tesseract", backend=FalseyBackend())
    assert result.failed is False
    assert result.report["engine_id"] == "fake"


def test_nested_suffix_and_symlink_inputs_are_safe(tmp_path: Path):
    input_dir = tmp_path / "images"
    nested = input_dir / "nested"
    nested.mkdir(parents=True)
    (input_dir / "z.txt").write_text("ignore", encoding="utf-8")
    (nested / "b.jpg").write_bytes(b"b")
    (nested / "a.PNG").write_bytes(b"a")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    os.symlink(outside, nested / "linked.jpg")
    report = benchmark_ocr.run_benchmark(input_dir, tmp_path / "report.json", "tesseract", backend=FakeBackend()).report
    assert [image["path"] for image in report["images"]] == ["nested/a.PNG", "nested/b.jpg"]


def test_effective_paddle_model_version_is_reported(tmp_path: Path):
    def runner(config, path, timeout):
        return ocr.OCRResult(ocr.OCRStatus.SUCCESS, "texto", 0.8)

    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    backend = ocr.PaddleOCRBackend(model_version="PP-OCRv5", runner=runner)
    report = benchmark_ocr.run_benchmark(
        input_dir, tmp_path / "report.json", "paddleocr", backend=backend
    ).report
    assert report["engine_id"] == "paddleocr"
    assert report["model_version"] == "PP-OCRv5-id+PP-OCRv5-en"
    assert report["languages"] == ["ind", "eng"]


def test_paddle_requires_offline_preprovisioned_model_dir(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    output = tmp_path / "report.json"
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(output), "--engine", "paddleocr"]
    ) == 2
    assert not output.exists()


def test_paddle_offline_environment_is_set_before_construction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    seen = {}

    def factory(engine):
        seen.update({key: os.environ.get(key) for key in ("PADDLE_PDX_OFFLINE", "PADDLEOCR_HOME", "PADDLE_PDX_CACHE_HOME")})
        return ProvisionedPaddleBackend()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    configure_paddle(monkeypatch, model_dir, manifest)
    guarded_keys = (
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
        "PADDLE_PDX_OFFLINE",
        "PADDLEOCR_HOME",
        "PADDLE_HOME",
        "PADDLE_PDX_CACHE_HOME",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
    )
    for key in guarded_keys:
        monkeypatch.setenv(key, f"caller-{key.lower()}")
    run_provisioned_paddle_child(monkeypatch, input_dir, tmp_path / "report.json")
    runtime_dir = str(tmp_path / ".instagram-post-watch-paddle-tmp")
    assert seen == {"PADDLE_PDX_OFFLINE": "1", "PADDLEOCR_HOME": runtime_dir, "PADDLE_PDX_CACHE_HOME": runtime_dir}
    for key in guarded_keys:
        assert os.environ[key] == f"caller-{key.lower()}"


def test_paddle_alias_gets_the_same_guard_and_restores_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    seen = {}

    def factory(engine):
        seen["engine"] = engine
        seen["offline"] = os.environ.get("PADDLE_PDX_OFFLINE")
        seen["bindings"] = json.loads(os.environ["INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_BINDINGS"])
        return ProvisionedPaddleBackend()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    configure_paddle(monkeypatch, model_dir, manifest)
    monkeypatch.setenv("PADDLE_PDX_OFFLINE", "caller-value")
    run_provisioned_paddle_child(monkeypatch, input_dir, tmp_path / "report.json", engine="paddle")
    assert seen["engine"] == "paddleocr"
    assert seen["offline"] == "1"
    assert seen["bindings"]["PP-OCRv5-id"]["model_dir"] == str(model_dir / "PP-OCRv5-id")
    assert seen["bindings"]["PP-OCRv5-en"]["artifacts"][0]["path"] == str(model_dir / "PP-OCRv5-en" / "model.bin")
    assert os.environ["PADDLE_PDX_OFFLINE"] == "caller-value"


def test_empty_or_incomplete_paddle_manifest_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = model_dir / "manifest.json"
    manifest.write_text(json.dumps({"files": []}), encoding="utf-8")
    configure_paddle(monkeypatch, model_dir, manifest)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2


def test_manifest_digest_mismatch_and_missing_artifact_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["models"]["PP-OCRv5-id"]["artifacts"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    configure_paddle(monkeypatch, model_dir, manifest)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2

    payload["models"]["PP-OCRv5-id"]["artifacts"][0]["path"] = "PP-OCRv5-id/missing.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report-2.json"), "--engine", "paddleocr"]
    ) == 2


def test_manifest_rejects_unexpected_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    (model_dir / "unexpected.cache").write_bytes(b"not listed")
    configure_paddle(monkeypatch, model_dir, manifest)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2


def test_manifest_rejects_one_byte_model_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    tiny = model_dir / "PP-OCRv5-id" / "model.bin"
    tiny.write_bytes(b"x")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["models"]["PP-OCRv5-id"]["artifacts"][0]["sha256"] = hashlib.sha256(tiny.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    configure_paddle(monkeypatch, model_dir, manifest)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2


def test_manifest_requires_paddleocr_runtime_version(tmp_path: Path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    del payload["verified_runtime"]["paddleocr_version"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(benchmark_ocr.BenchmarkInputError, match="runtime metadata"):
        benchmark_ocr._validate_paddle_manifest(model_dir, manifest)


def test_model_tree_snapshot_retains_full_sha256(tmp_path: Path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    provision_paddle_assets(model_dir)
    image = model_dir / "PP-OCRv5-id" / "model.bin"
    snapshot = benchmark_ocr._snapshot_model_tree(model_dir)

    assert snapshot["PP-OCRv5-id/model.bin"] == ("file", image.stat().st_size, hashlib.sha256(image.read_bytes()).hexdigest())
    assert len(snapshot["PP-OCRv5-id/model.bin"][2]) == 64


def test_installed_paddle_runtime_metadata_is_exact(monkeypatch: pytest.MonkeyPatch):
    class FakePaddleOCR:
        def __init__(self, model_name=None):
            self.model_name = model_name

    monkeypatch.setitem(sys.modules, "paddle", types.SimpleNamespace(__version__="3.3.1"))
    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(__version__="3.7.0", PaddleOCR=FakePaddleOCR))
    expected = {
        "paddle_version": "3.3.1",
        "paddleocr_version": "3.7.0",
        "constructor_api_sha256": hashlib.sha256(str(inspect.signature(FakePaddleOCR)).encode("utf-8")).hexdigest(),
    }

    benchmark_ocr._validate_installed_paddle_runtime(expected)
    expected["paddleocr_version"] = "3.7.1"
    with pytest.raises(benchmark_ocr.BenchmarkInputError, match="drifted"):
        benchmark_ocr._validate_installed_paddle_runtime(expected)


def test_paddle_sandbox_attestation_is_challenge_and_namespace_bound(tmp_path: Path):
    attestation = tmp_path / "attestation.json"
    argv = ["benchmark_ocr.py", "--engine", "paddleocr"]
    attestation.write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox": "unshare-user-network",
                "challenge": "a" * 32,
                "network_namespace": "net:[22]",
                "host_network_namespace": "net:[11]",
                "interfaces": ["lo"],
                "routes": ["0 0 0 0 lo"],
                "ipv6_routes": ["0 0 0 0 lo"],
                "argv_sha256": benchmark_ocr._argv_sha256(argv),
            }
        ),
        encoding="utf-8",
    )

    benchmark_ocr._read_unshare_network_attestation(attestation, "a" * 32, argv)
    with pytest.raises(benchmark_ocr.BenchmarkInputError):
        benchmark_ocr._read_unshare_network_attestation(attestation, "b" * 32, argv)


def test_paddle_sandbox_attestation_writer_requires_private_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    namespaces = iter(("net:[22]", "net:[11]"))
    monkeypatch.setattr(benchmark_ocr, "_network_namespace", lambda path: next(namespaces))
    monkeypatch.setattr(benchmark_ocr.socket, "if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr(benchmark_ocr, "_route_entries", lambda path: [])
    written = {}
    monkeypatch.setattr(benchmark_ocr, "_atomic_write_json", lambda path, payload: written.update(payload=payload))

    benchmark_ocr._write_unshare_network_attestation(tmp_path / "attestation.json", "a" * 32)

    assert written["payload"]["sandbox"] == "unshare-user-network"
    assert written["payload"]["interfaces"] == ["lo"]
    assert written["payload"]["routes"] == []
    assert benchmark_ocr._routes_are_loopback_only(["0 0 0 0 lo"])
    assert not benchmark_ocr._routes_are_loopback_only(["0 0 0 0 eth0"])


def test_paddle_sandbox_command_is_allowlisted_and_path_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    output = tmp_path / "reports" / "report.json"
    output.parent.mkdir()
    attestation = tmp_path / "reports" / "attestation.json"
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setattr(benchmark_ocr, "_trusted_paddle_sandbox_wrapper", lambda: Path("/usr/bin/unshare"))

    command = benchmark_ocr._build_paddle_sandbox_command(
        input_dir=input_dir,
        output=output,
        attestation=attestation,
        challenge="a" * 32,
        languages=("ind", "eng"),
        preprocessing_version="preprocess-1",
        accuracy_notes="safe",
    )

    assert command[:4] == ["/usr/bin/unshare", "-Urn", "--", str(Path(sys.executable).resolve())]
    assert "systemd-run" not in command
    assert "--" in command
    assert "sh" not in command and "-c" not in command
    with pytest.raises(benchmark_ocr.BenchmarkInputError, match="overlap"):
        benchmark_ocr._build_paddle_sandbox_command(
            input_dir=input_dir,
            output=input_dir / "report.json",
            attestation=attestation,
            challenge="a" * 32,
            languages=("eng",),
            preprocessing_version="preprocess-1",
            accuracy_notes="safe",
        )


def test_paddle_unshare_failure_reports_preflight_requirement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setattr(benchmark_ocr, "_trusted_paddle_sandbox_wrapper", lambda: Path("/usr/bin/unshare"))
    monkeypatch.setattr(benchmark_ocr.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=1))

    with pytest.raises(benchmark_ocr.BenchmarkInputError, match="preflight unavailable"):
        benchmark_ocr.run_benchmark(input_dir, output_dir / "report.json", "paddleocr")


def test_paddle_requires_an_allowlisted_os_sandbox_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    configure_paddle(monkeypatch, tmp_path / "models", tmp_path / "models" / "manifest.json")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX_WRAPPER", "/tmp/untrusted-wrapper")

    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2
    assert not (tmp_path / "report.json").exists()


def test_paddle_worker_hard_offline_guard_denies_network_before_backend(monkeypatch: pytest.MonkeyPatch):
    config = ocr.PaddleRuntimeConfig((), "test", ())
    events = []

    class Queue:
        def put(self, value):
            events.append(value)

    def attempts_network(config, image_path, bindings=None):
        socket.getaddrinfo("example.invalid", 443)
        raise AssertionError("network guard did not run")

    monkeypatch.setattr(ocr, "_paddle_worker_extract", attempts_network)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_HARD_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_BINDINGS", "{}")
    ocr._paddle_worker(config, "image.jpg", Queue())
    assert events == [("error", None)]


def test_python_offline_guard_denies_resolvers_connectors_and_sends():
    left, right = socket.socketpair()
    with tempfile.NamedTemporaryFile() as handle:
        calls = [
            lambda: socket.getaddrinfo("example.invalid", 443),
            lambda: socket.gethostbyname("example.invalid"),
            lambda: socket.gethostbyname_ex("example.invalid"),
            lambda: socket.gethostbyaddr("127.0.0.1"),
            lambda: socket.getfqdn("example.invalid"),
            lambda: socket.getnameinfo(("127.0.0.1", 443), 0),
            lambda: socket.create_connection(("127.0.0.1", 443)),
            lambda: left.connect(("127.0.0.1", 443)),
            lambda: left.connect_ex(("127.0.0.1", 443)),
            lambda: left.send(b"x"),
            lambda: left.sendall(b"x"),
            lambda: left.sendfile(handle),
            lambda: left.sendto(b"x", ("127.0.0.1", 443)),
        ]
        if hasattr(left, "sendmsg"):
            calls.append(lambda: left.sendmsg([b"x"]))
        try:
            with ocr.paddle_offline_network_guard():
                for call in calls:
                    with pytest.raises(OSError):
                        call()
        finally:
            left.close()
            right.close()


def test_caller_sandbox_marker_cannot_replace_os_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    configure_paddle(monkeypatch, model_dir, manifest)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX", "preflight-verified")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX_WRAPPER", "/tmp/untrusted-wrapper")
    attempted = tmp_path / "external-attempt"

    def factory(engine):
        attempted.write_text("must not run", encoding="utf-8")
        return ProvisionedPaddleBackend()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2
    assert not attempted.exists()


def test_paddle_tempfile_state_is_scoped_and_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    configure_paddle(monkeypatch, model_dir, manifest)
    stale = tmp_path / "stale-temp"
    tempfile.tempdir = str(stale)
    original_cwd = Path.cwd()
    seen = {}

    def factory(engine):
        seen["tempdir"] = tempfile.gettempdir()
        return ProvisionedPaddleBackend()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    try:
        run_provisioned_paddle_child(monkeypatch, input_dir, tmp_path / "report.json")
        assert seen["tempdir"] == str(tmp_path / ".instagram-post-watch-paddle-tmp")
        assert not (tmp_path / ".instagram-post-watch-paddle-tmp").exists()
        assert tempfile.tempdir == str(stale)
        assert Path.cwd() == original_cwd
    finally:
        tempfile.tempdir = None


def test_paddle_offline_environment_is_restored_after_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)

    def factory(engine):
        raise RuntimeError("construction failed")

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    configure_paddle(monkeypatch, model_dir, manifest)
    monkeypatch.setenv("HOME", "caller-home")
    with pytest.raises(RuntimeError):
        run_provisioned_paddle_child(monkeypatch, input_dir, tmp_path / "report.json")
    assert os.environ["HOME"] == "caller-home"


def test_paddle_model_tree_changes_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)

    def factory(engine):
        class WritesCache(ProvisionedPaddleBackend):
            def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
                (model_dir / "cache.tmp").write_text("unexpected", encoding="utf-8")
                return super().extract(path, languages)

        return WritesCache()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    configure_paddle(monkeypatch, model_dir, manifest)
    with pytest.raises(benchmark_ocr.BenchmarkInputError):
        benchmark_ocr.run_benchmark(input_dir, tmp_path / "report.json", "paddleocr")
    assert not (tmp_path / "report.json").exists()


def test_paddle_model_ancestor_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    model_dir = real_root / "models"
    model_dir.mkdir()
    manifest = provision_paddle_assets(model_dir)
    link_root = tmp_path / "link-root"
    os.symlink(real_root, link_root)
    configure_paddle(monkeypatch, link_root / "models", link_root / "models" / manifest.name)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddle"]
    ) == 2


def test_atomic_writer_cleans_temp_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    output = tmp_path / "report.json"

    def fail_replace(source, destination):
        raise OSError("simulated interruption")

    monkeypatch.setattr(benchmark_ocr.os, "replace", fail_replace)
    with pytest.raises(benchmark_ocr.BenchmarkInputError):
        benchmark_ocr.run_benchmark(input_dir, output, "tesseract", backend=FakeBackend())
    assert not list(tmp_path.glob(".report.json.*.tmp"))
    assert not output.exists()


def test_output_parent_symlink_is_rejected(tmp_path: Path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    link_parent = tmp_path / "link"
    os.symlink(real_parent, link_parent)
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    with pytest.raises(benchmark_ocr.BenchmarkInputError):
        benchmark_ocr.run_benchmark(input_dir, link_parent / "report.json", "tesseract", backend=FakeBackend())


def test_preprocessing_and_notes_are_bounded_and_redacted(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    report = benchmark_ocr.run_benchmark(
        input_dir,
        tmp_path / "report.json",
        "tesseract",
        backend=FakeBackend(),
        preprocessing_version="preprocess / local\nrun",
        accuracy_notes=(
            'token: "hidden value" password=secret ACCESS_TOKEN="access hidden" '
            'CLIENT_SECRET=client hidden SECRET_KEY: "key hidden" Authorization: Bearer bearer hidden\x00 '
            'source /private/my secret.jpg'
        ),
    ).report
    assert report["preprocessing_version"] == "preprocess___local_run"
    assert "hidden" not in report["accuracy_notes"]
    assert "secret.jpg" not in report["accuracy_notes"]
    assert "secret" not in report["accuracy_notes"]
    assert "access hidden" not in report["accuracy_notes"]
    assert "client hidden" not in report["accuracy_notes"]
    assert "key hidden" not in report["accuracy_notes"]
    assert "bearer hidden" not in report["accuracy_notes"]
    assert "/" not in report["accuracy_notes"]


@pytest.mark.parametrize(
    "note",
    [
        'AWS_SECRET_ACCESS_KEY="aws hidden value"',
        "PRIVATE_KEY=private hidden value",
        "X_API_KEY: x hidden value",
        "Authorization: Basic basic hidden value",
        "source C:\\private\\my secret.pem",
        "source \\\\server\\share\\my secret.pem",
        "source ../relative secret.pem",
    ],
)
def test_common_secret_and_path_forms_do_not_reach_report(tmp_path: Path, note: str):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    report = benchmark_ocr.run_benchmark(
        input_dir, tmp_path / "report.json", "tesseract", backend=FakeBackend(), accuracy_notes=note
    ).report
    rendered = report["accuracy_notes"]
    assert "hidden" not in rendered
    assert "secret.pem" not in rendered
    assert "C:" not in rendered
    assert "server" not in rendered


def test_preprocessing_rejects_arbitrary_secret_names():
    with pytest.raises(benchmark_ocr.BenchmarkInputError):
        benchmark_ocr._safe_preprocessing_version("AWS_SECRET_ACCESS_KEY=leak")


def test_effective_runtime_languages_are_normalized_before_reporting(tmp_path: Path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")

    class RuntimeConfig:
        model_version = "runtime-1"
        languages = ("IND", "eng")

    class RuntimeBackend(FakeBackend):
        def runtime_config(self, languages):
            return RuntimeConfig()

    report = benchmark_ocr.run_benchmark(
        input_dir, tmp_path / "report.json", "tesseract", backend=RuntimeBackend()
    ).report
    assert report["languages"] == ["ind", "eng"]


def test_malformed_input_returns_nonzero(tmp_path: Path):
    output = tmp_path / "report.json"

    assert benchmark_ocr.main(
        ["--input-dir", str(tmp_path / "missing"), "--output", str(output), "--engine", "tesseract"],
        backend=FakeBackend(),
    ) == 2
    assert not output.exists()
