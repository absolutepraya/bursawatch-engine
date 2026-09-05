from __future__ import annotations

import csv
import hashlib
import importlib
import json
import math
import multiprocessing
import os
import re
import selectors
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol

from models import DownloadedAsset


MAX_TEXT_PER_ASSET = 4000
MAX_TEXT_PER_PUBLICATION = 16000
DEFAULT_PREPROCESSING_VERSION = "preprocess-1"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TESSERACT_STDOUT_BYTES = 512 * 1024
_TESSERACT_REQUIRED_FIELDS = {"conf", "text"}


class OCRStatus(StrEnum):
    SUCCESS = "success"
    NO_TEXT = "no_text"
    UNCERTAIN = "uncertain"
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


class OCROutputLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class PaddleRuntimeConfig:
    languages: tuple[str, ...]
    model_version: str
    constructor_kwargs: dict[str, str]


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


def _backend_model_version(backend: OCRBackend, languages: tuple[str, ...]) -> str:
    runtime_config = getattr(backend, "runtime_config", None)
    if callable(runtime_config):
        return runtime_config(languages).model_version
    return backend.model_version


def _result_with_context(result: OCRResult, backend: OCRBackend, languages: tuple[str, ...], model_version: str) -> OCRResult:
    return OCRResult(
        status=OCRStatus(result.status),
        text=_cap_text(result.text, MAX_TEXT_PER_ASSET),
        confidence=result.confidence,
        min_confidence=result.min_confidence,
        engine_id=result.engine_id or backend.engine_id,
        model_version=result.model_version or model_version,
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


def _optional_confidence(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise ValueError("invalid confidence")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ValueError("invalid confidence")
    return parsed


def _read_cache(
    path: Path,
    *,
    image_sha256: str,
    engine_id: str,
    model_version: str,
    languages: tuple[str, ...],
    preprocessing_version: str,
) -> OCRResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    try:
        if type(payload) is not dict:
            return None
        status = OCRStatus(payload["status"])
        if not _cacheable(OCRResult(status=status)):
            return None
        if payload.get("image_sha256") != image_sha256:
            return None
        if payload.get("engine_id") != engine_id:
            return None
        if payload.get("model_version") != model_version:
            return None
        payload_languages = payload.get("languages", ())
        if type(payload_languages) is not list or any(type(language) is not str for language in payload_languages):
            return None
        if tuple(payload_languages) != languages:
            return None
        if payload.get("preprocessing_version") != preprocessing_version:
            return None
        text = payload.get("text", "")
        if type(text) is not str:
            return None
        confidence = _optional_confidence(payload.get("confidence"))
        min_confidence = _optional_confidence(payload.get("min_confidence"))
        return OCRResult(
            status=status,
            text=_cap_text(text, MAX_TEXT_PER_ASSET),
            confidence=confidence,
            min_confidence=min_confidence,
            engine_id=str(payload.get("engine_id", "")),
            model_version=str(payload.get("model_version", "")),
            languages=tuple(str(language) for language in payload.get("languages", ())),
            error=None,
        )
    except Exception:
        return None


def _write_cache(path: Path, result: OCRResult, *, image_sha256: str, preprocessing_version: str) -> None:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["languages"] = list(result.languages)
    payload["image_sha256"] = image_sha256
    payload["preprocessing_version"] = preprocessing_version
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
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
    model_version = _backend_model_version(backend, languages)
    engine = f"{backend.engine_id}:{model_version}"
    path = _cache_path(cache_root, cache_key(asset.sha256, engine, languages, preprocessing_version))
    cached = _read_cache(
        path,
        image_sha256=asset.sha256,
        engine_id=backend.engine_id,
        model_version=model_version,
        languages=languages,
        preprocessing_version=preprocessing_version,
    )
    if cached is not None:
        return cached
    try:
        extracted = _result_with_context(backend.extract(asset.path, languages), backend, languages, model_version)
    except OCRBackendUnavailable:
        return OCRResult(OCRStatus.UNAVAILABLE, engine_id=backend.engine_id, model_version=model_version, languages=languages, error="ocr backend unavailable")
    except TimeoutError:
        return OCRResult(OCRStatus.TIMEOUT, engine_id=backend.engine_id, model_version=model_version, languages=languages, error="ocr backend timed out")
    except subprocess.TimeoutExpired:
        return OCRResult(OCRStatus.TIMEOUT, engine_id=backend.engine_id, model_version=model_version, languages=languages, error="ocr backend timed out")
    except Exception:
        return OCRResult(OCRStatus.ERROR, engine_id=backend.engine_id, model_version=model_version, languages=languages, error="ocr backend failed")
    if _cacheable(extracted):
        _write_cache(path, extracted, image_sha256=asset.sha256, preprocessing_version=preprocessing_version)
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
    if not tsv.strip():
        return OCRResult(OCRStatus.NO_TEXT)
    words: list[str] = []
    confidences: list[float] = []
    invalid_confidence = False
    try:
        reader = csv.DictReader(tsv.splitlines(), delimiter="\t")
    except csv.Error:
        return OCRResult(OCRStatus.ERROR, error="ocr output malformed")
    if reader.fieldnames is None or not _TESSERACT_REQUIRED_FIELDS.issubset(set(reader.fieldnames)):
        return OCRResult(OCRStatus.ERROR, error="ocr output malformed")
    for row in reader:
        word = normalize_text(row.get("text", ""))
        if not word:
            continue
        words.append(word)
        try:
            confidence = float(row.get("conf", ""))
        except (TypeError, ValueError):
            invalid_confidence = True
            continue
        if math.isfinite(confidence) and confidence >= 0:
            confidences.append(min(confidence / 100, 1.0))
        else:
            invalid_confidence = True
        if sum(len(part) + 1 for part in words) >= MAX_TEXT_PER_ASSET:
            break
    text = _cap_text(" ".join(words), MAX_TEXT_PER_ASSET)
    if not text:
        return OCRResult(OCRStatus.NO_TEXT)
    if invalid_confidence or not confidences:
        return OCRResult(OCRStatus.UNCERTAIN, text=text, error="ocr confidence unavailable")
    confidence = sum(confidences) / len(confidences) if confidences else None
    min_confidence = min(confidences) if confidences else None
    return OCRResult(OCRStatus.SUCCESS, text=text, confidence=confidence, min_confidence=min_confidence)


def _run_tesseract_command(command: list[str], timeout_seconds: int, max_stdout_bytes: int) -> str:
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise OCRBackendUnavailable("ocr backend unavailable") from exc
    if process.stdout is None:
        raise RuntimeError("ocr backend failed")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    started = time.monotonic()
    chunks = bytearray()
    try:
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                process.kill()
                process.wait()
                raise TimeoutError("ocr backend timed out")
            events = selector.select(min(0.1, remaining))
            if not events:
                if process.poll() is not None:
                    break
                continue
            data = process.stdout.read1(8192)
            if not data:
                if process.poll() is not None:
                    break
                continue
            chunks.extend(data)
            if len(chunks) > max_stdout_bytes:
                process.kill()
                process.wait()
                raise OCROutputLimitExceeded("ocr output exceeded limit")
        return_code = process.wait(timeout=max(0.1, timeout_seconds - (time.monotonic() - started)))
    except TimeoutError:
        raise
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise TimeoutError("ocr backend timed out") from exc
    finally:
        selector.close()
    if return_code != 0:
        raise RuntimeError("ocr backend failed")
    return bytes(chunks).decode("utf-8", errors="replace")


class TesseractBackend:
    def __init__(
        self,
        *,
        binary: str = "tesseract",
        model_version: str = "system",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_stdout_bytes: int = MAX_TESSERACT_STDOUT_BYTES,
        runner: Callable[[list[str], int, int], str] | None = None,
    ):
        self.binary = binary
        self._model_version = model_version
        self.timeout_seconds = timeout_seconds
        self.max_stdout_bytes = max_stdout_bytes
        self._runner = runner or _run_tesseract_command

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
            stdout = self._runner(command, self.timeout_seconds, self.max_stdout_bytes)
        except FileNotFoundError as exc:
            raise OCRBackendUnavailable("ocr backend unavailable") from exc
        except (subprocess.TimeoutExpired, TimeoutError):
            raise
        except (subprocess.CalledProcessError, OCROutputLimitExceeded) as exc:
            raise RuntimeError("ocr backend failed") from exc
        return parse_tesseract_tsv(stdout)


def _paddle_worker(config: PaddleRuntimeConfig, image_path: str, queue) -> None:
    try:
        module = importlib.import_module("paddleocr")
        engine = module.PaddleOCR(**config.constructor_kwargs)
        queue.put(("ok", engine.ocr(image_path)))
    except ImportError:
        queue.put(("unavailable", None))
    except Exception:
        queue.put(("error", None))


def _run_paddle_process(config: PaddleRuntimeConfig, path: Path, timeout_seconds: int):
    queue = multiprocessing.Queue(maxsize=1)
    process = multiprocessing.Process(target=_paddle_worker, args=(config, str(path), queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join()
        raise TimeoutError("ocr backend timed out")
    try:
        status, payload = queue.get_nowait()
    except Exception as exc:
        raise RuntimeError("ocr backend failed") from exc
    if status == "ok":
        return payload
    if status == "unavailable":
        raise OCRBackendUnavailable("ocr backend unavailable")
    raise RuntimeError("ocr backend failed")


class PaddleOCRBackend:
    def __init__(
        self,
        *,
        model_version: str = "PP-OCRv5",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        runner: Callable[[PaddleRuntimeConfig, Path, int], object] | None = None,
    ):
        self._model_version = model_version
        self.timeout_seconds = timeout_seconds
        self._runner = runner or _run_paddle_process

    @property
    def engine_id(self) -> str:
        return "paddleocr"

    @property
    def model_version(self) -> str:
        return self._model_version

    def runtime_config(self, languages: tuple[str, ...]) -> PaddleRuntimeConfig:
        language_set = tuple(languages)
        if language_set == ("eng",):
            lang = "en"
        elif language_set in {("ind",), ("ind", "eng")}:
            # PaddleOCR's public runtime uses its Latin-script recognition family for Indonesian text.
            lang = "latin"
        else:
            raise ValueError("unsupported OCR language")
        version = f"{self._model_version}-{lang}"
        return PaddleRuntimeConfig(language_set, version, {"lang": lang, "ocr_version": self._model_version})

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult:
        try:
            config = self.runtime_config(languages)
            raw = self._runner(config, path, self.timeout_seconds)
        except (OCRBackendUnavailable, TimeoutError):
            raise
        except ValueError:
            raise
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
                if text and math.isfinite(confidence):
                    text_parts.append(text)
                    confidences.append(max(0.0, min(confidence, 1.0)))
                    if sum(len(part) + 1 for part in text_parts) >= MAX_TEXT_PER_ASSET:
                        break
            if sum(len(part) + 1 for part in text_parts) >= MAX_TEXT_PER_ASSET:
                break
        text = _cap_text(" ".join(text_parts), MAX_TEXT_PER_ASSET)
        if not text:
            return OCRResult(OCRStatus.NO_TEXT, engine_id=self.engine_id, model_version=config.model_version)
        confidence = sum(confidences) / len(confidences) if confidences else None
        min_confidence = min(confidences) if confidences else None
        if not confidences:
            return OCRResult(OCRStatus.UNCERTAIN, text=text, engine_id=self.engine_id, model_version=config.model_version, error="ocr confidence unavailable")
        return OCRResult(OCRStatus.SUCCESS, text=text, confidence=confidence, min_confidence=min_confidence, engine_id=self.engine_id, model_version=config.model_version)


def build_backend(engine: str | None = None) -> OCRBackend:
    selected = (engine or os.environ.get("INSTAGRAM_POST_WATCH_OCR_ENGINE") or "tesseract").strip().lower()
    if selected == "tesseract":
        return TesseractBackend(
            binary=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_BINARY", "tesseract"),
            model_version=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_MODEL_VERSION", "system"),
        )
    if selected in {"paddleocr", "paddle"}:
        return PaddleOCRBackend(model_version=os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_VERSION", "PP-OCRv5"))
    raise ValueError(f"unknown OCR engine: {selected}")
