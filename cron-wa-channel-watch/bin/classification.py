from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SourceStatus:
    label: str
    kind: str


_LEADING_MARKUP = frozenset("*_~`")
_TECHNICAL_REVIEW_RE = re.compile(r"^#TechnicalReview(?=[\s*_~`]|$)")
_STATUS_PATTERNS = (
    ("up", "bullish", re.compile(r"\bbullish\b", re.IGNORECASE)),
    ("down", "bearish", re.compile(r"\bbearish\b", re.IGNORECASE)),
    ("up", "overweight", re.compile(r"\boverweight\b", re.IGNORECASE)),
    ("down", "underweight", re.compile(r"\bunderweight\b", re.IGNORECASE)),
    ("up", "outperform", re.compile(r"\boutperform(?:s|ed|ing)?\b", re.IGNORECASE)),
    ("down", "underperform", re.compile(r"\bunderperform(?:s|ed|ing)?\b", re.IGNORECASE)),
    ("hold", "on track", re.compile(r"\bon\s+track\b", re.IGNORECASE)),
    ("hold", "hold", re.compile(r"\bhold\b", re.IGNORECASE)),
    ("hold", "neutral", re.compile(r"\bneutral\b", re.IGNORECASE)),
    ("up", "buy", re.compile(r"\bbuy\b", re.IGNORECASE)),
    ("down", "sell", re.compile(r"\bsell\b", re.IGNORECASE)),
)


def _without_leading_markup(value: str) -> str:
    value = value.lstrip("\ufeff \t\r\n")
    while value and value[0] in _LEADING_MARKUP:
        value = value[1:].lstrip(" \t\r\n")
    return value


def is_technical_review(text: str) -> bool:
    """Return true only for an exact, leading TechnicalReview tag."""
    return bool(_TECHNICAL_REVIEW_RE.match(_without_leading_markup(text)))


def _display_label(canonical: str) -> str:
    return canonical.capitalize()


def extract_source_status(text: str) -> SourceStatus | None:
    """Extract the first explicit source stance without inferring sentiment."""
    matches: list[tuple[int, int, str, str]] = []
    for order, (kind, canonical, pattern) in enumerate(_STATUS_PATTERNS):
        match = pattern.search(text)
        if match:
            matches.append((match.start(), order, kind, canonical))
    if not matches:
        return None
    _, _, kind, canonical = min(matches)
    return SourceStatus(label=_display_label(canonical), kind=kind)
