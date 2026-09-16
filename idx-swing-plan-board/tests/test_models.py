from dataclasses import FrozenInstanceError

import pytest

from conftest import example_buy_event, social_event
from models import Checkpoint, MarketState, PlanLevels, SourceEvent, SourceOutcome


def test_source_event_is_strict_and_normalizes_ticker() -> None:
    event = SourceEvent.from_json(
        {
            "event_key": "phintraco:1444713822:33655",
            "source": "phintraco",
            "kind": "buy",
            "ticker": "scma",
            "published_at": "2026-09-19T09:05:00+07:00",
            "source_url": "https://t.me/phintraprofits/33655",
            "all_content": "### <:phintraco:1> SCMA: Buy",
            "source_title": "SCMA: Trading Buy",
            "source_status": "New setup",
            "plan": {"entry": "208 to 212", "stop_loss": "<200", "targets": ["230"]},
            "media_path": None,
            "media_urls": [],
        }
    )
    assert event.ticker == "SCMA"
    assert event.plan == PlanLevels("208 to 212", "<200", ("230",))


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": "value"},
        {"published_at": "2026-09-19T09:05:00"},
        {"source_url": "ftp://example.com/source"},
        {"media_path": "relative/chart.png"},
        {"kind": "sell"},
        {"plan": None},
        {"source": "x"},
    ],
)
def test_source_event_rejects_untrusted_or_incomplete_buy(change: dict) -> None:
    payload = {
        "event_key": "phintraco:1444713822:33655",
        "source": "phintraco",
        "kind": "buy",
        "ticker": "SCMA",
        "published_at": "2026-09-19T09:05:00+07:00",
        "source_url": "https://t.me/phintraprofits/33655",
        "all_content": "### <:phintraco:1> SCMA: Buy",
        "source_title": "SCMA: Trading Buy",
        "source_status": "New setup",
        "plan": {"entry": "208 to 212", "stop_loss": "<200", "targets": ["230"]},
        "media_path": None,
        "media_urls": [],
    }
    payload.update(change)
    with pytest.raises(ValueError):
        SourceEvent.from_json(payload)


def test_social_event_preserves_exact_source_title_and_cannot_have_a_plan() -> None:
    event = social_event(
        "x:marketwriter:101",
        "kpig",
        "KPIG: Wave IV diproyeksikan menuju area 97 sampai 108",
    )
    assert event.ticker == "KPIG"
    assert event.plan is None

    invalid = dict(event.__dict__)
    invalid["plan"] = {"entry": "97", "stop_loss": "<90", "targets": ["108"]}
    with pytest.raises(ValueError):
        SourceEvent.from_json(invalid)

    invalid["plan"] = None
    invalid["source_title"] = ""
    with pytest.raises(ValueError):
        SourceEvent.from_json(invalid)


def test_value_objects_are_closed_and_target_mapping_is_bounded() -> None:
    event = example_buy_event()
    with pytest.raises(FrozenInstanceError):
        event.ticker = "BBRI"
    assert MarketState.from_target_number(1) is MarketState.TP1_REACHED
    assert MarketState.from_target_number(5) is MarketState.TP5_REACHED
    assert MarketState.from_target_number(6) is MarketState.TP6_REACHED
    with pytest.raises(ValueError):
        MarketState.from_target_number(0)
    with pytest.raises(ValueError):
        MarketState.from_target_number(7)


def test_source_outcome_and_checkpoint_accept_only_market_states() -> None:
    outcome = SourceOutcome(MarketState.TP1_REACHED, "Target 1 achieved")
    checkpoint = Checkpoint.market(
        session_date="2026-09-19",
        checked_at="2026-09-19T16:30:00+07:00",
        close_price="230",
        state=MarketState.TP1_REACHED,
    )
    assert outcome.state is MarketState.TP1_REACHED
    assert checkpoint.state is MarketState.TP1_REACHED

    with pytest.raises(ValueError):
        SourceOutcome("TP1 reached", "Target 1 achieved")
    with pytest.raises(ValueError):
        Checkpoint.market(
            session_date="2026-09-19",
            checked_at="2026-09-19T16:30:00+07:00",
            close_price="230",
            state="TP1 reached",
        )
