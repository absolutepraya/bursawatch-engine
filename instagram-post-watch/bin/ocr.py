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
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
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
MAX_PADDLE_RESULT_LINES = 256
MAX_PADDLE_COMPACT_BYTES = 64 * 1024
DEFAULT_TESSERACT_PSM = "3"
TESSERACT_FALLBACK_PSM = "11"
DEFAULT_TESSERACT_MODEL_VERSION = "system-psm3-fallback11"
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
class PaddleModelSelection:
    source_language: str
    model_version: str
    constructor_kwargs: dict[str, object]


@dataclass(frozen=True)
class PaddleRuntimeConfig:
    languages: tuple[str, ...]
    model_version: str
    selections: tuple[PaddleModelSelection, ...]


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
    normalized = _normalize_extracted_result(result)
    return OCRResult(
        status=normalized.status,
        text=normalized.text,
        confidence=normalized.confidence,
        min_confidence=normalized.min_confidence,
        engine_id=result.engine_id or backend.engine_id,
        model_version=result.model_version or model_version,
        languages=tuple(languages),
        error=normalized.error,
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


def _cache_payload_consistent(status: OCRStatus, text: str, confidence: float | None, min_confidence: float | None) -> bool:
    if status is OCRStatus.NO_TEXT:
        return text == "" and confidence is None and min_confidence is None
    if status is OCRStatus.SUCCESS:
        if not text or confidence is None or min_confidence is None:
            return False
        return min_confidence <= confidence
    return False


def _normalize_extracted_result(result: OCRResult) -> OCRResult:
    status = OCRStatus(result.status)
    text = _cap_text(result.text, MAX_TEXT_PER_ASSET)
    confidence = result.confidence
    min_confidence = result.min_confidence
    if status is OCRStatus.SUCCESS and min_confidence is None:
        min_confidence = confidence
    try:
        confidence = _optional_confidence(confidence)
        min_confidence = _optional_confidence(min_confidence)
    except ValueError:
        return OCRResult(OCRStatus.UNCERTAIN, text=text, engine_id=result.engine_id, model_version=result.model_version, languages=result.languages, error="ocr output uncertain")
    if status in {OCRStatus.SUCCESS, OCRStatus.NO_TEXT} and not _cache_payload_consistent(status, text, confidence, min_confidence):
        return OCRResult(OCRStatus.UNCERTAIN, text=text if text else "", engine_id=result.engine_id, model_version=result.model_version, languages=result.languages, error="ocr output uncertain")
    return OCRResult(status, text, confidence, min_confidence, result.engine_id, result.model_version, result.languages, result.error)


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
        if not _cache_payload_consistent(status, _cap_text(text, MAX_TEXT_PER_ASSET), confidence, min_confidence):
            return None
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
        if math.isfinite(confidence) and 0 <= confidence <= 100:
            confidences.append(confidence / 100)
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
        model_version: str = DEFAULT_TESSERACT_MODEL_VERSION,
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
        base_command = [self.binary, str(path), "stdout", "-l", self.map_languages(languages)]
        try:
            stdout = self._runner(base_command + ["--psm", DEFAULT_TESSERACT_PSM, "tsv"], self.timeout_seconds, self.max_stdout_bytes)
        except FileNotFoundError as exc:
            raise OCRBackendUnavailable("ocr backend unavailable") from exc
        except (subprocess.TimeoutExpired, TimeoutError):
            raise
        except (subprocess.CalledProcessError, OCROutputLimitExceeded) as exc:
            raise RuntimeError("ocr backend failed") from exc
        result = parse_tesseract_tsv(stdout)
        if result.status is not OCRStatus.NO_TEXT:
            return result
        try:
            fallback_stdout = self._runner(base_command + ["--psm", TESSERACT_FALLBACK_PSM, "tsv"], self.timeout_seconds, self.max_stdout_bytes)
        except FileNotFoundError as exc:
            raise OCRBackendUnavailable("ocr backend unavailable") from exc
        except (subprocess.TimeoutExpired, TimeoutError):
            raise
        except (subprocess.CalledProcessError, OCROutputLimitExceeded) as exc:
            raise RuntimeError("ocr backend failed") from exc
        fallback = parse_tesseract_tsv(fallback_stdout)
        return fallback if fallback.status is not OCRStatus.NO_TEXT else result


def _paddle_line(line: object) -> tuple[str, float] | None:
    try:
        candidate = line[1]
        text = normalize_text(candidate[0])
        confidence = float(candidate[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if not text or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        return None
    return text, confidence


def _iter_paddle_lines(raw: object):
    if type(raw) in {str, bytes} or not hasattr(raw, "__iter__"):
        raise ValueError("ocr output malformed")
    for page in raw:
        if type(page) in {str, bytes} or not hasattr(page, "__iter__"):
            raise ValueError("ocr output malformed")
        for line in page:
            yield line


def _iter_paddle_result_lines(raw: object):
    """Yield text and confidence pairs from PaddleOCR 3.x or legacy output."""
    if type(raw) in {str, bytes} or not hasattr(raw, "__iter__"):
        raise ValueError("ocr output malformed")
    for page in raw:
        if hasattr(page, "get"):
            texts = page.get("rec_texts")
            scores = page.get("rec_scores")
            if texts is None or scores is None:
                raise ValueError("ocr output malformed")
            if not isinstance(texts, (list, tuple)) or not isinstance(scores, (list, tuple)) or len(texts) != len(scores):
                raise ValueError("ocr output malformed")
            for text, confidence in zip(texts, scores):
                yield (None, (text, confidence))
            continue
        for line in _iter_paddle_lines((page,)):
            yield line


def parse_paddle_output(raw: object, config: PaddleRuntimeConfig) -> OCRResult:
    text_parts: list[str] = []
    confidences: list[float] = []
    malformed_seen = False
    line_count = 0
    try:
        for line in _iter_paddle_result_lines(raw):
            line_count += 1
            if line_count > MAX_PADDLE_RESULT_LINES:
                return OCRResult(OCRStatus.ERROR, engine_id="paddleocr", model_version=config.model_version, error="ocr output exceeded limit")
            parsed = _paddle_line(line)
            if parsed is None:
                malformed_seen = True
                continue
            text, confidence = parsed
            text_parts.append(text)
            confidences.append(confidence)
            compact_bytes = len(json.dumps({"text": text_parts, "confidence": confidences}, separators=(",", ":")).encode("utf-8"))
            if compact_bytes > MAX_PADDLE_COMPACT_BYTES:
                return OCRResult(OCRStatus.ERROR, engine_id="paddleocr", model_version=config.model_version, error="ocr output exceeded limit")
            if sum(len(part) + 1 for part in text_parts) >= MAX_TEXT_PER_ASSET:
                break
    except ValueError:
        return OCRResult(OCRStatus.ERROR, engine_id="paddleocr", model_version=config.model_version, error="ocr output malformed")
    text = _cap_text(" ".join(text_parts), MAX_TEXT_PER_ASSET)
    if not text:
        if malformed_seen:
            return OCRResult(OCRStatus.UNCERTAIN, engine_id="paddleocr", model_version=config.model_version, error="ocr output uncertain")
        return OCRResult(OCRStatus.NO_TEXT, engine_id="paddleocr", model_version=config.model_version)
    if malformed_seen or not confidences:
        return OCRResult(OCRStatus.UNCERTAIN, text=text, engine_id="paddleocr", model_version=config.model_version, error="ocr output uncertain")
    confidence = sum(confidences) / len(confidences)
    min_confidence = min(confidences)
    return OCRResult(OCRStatus.SUCCESS, text=text, confidence=confidence, min_confidence=min_confidence, engine_id="paddleocr", model_version=config.model_version)


def _merge_ocr_results(results: tuple[OCRResult, ...], config: PaddleRuntimeConfig) -> OCRResult:
    if any(result.status is OCRStatus.ERROR for result in results):
        return OCRResult(OCRStatus.ERROR, engine_id="paddleocr", model_version=config.model_version, error="ocr output malformed")
    status = OCRStatus.SUCCESS
    if any(result.status is OCRStatus.UNCERTAIN for result in results):
        status = OCRStatus.UNCERTAIN
    elif all(result.status is OCRStatus.NO_TEXT for result in results):
        return OCRResult(OCRStatus.NO_TEXT, engine_id="paddleocr", model_version=config.model_version)
    texts = [result.text for result in results if result.text]
    confidences = [result.confidence for result in results if result.confidence is not None]
    min_confidences = [result.min_confidence for result in results if result.min_confidence is not None]
    text = _cap_text(" ".join(texts), MAX_TEXT_PER_ASSET)
    if status is OCRStatus.UNCERTAIN:
        return OCRResult(OCRStatus.UNCERTAIN, text=text, engine_id="paddleocr", model_version=config.model_version, error="ocr output uncertain")
    if not text or not confidences or not min_confidences:
        return OCRResult(OCRStatus.UNCERTAIN, text=text, engine_id="paddleocr", model_version=config.model_version, error="ocr output uncertain")
    return OCRResult(OCRStatus.SUCCESS, text=text, confidence=sum(confidences) / len(confidences), min_confidence=min(min_confidences), engine_id="paddleocr", model_version=config.model_version)


def _paddle_worker_extract(config: PaddleRuntimeConfig, image_path: Path, bindings: dict | None = None) -> OCRResult:
    module = importlib.import_module("paddleocr")
    results: list[OCRResult] = []
    for selection in config.selections:
        constructor_kwargs = dict(selection.constructor_kwargs)
        if bindings is not None:
            constructor_kwargs.update(bindings[selection.model_version]["constructor_kwargs"])
        engine = module.PaddleOCR(**constructor_kwargs)
        selection_config = PaddleRuntimeConfig(config.languages, selection.model_version, (selection,))
        results.append(parse_paddle_output(engine.predict(str(image_path)), selection_config))
    return _merge_ocr_results(tuple(results), config)


def _paddle_path_has_symlink_ancestor(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            return True
    return False


def _paddle_path_has_dot_segment(path: Path) -> bool:
    return any(component in {".", ".."} for component in path.parts)


def _validate_paddle_worker_bindings(config: PaddleRuntimeConfig) -> dict:
    """Revalidate the benchmark's exact local model bindings in the worker."""
    raw = os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_BINDINGS", "")
    try:
        payload = json.loads(raw)
        if type(payload) is not dict:
            raise ValueError
        for selection in config.selections:
            binding = payload[selection.model_version]
            model_dir = Path(binding["model_dir"])
            artifacts = binding["artifacts"]
            constructor_kwargs = binding["constructor_kwargs"]
            if (
                not model_dir.is_absolute()
                or _paddle_path_has_dot_segment(model_dir)
                or _paddle_path_has_symlink_ancestor(model_dir)
                or not model_dir.is_dir()
            ):
                raise ValueError
            if type(artifacts) is not list or not artifacts:
                raise ValueError
            if type(constructor_kwargs) is not dict or not constructor_kwargs:
                raise ValueError
            for key, value in constructor_kwargs.items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
                    raise ValueError
                if key.endswith("_dir"):
                    if not isinstance(value, str):
                        raise ValueError
                    path = Path(value)
                    if not path.is_absolute() or _paddle_path_has_dot_segment(path) or _paddle_path_has_symlink_ancestor(path):
                        raise ValueError
                    try:
                        path.relative_to(model_dir)
                    except ValueError as exc:
                        raise ValueError from exc
                    if not path.is_dir():
                        raise ValueError
                elif type(value) not in {str, bool, int, float}:
                    raise ValueError
            for artifact in artifacts:
                path = Path(artifact["path"])
                digest = artifact["sha256"]
                if _paddle_path_has_dot_segment(path):
                    raise ValueError
                try:
                    path.relative_to(model_dir)
                except ValueError as exc:
                    raise ValueError from exc
                if not path.is_absolute() or _paddle_path_has_symlink_ancestor(path):
                    raise ValueError
                stat = path.stat()
                if not path.is_file() or path.is_symlink() or stat.st_nlink != 1 or stat.st_size < 256 or type(digest) is not str or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                    raise ValueError
                hasher = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                if hasher.hexdigest() != digest:
                    raise ValueError
        return payload
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OCRBackendUnavailable("ocr backend unavailable") from exc


@contextmanager
def paddle_offline_network_guard():
    """Deny DNS and socket connection attempts for an offline Paddle worker."""
    denied = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline OCR network denied"))
    methods = ["connect", "connect_ex", "send", "sendall", "sendfile", "sendto"]
    if hasattr(socket.socket, "sendmsg"):
        methods.append("sendmsg")
    resolver_names = ["getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getfqdn", "getnameinfo"]
    original = {name: getattr(socket, name) for name in resolver_names}
    original["create_connection"] = socket.create_connection
    original.update({method: getattr(socket.socket, method) for method in methods})
    for name in resolver_names:
        setattr(socket, name, denied)
    socket.create_connection = denied
    for method in methods:
        setattr(socket.socket, method, denied)
    try:
        yield
    finally:
        for name in resolver_names:
            setattr(socket, name, original[name])
        socket.create_connection = original["create_connection"]
        for method in methods:
            setattr(socket.socket, method, original[method])


def _paddle_worker(config: PaddleRuntimeConfig, image_path: str, queue) -> None:
    try:
        if os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_HARD_OFFLINE") == "1":
            with paddle_offline_network_guard():
                bindings = _validate_paddle_worker_bindings(config)
                result = _paddle_worker_extract(config, Path(image_path), bindings)
        else:
            result = _paddle_worker_extract(config, Path(image_path))
        queue.put(("ok", asdict(result) | {"status": result.status.value}))
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
        try:
            return OCRResult(status=OCRStatus(payload["status"]), text=payload.get("text", ""), confidence=payload.get("confidence"), min_confidence=payload.get("min_confidence"), engine_id=payload.get("engine_id", "paddleocr"), model_version=payload.get("model_version", config.model_version), error=payload.get("error"))
        except Exception as exc:
            raise RuntimeError("ocr backend failed") from exc
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
        common_kwargs = {
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "enable_mkldnn": False,
        }
        selection_map = {
            "ind": PaddleModelSelection(
                "ind",
                f"{self._model_version}-id",
                common_kwargs
                | {
                    "text_recognition_model_name": "latin_PP-OCRv5_mobile_rec",
                },
            ),
            "eng": PaddleModelSelection(
                "eng",
                f"{self._model_version}-en",
                common_kwargs
                | {
                    "text_recognition_model_name": "en_PP-OCRv5_mobile_rec",
                },
            ),
        }
        if language_set == ("eng",):
            selections = (selection_map["eng"],)
        elif language_set == ("ind",):
            selections = (selection_map["ind"],)
        elif language_set == ("ind", "eng"):
            selections = (selection_map["ind"], selection_map["eng"])
        else:
            raise ValueError("unsupported OCR language")
        version = "+".join(selection.model_version for selection in selections)
        return PaddleRuntimeConfig(language_set, version, selections)

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult:
        try:
            config = self.runtime_config(languages)
            result = self._runner(config, path, self.timeout_seconds)
        except (OCRBackendUnavailable, TimeoutError):
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError("ocr backend failed") from exc
        if not isinstance(result, OCRResult):
            raise RuntimeError("ocr backend failed")
        return result


def build_backend(engine: str | None = None) -> OCRBackend:
    selected = (engine or os.environ.get("INSTAGRAM_POST_WATCH_OCR_ENGINE") or "tesseract").strip().lower()
    if selected == "tesseract":
        return TesseractBackend(
            binary=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_BINARY", "tesseract"),
            model_version=os.environ.get("INSTAGRAM_POST_WATCH_TESSERACT_MODEL_VERSION", DEFAULT_TESSERACT_MODEL_VERSION),
        )
    if selected in {"paddleocr", "paddle"}:
        return PaddleOCRBackend(model_version=os.environ.get("INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_VERSION", "PP-OCRv5"))
    raise ValueError(f"unknown OCR engine: {selected}")
