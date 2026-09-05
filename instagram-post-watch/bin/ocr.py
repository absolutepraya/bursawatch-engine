from __future__ import annotations

import csv
import hashlib
import importlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from models import DownloadedAsset


MAX_TEXT_PER_ASSET = 4000
MAX_TEXT_PER_PUBLICATION = 16000
DEFAULT_PREPROCESSING_VERSION = "preprocess-1"
DEFAULT_TIMEOUT_SECONDS = 30


class OCRStatus(StrEnum):
    SUCCESS = "success"
    NO_TEXT = "no_text"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class OCRResult:
    status: OCRStatus
    text: str = ""
    confidence: float | None = None
    min_confidence: float | None = None
    engine_id: str = ""
    model_version: str = ""
    languages: tuple[str, ...] = ()
    error: str | None = None


class OCRBackendUnavailable(RuntimeError):
    pass


class OCRCacheError(RuntimeError):
    pass


class OCRBackend(Protocol):
    @property
    def engine_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult: ...


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cap_text(text: str, limit: int) -> str:
    normalized = normalize_text(text)
    return normalized[:limit]


def cache_key(
    image_sha256: str,
    engine: str,
    languages: tuple[str, ...],
    preprocessing_version: str,
) -> str:
    payload = {
        "image_sha256": image_sha256,
        "engine": engine,
        "languages": list(languages),
        "preprocessing_version": preprocessing_version,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _result_with_context(result: OCRResult, backend: OCRBackend, languages: tuple[str, ...]) -> OCRResult:
    return OCRResult(
        status=OCRStatus(result.status),
        text=_cap_text(result.text, MAX_TEXT_PER_ASSET),
        confidence=result.confidence,
        min_confidence=result.min_confidence,
        engine_id=backend.engine_id,
        model_version=backend.model_version,
        languages=tuple(languages),
        error=result.error,
    )


def _cacheable(result: OCRResult) -> bool:
    return result.status in {OCRStatus.SUCCESS, OCRStatus.NO_TEXT}


def _safe_cache_root(cache_root: Path) -> Path:
    if cache_root.exists() and (cache_root.is_symlink() or not cache_root.is_dir()):
        raise OCRCacheError("cache root is invalid")
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise OCRCacheError("cache root is invalid") from exc
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise OCRCacheError("cache root is invalid")
    return cache_root.resolve()


def _cache_path(cache_root: Path, key: str) -> Path:
    root = _safe_cache_root(cache_root)
    path = (root / f"{key}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OCRCacheError("cache path is invalid") from exc
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise OCRCacheError("cache path is invalid")
    return path


def _read_cache(path: Path) -> OCRResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    try:
        status = OCRStatus(payload["status"])
        if not _cacheable(OCRResult(status=status)):
            return None
        return OCRResult(
            status=status,
            text=_cap_text(str(payload.get("text", "")), MAX_TEXT_PER_ASSET),
            confidence=payload.get("confidence"),
            min_confidence=payload.get("min_confidence"),
            engine_id=str(payload.get("engine_id", "")),
            model_version=str(payload.get("model_version", "")),
            languages=tuple(str(language) for language in payload.get("languages", ())),
            error=None,
        )
    except Exception:
        return None


def _write_cache(path: Path, result: OCRResult) -> None:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["languages"] = list(result.languages)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def extract_cached(
    asset: DownloadedAsset,
    cache_root: Path,
    backend: OCRBackend,
    languages: tuple[str, ...],
    *,
    preprocessing_version: str = DEFAULT_PREPROCESSING_VERSION,
) -> OCRResult:
    engine = f"{backend.engine_id}:{backend.model_version}"
    path = _cache_path(cache_root, cache_key(asset.sha256, engine, languages, preprocessing_version))
    cached = _read_cache(path)
    if cached is not None:
        return cached
    try:
        extracted = _result_with_context(backend.extract(asset.path, languages), backend, languages)
    except OCRBackendUnavailable:
        return OCRResult(OCRStatus.UNAVAILABLE, engine_id=backend.engine_id, model_version=backend.model_version, languages=languages, error="ocr backend unavailable")
    except TimeoutError:
        return OCRResult(OCRStatus.TIMEOUT, engine_id=backend.engine_id, model_version=backend.model_version, languages=languages, error="ocr backend timed out")
    except subprocess.TimeoutExpired:
        return OCRResult(OCRStatus.TIMEOUT, engine_id=backend.engine_id, model_version=backend.model_version, languages=languages, error="ocr backend timed out")
    except Exception:
        return OCRResult(OCRStatus.ERROR, engine_id=backend.engine_id, model_version=backend.model_version, languages=languages, error="ocr backend failed")
    if _cacheable(extracted):
        _write_cache(path, extracted)
    return extracted


def bound_publication_results(results: tuple[OCRResult, ...]) -> tuple[OCRResult, ...]:
    remaining = MAX_TEXT_PER_PUBLICATION
    bounded: list[OCRResult] = []
    for result in results:
        text = _cap_text(result.text, min(MAX_TEXT_PER_ASSET, max(remaining, 0)))
        remaining -= len(text)
        bounded.append(OCRResult(result.status, text, result.confidence, result.min_confidence, result.engine_id, result.model_version, result.languages, result.error))
    return tuple(bounded)


def parse_tesseract_tsv(tsv: str) -> OCRResult:
    words: list[str] = []
    confidences: list[float] = []
    reader = csv.DictReader(tsv.splitlines(), delimiter="\t")
    for row in reader:
        word = normalize_text(row.get("text", ""))
        if not word:
            continue
        words.append(word)
        try:
            confidence = float(row.get("conf", ""))
        except ValueError:
            continue
        if confidence >= 0:
            confidences.append(min(confidence / 100, 1.0))
    text = _cap_text(" ".join(words), MAX_TEXT_PER_ASSET)
    if not text:
        return OCRResult(OCRStatus.NO_TEXT)
    confidence = sum(confidences) / len(confidences) if confidences else None
    min_confidence = min(confidences) if confidences else None
    return OCRResult(OCRStatus.SUCCESS, text=text, confidence=confidence, min_confidence=min_confidence)


class TesseractBackend:
    def __init__(self, *, binary: str = "tesseract", model_version: str = "system", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.binary = binary
        self._model_version = model_version
        self.timeout_seconds = timeout_seconds

    @property
    def engine_id(self) -> str:
        return "tesseract"

    @property
    def model_version(self) -> str:
        return self._model_version

    def map_languages(self, languages: tuple[str, ...]) -> str:
        mapping = {"ind": "ind", "eng": "eng"}
        try:
            return "+".join(mapping[language] for language in languages)
        except KeyError as exc:
            raise ValueError("unsupported OCR language") from exc

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult:
        command = [self.binary, str(path), "stdout", "-l", self.map_languages(languages), "tsv"]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=self.timeout_seconds)
        except FileNotFoundError as exc:
            raise OCRBackendUnavailable("ocr backend unavailable") from exc
        except subprocess.TimeoutExpired:
            raise
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("ocr backend failed") from exc
        return parse_tesseract_tsv(result.stdout)


class PaddleOCRBackend:
    def __init__(self, *, model_version: str = "pp-ocrv5-mobile"):
        self._model_version = model_version
        self._instances: dict[str, object] = {}

    @property
    def engine_id(self) -> str:
        return "paddleocr"

    @property
    def model_version(self) -> str:
        return self._model_version

    def _language_key(self, languages: tuple[str, ...]) -> str:
        if "ind" in languages and "eng" in languages:
            return "latin"
        if "ind" in languages:
            return "id"
        if "eng" in languages:
            return "en"
        raise ValueError("unsupported OCR language")

    def _instance(self, languages: tuple[str, ...]):
        language = self._language_key(languages)
        if language not in self._instances:
            try:
                module = importlib.import_module("paddleocr")
                self._instances[language] = module.PaddleOCR(lang=language)
            except ImportError as exc:
                raise OCRBackendUnavailable("ocr backend unavailable") from exc
            except Exception as exc:
                raise RuntimeError("ocr backend failed") from exc
        return self._instances[language]

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult:
        engine = self._instance(languages)
        try:
            raw = engine.ocr(str(path))
        except Exception as exc:
            raise RuntimeError("ocr backend failed") from exc
        text_parts: list[str] = []
        confidences: list[float] = []
        for page in raw or ():
            for line in page or ():
                try:
                    text = normalize_text(line[1][0])
                    confidence = float(line[1][1])
                except (TypeError, ValueError, IndexError):
                    continue
                if text:
                    text_parts.append(text)
                    confidences.append(max(0.0, min(confidence, 1.0)))
        text = _cap_text(" ".join(text_parts), MAX_TEXT_PER_ASSET)
        if not text:
            return OCRResult(OCRStatus.NO_TEXT)
        confidence = sum(confidences) / len(confidences) if confidences else None
        min_confidence = min(confidences) if confidences else None
        return OCRResult(OCRStatus.SUCCESS, text=text, confidence=confidence, min_confidence=min_confidence)


def build_backend(engine: str | None = None) -> OCRBackend:
    selected = (engine or os.environ.get("INSTAGRAM_POST_WATCH_OCR_ENGINE") or "tesseract").strip().lower()
    if selected == "tesseract":
        return TesseractBackend(
            binary=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_BINARY", "tesseract"),
            model_version=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_MODEL_VERSION", "system"),
        )
    if selected in {"paddleocr", "paddle"}:
        return PaddleOCRBackend(model_version=os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_VERSION", "pp-ocrv5-mobile"))
    raise ValueError(f"unknown OCR engine: {selected}")
