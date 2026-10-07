from datetime import date, timedelta
from copy import deepcopy
import pytest
from yahoo_market_data import close_performance, parse_closes


def history():
    sessions=tuple(date(2026,1,1)+timedelta(days=i) for i in range(70))
    closes={day.isoformat():1000+i*10 for i,day in enumerate(sessions)}
    return sessions,closes


def test_explicit_session_offsets_and_correct_denominators():
    days,closes=history();result=close_performance(closes,sessions=days,through=days[-1])
    assert result['latest_price']==1690 and result['one_day_change']==10 and result['one_week_change']==50
    assert result['one_month_change']==220 and result['three_month_change']==660
    assert result['three_month_percent']==pytest.approx(100*660/1030)


def test_missing_anchor_does_not_slide_to_another_day_or_hide_other_horizons():
    days,closes=history();closes[days[-23].isoformat()]=None
    result=close_performance(closes,sessions=days,through=days[-1])
    assert result['one_month_change'] is None and result['one_month_percent'] is None
    assert result['one_week_change']==50 and result['three_month_change']==660
    short=close_performance(closes,sessions=days[-3:],through=days[-1])
    assert short['one_day_change']==10 and short['one_week_change'] is None


@pytest.mark.parametrize('value',[None,0,-1,float('nan'),float('inf'),True])
def test_invalid_latest_price_never_fabricates_changes(value):
    days,closes=history();closes[days[-1].isoformat()]=value
    result=close_performance(closes,sessions=days,through=days[-1])
    assert result['latest_price'] is None and all(result[k] is None for k in result if k.endswith(('_change','_percent')))


def test_closes_parser_retains_missing_calendar_positions_and_ordinary_close():
    days=(date(2026,10,1),date(2026,10,2),date(2026,10,5))
    stamps=[int(__import__('datetime').datetime.combine(d,__import__('datetime').time(2),__import__('datetime').timezone.utc).timestamp()) for d in days]
    payload={'chart':{'error':None,'result':[{'meta':{'symbol':'^JKSE','exchangeTimezoneName':'Asia/Jakarta','dataGranularity':'1d'},'timestamp':stamps,'indicators':{'quote':[{'close':[100,None,102]}],'adjclose':[{'adjclose':[999,999,999]}]}}]}}
    values=parse_closes(payload,symbol='^JKSE',exchange_timezone='Asia/Jakarta',through=days[-1],session_dates=days)
    assert values=={'2026-10-01':100.,'2026-10-02':None,'2026-10-05':102.}
    assert close_performance(values,sessions=days,through=days[-1])['one_day_change'] is None
    bad=deepcopy(payload);bad['chart']['result'][0]['timestamp'][1]=stamps[0]
    with pytest.raises(ValueError):parse_closes(bad,symbol='^JKSE',exchange_timezone='Asia/Jakarta',through=days[-1],session_dates=days)
