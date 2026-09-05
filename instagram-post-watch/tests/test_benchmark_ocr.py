from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import benchmark_ocr
import ocr


class FakeBackend:
    engine_id = "fake"
    model_version = "test-1"

    def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
        return ocr.OCRResult(ocr.OCRStatus.SUCCESS, path.stem, 0.91)


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

    assert result.unavailable is False
    assert [image["path"] for image in report["images"]] == ["a.png", "b.jpg"]
    assert all("/" not in image["path"] for image in report["images"])
    assert report["accuracy_notes"] == "manual [redacted] [path-redacted]"
    assert report["languages"] == ["ind", "eng"]


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


def test_malformed_input_returns_nonzero(tmp_path: Path):
    output = tmp_path / "report.json"

    assert benchmark_ocr.main(
        ["--input-dir", str(tmp_path / "missing"), "--output", str(output), "--engine", "tesseract"],
        backend=FakeBackend(),
    ) == 2
    assert not output.exists()
