"""Canonical lifecycle and market tag vocabulary for the Swing board."""

from __future__ import annotations

from collections.abc import Iterable


PRIMARY_PLAN = "Primary plan"
SUPPORTING_SETUP = "Supporting setup"
CHART_CONTEXT = "Chart context"
RESOLVED = "Resolved"
LEGACY_SOURCE_PLAN = "Source plan"

BELOW_ENTRY = "Below entry"
ENTRY_ZONE = "Entry zone"
ABOVE_ENTRY = "Above entry"
STOP_LOSS_BREACHED = "Stop-loss breached"

_GTW_SOURCES = frozenset({"kelas-investasi", "kelas_investasi", "gtw"})
_SOURCE_TIER_RANK = {
    CHART_CONTEXT: 1,
    SUPPORTING_SETUP: 2,
}


def source_tier(source: str) -> str:
    """Return the visible source tier for a non-primary board event."""
    normalized = source.strip().casefold()
    return SUPPORTING_SETUP if normalized in _GTW_SOURCES else CHART_CONTEXT


def merge_source_tier(current: str | None, incoming: str) -> str:
    """Keep the strongest source-only tier present in one ticker episode."""
    if incoming not in _SOURCE_TIER_RANK:
        raise ValueError(f"unsupported source tier: {incoming}")
    if current in {PRIMARY_PLAN, RESOLVED}:
        return current
    if current == LEGACY_SOURCE_PLAN:
        return incoming
    if current not in _SOURCE_TIER_RANK:
        return incoming
    return max((current, incoming), key=_SOURCE_TIER_RANK.__getitem__)


def source_tier_for_sources(sources: Iterable[str]) -> str:
    """Return the strongest source-only tier for an episode's source set."""
    tiers = [source_tier(source) for source in sources]
    if not tiers:
        raise ValueError("source-only episode has no source events")
    return max(tiers, key=_SOURCE_TIER_RANK.__getitem__)


def desired_lifecycle_tag(lifecycle: str, current: str | None, sources: Iterable[str] = ()) -> str:
    """Compute the canonical visible lifecycle tag without guessing."""
    if lifecycle == "primary":
        return PRIMARY_PLAN
    if lifecycle == "resolved":
        return RESOLVED
    if lifecycle != "source":
        raise ValueError(f"unsupported episode lifecycle: {lifecycle}")
    if current in {SUPPORTING_SETUP, CHART_CONTEXT}:
        return current
    return source_tier_for_sources(sources)

