import json
import os

from datetime import datetime, timedelta

import pytest

from agent_protocol import submit_classification
from domain import CompanyCandidate, EventClass, Provider, SourceKind, Tier
from selection import (
    SelectionCandidate,
    assign_tier,
    digest_window,
    is_confident_duplicate,
    rank_tier_two,
    select_digest_candidates,
    pending_selection_candidates,
)
from state import claim_oldest_pending_analysis, empty_state, enqueue_candidate, load_state


def _candidate(provider, message_id, ticker, published_at):
    return CompanyCandidate(
        provider=provider,
        source_message_id=message_id,
        ticker=ticker,
        source_kind=SourceKind.CORPORATE_ENTRY,
        published_at=published_at,
        source_text=f"{ticker} source update.",
        direct_image=False,
    )


def _selection_candidate(
    provider,
    message_id,
    ticker,
    published_at,
    *,
    event_class=EventClass.QUANTIFIED_OPERATIONAL_EXECUTION,
    ranking_band=1,
    material_facts=("reported volume",),
    dedupe_facts=("production volume", "reporting period"),
    source_text=None,
):
    return SelectionCandidate(
        candidate=CompanyCandidate(
            provider=provider,
            source_message_id=message_id,
            ticker=ticker,
            source_kind=SourceKind.CORPORATE_ENTRY,
            published_at=published_at,
            source_text=source_text or f"{ticker} source update.",
            direct_image=False,
        ),
        event_class=event_class,
        ranking_band=ranking_band,
        material_facts=material_facts,
        dedupe_facts=dedupe_facts,
    )


@pytest.fixture
def dewa_tuntun():
    return _selection_candidate(
        Provider.TUNTUN,
        100,
        "DEWA",
        datetime.fromisoformat("2026-07-14T08:00:00+07:00"),
    )


@pytest.fixture
def dewa_phintraco():
    return _selection_candidate(
        Provider.PHINTRACO,
        200,
        "DEWA",
        datetime.fromisoformat("2026-07-14T09:00:00+07:00"),
        dedupe_facts=("production volume", "reporting period", "mine location"),
    )


@pytest.fixture
def dewa_different_fact():
    return _selection_candidate(
        Provider.PHINTRACO,
        201,
        "DEWA",
        datetime.fromisoformat("2026-07-14T09:00:00+07:00"),
        dedupe_facts=("new customer", "contract duration"),
    )


@pytest.fixture
def tier_two_candidates():
    published_at = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    return [
        _selection_candidate(Provider.TUNTUN, index, ticker, published_at + timedelta(minutes=index))
        for index, ticker in enumerate(("AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF", "GGGG", "HHHH", "IIII", "JJJJ", "KKKK"), start=1)
    ]


@pytest.fixture
def state(tmp_path, monkeypatch, tier_two_candidates):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    current_state = empty_state()
    now = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    for item in tier_two_candidates:
        enqueue_candidate(current_state, item.candidate, now)
        record = current_state["candidates"][item.key]
        record["phase"] = "pending_selection"
        record["classification"] = item.event_class.value
        record["selection"] = {
            "ranking_band": item.ranking_band,
            "material_facts": list(item.material_facts),
            "dedupe_facts": list(item.dedupe_facts),
        }
    return current_state


def test_confident_cross_provider_duplicate_requires_same_issuer_class_and_facts(
    dewa_tuntun, dewa_phintraco, dewa_different_fact
):
    assert is_confident_duplicate(dewa_tuntun, dewa_phintraco)
    assert not is_confident_duplicate(dewa_tuntun, dewa_different_fact)


def test_digest_selects_top_ten_and_terminally_suppresses_overflow(tier_two_candidates, state):
    selected, overflow = select_digest_candidates(state, tier_two_candidates)

    assert [item.ticker for item in selected] == ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF", "GGGG", "HHHH", "IIII", "JJJJ"]
    assert [item.ticker for item in overflow] == ["KKKK"]
    assert state["candidates"][overflow[0].key]["phase"] == "suppressed_rank"
    assert all(state["candidates"][item.key]["phase"] == "pending_delivery" for item in selected)


def test_monday_premarket_window_includes_friday_after_close_and_weekend():
    now = datetime.fromisoformat("2026-07-20T08:30:00+07:00")
    window = digest_window(now)

    assert window is not None
    assert window.kind == "pre_market"
    assert window.start.isoformat() == "2026-07-17T16:30:00+07:00"


def test_duplicate_matches_same_provider_with_shared_facts_and_seven_day_window(
    dewa_tuntun, dewa_phintraco
):
    same_provider = _selection_candidate(
        Provider.TUNTUN,
        101,
        "DEWA",
        dewa_tuntun.published_at + timedelta(hours=1),
    )
    different_class = _selection_candidate(
        Provider.PHINTRACO,
        202,
        "DEWA",
        dewa_tuntun.published_at + timedelta(hours=1),
        event_class=EventClass.ROUTINE_STATUS,
    )
    too_late = _selection_candidate(
        Provider.PHINTRACO,
        203,
        "DEWA",
        dewa_tuntun.published_at + timedelta(hours=24, seconds=1),
    )

    assert is_confident_duplicate(dewa_tuntun, same_provider)
    assert not is_confident_duplicate(dewa_tuntun, different_class)
    assert not is_confident_duplicate(dewa_tuntun, too_late)


def test_same_provider_duplicate_can_use_strong_source_overlap_without_shared_facts():
    published_at = datetime.fromisoformat("2026-08-14T08:00:00+07:00")
    original = _selection_candidate(
        Provider.TUNTUN,
        14395,
        "INDY",
        published_at,
        event_class=EventClass.CORPORATE_ACTION,
        dedupe_facts=("INDY mendirikan dua anak usaha baru",),
        source_text=(
            "INDY mendirikan dua anak usaha baru di bidang logistik dan kepelabuhanan. "
            "Langkah ini memperkuat integrasi rantai pasok dan membuka sumber pendapatan baru."
        ),
    )
    repost = _selection_candidate(
        Provider.TUNTUN,
        14396,
        "INDY",
        published_at + timedelta(minutes=7),
        event_class=EventClass.CORPORATE_ACTION,
        dedupe_facts=("INDY membentuk TRADE dan TRADA",),
        source_text=(
            "INDY membentuk dua anak usaha baru, TRADE dan TRADA, di bidang logistik dan "
            "pelayanan kepelabuhanan untuk memperkuat diversifikasi bisnis."
        ),
    )

    assert is_confident_duplicate(original, repost)


def test_same_provider_different_event_is_not_duplicate():
    published_at = datetime.fromisoformat("2026-08-14T08:00:00+07:00")
    first = _selection_candidate(
        Provider.TUNTUN,
        14403,
        "GGRM",
        published_at,
        event_class=EventClass.FINANCIAL_RESULTS_OR_GUIDANCE,
        source_text="GGRM laba bersih meningkat menjadi Rp2,97 triliun pada semester pertama.",
    )
    second = _selection_candidate(
        Provider.TUNTUN,
        14406,
        "GGRM",
        published_at + timedelta(days=3),
        event_class=EventClass.FINANCING_OR_OWNERSHIP,
        source_text="GGRM menambah modal Rp200 miliar kepada SDHI untuk operasional Bandara Dhoho.",
    )

    assert not is_confident_duplicate(first, second)


def test_tier_one_bypasses_digest_and_ineligible_is_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    current_state = empty_state()
    now = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    tier_one = _selection_candidate(
        Provider.TUNTUN,
        300,
        "TOPS",
        now,
        event_class=EventClass.CORPORATE_ACTION,
    )
    ineligible = _selection_candidate(
        Provider.PHINTRACO,
        301,
        "NONE",
        now,
        event_class=EventClass.NOT_ELIGIBLE,
    )
    for item in (tier_one, ineligible):
        enqueue_candidate(current_state, item.candidate, now)
        record = current_state["candidates"][item.key]
        record["phase"] = "pending_selection"
        record["classification"] = item.event_class.value
        record["selection"] = {
            "ranking_band": item.ranking_band,
            "material_facts": list(item.material_facts),
            "dedupe_facts": list(item.dedupe_facts),
        }

    assert assign_tier(current_state, tier_one) is Tier.ONE
    assert current_state["candidates"][tier_one.key]["phase"] == "pending_delivery"
    assert assign_tier(current_state, ineligible) is None
    assert current_state["candidates"][ineligible.key]["phase"] == "suppressed_ineligible"
    assert select_digest_candidates(current_state, [tier_one]) == ([], [])


def test_ranking_uses_event_weight_then_band_then_fact_count_then_publication_time():
    published_at = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    routine = _selection_candidate(
        Provider.TUNTUN,
        401,
        "ROUT",
        published_at,
        event_class=EventClass.ROUTINE_STATUS,
        ranking_band=1,
        material_facts=("a", "b", "c"),
    )
    other = _selection_candidate(
        Provider.TUNTUN,
        402,
        "OTHR",
        published_at,
        event_class=EventClass.OTHER_COMPANY_OPERATION,
        ranking_band=5,
        material_facts=("a",),
    )
    few_facts = _selection_candidate(
        Provider.TUNTUN,
        403,
        "FEWS",
        published_at,
        ranking_band=2,
        material_facts=("a",),
    )
    many_facts_later = _selection_candidate(
        Provider.TUNTUN,
        404,
        "MANY",
        published_at + timedelta(minutes=1),
        ranking_band=2,
        material_facts=("a", "b"),
    )
    many_facts_earlier = _selection_candidate(
        Provider.TUNTUN,
        405,
        "EARL",
        published_at,
        ranking_band=2,
        material_facts=("a", "b"),
    )

    ranked = rank_tier_two([routine, other, few_facts, many_facts_later, many_facts_earlier])

    assert [item.ticker for item in ranked] == ["EARL", "MANY", "FEWS", "OTHR", "ROUT"]


def test_digest_window_only_exists_on_weekday_wib_due_instants():
    assert digest_window(datetime.fromisoformat("2026-07-20T08:29:59+07:00")) is None
    assert digest_window(datetime.fromisoformat("2026-07-20T16:30:00+07:00")).kind == "after_close"
    assert digest_window(datetime.fromisoformat("2026-07-18T08:30:00+07:00")) is None



def test_validated_selection_data_survives_reload_for_duplicate_and_digest_ranking(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_path / "state.json"))
    current_state = empty_state()
    now = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    candidate_inputs = (
        (Provider.TUNTUN, 501, "DEWA", ("production volume", "reporting period")),
        (Provider.PHINTRACO, 502, "DEWA", ("production volume", "reporting period")),
        (Provider.TUNTUN, 503, "AAAA", ("fact AAAA one", "fact AAAA two")),
        (Provider.PHINTRACO, 504, "BBBB", ("fact BBBB one", "fact BBBB two")),
        (Provider.TUNTUN, 505, "CCCC", ("fact CCCC one", "fact CCCC two")),
        (Provider.PHINTRACO, 506, "DDDD", ("fact DDDD one", "fact DDDD two")),
    )

    for index, (provider, message_id, ticker, dedupe_facts) in enumerate(candidate_inputs):
        candidate = _candidate(provider, message_id, ticker, now + timedelta(minutes=index))
        enqueue_candidate(current_state, candidate, now)
        claimed = claim_oldest_pending_analysis(current_state, now)
        assert claimed == candidate
        payload = {
            "candidate_key": claimed.key,
            "ticker": claimed.ticker,
            "event_class": EventClass.QUANTIFIED_OPERATIONAL_EXECUTION.value,
            "summary": "The company reported an operational update. The source confirms the facts. The update identifies the affected activity.",
            "material_facts": [f"{ticker} reported volume"],
            "ranking_band": 1,
            "dedupe_facts": list(dedupe_facts),
            "eligible": True,
            "source_evidence": "The provider message directly states the update.",
        }
        if provider is Provider.TUNTUN:
            payload["title"] = f"{ticker}: Operational update"
            payload["route"] = "id_stocks_news"
        submit_classification(
            current_state,
            claimed,
            payload,
            now,
        )

    restored = load_state()
    restored_candidates = pending_selection_candidates(restored)

    assert is_confident_duplicate(restored_candidates[0], restored_candidates[1])
    selected, overflow = select_digest_candidates(restored)
    assert [item.ticker for item in selected] == ["DEWA", "DEWA", "AAAA", "BBBB", "CCCC", "DDDD"]
    assert overflow == []
    assert all(restored["candidates"][item.key]["phase"] == "pending_delivery" for item in selected)


def test_legacy_pending_selection_reloads_as_reclassifiable_and_selectable(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(path))
    now = datetime.fromisoformat("2026-07-20T08:00:00+07:00")
    legacy_candidate = _candidate(Provider.TUNTUN, 601, "LEGA", now)
    legacy_state = empty_state()
    enqueue_candidate(legacy_state, legacy_candidate, now)
    legacy_record = legacy_state["candidates"][legacy_candidate.key]
    legacy_record["phase"] = "pending_selection"
    legacy_record["classification"] = EventClass.QUANTIFIED_OPERATIONAL_EXECUTION.value
    del legacy_record["selection"]
    path.write_text(json.dumps(legacy_state), encoding="utf-8")
    os.chmod(path, 0o600)

    restored = load_state()
    migrated_record = restored["candidates"][legacy_candidate.key]
    assert migrated_record["phase"] == "pending_analysis"
    assert migrated_record["classification"] is None
    assert migrated_record["selection"] is None
    assert migrated_record["agent_lease_until"] is None

    claimed = claim_oldest_pending_analysis(restored, now)
    assert claimed == legacy_candidate
    submit_classification(
        restored,
        claimed,
        {
            "candidate_key": claimed.key,
            "ticker": claimed.ticker,
            "event_class": EventClass.QUANTIFIED_OPERATIONAL_EXECUTION.value,
            "title": "LEGA: Operational update",
            "summary": "The company reported an operational update. The source confirms the facts. The update identifies the affected activity.",
            "material_facts": ["reported volume"],
            "ranking_band": 1,
            "dedupe_facts": ["production volume", "reporting period"],
            "eligible": True,
            "route": "id_stocks_news",
            "source_evidence": "The provider message directly states the update.",
        },
        now,
    )
    selected, overflow = select_digest_candidates(restored)

    assert [item.key for item in selected] == [legacy_candidate.key]
    assert overflow == []
