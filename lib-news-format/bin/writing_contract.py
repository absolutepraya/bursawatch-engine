"""Source-neutral writing guidance, without classification or validation gates."""
from typing import Literal

PresentationCategory = Literal["issuer", "macro", "industry", "swing"]

COMMON_WRITING_INSTRUCTION = (
    "Use descriptive sentence-case headlines, capitalizing the first subject word after any ticker prefix. "
    "Preserve exact ticker, acronym, official-name and proper-name casing. "
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
    "industry": (
        "For industry news, use only supplied publication evidence, eligible-post image context and explicitly "
        "provided source context. Separate reported developments from company implications with attribution "
        "and qualified wording. A qualitative company implication is allowed only when supplied evidence "
        "establishes specific exposure and a direct connecting mechanism, even without a quantified effect. "
        "Preserve source forecasts and their assumptions. Do not invent impact size, turn a policy target "
        "into a contract award, or predict a share-price move. Omit unsupported implications and still deliver "
        "eligible industry news. Company impact is optional; no mandatory field or block, external research, "
        "or automatic related-company discovery. "
    ),
    "swing": (
        "For Swing source presentation, use Entry, Stop-loss and numbered Target n. "
        "Entry, Stop-loss and Target 1 are base fields with - for unavailable levels; "
        "show additional targets/stops only when explicitly supplied, retaining their numbers. "
        "Interpret Watch on and Buy area as Entry. Support utama is the approved Stop-loss synonym: "
        "bare Support utama 260 means <260; preserve an explicit comparator exactly. "
        "Generic support is not a stop. Unnumbered Target is Target 1; TP2 remains Target 2 even without TP1. "
        "Preserve exact source ranges, comparators, dates, status, conditions and raw wording/evidence. "
        "Never calculate a midpoint or invent levels. Supply unchanged-source character spans for selected "
        "whole level phrases, including the source label. Missing or invalid optional fields must not block "
        "delivery. Presentation does not decide Board tiers, promotion, price comparisons or lifecycle. "
    ),
}


def category_instruction(category: PresentationCategory) -> str:
    """Return category obligations; compose common writing rules once at the caller."""
    try:
        return _CATEGORY_INSTRUCTIONS[category]
    except (KeyError, TypeError):
        raise ValueError("unsupported presentation category") from None
