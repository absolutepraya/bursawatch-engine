from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from yahoo_market_data.rotation import parse_caps, parse_rotation_history


def history():
    sessions=tuple(date(2026,4,1)+timedelta(days=i) for i in range(18))
    stamps=[int(datetime(day.year,day.month,day.day,2,tzinfo=timezone.utc).timestamp()) for day in sessions]
    closes=[100.+i for i in range(18)]
    row=dict(meta=dict(symbol='DSSA.JK',exchangeTimezoneName='Asia/Jakarta',dataGranularity='1d',
        currency='IDR',instrumentType='EQUITY'),timestamp=stamps,
        indicators=dict(quote=[dict(open=closes,high=closes,low=closes,close=closes,volume=[1000]*18)],
                        adjclose=[dict(adjclose=[1.]*18)]),
        events=dict(splits={str(stamps[8]):dict(date=stamps[8],numerator=25.,denominator=1.,splitRatio='25:1')},
                    dividends={str(stamps[10]):dict(date=stamps[10],amount=3.)}))
    return dict(chart=dict(error=None,result=[row])),sessions


def test_ordinary_close_is_not_double_split_adjusted_or_dividend_adjusted():
    payload,sessions=history()
    parsed=parse_rotation_history(payload,symbol='DSSA.JK',sessions=sessions)
    assert parsed['closes'][sessions[0].isoformat()]==100.
    assert parsed['basis']=='split_adjusted' and parsed['trading_eligible'] is True
    assert {a['treatment'] for a in parsed['actions']}=={'already_adjusted','exclude_dividend'}
    assert next(a for a in parsed['actions'] if a['treatment']=='already_adjusted')['ratio']==25.


@pytest.mark.parametrize('change',[
    lambda r:r['indicators']['quote'][0]['volume'].__setitem__(5,0),
    lambda r:r['indicators']['quote'][0]['volume'].__setitem__(5,None),
    lambda r:r['indicators']['quote'][0]['close'].__setitem__(5,None),
    lambda r:r['events'].__setitem__('capitalGains',{}),
    lambda r:r['events']['splits'][next(iter(r['events']['splits']))].__setitem__('splitRatio','1:25'),
    lambda r:r['meta'].__setitem__('currency','USD'),
    lambda r:r['timestamp'].pop(),
])
def test_missing_trading_and_unresolved_action_evidence_rejects_stock(change):
    payload,sessions=history();change(payload['chart']['result'][0])
    with pytest.raises(ValueError):parse_rotation_history(payload,symbol='DSSA.JK',sessions=sessions)


def test_caps_keep_exact_native_missing_caps_missing_without_using_tradeable():
    row=dict(symbol='BBCA.JK',currency='IDR',quoteType='EQUITY',exchangeTimezoneName='Asia/Jakarta',
             marketCap=1000000000.,tradeable=False)
    payload=dict(quoteResponse=dict(error=None,result=[row,dict(row,symbol='DSSA.JK',marketCap=None)]))
    assert parse_caps(payload,symbols=['BBCA.JK','DSSA.JK','ABBA.JK'])=={'BBCA':1000000000.}
    wrong=deepcopy(payload);wrong['quoteResponse']['result'].append(dict(row))
    with pytest.raises(ValueError,match='duplicate'):parse_caps(wrong,symbols=['BBCA.JK','DSSA.JK','ABBA.JK'])
    wrong=deepcopy(payload);wrong['quoteResponse']['result'][0]['symbol']='AAPL'
    with pytest.raises(ValueError,match='unexpected'):parse_caps(wrong,symbols=['BBCA.JK','DSSA.JK'])
