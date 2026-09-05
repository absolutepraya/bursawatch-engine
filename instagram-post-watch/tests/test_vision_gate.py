from __future__ import annotations

from pathlib import Path

import pytest

import ocr
import vision_gate
from config import load_watch_config
from models import DownloadedAsset, MediaKind, SourceMedia


@pytest.fixture
def profile(config_path):
    return load_watch_config(config_path).profiles[0]


def asset(tmp_path: Path, index: int, *, kind: MediaKind = MediaKind.IMAGE, name: str | None = None) -> DownloadedAsset:
    suffix = ".mp4" if kind is MediaKind.VIDEO else ".jpg"
    path = tmp_path / (name or f"{index}{suffix}")
    path.write_bytes(b"asset")
    return DownloadedAsset(
        SourceMedia(f"https://cdn.example/{path.name}", kind, index),
        path,
        f"{index:064x}"[-64:],
        5,
        "video/mp4" if kind is MediaKind.VIDEO else "image/jpeg",
    )


def result(text: str = "market earnings growth", confidence: float | None = 0.9, status: ocr.OCRStatus = ocr.OCRStatus.SUCCESS) -> ocr.OCRResult:
    return ocr.OCRResult(status=status, text=text, confidence=confidence)


def test_complete_high_confidence_ocr_with_sufficient_context_is_text_only(tmp_path, profile):
    assets = (asset(tmp_path, 0), asset(tmp_path, 1))
    results = (
        result("Bank lending expanded with stronger NIM and solid deposit growth."),
        result("Management guided stable margins and lower credit costs."),
    )

    decision = vision_gate.decide_vision_mode(
        "Quarterly result discussion with enough written context for analysis.",
        assets,
        results,
        profile,
    )

    assert decision.mode is vision_gate.VisionMode.TEXT_ONLY
    assert decision.reason == vision_gate.REASON_TEXT_SUFFICIENT
    assert decision.asset_ids == ()
    assert decision.asset_paths == ()


def test_one_ocr_timeout_returns_partial_with_only_that_asset(tmp_path, profile):
    assets = (asset(tmp_path, 0), asset(tmp_path, 1))
    results = (
        result("Bank lending expanded with stronger NIM and solid deposit growth."),
        result("", None, ocr.OCRStatus.TIMEOUT),
    )

    decision = vision_gate.decide_vision_mode("Quarterly result discussion.", assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_PARTIAL
    assert decision.reason == vision_gate.REASON_PARTIAL_UNCERTAIN
    assert decision.asset_ids == (1,)
    assert decision.asset_paths == (assets[1].path,)


def test_one_low_confidence_text_asset_returns_partial(tmp_path, profile):
    assets = (asset(tmp_path, 0), asset(tmp_path, 1))
    results = (
        result("High confidence extracted slide content for market review.", 0.95),
        result("low confidence extracted text", 0.42),
    )

    decision = vision_gate.decide_vision_mode("Quarterly result discussion.", assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_PARTIAL
    assert decision.asset_ids == (1,)
    assert decision.asset_paths == (assets[1].path,)


def test_two_uncertain_assets_return_full_with_all_publication_images(tmp_path, profile):
    assets = (asset(tmp_path, 0), asset(tmp_path, 1), asset(tmp_path, 2))
    results = (
        result("clear slide with useful market context", 0.94),
        result("uncertain", 0.41),
        result("", None, ocr.OCRStatus.ERROR),
    )

    decision = vision_gate.decide_vision_mode("Quarterly result discussion.", assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_FULL
    assert decision.reason == vision_gate.REASON_MULTIPLE_UNCERTAIN
    assert decision.asset_ids == (0, 1, 2)
    assert decision.asset_paths == tuple(asset.path for asset in assets)


def test_sparse_caption_plus_blank_ocr_returns_full(tmp_path, profile):
    assets = (asset(tmp_path, 0),)
    results = (result("", None, ocr.OCRStatus.NO_TEXT),)

    decision = vision_gate.decide_vision_mode("FYI", assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_FULL
    assert decision.reason == vision_gate.REASON_SPARSE_CONTEXT
    assert decision.asset_ids == (0,)


@pytest.mark.parametrize("caption", ["see chart below", "table says it all", "diagram update", "see slide 3"])
def test_visual_reference_caption_returns_full(tmp_path, profile, caption):
    assets = (asset(tmp_path, 0), asset(tmp_path, 1))
    results = (
        result("High confidence extracted written context from the first slide.", 0.95),
        result("High confidence extracted written context from the second slide.", 0.95),
    )

    decision = vision_gate.decide_vision_mode(caption, assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_FULL
    assert decision.reason == vision_gate.REASON_VISUAL_REFERENCE
    assert decision.asset_ids == (0, 1)


def test_blank_ocr_with_descriptive_caption_remains_text_only(tmp_path, profile):
    assets = (asset(tmp_path, 0),)
    descriptive = (
        "Bank Indonesia kept rates unchanged while explaining that currency stability, "
        "inflation expectations, and export demand remain the main drivers for the next quarter."
    )

    decision = vision_gate.decide_vision_mode(descriptive, assets, (result("", None, ocr.OCRStatus.NO_TEXT),), profile)

    assert decision.mode is vision_gate.VisionMode.TEXT_ONLY
    assert decision.reason == vision_gate.REASON_TEXT_SUFFICIENT
    assert decision.asset_ids == ()


def test_reel_full_uses_sampled_frame_paths_never_original_video(tmp_path, profile):
    original_video = asset(tmp_path, 0, kind=MediaKind.VIDEO, name="reel.mp4")
    cover = asset(tmp_path, 0, name="cover.jpg")
    frame = asset(tmp_path, 1, name="frame-1.jpg")
    assets = (original_video, cover, frame)
    results = (
        result("", None, ocr.OCRStatus.NO_TEXT),
        result("", None, ocr.OCRStatus.NO_TEXT),
        result("", None, ocr.OCRStatus.NO_TEXT),
    )

    decision = vision_gate.decide_vision_mode("see slide for details", assets, results, profile)

    assert decision.mode is vision_gate.VisionMode.VISION_FULL
    assert decision.asset_ids == (0, 1)
    assert decision.asset_paths == (cover.path, frame.path)
    assert original_video.path not in decision.asset_paths
