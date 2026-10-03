"""Source-neutral writing guidance, without classification or validation gates."""
from typing import Literal

PresentationCategory = Literal["issuer", "macro", "industry", "swing"]

COMMON_WRITING_INSTRUCTION = (
    "Report directly in factual Bahasa Indonesia, starting with the actual subject or action. "
    "Avoid generic writer narration and saya/kami. Preserve meaningful attribution for research, estimates, "
    "forecasts, guidance and interpretation, including periods, units, assumptions and uncertainty. "
    "Prefer two short paragraphs separated by \\n\\n for longer summaries; a short or cohesive item can use one. "
    "Use judgment without a fixed length threshold, padding or invented facts. "
    "A writing-style deviation must never make an otherwise eligible item undeliverable. "
)

_CATEGORY_INSTRUCTIONS: dict[PresentationCategory, str] = {
    "issuer": "Preserve the supplied issuer, action, source date and material facts. ",
    "macro": (
        "For macro news, preserve each retained figure's period, unit, comparison basis and attribution. "
        "Distinguish actual, forecast, consensus, prior-period figures and revisions. YoY differs from MoM; "
        "percent differs from percentage points. Retain provisional qualifiers and explicit revision explanations. "
        "Missing periods, units or context stay missing; never guess. Different actual and forecast figures are "
        "not a conflict. Briefly disclose a central unexplained source discrepancy; omit a peripheral disputed "
        "claim while delivering supported news. Dense releases may retain only material indicators, with their "
        "context. Do not require a table or a fixed paragraph count. "
    ),
    "industry": "",
    "swing": "",
}


def category_instruction(category: PresentationCategory) -> str:
    """Return category obligations; compose common writing rules once at the caller."""
    try:
        return _CATEGORY_INSTRUCTIONS[category]
    except (KeyError, TypeError):
        raise ValueError("unsupported presentation category") from None
