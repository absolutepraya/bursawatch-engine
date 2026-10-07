from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from yahoo_market_data import parse_daily, simple_moving_average, wilder_rsi


def payload():
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': '^JKSE', 'dataGranularity': '1d', 'exchangeTimezoneName': 'Asia/Jakarta'},
        'timestamp': [int(datetime(2026, 10, day, 2, tzinfo=timezone.utc).timestamp()) for day in (1, 2)],
        'indicators': {'quote': [{'open': [99, 101], 'high': [103, 104],
                                 'low': [98, 100], 'close': [102, 103]}],
                       'adjclose': [{'adjclose': [50, 51]}]}}]}}


def parse(value):
    return parse_daily(value, symbol='^JKSE', exchange_timezone='Asia/Jakarta', through=date(2026, 10, 2))


def test_daily_ordinary_prices_exclude_later_unfinished_bars():
    value = payload()
    value['chart']['result'][0]['indicators']['quote'][0]['close'][-1] = None
    bars = parse_daily(value, symbol='^JKSE', exchange_timezone='Asia/Jakarta', through=date(2026, 10, 1))
    assert len(bars) == 1 and bars[0].close == 102 and bars[0].low == 98


@pytest.mark.parametrize('change', ['symbol', 'interval', 'timezone', 'duplicate', 'unordered', 'null', 'nan', 'bounds', 'length'])
def test_native_daily_validation(change):
    value = deepcopy(payload()); row = value['chart']['result'][0]
    if change == 'symbol': row['meta']['symbol'] = 'OTHER'
    if change == 'interval': row['meta']['dataGranularity'] = '1h'
    if change == 'timezone': row['meta']['exchangeTimezoneName'] = 'UTC'
    if change == 'duplicate': row['timestamp'][1] = row['timestamp'][0] + 60
    if change == 'unordered': row['timestamp'].reverse()
    if change == 'null': row['indicators']['quote'][0]['open'][0] = None
    if change == 'nan': row['indicators']['quote'][0]['low'][0] = float('nan')
    if change == 'bounds': row['indicators']['quote'][0]['low'][0] = 110
    if change == 'length': row['indicators']['quote'][0]['high'].pop()
    with pytest.raises(ValueError): parse(value)


def test_sma_exact_windows_and_warmup():
    assert simple_moving_average([2, 4, 8, 10], 3) == (None, None, 14 / 3, 22 / 3)
    assert simple_moving_average([2, 4], 100) == (None, None)


def test_explicit_session_filter_ignores_null_holiday_placeholder_only():
    value = payload(); row = value['chart']['result'][0]
    for values in row['indicators']['quote'][0].values(): values[0] = None
    bars = parse_daily(value, symbol='^JKSE', exchange_timezone='Asia/Jakarta',
                       through=date(2026, 10, 2), session_dates=(date(2026, 10, 2),))
    assert len(bars) == 1 and bars[0].close == 103
    with pytest.raises(ValueError): parse(value)


def test_wilder_rsi_reference_and_edge_cases():
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    rsi = wilder_rsi(closes)
    assert rsi[:14] == (None,) * 14
    assert rsi[14] == pytest.approx(70.464135, abs=1e-6)
    assert rsi[15] == pytest.approx(66.249619, abs=1e-6)
    assert wilder_rsi([100] * 20)[14:] == (50,) * 6
    assert wilder_rsi(range(1, 21))[14:] == (100,) * 6
    assert wilder_rsi(range(20, 0, -1))[14:] == (0,) * 6
