from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from models import DownloadedAsset, FailedAsset, MediaKind, Profile
from ocr import OCRResult, OCRStatus, normalize_text


MIN_AGGREGATE_CONTEXT_CHARS = 80
NOISE_WORD_RATIO_MIN = 0.45
VISUAL_REFERENCE_RE = re.compile(
    r"\b(charts?|tables?|diagrams?|annotations?|annotated|visual\s+comparisons?|see\s+slides?|slides?\s+\d+|diagrammatic)\b",
    re.IGNORECASE,
)

REASON_TEXT_SUFFICIENT = "text_sufficient"
REASON_PARTIAL_UNCERTAIN = "partial_uncertain_assets"
REASON_MULTIPLE_UNCERTAIN = "multiple_uncertain_assets"
REASON_SPARSE_CONTEXT = "sparse_context"
REASON_VISUAL_REFERENCE = "visual_reference"
REASON_ASSET_RESULT_MISMATCH = "asset_result_mismatch"
KNOWN_FAILED_REASONS = {
    "asset_size_limit",
    "decode_failed",
    "download_failed",
    "frame_sampling_failed",
    "publication_size_limit",
    "redirect_not_supported",
    "unsupported_content_type",
    "unsupported_media_url",
}


class VisionMode(StrEnum):
    TEXT_ONLY = "text_only"
    VISION_PARTIAL = "vision_partial"
    VISION_FULL = "vision_full"


@dataclass(frozen=True)
class VisionDecision:
    mode: VisionMode
    reason: str
    asset_ids: tuple[int, ...]
    asset_paths: tuple[Path, ...]
    analysis_ids: tuple[str, ...] = ()


def _context_length(caption_text: str, results: tuple[OCRResult, ...]) -> int:
    context = " ".join([caption_text, *(result.text for result in results)])
    return len(normalize_text(context))


def _mostly_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    tokens = normalized.split()
    if not tokens:
        return False
    wordish = sum(1 for token in tokens if re.search(r"[A-Za-z0-9]{2,}", token))
    return wordish / len(tokens) < NOISE_WORD_RATIO_MIN


def _uncertain(result: OCRResult, profile: Profile) -> bool:
    if result.status in {OCRStatus.ERROR, OCRStatus.TIMEOUT, OCRStatus.UNAVAILABLE, OCRStatus.UNCERTAIN}:
        return True
    if result.status is OCRStatus.SUCCESS:
        if result.confidence is None and result.text:
            return True
        if result.min_confidence is not None and result.min_confidence < profile.ocr_min_confidence:
            return True
        if result.confidence is not None and result.confidence < profile.ocr_min_confidence:
            return True
        if _mostly_noise(result.text):
            return True
    return False


def analysis_id(asset: DownloadedAsset | FailedAsset) -> str:
    if isinstance(asset, FailedAsset):
        reason = asset.reason if asset.reason in KNOWN_FAILED_REASONS else f"failure_{hashlib.sha256(asset.reason.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
        return f"failed:{asset.source.kind.value}:{asset.source.index}:{reason}"
    return f"{asset.source.kind.value}:{asset.source.index}:{asset.sha256[:12]}"


def _vision_assets(assets: tuple[DownloadedAsset | FailedAsset, ...]) -> tuple[DownloadedAsset | FailedAsset, ...]:
    return tuple(asset for asset in assets if asset.source.kind is MediaKind.IMAGE)


def _decision(mode: VisionMode, reason: str, assets: tuple[DownloadedAsset | FailedAsset, ...]) -> VisionDecision:
    downloaded = tuple(asset for asset in assets if isinstance(asset, DownloadedAsset))
    return VisionDecision(
        mode,
        reason,
        tuple(asset.source.index for asset in assets),
        tuple(asset.path for asset in downloaded),
        tuple(analysis_id(asset) for asset in assets),
    )


def decide_vision_mode(
    caption_text: str,
    assets: tuple[DownloadedAsset, ...],
    results: tuple[OCRResult, ...],
    profile: Profile,
    *,
    failed_assets: tuple[FailedAsset, ...] = (),
) -> VisionDecision:
    if len(assets) != len(results):
        return _decision(VisionMode.VISION_FULL, REASON_ASSET_RESULT_MISMATCH, _vision_assets((*assets, *failed_assets)))
    vision_assets = _vision_assets((*assets, *failed_assets))
    if VISUAL_REFERENCE_RE.search(caption_text):
        return _decision(VisionMode.VISION_FULL, REASON_VISUAL_REFERENCE, vision_assets)

    uncertain_assets = tuple(asset for asset, result in zip(assets, results, strict=True) if asset.source.kind is MediaKind.IMAGE and _uncertain(result, profile))
    all_uncertain_assets = (*uncertain_assets, *failed_assets)
    if len(all_uncertain_assets) >= 2:
        return _decision(VisionMode.VISION_FULL, REASON_MULTIPLE_UNCERTAIN, vision_assets)
    if len(all_uncertain_assets) == 1:
        return _decision(VisionMode.VISION_PARTIAL, REASON_PARTIAL_UNCERTAIN, all_uncertain_assets)

    if _context_length(caption_text, results) < MIN_AGGREGATE_CONTEXT_CHARS:
        return _decision(VisionMode.VISION_FULL, REASON_SPARSE_CONTEXT, vision_assets)

    return _decision(VisionMode.TEXT_ONLY, REASON_TEXT_SUFFICIENT, ())
