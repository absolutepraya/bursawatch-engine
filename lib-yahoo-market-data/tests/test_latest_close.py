"""Synthetic payloads shaped like the 2026-10-08 07:29 WIB Yahoo responses, no network."""
from copy import deepcopy
from datetime import datetime, timedelta
import pytest

from yahoo_market_data.latest_close import fill_latest_close


def at(value): return datetime.fromisoformat(value)
def unix(value): return int(at(value).timestamp())


# Jakarta stock: the latest completed session has every field except close.
START = at('2026-10-07T09:00:00+07:00')
END = at('2026-10-07T16:00:00+07:00')


def daily(*, close=None, price=2600.0, price_at='2026-10-07T16:12:00+07:00', volume=26192100, day_volume=26192100,
          high=2650.0, low=2580.0, day_high=2650.0, day_low=2580.0, symbol='ADRO.JK'):
    previous = unix('2026-10-06T09:00:00+07:00'), 2590.0, 2610.0, 2570.0, 2600.0, 20000000
    latest = unix('2026-10-07T09:00:00+07:00'), 2600.0, high, low, close, volume
    rows = [previous, latest]
    meta = dict(symbol=symbol, exchangeTimezoneName='Asia/Jakarta', dataGranularity='1d', regularMarketPrice=price,
                regularMarketTime=unix(price_at), regularMarketDayHigh=day_high, regularMarketDayLow=day_low,
                regularMarketVolume=day_volume)
    quote = {name: [row[i] for row in rows] for i, name in enumerate(('open', 'high', 'low', 'close', 'volume'), start=1)}
    return {'chart': {'error': None, 'result': [dict(meta=meta, timestamp=[row[0] for row in rows], indicators={'quote': [quote]})]}}


def closes(payload): return payload['chart']['result'][0]['indicators']['quote'][0]['close']


def test_meta_price_fills_a_null_close_when_the_payload_agrees_with_the_bar():
    filled, repair = fill_latest_close(daily(), session_start=START, session_end=END)
    assert closes(filled) == [2600.0, 2600.0] and repair['method'] == 'meta_regular_market_price'
    assert repair['value'] == 2600.0 and repair['session_start'] == START.isoformat()


def test_original_payload_is_never_mutated_and_a_present_close_is_left_alone():
    original = daily()
    before = deepcopy(original)
    fill_latest_close(original, session_start=START, session_end=END)
    assert original == before
    present = daily(close=2611.0)
    same, repair = fill_latest_close(present, session_start=START, session_end=END)
    assert same == present and repair is None


@pytest.mark.parametrize('change', [
    dict(volume=1000),                                       # partial bar, volume disagrees with the day total
    dict(day_high=2700.0),                                   # high disagrees
    dict(day_low=2500.0),                                    # low disagrees
    dict(price=2700.0),                                      # price outside the bar's range
    dict(price_at='2026-10-07T14:00:00+07:00'),              # not a closing-window quote
    dict(price_at='2026-10-08T09:10:00+07:00'),              # next session's quote
])
def test_any_disagreement_leaves_the_close_missing(change):
    filled, repair = fill_latest_close(daily(**change), session_start=START, session_end=END)
    assert closes(filled)[-1] is None and repair is None


def test_only_the_single_latest_session_is_repaired_never_an_interior_gap():
    payload = daily()
    payload['chart']['result'][0]['indicators']['quote'][0]['close'][0] = None
    filled, repair = fill_latest_close(payload, session_start=START, session_end=END)
    assert closes(filled) == [None, 2600.0] and repair['value'] == 2600.0


def test_non_positive_or_non_finite_price_is_rejected():
    for bad in (0, -1, float('nan'), float('inf'), None, 'x'):
        filled, repair = fill_latest_close(daily(price=bad), session_start=START, session_end=END)
        assert repair is None and closes(filled)[-1] is None


# US ETF: the bar is partial (volume below the day total), so the intraday series is the evidence.
US_START = at('2026-10-07T09:30:00-04:00')
US_END = at('2026-10-07T16:00:00-04:00')


def us_daily(*, volume=30746070, day_volume=51000000):
    previous = unix('2026-10-06T09:30:00-04:00'), 778.15, 781.62, 777.96, 779.09, 36054300
    latest = unix('2026-10-07T09:30:00-04:00'), 775.77, 779.1021, 773.61, None, volume
    rows = [previous, latest]
    meta = dict(symbol='SPY', exchangeTimezoneName='America/New_York', dataGranularity='1d', regularMarketPrice=777.22,
                regularMarketTime=unix('2026-10-07T16:00:00-04:00'), regularMarketDayHigh=779.9, regularMarketDayLow=773.0,
                regularMarketVolume=day_volume)
    quote = {name: [row[i] for row in rows] for i, name in enumerate(('open', 'high', 'low', 'close', 'volume'), start=1)}
    return {'chart': {'error': None, 'result': [dict(meta=meta, timestamp=[row[0] for row in rows], indicators={'quote': [quote]})]}}


def intraday(symbol, zone, bars, *, price=None, price_at=None):
    meta = dict(symbol=symbol, exchangeTimezoneName=zone, dataGranularity='60m')
    if price is not None: meta.update(regularMarketPrice=price, regularMarketTime=unix(price_at))
    quote = {'close': [b[1] for b in bars], 'high': [b[1] + 0.3 for b in bars], 'low': [b[1] - 0.3 for b in bars]}
    return {'chart': {'error': None, 'result': [dict(meta=meta, timestamp=[unix(b[0]) for b in bars], indicators={'quote': [quote]})]}}


US_BARS = [('2026-10-07T09:30:00-04:00', 776.0), ('2026-10-07T14:30:00-04:00', 777.0), ('2026-10-07T15:30:00-04:00', 777.22)]


def test_partial_daily_bar_uses_the_last_intraday_close_when_it_matches_the_market_price():
    series = intraday('SPY', 'America/New_York', US_BARS)
    filled, repair = fill_latest_close(us_daily(), session_start=US_START, session_end=US_END, intraday=series)
    assert closes(filled)[-1] == 777.22 and repair['method'] == 'last_intraday_bar_close'


def test_intraday_close_must_agree_with_the_market_price_at_the_session_end():
    series = intraday('SPY', 'America/New_York', US_BARS[:2] + [('2026-10-07T15:30:00-04:00', 770.0)])
    filled, repair = fill_latest_close(us_daily(), session_start=US_START, session_end=US_END, intraday=series)
    assert repair is None and closes(filled)[-1] is None


def test_intraday_series_must_reach_the_end_of_the_session_and_match_the_symbol():
    early = intraday('SPY', 'America/New_York', US_BARS[:2])
    assert fill_latest_close(us_daily(), session_start=US_START, session_end=US_END, intraday=early)[1] is None
    wrong = intraday('QQQ', 'America/New_York', US_BARS)
    assert fill_latest_close(us_daily(), session_start=US_START, session_end=US_END, intraday=wrong)[1] is None


# Asian index: the whole latest row is null and the metadata already shows the next live session.
KR_START = at('2026-10-07T09:00:00+09:00')
KR_END = at('2026-10-07T15:30:00+09:00')


def kr_daily():
    rows = [(unix('2026-10-06T09:00:00+09:00'), 7044.0, 7044.7, 6897.4, 6941.39),
            (unix('2026-10-07T09:00:00+09:00'), None, None, None, None),
            (unix('2026-10-08T09:00:00+09:00'), 6808.68, 6810.83, 6771.79, 6785.2)]
    meta = dict(symbol='^KS11', exchangeTimezoneName='Asia/Seoul', dataGranularity='1d', regularMarketPrice=6785.2,
                regularMarketTime=unix('2026-10-08T09:09:00+09:00'))
    quote = {name: [row[i] for row in rows] for i, name in enumerate(('open', 'high', 'low', 'close'), start=1)}
    return {'chart': {'error': None, 'result': [dict(meta=meta, timestamp=[row[0] for row in rows], indicators={'quote': [quote]})]}}


def test_hourly_series_alone_is_not_trusted_when_the_market_price_is_another_session():
    # The hourly series can stop before the closing auction (real KOSPI: 6826.18 vs 6803.90 official).
    series = intraday('^KS11', 'Asia/Seoul', [('2026-10-07T09:00:00+09:00', 6810.0), ('2026-10-07T14:00:00+09:00', 6803.9),
                                              ('2026-10-07T15:00:00+09:00', 6826.18)])
    filled, repair = fill_latest_close(kr_daily(), session_start=KR_START, session_end=KR_END, intraday=series)
    assert repair is None and closes(filled)[1] is None


def one_day_chart(symbol='^KS11', previous=6803.9, bars=('2026-10-08T09:00:00+09:00',)):
    meta = dict(symbol=symbol, exchangeTimezoneName='Asia/Seoul', dataGranularity='1d', chartPreviousClose=previous)
    return {'chart': {'error': None, 'result': [dict(meta=meta, timestamp=[unix(b) for b in bars],
                                                    indicators={'quote': [{'close': [6756.16] * len(bars)}]})]}}


def test_previous_close_of_a_later_one_day_chart_fills_the_asian_baseline():
    filled, repair = fill_latest_close(kr_daily(), session_start=KR_START, session_end=KR_END, previous_close=one_day_chart())
    assert closes(filled) == [6941.39, 6803.9, 6785.2] and repair['method'] == 'chart_previous_close'


@pytest.mark.parametrize('chart', [
    one_day_chart(symbol='^N225'),                                        # wrong instrument
    one_day_chart(previous=0),                                            # not a usable close
    one_day_chart(bars=('2026-10-07T09:00:00+09:00',)),                   # still the same session, not a later one
    one_day_chart(bars=('2026-10-08T09:00:00+09:00', '2026-10-07T09:00:00+09:00')),
])
def test_unusable_previous_close_charts_leave_the_gap(chart):
    filled, repair = fill_latest_close(kr_daily(), session_start=KR_START, session_end=KR_END, previous_close=chart)
    assert repair is None and closes(filled)[1] is None


def test_without_any_evidence_the_gap_is_kept():
    filled, repair = fill_latest_close(kr_daily(), session_start=KR_START, session_end=KR_END)
    assert repair is None and closes(filled)[1] is None
