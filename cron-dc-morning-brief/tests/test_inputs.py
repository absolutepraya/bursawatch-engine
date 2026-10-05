import json
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from test_calendar_state import NOW, calendar_file


def test_csv_overlap_and_bytes_provenance(core):
    m=core('inputs'); path=Path(__file__).resolve().parents[2]/'docs/notes/references/konglo_tickers_arthara_2026-09-22.csv'
    membership=m.load_konglo_csv(path,version='arthara-2026-09-22', source_url='supplied-csv')
    assert len(membership.groups)==34
    assert len({s for members in membership.groups.values() for s in members})==188
    assert sum(map(len,membership.groups.values()))>188
    assert membership.ownership_as_of is None
    assert len(membership.provenance.digest)==64


def test_membership_and_caps_validate_retained_shape(core,tmp_path):
    m=core('inputs')
    path=tmp_path/'members.json'; path.write_text(json.dumps({'summary':{'checked_at':NOW.isoformat(),'complete_for_filter':True,'filter':'sector IS NOT NULL','total_count':2,'rows_collected':2,'failure':None,'counts':{'Energy':2}},'memberships':[{'symbol':'AAAA.JK','sector':'Energy'},{'symbol':'BBBB.JK','sector':'Energy'}]}))
    members=m.load_sector_membership(path,version='v1',official_check_reference='official-unavailable-ref',source_url='https://api.sectors.app/v1/companies/')
    assert members.groups=={'Energy':('AAAA','BBBB')}
    assert members.provenance.method=='official-first/sectors-idx-ic-fallback'
    data={'checked_at':NOW.isoformat(),'completed_at':NOW.isoformat(),'failure':None,'data':{'caps_0':{'results':[{'symbol':'AAAA.JK','query_values':{'market_cap':90}},{'symbol':'BBBB.JK','query_values':{'market_cap':10}}],'pagination':{'total_count':2,'showing':2,'limit':200,'offset':0,'has_next':False,'next_offset':None}}}}
    path=tmp_path/'caps.json'; path.write_text(json.dumps(data))
    cap=m.load_cap_snapshot(path,identity='caps:2026-W41',source_url='https://api.sectors.app/v1/companies/')
    assert cap.values=={'AAAA':90.0,'BBBB':10.0}
    assert cap.effective_date is None
    data['data']['caps_0']['results'][1]['symbol']='AAAA.JK';path.write_text(json.dumps(data))
    with pytest.raises(ValueError): m.load_cap_snapshot(path,identity='caps:2026-W41',source_url='sectors')


def test_caps_allow_current_or_one_extra_verified_week(core,tmp_path):
    m=core('inputs'); calmod=core('calendar')
    cal=calmod.SessionCalendar.from_file(calendar_file(tmp_path),expected_version='idx-2026-v2',expected_amendment='amend-2',as_of=NOW)
    provenance=m.Provenance('fixture','d'*64,'fixture','fixture')
    def cap(collected): return m.CapSnapshot('caps-v1',datetime.fromisoformat(collected),None,{'AAAA':100.},provenance)
    assert m.cap_status(cap('2026-09-29T01:00:00+00:00'),date(2026,10,6),cal)=='extra_week'
    assert m.cap_status(cap('2026-09-25T01:00:00+00:00'),date(2026,10,6),cal)=='expired'
    assert m.cap_status(cap('2026-10-06T01:00:00+00:00'),date(2026,10,7),cal)=='current_week'
    assert m.cap_status(cap('2026-10-07T01:00:00+00:00'),date(2026,10,6),cal)=='future'


def test_adjustment_never_double_applies_and_unresolved_excludes(core):
    m=core('inputs')
    # DSSA publicly sampled daily and bulk prices agree across the split.
    series=m.PriceSeries('DSSA',{'2026-04-08':2680.,'2026-04-09':3120.},'split_adjusted','sample-v1',True)
    action=m.ActionDecision('DSSA','split-2026-04-09','resolved','already_adjusted',30.,'sampled-daily-bulk-agreement')
    assert m.compatible_closes(series,[action])==series.closes
    with pytest.raises(ValueError): m.compatible_closes(series,[m.ActionDecision('DSSA','x','unresolved','unknown',None,'unknown')])
    raw=m.PriceSeries('DSSA',{'2026-04-08':80400.,'2026-04-09':3120.},'raw','raw-v1',True)
    split=m.ActionDecision('DSSA','x','resolved','adjust_raw',30.,'verified-split',effective_session='2026-04-09')
    assert m.compatible_closes(raw,[split])==series.closes
    with pytest.raises(ValueError): m.compatible_closes(series,[split])
    with pytest.raises(ValueError): m.compatible_closes(m.PriceSeries('DSSA',series.closes,'split_adjusted','v1',False),[action])


def test_typed_inputs_reject_unversioned_and_duplicate_action_evidence(core):
    m=core('inputs');p=m.Provenance('fixture','a'*64,'fixture','fixture')
    with pytest.raises(ValueError):m.CapSnapshot('',NOW,None,{'AAAA':1.},p)
    with pytest.raises(ValueError):m.CapSnapshot('v1',datetime(2026,10,5),None,{'AAAA':1.},p)
    series=m.PriceSeries('DSSA',{'2026-04-08':2680.,'2026-04-09':3120.},'split_adjusted','v1',True)
    split=m.ActionDecision('DSSA','split','resolved','already_adjusted',30.,'sample')
    with pytest.raises(ValueError):m.compatible_closes(series,[split,split])
    bad=m.PriceSeries('DSSA',{'2026-04-08':float('nan')},'split_adjusted','v1',True)
    with pytest.raises(ValueError):m.compatible_closes(bad,[])
    raw=m.PriceSeries('DSSA',series.closes,'raw','v1',True)
    with pytest.raises(ValueError):m.compatible_closes(raw,[])


def test_refresh_caps_only_on_first_verified_session_of_week(core,tmp_path):
    m=core('inputs');c=core('calendar').SessionCalendar.from_file(calendar_file(tmp_path),expected_version='idx-2026-v2',expected_amendment='amend-2',as_of=NOW)
    assert m.cap_refresh_due(date(2026,10,6),c)
    assert not m.cap_refresh_due(date(2026,10,7),c)
    assert not m.cap_refresh_due(date(2026,10,5),c)
    assert m.cap_refresh_due(date(2026,9,29),c)


def test_prepared_inputs_enforce_verified_window_and_frozen_provenance(core,tmp_path):
    m=core('inputs');calmod=core('calendar');r=core('rotation')
    from datetime import timedelta
    sessions=[(date(2026,9,1)+timedelta(days=n)).isoformat() for n in range(18)]
    path=calendar_file(tmp_path);payload=json.loads(path.read_text());payload['sessions']=sessions+payload['sessions'];payload['sessions']=sorted(set(payload['sessions']));path.write_text(json.dumps(payload))
    cal=calmod.SessionCalendar.from_file(path,expected_version='idx-2026-v2',expected_amendment='amend-2',as_of=NOW)
    provenance=m.Provenance('fixture','a'*64,'fixture','fixture')
    membership=m.MembershipSnapshot('members-v1',{'Energy':('AAAA',)},provenance)
    caps=m.CapSnapshot('caps-v1',datetime(2026,9,14,tzinfo=timezone.utc),None,{'AAAA':100.},provenance)
    prices={'AAAA':m.PriceSeries('AAAA',{s:100. for s in sessions},'split_adjusted','price-v1',True)}
    window=m.prepare_numerical_inputs(cal,membership,caps,prices,{s:100. for s in sessions},through=date(2026,9,18),freeze_at=NOW)
    result=r.calculate_from_inputs('Energy',window)
    assert result.provenance['membership']=='members-v1'
    assert result.provenance['calendar']=='idx-2026-v2'
    assert result.provenance['amendment']=='amend-2'
    assert result.provenance['membership_digest']=='a'*64
    assert len(window.sessions)==18
    with pytest.raises(m.InputUnavailable):m.prepare_numerical_inputs(cal,membership,caps,prices,{},through=date(2026,10,2),freeze_at=NOW)
    future=m.CapSnapshot('future',NOW+timedelta(days=1),None,{'AAAA':100.},provenance)
    with pytest.raises(m.InputUnavailable):m.prepare_numerical_inputs(cal,membership,future,prices,{},through=date(2026,9,18),freeze_at=NOW)
    with pytest.raises(m.InputUnavailable):m.prepare_numerical_inputs(cal,membership,caps,prices,{},through=date(2026,10,5),freeze_at=NOW)


def test_raw_split_cannot_be_applied_twice_under_different_ids(core):
    m=core('inputs')
    raw=m.PriceSeries('DSSA',{'2026-04-08':80400.,'2026-04-09':3120.},'raw','v1',True)
    actions=[m.ActionDecision('DSSA',identity,'resolved','adjust_raw',30.,'verified-split',effective_session='2026-04-09') for identity in ('source-one','source-two')]
    with pytest.raises(ValueError):m.compatible_closes(raw,actions)
