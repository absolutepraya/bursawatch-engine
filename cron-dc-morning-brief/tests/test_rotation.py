from datetime import date,timedelta,datetime,timezone
import pytest


def fixture(core, missing=False, caps=(90.,10.)):
    i=core('inputs'); r=core('rotation')
    sessions=tuple(date(2026,9,1)+timedelta(days=n) for n in range(18)) # explicit synthetic analytical sessions
    prov=i.Provenance('analytical','a'*64,'fixture','analytical')
    snapshot=i.CapSnapshot('cap-v1',datetime(2026,9,1,tzinfo=timezone.utc),None,dict(zip(('AAAA','BBBB'),caps)),prov)
    closes_a={s.isoformat():100.*1.01**n for n,s in enumerate(sessions)}
    closes_b={s.isoformat():100. for s in sessions}
    if missing: del closes_b[sessions[2].isoformat()]
    series={'AAAA':i.PriceSeries('AAAA',closes_a,'split_adjusted','a-v1',True),'BBBB':i.PriceSeries('BBBB',closes_b,'split_adjusted','b-v1',True)}
    benchmark={s.isoformat():100. for s in sessions}
    return r,sessions,snapshot,series,benchmark


def test_fixed_weights_compound_ten_sessions_and_five_positions(core):
    r,s,c,p,b=fixture(core)
    result=r.calculate_basket('Fixture',('BBBB','AAAA'),c,p,b,s,provenance={'calendar':'cal-v1','amendment':'amend-v1','membership':'members-v1'})
    assert len(result.trail)==5
    # Hand-independent: each day 90%*1% +10%*0%=0.9%, ten days -> 9.373387280252646%.
    assert result.trail[-1].x==pytest.approx(9.373387280252646)
    assert result.trail[-1].y==pytest.approx(0.,abs=1e-10)
    assert result.weights=={'AAAA':.9,'BBBB':.1}
    assert result.coverage==1.
    assert result.provenance['cap_snapshot']=='cap-v1'
    assert result.provenance['calendar']=='cal-v1'
    assert result.provenance['price_versions']=={'AAAA':'a-v1','BBBB':'b-v1'}
    shuffled=r.calculate_basket('Fixture',('AAAA','BBBB'),c,dict(reversed(list(p.items()))),b,s,provenance={'calendar':'cal-v1','amendment':'amend-v1','membership':'members-v1'})
    assert result==shuffled
    with pytest.raises(ValueError): r.calculate_basket('Fixture',('AAAA','BBBB'),c,p,b,s[:-1],provenance={})


def test_partial_coverage_and_unknown_caps_preserve_exclusions(core):
    r,s,c,p,b=fixture(core,missing=True)
    result=r.calculate_basket('Fixture',('AAAA','BBBB'),c,p,b,s,provenance={})
    assert result.coverage==.9
    assert result.weights=={'AAAA':1.}
    assert result.excluded['BBBB']=='missing_session'
    assert result.trail[-1].x==pytest.approx(10.46221254112045)
    r,s,c,p,b=fixture(core,missing=True,caps=(89.9,10.1))
    result=r.calculate_basket('Fixture',('AAAA','BBBB'),c,p,b,s,provenance={})
    assert result.coverage==pytest.approx(.899)
    assert result.weights=={'AAAA':1.}
    del c.values['BBBB']
    result=r.calculate_basket('Fixture',('AAAA','BBBB'),c,p,b,s,provenance={})
    assert result.coverage==1.
    assert result.excluded=={'BBBB':'missing_or_invalid_cap'}
    assert result.provenance['missing_cap_members']==('BBBB',)
    p.clear()
    with pytest.raises(r.UnsupportedBasket):r.calculate_basket('Fixture',('AAAA','BBBB'),c,p,b,s,provenance={})


def test_compounding_axes_changes_and_quadrants(core):
    r,s,c,p,b=fixture(core,caps=(100.,0.))
    # Replace caps with one member and a final 10% jump; flat index.
    c.values.pop('BBBB');p.pop('BBBB')
    for key in p['AAAA'].closes:p['AAAA'].closes[key]=100.
    p['AAAA'].closes[s[-1].isoformat()]=110.
    result=r.calculate_basket('One',('AAAA',),c,p,b,s,provenance={})
    assert [t.x for t in result.trail]==pytest.approx([0,0,0,0,10.])
    assert result.trail[-1].y==pytest.approx(10.)
    assert result.trail[-1].quadrant=='Leading'
    assert result.previous_quadrant=='Neutral'
    assert result.changed_quadrant
    assert [r.quadrant(x,y) for x,y in [(1,1),(-1,1),(1,-1),(-1,-1),(0,1),(1,0)]]==['Leading','Improving','Weakening','Lagging','Neutral','Neutral']


def test_selection_table_sort_and_unselected_alphabetic_letters(core):
    r=core('rotation')
    def row(name,x,y,changed=False):return r.GroupRanking(name,x,y,r.quadrant(x,y),changed)
    rows=[row('Alpha',20.,1.),row('Beta',-3.,9.),row('Changed',-4.,.1,True),row('Neutral',0.,0.)]
    assert [v.name for v in r.select_groups(rows,limit=2)]==['Changed','Beta']
    assert [v.name for v in r.table_order(rows)]==['Alpha','Beta','Changed','Neutral']
    rows=[row('Group '+str(n).zfill(2),float(n+1),1.) for n in range(34)]
    selected=r.select_groups(rows)
    assert len(selected)==18
    mapping=r.unselected_letters(rows,selected)
    assert list(mapping.values())==list('ABCDEFGHIJKLMNOP')
    assert r.unselected_letters(list(reversed(rows)),selected)==mapping


def test_all_five_positions_use_ten_day_return_and_three_session_momentum(core):
    r,s,c,p,b=fixture(core)
    c.values.pop('BBBB');p.pop('BBBB')
    # Independent piecewise levels: jump 100 to 110 at level 11,
    # then 110 to 99 at level 17. X(10)=0, X(11..16)=10, X(17)=-1.
    for n,key in enumerate(p['AAAA'].closes):
        p['AAAA'].closes[key]=100. if n<11 else (99. if n==17 else 110.)
    result=r.calculate_basket('One',('AAAA',),c,p,b,s,provenance={'mode':'synthetic_preview'})
    assert [v.x for v in result.trail]==pytest.approx([10.,10.,10.,10.,-1.])
    assert [v.y for v in result.trail]==pytest.approx([10.,0.,0.,0.,-11.])
    assert [v.quadrant for v in result.trail]==['Leading','Neutral','Neutral','Neutral','Lagging']
    # Small nonzero coordinates still belong to a quadrant.
    assert r.quadrant(1e-13,-1e-13)=='Weakening'


def test_excludes_unresolved_action_without_changing_original_denominator(core):
    r,s,c,p,b=fixture(core)
    i=core('inputs')
    decision=i.ActionDecision('BBBB','uncertain-split','unresolved','unknown',None,'unverified')
    result=r.calculate_basket('One',('AAAA','BBBB'),c,p,b,s,provenance={},actions=(decision,))
    assert result.coverage==.9
    assert result.excluded=={'BBBB':'unresolved_action_or_eligibility'}
    assert result.provenance['action_identities']==('uncertain-split',)
    assert result.action_decisions==(decision,)
    del b[s[0].isoformat()]
    with pytest.raises(r.UnsupportedBasket):r.calculate_basket('One',('AAAA','BBBB'),c,p,b,s,provenance={})


def test_calculated_nonzero_axes_are_not_rounded_into_neutral(core):
    r,s,c,p,b=fixture(core)
    c.values.pop('BBBB');p.pop('BBBB')
    for key in p['AAAA'].closes:p['AAAA'].closes[key]=100.
    p['AAAA'].closes[s[-1].isoformat()]=100.00000000000001
    result=r.calculate_basket('Tiny',('AAAA',),c,p,b,s,provenance={})
    assert result.x>0 and result.y>0
    assert result.quadrant=='Leading'
