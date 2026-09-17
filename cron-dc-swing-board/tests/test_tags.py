import pytest

from tags import (
    CHART_CONTEXT,
    LEGACY_SOURCE_PLAN,
    PRIMARY_PLAN,
    RESOLVED,
    SUPPORTING_SETUP,
    desired_lifecycle_tag,
    merge_source_tier,
    source_tier,
    source_tier_for_sources,
)


def test_source_tiers_distinguish_gtw_from_social_context():
    assert source_tier("kelas-investasi") == SUPPORTING_SETUP
    assert source_tier("x") == CHART_CONTEXT
    assert source_tier_for_sources({"x", "kelas-investasi"}) == SUPPORTING_SETUP


def test_source_tier_merge_keeps_strongest_context():
    assert merge_source_tier(CHART_CONTEXT, SUPPORTING_SETUP) == SUPPORTING_SETUP
    assert merge_source_tier(SUPPORTING_SETUP, CHART_CONTEXT) == SUPPORTING_SETUP
    assert merge_source_tier(LEGACY_SOURCE_PLAN, CHART_CONTEXT) == CHART_CONTEXT


@pytest.mark.parametrize(
    ("lifecycle", "current", "sources", "expected"),
    [
        ("primary", None, (), PRIMARY_PLAN),
        ("resolved", PRIMARY_PLAN, (), RESOLVED),
        ("source", None, ("kelas-investasi",), SUPPORTING_SETUP),
        ("source", LEGACY_SOURCE_PLAN, ("x",), CHART_CONTEXT),
        ("source", SUPPORTING_SETUP, ("x",), SUPPORTING_SETUP),
    ],
)
def test_desired_lifecycle_tag(lifecycle, current, sources, expected):
    assert desired_lifecycle_tag(lifecycle, current, sources) == expected


def test_source_episode_without_sources_fails_closed():
    with pytest.raises(ValueError, match="no source events"):
        desired_lifecycle_tag("source", None, ())

