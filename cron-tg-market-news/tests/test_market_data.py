from __future__ import annotations

import sys
from types import SimpleNamespace
import pandas as pd

import market_data


class FakeHistory(dict):
    pass


class FakeQuote:
    def __init__(self, closes):
        self.closes = closes
        self.history_args = None
        self.fast_info = {"last_price": closes[-1] + 1, "previous_close": closes[-1]}

    def history(self, **kwargs):
        self.history_args = kwargs
        return pd.DataFrame({'Close': self.closes}, index=pd.bdate_range(end='2026-10-01', periods=len(self.closes), tz='Asia/Jakarta'))

    def get_history_metadata(self):
        return {'regularMarketTime': pd.Timestamp('2026-10-01T16:00:00+07:00').timestamp(),
                'exchangeTimezoneName': 'Asia/Jakarta'}

    def get_info(self):
        return {"longName": "PT Rukun Raharja Tbk"}


def test_market_snapshot_uses_one_year_history_and_22_66_session_horizons(monkeypatch):
    quote = FakeQuote(list(range(1, 68)))
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda ticker: quote))

    snapshot = market_data.get_market_snapshot("RAJA", "RAJA: headline")

    assert snapshot is not None
    assert quote.history_args == {
        "period": "1y",
        "interval": "1d",
        "auto_adjust": False,
        "raise_errors": True,
        "timeout": 5,
    }
    assert snapshot.latest_price == 68
    assert snapshot.one_day_change == 1
    assert snapshot.one_week_change == 6
    assert snapshot.one_month_change == 23
    assert snapshot.three_month_change == 67


def test_market_snapshot_keeps_shorter_horizons_when_longer_history_is_unavailable(monkeypatch):
    quote = FakeQuote(list(range(1, 23)))
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda ticker: quote))

    snapshot = market_data.get_market_snapshot("RAJA", "RAJA: headline")

    assert snapshot is not None
    assert snapshot.one_week_change == 6
    assert snapshot.one_month_change is None
    assert snapshot.one_month_percent is None
    assert snapshot.three_month_change is None
    assert snapshot.three_month_percent is None
