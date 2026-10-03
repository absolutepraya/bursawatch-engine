"""Typed client for the local Bursawatch Source Media Owner."""

from .client import SourceMediaClient, SourceMediaClientError
from .models import MediaDownload

__all__ = ["MediaDownload", "SourceMediaClient", "SourceMediaClientError"]

from .summary_images import (SummaryImageRef, PreparedSummaryImage, SummaryImageBundle, SummaryImageLimits, prepare_summary_images, cleanup_summary_images)
__all__ += ["SummaryImageRef", "PreparedSummaryImage", "SummaryImageBundle", "SummaryImageLimits", "prepare_summary_images", "cleanup_summary_images"]

from .summary_context import SummaryContextClaim, claim_id, context_instruction, image_refs, prepare_claim_context
__all__ += ["SummaryContextClaim", "claim_id", "context_instruction", "image_refs", "prepare_claim_context"]
