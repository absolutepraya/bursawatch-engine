from datetime import date
from decimal import Decimal

import pytest

from prices import classify_close, fetch_session_close, parse_plan_levels


def dataframe_for(day, close):
    import pandas as pd
    return pd.DataFrame({"Close": [close]}, index=pd.DatetimeIndex([day], tz="Asia/Jakarta"))


@pytest.mark.parametrize("close,expected", [
    ("199", "Stop-loss breached"), ("250", "TP2 reached"),
    ("210", "Entry zone"), ("205", "Below entry"), ("220", "Above entry"),
])
def test_classify_close_prefers_stop_then_highest_target(close, expected):
    plan = parse_plan_levels("208 to 212", "<200", ("230", "250", "270"))
    assert classify_close(Decimal(close), plan).value == expected


@pytest.mark.parametrize("entry", ["208.5", "-208", "208 212", "buy 208", "212 to 208", "1.00", "1,000", "0", "208 to 212 to 230"])
def test_rejects_ambiguous_levels(entry):
    with pytest.raises(ValueError):
        parse_plan_levels(entry, "<200", ("230",))


def test_thousands_unbounded_entry_and_target_clamping():
    plan = parse_plan_levels(">=1.000", "<900", ("1.200 to 1.250", "1.300", "1.400", "1.500", "1.600", "1.700"))
    assert classify_close(Decimal("1199"), plan).value == "Entry zone"
    assert classify_close(Decimal("1200"), plan).value == "TP1 reached"
    assert classify_close(Decimal("1700"), plan).value == "TP6 reached"
    assert len(plan.targets) == 6


@pytest.mark.parametrize("stop,close,breached", [("<200", "200", False), ("<=200", "200", True), ("200", "200", True), (">200", "201", True), (">=200", "200", True)])
def test_stop_operator_boundaries(stop, close, breached):
    levels = parse_plan_levels("210", stop, ("230",))
    assert levels.stop_loss.is_breached_by(Decimal(close)) is breached


def test_fetch_session_close_rejects_previous_yahoo_bar(monkeypatch):
    monkeypatch.setattr("prices._history", lambda symbol: dataframe_for(date(2026, 9, 18), "230"))
    assert fetch_session_close("SCMA", date(2026, 9, 21)) is None


@pytest.mark.parametrize("close", ["NaN", "Infinity", "0", "-1", "invalid", None])
def test_fetch_rejects_invalid_close(monkeypatch, close):
    monkeypatch.setattr("prices._history", lambda symbol: dataframe_for(date(2026, 9, 21), close))
    assert fetch_session_close("SCMA", date(2026, 9, 21)) is None


def test_fetch_valid_close_and_provider_failure(monkeypatch):
    seen = []
    monkeypatch.setattr("prices._history", lambda symbol: (seen.append(symbol) or dataframe_for(date(2026, 9, 21), "230")))
    assert fetch_session_close("SCMA", date(2026, 9, 21)) == Decimal("230")
    assert seen == ["SCMA.JK"]
    monkeypatch.setattr("prices._history", lambda symbol: (_ for _ in ()).throw(RuntimeError("offline")))
    assert fetch_session_close("SCMA", date(2026, 9, 21)) is None
