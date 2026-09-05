#!/usr/bin/env python3
"""Run a local, state-free OCR benchmark over a scratch image directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

from ocr import OCRBackend, OCRBackendUnavailable, OCRResult, OCRStatus, build_backend


IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
DEFAULT_LANGUAGES = ("ind", "eng")
DEFAULT_PREPROCESSING_VERSION = "preprocess-1"
MAX_NOTE_LENGTH = 2000


class BenchmarkInputError(ValueError):
    """Raised when the supplied scratch input or output cannot be used."""


@dataclass(frozen=True)
class BenchmarkResult:
    report: dict[str, object]
    unavailable: bool = False


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
    return label[:200] if re.fullmatch(r"[A-Za-z0-9_.:+-]{1,200}", label) else "unknown"


def _safe_notes(value: str) -> str:
    notes = re.sub(r"(?i)(?:token|password|secret|api[_-]?key)\s*=\s*[^\s,;]+", "[redacted]", value)
    notes = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s,;]+)", "[path-redacted]", notes)
    notes = re.sub(r"(?i)\b[A-Z]:\\[^\s,;]+", "[path-redacted]", notes)
    return notes[:MAX_NOTE_LENGTH]


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


def _safe_result(result: OCRResult, backend: OCRBackend, languages: tuple[str, ...]) -> OCRResult:
    """Keep injected backends from placing unbounded or sensitive values in output."""
    try:
        status = OCRStatus(result.status)
    except (TypeError, ValueError):
        return OCRResult(OCRStatus.ERROR, engine_id=backend.engine_id, model_version=backend.model_version, languages=languages)
    text = result.text if isinstance(result.text, str) else ""
    confidence = result.confidence if isinstance(result.confidence, (int, float)) else None
    if confidence is not None and not 0 <= confidence <= 1:
        confidence = None
    return OCRResult(
        status=status,
        text=text[:4000],
        confidence=confidence,
        engine_id=str(result.engine_id or backend.engine_id)[:200],
        model_version=str(result.model_version or backend.model_version)[:200],
        languages=languages,
    )


def run_benchmark(
    input_dir: Path,
    output: Path,
    engine: str,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGES,
    preprocessing_version: str = DEFAULT_PREPROCESSING_VERSION,
    accuracy_notes: str = "",
    backend: OCRBackend | None = None,
) -> BenchmarkResult:
    """Benchmark an injected or Task 3 backend without using OCR cache/state."""
    input_dir = Path(input_dir)
    output = Path(output)
    language_set = _normalise_languages(languages)
    if not preprocessing_version or len(preprocessing_version) > 200:
        raise BenchmarkInputError("preprocessing version is invalid")
    if len(accuracy_notes) > MAX_NOTE_LENGTH:
        raise BenchmarkInputError("accuracy notes are too long")
    paths = _image_paths(input_dir)
    selected = backend or build_backend(engine)
    started = time.perf_counter()
    images: list[dict[str, object]] = []
    unavailable = False

    for path in paths:
        image_started = time.perf_counter()
        try:
            _sha256(path)
            result = _safe_result(selected.extract(path, language_set), selected, language_set)
        except OCRBackendUnavailable:
            result = OCRResult(OCRStatus.UNAVAILABLE, engine_id=selected.engine_id, model_version=selected.model_version, languages=language_set)
        except (OSError, ValueError):
            raise BenchmarkInputError("an input image is malformed or unreadable")
        except TimeoutError:
            result = OCRResult(OCRStatus.TIMEOUT, engine_id=selected.engine_id, model_version=selected.model_version, languages=language_set)
        except Exception:
            result = OCRResult(OCRStatus.ERROR, engine_id=selected.engine_id, model_version=selected.model_version, languages=language_set)
        unavailable = unavailable or result.status is OCRStatus.UNAVAILABLE
        images.append(
            {
                "path": path.relative_to(input_dir).as_posix(),
                "latency_seconds": round(time.perf_counter() - image_started, 6),
                "status": result.status.value,
                "character_count": len(result.text),
                "confidence": result.confidence,
            }
        )

    report = {
        "engine_id": _safe_label(selected.engine_id),
        "model_version": _safe_label(selected.model_version),
        "languages": list(language_set),
        "preprocessing_version": preprocessing_version,
        "images": images,
        "total_latency_seconds": round(time.perf_counter() - started, 6),
        "peak_rss_bytes": _peak_rss_bytes(),
        "accuracy_notes": _safe_notes(accuracy_notes),
    }
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise OSError("output path is invalid")
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise BenchmarkInputError("output path is invalid") from exc
    return BenchmarkResult(report, unavailable=unavailable)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine", required=True, choices=("tesseract", "paddleocr"))
    parser.add_argument("--languages", nargs="+", default=list(DEFAULT_LANGUAGES), metavar="LANG")
    parser.add_argument("--preprocessing-version", default=DEFAULT_PREPROCESSING_VERSION)
    parser.add_argument("--accuracy-notes", default="")
    return parser


def main(argv: Sequence[str] | None = None, *, backend: OCRBackend | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_benchmark(
            args.input_dir,
            args.output,
            args.engine,
            languages=args.languages,
            preprocessing_version=args.preprocessing_version,
            accuracy_notes=args.accuracy_notes,
            backend=backend,
        )
    except (BenchmarkInputError, OCRBackendUnavailable, ValueError):
        return 2
    return 2 if result.unavailable else 0


if __name__ == "__main__":
    raise SystemExit(main())
