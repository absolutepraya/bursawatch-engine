from __future__ import annotations

from pathlib import Path

import pytest

import ocr
from models import DownloadedAsset, MediaKind, SourceMedia


class FakeBackend:
    engine_id = "fake"
    model_version = "v1"

    def __init__(self, result=None, *, raises: Exception | None = None):
        self.result = result
        self.raises = raises
        self.calls = 0

    def extract(self, path: Path, languages: tuple[str, ...]) -> ocr.OCRResult:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        assert self.result is not None
        return self.result


def asset(tmp_path: Path, *, sha256: str = "a" * 64) -> DownloadedAsset:
    path = tmp_path / f"{sha256[:8]}.jpg"
    path.write_bytes(b"image")
    return DownloadedAsset(
        SourceMedia("https://cdn.example/image.jpg", MediaKind.IMAGE, 0),
        path,
        sha256,
        5,
        "image/jpeg",
    )


def test_cache_key_changes_when_engine_changes():
    tesseract = ocr.cache_key("abc", "tesseract:5.3", ("ind", "eng"), "preprocess-1")
    paddle = ocr.cache_key("abc", "paddleocr:pp-ocrv5-mobile", ("ind", "eng"), "preprocess-1")

    assert tesseract != paddle


@pytest.mark.parametrize(
    ("kwargs", "other_kwargs"),
    [
        ({"image_sha256": "abc"}, {"image_sha256": "def"}),
        ({"engine": "tesseract:5.3"}, {"engine": "tesseract:5.4"}),
        ({"languages": ("ind", "eng")}, {"languages": ("eng", "ind")}),
        ({"preprocessing_version": "preprocess-1"}, {"preprocessing_version": "preprocess-2"}),
    ],
)
def test_cache_key_includes_all_identity_inputs(kwargs, other_kwargs):
    base = {
        "image_sha256": "abc",
        "engine": "tesseract:5.3",
        "languages": ("ind", "eng"),
        "preprocessing_version": "preprocess-1",
    }

    assert ocr.cache_key(**(base | kwargs)) != ocr.cache_key(**(base | other_kwargs))


def test_extract_cached_writes_and_reads_successful_text_result(tmp_path):
    source = asset(tmp_path, sha256="1" * 64)
    result = ocr.OCRResult(status=ocr.OCRStatus.SUCCESS, text="  IDX\n  earnings\tup  ", confidence=0.91)
    backend = FakeBackend(result)

    first = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))
    second = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))

    assert first.status is ocr.OCRStatus.SUCCESS
    assert first.text == "IDX earnings up"
    assert second == first
    assert backend.calls == 1


def test_extract_cached_writes_and_reads_blank_result(tmp_path):
    source = asset(tmp_path, sha256="2" * 64)
    backend = FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.NO_TEXT, text="", confidence=None))

    first = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))
    second = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))

    assert first.status is ocr.OCRStatus.NO_TEXT
    assert second.status is ocr.OCRStatus.NO_TEXT
    assert backend.calls == 1


def test_extract_cached_does_not_cache_backend_errors(tmp_path):
    source = asset(tmp_path, sha256="3" * 64)
    backend = FakeBackend(raises=RuntimeError("secret stdout with token abc123"))

    first = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))
    second = ocr.extract_cached(source, tmp_path / "cache", backend, ("ind", "eng"))

    assert first.status is ocr.OCRStatus.ERROR
    assert second.status is ocr.OCRStatus.ERROR
    assert first.error == "ocr backend failed"
    assert "secret" not in (first.error or "")
    assert backend.calls == 2


def test_extract_cached_sanitizes_timeout_and_unavailable_without_cache(tmp_path):
    source = asset(tmp_path, sha256="4" * 64)
    timeout = FakeBackend(raises=TimeoutError("command timed out after dumping args"))
    unavailable = FakeBackend(raises=ocr.OCRBackendUnavailable("missing /private/path/tesseract"))

    timeout_result = ocr.extract_cached(source, tmp_path / "cache", timeout, ("ind",))
    unavailable_result = ocr.extract_cached(source, tmp_path / "cache", unavailable, ("ind",))

    assert timeout_result.status is ocr.OCRStatus.TIMEOUT
    assert timeout_result.error == "ocr backend timed out"
    assert unavailable_result.status is ocr.OCRStatus.UNAVAILABLE
    assert unavailable_result.error == "ocr backend unavailable"


def test_text_is_capped_per_asset_and_publication(tmp_path):
    source = asset(tmp_path)
    backend = FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.SUCCESS, text="x" * 5000, confidence=0.9))
    single = ocr.extract_cached(source, tmp_path / "cache", backend, ("eng",))

    bounded = ocr.bound_publication_results(
        tuple(ocr.OCRResult(status=ocr.OCRStatus.SUCCESS, text=str(index % 10) * 5000, confidence=0.9) for index in range(5))
    )

    assert len(single.text) == ocr.MAX_TEXT_PER_ASSET
    assert sum(len(result.text) for result in bounded) == ocr.MAX_TEXT_PER_PUBLICATION


def test_cache_root_is_bounded_and_requires_regular_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_link = tmp_path / "cache-link"
    cache_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ocr.OCRCacheError, match="cache root is invalid"):
        ocr.extract_cached(asset(tmp_path), cache_link, FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.NO_TEXT)), ("eng",))


def test_build_backend_rejects_unknown_engine():
    with pytest.raises(ValueError, match="unknown OCR engine"):
        ocr.build_backend("unknown-engine")


def test_tesseract_language_mapping_is_safe_and_ordered():
    backend = ocr.TesseractBackend(binary="tesseract")

    assert backend.map_languages(("ind", "eng")) == "ind+eng"


def test_parse_tesseract_tsv_ignores_invalid_confidence_and_blank_words():
    result = ocr.parse_tesseract_tsv(
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t96\tTotal\n"
        "5\t1\t1\t1\t1\t2\tbad\t\n"
        "5\t1\t1\t1\t2\t1\t70\tAssets\n"
    )

    assert result.status is ocr.OCRStatus.SUCCESS
    assert result.text == "Total Assets"
    assert result.confidence == pytest.approx(0.83)


def test_parse_tesseract_tsv_distinguishes_blank_from_malformed():
    blank = ocr.parse_tesseract_tsv("level\tconf\ttext\n5\t-1\t\n")
    malformed = ocr.parse_tesseract_tsv("not a tsv document with recognized headers")

    assert blank.status is ocr.OCRStatus.NO_TEXT
    assert malformed.status is ocr.OCRStatus.ERROR
    assert malformed.error == "ocr output malformed"


@pytest.mark.parametrize("confidence", ["", "bad", "nan", "inf"])
def test_parse_tesseract_tsv_with_text_but_invalid_confidence_is_uncertain(confidence):
    parsed = ocr.parse_tesseract_tsv(f"level\tconf\ttext\n5\t{confidence}\tRevenue\n")

    assert parsed.status is ocr.OCRStatus.UNCERTAIN
    assert parsed.text == "Revenue"
    assert parsed.confidence is None
    assert parsed.error == "ocr confidence unavailable"


def test_parse_tesseract_tsv_any_text_word_with_invalid_confidence_is_uncertain():
    parsed = ocr.parse_tesseract_tsv(
        "level\tconf\ttext\n"
        "5\t96\tRevenue\n"
        "5\tbad\tGrowth\n"
    )

    assert parsed.status is ocr.OCRStatus.UNCERTAIN
    assert parsed.text == "Revenue Growth"
    assert parsed.error == "ocr confidence unavailable"


def test_tesseract_runner_output_limit_is_sanitized_by_cache(tmp_path):
    source = asset(tmp_path, sha256="5" * 64)

    def runner(command, timeout_seconds, max_stdout_bytes):
        raise ocr.OCROutputLimitExceeded("stdout contained raw OCR text")

    backend = ocr.TesseractBackend(binary="tesseract", runner=runner)
    result = ocr.extract_cached(source, tmp_path / "cache", backend, ("eng",))

    assert result.status is ocr.OCRStatus.ERROR
    assert result.error == "ocr backend failed"


def test_cache_mismatch_is_a_miss_not_a_trusted_hit(tmp_path):
    source = asset(tmp_path, sha256="6" * 64)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    key = ocr.cache_key(source.sha256, "fake:v1", ("eng",), ocr.DEFAULT_PREPROCESSING_VERSION)
    (cache_root / f"{key}.json").write_text(
        '{"status":"success","text":"stale","confidence":0.99,'
        '"engine_id":"other","model_version":"v1","languages":["eng"],'
        '"image_sha256":"' + source.sha256 + '","preprocessing_version":"' + ocr.DEFAULT_PREPROCESSING_VERSION + '"}',
        encoding="utf-8",
    )
    backend = FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.SUCCESS, text="fresh", confidence=0.9))

    result = ocr.extract_cached(source, cache_root, backend, ("eng",))

    assert result.text == "fresh"
    assert backend.calls == 1


def test_cache_rejects_invalid_embedded_status_and_symlinked_file(tmp_path):
    source = asset(tmp_path, sha256="7" * 64)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    key = ocr.cache_key(source.sha256, "fake:v1", ("eng",), ocr.DEFAULT_PREPROCESSING_VERSION)
    cache_file = cache_root / f"{key}.json"
    cache_file.write_text('{"status":"not-real"}', encoding="utf-8")
    backend = FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.NO_TEXT))

    assert ocr.extract_cached(source, cache_root, backend, ("eng",)).status is ocr.OCRStatus.NO_TEXT
    cache_file.unlink()
    cache_file.symlink_to(tmp_path / "missing-cache.json")

    with pytest.raises(ocr.OCRCacheError, match="cache path is invalid"):
        ocr.extract_cached(source, cache_root, backend, ("eng",))


def test_cache_malformed_metadata_values_are_misses(tmp_path):
    source = asset(tmp_path, sha256="9" * 64)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    key = ocr.cache_key(source.sha256, "fake:v1", ("eng",), ocr.DEFAULT_PREPROCESSING_VERSION)
    (cache_root / f"{key}.json").write_text(
        '{"status":"success","text":"tampered","confidence":"high",'
        '"engine_id":"fake","model_version":"v1","languages":["eng"],'
        '"image_sha256":"' + source.sha256 + '","preprocessing_version":"' + ocr.DEFAULT_PREPROCESSING_VERSION + '"}',
        encoding="utf-8",
    )
    backend = FakeBackend(ocr.OCRResult(status=ocr.OCRStatus.SUCCESS, text="fresh", confidence=0.9))

    assert ocr.extract_cached(source, cache_root, backend, ("eng",)).text == "fresh"
    assert backend.calls == 1


def test_paddle_runtime_mapping_binds_languages_to_constructor_config(tmp_path):
    calls = []

    def runner(config, path, timeout_seconds):
        calls.append((config, path, timeout_seconds))
        return [[(None, ("Laba bersih naik", 0.92))]]

    backend = ocr.PaddleOCRBackend(model_version="PP-OCRv5", runner=runner, timeout_seconds=3)
    result = backend.extract(asset(tmp_path).path, ("ind", "eng"))

    assert result.status is ocr.OCRStatus.SUCCESS
    assert result.text == "Laba bersih naik"
    assert calls[0][0].constructor_kwargs == {"lang": "latin", "ocr_version": "PP-OCRv5"}
    assert calls[0][0].model_version == "PP-OCRv5-latin"
    assert calls[0][2] == 3


@pytest.mark.parametrize(
    ("languages", "kwargs", "model_version"),
    [
        (("ind",), {"lang": "latin", "ocr_version": "PP-OCRv5"}, "PP-OCRv5-latin"),
        (("eng",), {"lang": "en", "ocr_version": "PP-OCRv5"}, "PP-OCRv5-en"),
        (("ind", "eng"), {"lang": "latin", "ocr_version": "PP-OCRv5"}, "PP-OCRv5-latin"),
    ],
)
def test_paddle_runtime_config_is_explicit_for_supported_languages(languages, kwargs, model_version):
    backend = ocr.PaddleOCRBackend(model_version="PP-OCRv5", runner=lambda config, path, timeout: ())
    config = backend.runtime_config(languages)

    assert config.constructor_kwargs == kwargs
    assert config.model_version == model_version


def test_paddle_rejects_unknown_language():
    backend = ocr.PaddleOCRBackend(model_version="PP-OCRv5", runner=lambda config, path, timeout: ())

    with pytest.raises(ValueError, match="unsupported OCR language"):
        backend.runtime_config(("fra",))


def test_paddle_constructor_failure_and_timeout_are_sanitized(tmp_path):
    source = asset(tmp_path, sha256="8" * 64)

    unavailable = ocr.PaddleOCRBackend(
        model_version="PP-OCRv5",
        runner=lambda config, path, timeout: (_ for _ in ()).throw(ocr.OCRBackendUnavailable("missing package path")),
    )
    timeout = ocr.PaddleOCRBackend(
        model_version="PP-OCRv5",
        runner=lambda config, path, timeout: (_ for _ in ()).throw(TimeoutError("raw model timeout")),
    )

    assert ocr.extract_cached(source, tmp_path / "cache-a", unavailable, ("eng",)).error == "ocr backend unavailable"
    timed_out = ocr.extract_cached(source, tmp_path / "cache-b", timeout, ("eng",))
    assert timed_out.status is ocr.OCRStatus.TIMEOUT
    assert timed_out.error == "ocr backend timed out"


def test_paddle_accumulation_stops_at_per_asset_limit(tmp_path):
    iterated = 0

    def lines():
        nonlocal iterated
        for _ in range(200):
            iterated += 1
            yield (None, ("x" * 200, 0.9))

    backend = ocr.PaddleOCRBackend(model_version="PP-OCRv5", runner=lambda config, path, timeout: (lines(),))
    parsed = backend.extract(asset(tmp_path).path, ("eng",))

    assert len(parsed.text) == ocr.MAX_TEXT_PER_ASSET
    assert iterated < 200


def test_tesseract_parsing_caps_without_processing_all_words():
    parsed = ocr.parse_tesseract_tsv("level\tconf\ttext\n" + "\n".join(f"5\t99\t{'x' * 200}" for _ in range(200)))

    assert parsed.status is ocr.OCRStatus.SUCCESS
    assert len(parsed.text) == ocr.MAX_TEXT_PER_ASSET
