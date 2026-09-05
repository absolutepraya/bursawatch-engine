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
