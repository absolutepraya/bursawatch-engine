from datetime import datetime, timezone

import pytest

from domain import (
    CompanyCandidate,
    EventClass,
    Provider,
    SourceKind,
    Tier,
    candidate_key,
    retry_delay_minutes,
    source_message_url,
    tier_for_event_class,
)


def test_tier_policy_is_closed_and_strict():
    assert tier_for_event_class(EventClass.CORPORATE_ACTION) is Tier.ONE
    assert tier_for_event_class(EventClass.MATERIAL_CONTRACT) is Tier.ONE
    assert tier_for_event_class(EventClass.QUANTIFIED_OPERATIONAL_EXECUTION) is Tier.TWO
    assert tier_for_event_class(EventClass.ROUTINE_STATUS) is Tier.TWO
    assert tier_for_event_class(EventClass.NOT_ELIGIBLE) is None


def test_candidate_identity_is_provider_message_and_ticker():
    candidate = CompanyCandidate(
        provider=Provider.TUNTUN,
        source_message_id=13597,
        ticker="DEWA",
        source_kind=SourceKind.CORPORATE_ENTRY,
        published_at=datetime(2026, 7, 1, 6, 18, 54, tzinfo=timezone.utc),
        source_text="DEWA (Darma Henwa): kontrak Rp22 triliun.",
        direct_image=False,
    )
    assert candidate_key(candidate) == "tuntun:13597:DEWA"
    assert candidate.key == "tuntun:13597:DEWA"
    assert source_message_url(candidate) == "https://t.me/tuntunsekuritas/13597"


@pytest.mark.parametrize("attempt,minutes", [(0, 1), (1, 2), (2, 4), (3, 8), (4, 15), (5, 30), (6, 60), (99, 60)])
def test_retry_backoff_is_bounded(attempt, minutes):
    assert retry_delay_minutes(attempt) == minutes


@pytest.mark.parametrize(
    ("event_class", "tier"),
    [
        (EventClass.FINANCIAL_RESULTS_OR_GUIDANCE, Tier.ONE),
        (EventClass.FINANCING_OR_OWNERSHIP, Tier.ONE),
        (EventClass.MNA_OR_ASSET_TRANSACTION, Tier.ONE),
        (EventClass.LISTING_LEGAL_REGULATORY_OR_CREDIT, Tier.ONE),
        (EventClass.OTHER_COMPANY_OPERATION, Tier.TWO),
    ],
)
def test_tier_policy_covers_every_eligible_class(event_class, tier):
    assert tier_for_event_class(event_class) is tier


@pytest.mark.parametrize("ticker", ["D", "TOOLONG", "dewa", "DE-WA"])
def test_candidate_rejects_non_exchange_ticker(ticker):
    with pytest.raises(ValueError, match=r"ticker must match \[A-Z\]\{2,5\}"):
        CompanyCandidate(
            provider=Provider.TUNTUN,
            source_message_id=13597,
            ticker=ticker,
            source_kind=SourceKind.CORPORATE_ENTRY,
            published_at=datetime(2026, 7, 1, 6, 18, 54, tzinfo=timezone.utc),
            source_text="DEWA (Darma Henwa): kontrak Rp22 triliun.",
            direct_image=False,
        )


def test_candidate_rejects_naive_publication_timestamp():
    with pytest.raises(ValueError, match="published_at must be timezone-aware"):
        CompanyCandidate(
            provider=Provider.PHINTRACO,
            source_message_id=13597,
            ticker="DEWA",
            source_kind=SourceKind.PHINTRACO_NOTE,
            published_at=datetime(2026, 7, 1, 6, 18, 54),
            source_text="DEWA secures a Rp22 trillion contract.",
            direct_image=False,
        )
