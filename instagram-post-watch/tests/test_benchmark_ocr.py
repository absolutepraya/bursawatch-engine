from __future__ import annotations

import json
import os
import sys
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
    for selection in ("PP-OCRv5-id", "PP-OCRv5-en"):
        asset_dir = model_dir / selection
        asset_dir.mkdir(parents=True)
        (asset_dir / "model.bin").write_bytes(selection.encode())
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"files": ["PP-OCRv5-id/model.bin", "PP-OCRv5-en/model.bin"]}), encoding="utf-8"
    )
    return manifest


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
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(manifest))
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
    benchmark_ocr.run_benchmark(input_dir, tmp_path / "report.json", "paddleocr")
    assert seen == {"PADDLE_PDX_OFFLINE": "1", "PADDLEOCR_HOME": str(model_dir), "PADDLE_PDX_CACHE_HOME": str(model_dir)}
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
        return ProvisionedPaddleBackend()

    monkeypatch.setattr(benchmark_ocr, "build_backend", factory)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(manifest))
    monkeypatch.setenv("PADDLE_PDX_OFFLINE", "caller-value")
    benchmark_ocr.run_benchmark(input_dir, tmp_path / "report.json", "paddle")
    assert seen == {"engine": "paddleocr", "offline": "1"}
    assert os.environ["PADDLE_PDX_OFFLINE"] == "caller-value"


def test_empty_or_incomplete_paddle_manifest_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    manifest = model_dir / "manifest.json"
    manifest.write_text(json.dumps({"files": []}), encoding="utf-8")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(manifest))
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"a")
    assert benchmark_ocr.main(
        ["--input-dir", str(input_dir), "--output", str(tmp_path / "report.json"), "--engine", "paddleocr"]
    ) == 2


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
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(manifest))
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
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE", "1")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR", str(link_root / "models"))
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST", str(link_root / "models" / manifest.name))
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
        accuracy_notes='token: "hidden value" password=secret\x00 source /private/my secret.jpg',
    ).report
    assert report["preprocessing_version"] == "preprocess___local_run"
    assert "hidden" not in report["accuracy_notes"]
    assert "secret.jpg" not in report["accuracy_notes"]
    assert "secret" not in report["accuracy_notes"]
    assert "/" not in report["accuracy_notes"]


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
