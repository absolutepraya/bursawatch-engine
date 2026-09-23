import json
from datetime import datetime, timezone

import pytest

import config
from agent_protocol import TUNTUN_INSTRUCTION, agent_item, build_wake_payload, submit_classification, validate_agent_submission
from domain import CompanyCandidate, EventClass, Provider, SourceKind
from state import claim_oldest_pending_analysis, empty_state, enqueue_candidate


INSTRUCTION = TUNTUN_INSTRUCTION


def _tuntun_candidate() -> CompanyCandidate:
    return CompanyCandidate(
        Provider.TUNTUN,
        13597,
        "DEWA",
        SourceKind.CORPORATE_ENTRY,
        datetime.now(timezone.utc),
        "DEWA (Darma Henwa): kontrak Rp22 triliun.",
        False,
    )


def _validate(payload, candidate=None):
    return validate_agent_submission(candidate or _tuntun_candidate(), payload)


def test_wake_payload_contains_one_bounded_untrusted_source_item():
    candidate = CompanyCandidate(
        Provider.TUNTUN,
        13597,
        "DEWA",
        SourceKind.CORPORATE_ENTRY,
        datetime.now(timezone.utc),
        "DEWA (Darma Henwa): kontrak Rp22 triliun.",
        False,
    )
    item = agent_item(candidate)
    payload = build_wake_payload([item])

    assert payload["wakeAgent"] is True
    assert payload["items"] == [item]
    assert item["source_text"] == candidate.source_text
    assert item["instruction"] == INSTRUCTION
    assert item == {
        "candidate_key": candidate.key,
        "ticker": "DEWA",
        "provider": "tuntun",
        "source_url": "https://t.me/tuntunsekuritas/13597",
        "source_published_at": candidate.published_at.isoformat(),
        "source_kind": "corporate_entry",
        "candidate_type": "issuer",
        "source_text": candidate.source_text,
        "instruction": INSTRUCTION,
    }


def test_wake_payload_rejects_anything_but_one_item(candidate):
    item = agent_item(candidate)

    with pytest.raises(ValueError, match="exactly one"):
        build_wake_payload([])
    with pytest.raises(ValueError, match="exactly one"):
        build_wake_payload([item, item])


def test_wake_payload_uses_the_frozen_operator_prompt_and_source_username():
    candidate = _tuntun_candidate()
    watch_config = config.load_watch_config_data(
        {
            "version": 1,
            "providers": {
                "phintraco": {"telegram_username": "phintracocp"},
                "tuntun": {"telegram_username": "tuntuncontrol"},
            },
            "destinations": {
                "id_stocks_news_discord_channel_id": "1525102508714889258",
                "macro_news_discord_channel_id": "1531655369884045383",
                "industry_news_discord_channel_id": "1549418098807930881",
                "heartbeat_discord_channel_id": "1505162000420835389",
            },
            "additional_prompt_instruction": "Utamakan ringkasan yang padat.",
        }
    )

    with config.activate_watch_config(watch_config):
        item = agent_item(candidate)
        payload = build_wake_payload([item])

    assert item["source_url"] == "https://t.me/tuntuncontrol/13597"
    assert "Additional operator context follows." in item["instruction"]
    assert item["instruction"].endswith("Utamakan ringkasan yang padat.\n")
    assert payload["items"] == [item]


def test_phintraco_prompt_includes_route_classification_and_estimate_attribution(later_candidate):
    instruction = agent_item(later_candidate)["instruction"]

    assert "macro_news" in instruction
    assert "broader market" in instruction
    assert "Attribute research estimates to Phintraco" in instruction
    assert "preserve the stated period, units" in instruction


def test_agent_submission_requires_exact_candidate_ticker(load_fixture):
    payload = json.loads(load_fixture("classification-invalid-ticker.json"))
    payload["candidate_key"] = "tuntun:13597:DEWA"
    with pytest.raises(ValueError, match="ticker"):
        _validate(payload)


def test_agent_submission_requires_key_ticker_to_match_without_candidate_key(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload["candidate_key"] = "tuntun:13597:INCO"

    with pytest.raises(ValueError, match="candidate_key"):
        _validate(payload)

def test_agent_submission_rejects_mismatched_candidate_key(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload["candidate_key"] = "tuntun:1:DEWA"

    with pytest.raises(ValueError, match="candidate_key"):
        _validate(payload)


def test_agent_submission_accepts_only_the_closed_schema(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))

    assert _validate(payload) is EventClass.MATERIAL_CONTRACT

    payload["unrelated_state"] = "do not expose this"
    with pytest.raises(ValueError, match="unexpected"):
        _validate(payload)


def test_agent_submission_accepts_a_single_factual_sentence_when_it_is_sufficient(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload["summary"] = "DEWA mengungkapkan kontrak material senilai Rp22 triliun."

    assert _validate(payload) is EventClass.MATERIAL_CONTRACT


def test_phintraco_submission_does_not_require_a_title(candidate, later_candidate, load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "candidate_key": later_candidate.key,
            "ticker": later_candidate.ticker,
        }
    )
    payload.pop("title")

    assert _validate(payload, later_candidate) is EventClass.MATERIAL_CONTRACT


def test_phintraco_submission_requires_a_closed_route(load_fixture, later_candidate):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update({"candidate_key": later_candidate.key, "ticker": later_candidate.ticker})
    payload.pop("title")
    payload.pop("route")

    with pytest.raises(ValueError, match="route"):
        _validate(payload, later_candidate)


def test_phintraco_macro_route_can_suppress_an_issuer_card(load_fixture, later_candidate):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "candidate_key": later_candidate.key,
            "ticker": later_candidate.ticker,
            "route": "macro_news",
        }
    )
    payload.pop("title")

    assert _validate(payload, later_candidate) is EventClass.MATERIAL_CONTRACT
    payload["eligible"] = False
    with pytest.raises(ValueError, match="eligible"):
        _validate(payload, later_candidate)


@pytest.mark.parametrize(
    "title",
    [
        "DEWA headline",
        "INCO: Headline",
        "DEWA: Headline.",
        "DEWA: https://example.com",
    ],
)
def test_tuntun_title_must_be_prefixed_plain_and_without_ending_punctuation(load_fixture, title):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload["title"] = title

    with pytest.raises(ValueError, match="title"):
        _validate(payload)


def test_tuntun_submission_requires_title(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.pop("title")

    with pytest.raises(ValueError, match="title"):
        _validate(payload)


def test_tuntun_submission_requires_a_closed_route(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.pop("route")

    with pytest.raises(ValueError, match="route"):
        _validate(payload)


def test_macro_candidate_can_only_route_to_macro_news_or_exclude(load_fixture):
    candidate = CompanyCandidate(
        Provider.TUNTUN,
        14786,
        None,
        SourceKind.TUNTUN_UPDATE_SECTION,
        datetime.now(timezone.utc),
        "ECB menaikkan suku bunga deposit.",
        False,
        candidate_id="macro-1",
    )
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "candidate_key": candidate.key,
            "ticker": "",
            "title": "ECB naikkan suku bunga deposit",
            "route": "macro_news",
        }
    )

    assert _validate(payload, candidate) is EventClass.MATERIAL_CONTRACT
    payload["route"] = "id_stocks_news"
    with pytest.raises(ValueError, match="macro candidate"):
        _validate(payload, candidate)


def test_industry_update_candidate_can_only_route_to_macro_news_or_exclude(load_fixture):
    candidate = CompanyCandidate(
        Provider.TUNTUN,
        14786,
        None,
        SourceKind.TUNTUN_UPDATE_INDUSTRY,
        datetime.now(timezone.utc),
        "Harga minyak meningkat.",
        False,
        candidate_id="industry-1",
    )
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "candidate_key": candidate.key,
            "ticker": "",
            "title": "Harga minyak meningkat",
            "route": "macro_news",
        }
    )

    assert _validate(payload, candidate) is EventClass.MATERIAL_CONTRACT
    payload["route"] = "id_stocks_news"
    with pytest.raises(ValueError, match="macro candidate|Industry update candidate"):
        _validate(payload, candidate)


def test_tickered_tuntun_candidate_uses_an_unprefixed_title_when_routed_to_macro(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "route": "macro_news",
            "title": "Harga minyak mendekati US$110 per barel",
        }
    )

    assert _validate(payload) is EventClass.MATERIAL_CONTRACT
    payload["title"] = "DEWA: Harga minyak mendekati US$110 per barel"
    with pytest.raises(ValueError, match="macro title"):
        _validate(payload)


def test_summary_marker_is_owned_by_the_renderer(load_fixture):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload["summary"] = "*(Ringkasan)* Ringkasan tidak boleh dikirim oleh agent."

    with pytest.raises(ValueError, match="Ringkasan"):
        _validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("event_class", "unknown_class", "event_class"),
        ("summary", "First. Second. Third. Fourth. Fifth. Sixth.", "summary"),
        ("ranking_band", 6, "ranking_band"),
        ("ranking_band", True, "ranking_band"),
        ("material_facts", ["fact", 7], "material_facts"),
        ("dedupe_facts", "not an array", "dedupe_facts"),
        ("source_evidence", "", "source_evidence"),
        ("summary", "The facts support a BUY. This is material. The source names the issuer.", "investment language"),
    ],
)
def test_agent_submission_rejects_invalid_closed_schema_fields(load_fixture, field, value, error):
    payload = json.loads(load_fixture("classification-valid.json"))
    payload[field] = value

    with pytest.raises(ValueError, match=error):
        _validate(payload)


def test_submit_classification_validates_before_mutating_pending_lease(load_fixture, candidate):
    now = datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc)
    state = empty_state()
    enqueue_candidate(state, candidate, now)
    assert claim_oldest_pending_analysis(state, now) == candidate
    invalid_payload = json.loads(load_fixture("classification-valid.json"))
    invalid_payload["ranking_band"] = 0

    with pytest.raises(ValueError, match="ranking_band"):
        submit_classification(state, candidate, invalid_payload, now)

    record = state["candidates"][candidate.key]
    assert record["phase"] == "awaiting_agent"
    assert record["retry"] == {
        "attempts": 0,
        "next_attempt_at": now.isoformat(),
        "last_error": None,
    }


def test_submit_classification_persists_validated_event_class(load_fixture, candidate):
    now = datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc)
    state = empty_state()
    enqueue_candidate(state, candidate, now)
    assert claim_oldest_pending_analysis(state, now) == candidate

    classification = submit_classification(
        state,
        candidate,
        json.loads(load_fixture("classification-valid.json")),
        now,
    )

    assert classification.candidate == candidate
    assert classification.event_class is EventClass.MATERIAL_CONTRACT
    assert state["candidates"][candidate.key]["phase"] == "pending_selection"
    assert state["candidates"][candidate.key]["selection"]["title"] == "DEWA: Kontrak material terungkap"
    assert state["candidates"][candidate.key]["selection"]["route"] == "id_stocks_news"


def test_submit_classification_persists_phintraco_macro_route(load_fixture, later_candidate):
    now = datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc)
    state = empty_state()
    enqueue_candidate(state, later_candidate, now)
    assert claim_oldest_pending_analysis(state, now) == later_candidate
    payload = json.loads(load_fixture("classification-valid.json"))
    payload.update(
        {
            "candidate_key": later_candidate.key,
            "ticker": later_candidate.ticker,
            "route": "macro_news",
        }
    )
    payload.pop("title")

    submit_classification(state, later_candidate, payload, now)

    assert state["candidates"][later_candidate.key]["selection"]["route"] == "macro_news"
