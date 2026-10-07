from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys
import pytest
from PIL import Image, ImageFont

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'lib-chart-img/bin'))
from chart_img_client.models import RenderRequest, AsOfVerification, validate_image
from morning_brief.rotation import BasketResult, Position, quadrant, select_groups, unselected_letters


def baskets(count=34):
    rows=[]
    for i in range(count):
        x=(i%7-3)*.7+.12; y=(i//7-2)*.8+.13
        trail=tuple(Position(f'2026-09-{21+j:02}',x-.3+.075*j,y+.16-.04*j,quadrant(x-.3+.075*j,y+.16-.04*j)) for j in range(5))
        rows.append(BasketResult(f'Group {i:02} Full Name',trail,trail[-2].quadrant,i%3==0,.93,{'X':1.},{'Z':'missing'}, {},(),{'cap_snapshot':'fixture-cap','price_versions':{'X':'fixture-v'},'publication_session':'2026-10-05'}))
    return tuple(rows)


def chart():
    request=RenderRequest('fallback-v1','layout-v1','IDX:COMPOSITE','1D','3M',datetime(2026,10,5,tzinfo=timezone.utc),width=800,height=600)
    image=Image.new('RGB',(800,600),'white')
    image.putpixel((50,550),(150,20,70))  # Attribution sentinel stays untouched.
    stream=BytesIO();image.save(stream,format='PNG')
    artifact=validate_image(stream.getvalue(),'image/png',request,datetime(2026,10,5,tzinfo=timezone.utc))
    proof=AsOfVerification(artifact.sha256,request.identity,'2026-10-02',artifact.retrieved_at,'fixture-only','synthetic-fixture','3M')
    return artifact.with_verification(proof)


def test_rotation_geometry_coordinates_frozen_letters_and_assets(core):
    render=core('rendering'); rows=baskets(); letters=unselected_letters(rows,select_groups(rows))
    artifact=render.render_rotation(rows,kind='konglo',publication_session=date(2026,10,5),letters=letters)
    assert (artifact.width,artifact.height)==(5200,4800)
    assert artifact.sha256==sha256(artifact.data).hexdigest()
    assert Image.open(BytesIO(artifact.data)).format=='PNG'
    manifest=artifact.manifest
    assert manifest['plot_bounds']==[160,260,1420,1520]
    assert manifest['secondary_letters']==letters
    assert len(manifest['table_names'])==18
    assert set(manifest['groups'])=={r.name for r in rows}
    for row in rows:
        assert manifest['groups'][row.name]['coordinates']==[[p.session,p.x,p.y] for p in row.trail]
        assert manifest['groups'][row.name]['provenance']==row.provenance
        assert manifest['groups'][row.name]['coverage']==row.coverage
        assert manifest['groups'][row.name]['excluded']==row.excluded
    assert manifest['colors']['Improving']=='#78ACF2'
    assert manifest['trails_drawn']==[r.name for r in select_groups(rows)]
    assert all(0<=x0<x1<=2600 and 0<=y0<y1<=2400 for x0,y0,x1,y1 in manifest['text_bounds'])
    font=ImageFont.truetype(str(render.ASSETS/'HankenGrotesk-400.ttf'),24)
    assert font.getname()[0]=='Hanken Grotesk'
    assert 'SIL OPEN FONT LICENSE' in (render.ASSETS/'OFL.txt').read_text()
    assert manifest['asset_sha256'].keys()=={'font_regular','font_bold','logo','font_license'}
    assert render.render_rotation(rows,kind='konglo',publication_session=date(2026,10,5),letters=letters).data==artifact.data


def test_sectors_all_rows_and_neutral(core):
    rows=baskets(11)
    artifact=core('rendering').render_rotation(rows,kind='sectors',publication_session=date(2026,10,5))
    assert len(artifact.manifest['table_names'])==11
    assert artifact.manifest['secondary_letters']=={}
    neutral=replace(rows[0],trail=tuple(Position(p.session,0,p.y,'Neutral') for p in rows[0].trail))
    artifact=core('rendering').render_rotation((neutral,),kind='sectors',publication_session=date(2026,10,5))
    assert artifact.manifest['distribution']['Neutral']==1


def test_invalid_rotation_not_silently_relabelled(core):
    render=core('rendering'); rows=baskets()
    with pytest.raises(ValueError):render.render_rotation(rows,kind='konglo',publication_session=date(2026,10,5),letters={})
    with pytest.raises(ValueError):render.render_rotation(rows+rows[:1],kind='sectors',publication_session=date(2026,10,5))
    with pytest.raises(ValueError):render.render_rotation((replace(rows[0],trail=(Position('x',float('nan'),1,'Leading'),)),),kind='sectors',publication_session=date(2026,10,5))


def test_ihsg_entire_provider_panel_preserved(core):
    artifact=chart(); wrapped=core('rendering').render_ihsg(artifact,publication_session=date(2026,10,5),latest_close=date(2026,10,2))
    output=Image.open(BytesIO(wrapped.data)); bounds=wrapped.manifest['provider_bounds']
    assert output.crop(tuple(bounds)).tobytes()==Image.open(BytesIO(artifact.data)).convert('RGB').tobytes()
    assert wrapped.manifest['provider_sha256']==artifact.sha256
    assert wrapped.manifest['as_of']['evidence_ref']=='synthetic-fixture'
    assert wrapped.manifest['request_identity']==artifact.request.identity


@pytest.mark.parametrize('change',[{'verification':None},{'sha256':'0'*64},{'data':b'<html>error</html>'},{'content_type':'text/html'},{'verification':'fake'}])
def test_unsupported_ihsg_safe_omission_boundary(core,change):
    render=core('rendering')
    with pytest.raises(render.UnsupportedImage):render.render_ihsg(replace(chart(),**change),publication_session=date(2026,10,5),latest_close=date(2026,10,2))


def test_wrong_close_or_rebound_proof_rejected(core):
    render=core('rendering'); artifact=chart()
    with pytest.raises(render.UnsupportedImage):render.render_ihsg(artifact,publication_session=date(2026,10,5),latest_close=date(2026,10,1))
    proof=replace(artifact.verification,request_identity='1'*64)
    with pytest.raises(render.UnsupportedImage):render.render_ihsg(replace(artifact,verification=proof),publication_session=date(2026,10,5),latest_close=date(2026,10,2))


def test_long_full_names_wrap_in_labels_and_table(core):
    rows=tuple(replace(row,name='Properties and Real Estate '+row.name) for row in baskets(11))
    artifact=core('rendering').render_rotation(rows,kind='sectors',publication_session=date(2026,10,5))
    assert artifact.manifest['table_names']
    assert any('\n' in item['label'] for item in artifact.manifest['labels'])
    assert all(item['label'].replace('\n',' ')==item['name'] for item in artifact.manifest['labels'])


def test_ihsg_native_width_with_reviewed_padding(core):
    wrapped=core('rendering').render_ihsg(chart(),publication_session=date(2026,10,5),latest_close=date(2026,10,2))
    assert wrapped.width==800+160
    assert wrapped.manifest['provider_bounds']==[80,240,880,840]


def test_chart_cutoff_must_match_frozen_publication(core):
    render=core('rendering'); artifact=chart()
    changed=replace(artifact.request,cutoff=datetime(2026,10,6,tzinfo=timezone.utc))
    proof=replace(artifact.verification,request_identity=changed.identity)
    with pytest.raises(render.UnsupportedImage):render.render_ihsg(replace(artifact,request=changed,verification=proof),publication_session=date(2026,10,5),latest_close=date(2026,10,2))


def test_render_manifest_detaches_caller_provenance(core):
    rows=baskets(1)
    artifact=core('rendering').render_rotation(rows,kind='sectors',publication_session=date(2026,10,5))
    rows[0].provenance['price_versions']['X']='mutated'
    assert artifact.manifest['groups'][rows[0].name]['provenance']['price_versions']['X']=='fixture-v'


def test_tiny_partial_coverage_and_stale_caps_are_visible(core):
    rows=(replace(baskets(1)[0],coverage=.0183,excluded={'ZZZZ':'missing_price_series'},
        provenance={'cap_collection_status':'stale','missing_cap_members':('YYYY',),'cap_collected_at':'2026-08-01T07:00:00+07:00'}),)
    artifact=core('rendering').render_rotation(rows,kind='sectors',publication_session=date(2026,10,5))
    assert artifact.manifest['groups'][rows[0].name]['coverage']==.0183
    from morning_brief.formatting import _rotation_text
    text=_rotation_text(rows,'Rotasi Sektor ',date(2026,10,5),[])
    assert 'Basket parsial' in text and '1.8%' in text and '(stale)' in text
    assert '1 cap tidak tersedia' in text


def test_visual_curves_interpolate_observations_without_segment_overshoot(core):
    smooth=core('rendering')._smooth_trail
    points=[(0.,0.),(1.,4.),(2.,1.),(2.,1.),(-3.,-2.)]
    curve=smooth(points)
    assert curve[::48]==points
    for i,(a,b) in enumerate(zip(points,points[1:])):
        for p in curve[i*48:(i+1)*48+1]:
            for axis in (0,1):
                assert min(a[axis],b[axis])-1e-12<=p[axis]<=max(a[axis],b[axis])+1e-12
    assert any(p[1]!=pytest.approx(4*p[0]) for p in curve[1:48])


def test_crowded_konglo_zoom_codes_and_full_range_preserve_observations(core):
    rows=list(baskets())
    for i,row in enumerate(rows):
        x=(i%6-3)*.05;y=(i//6-3)*.04
        rows[i]=replace(row,trail=tuple(Position(p.session,x,y,quadrant(x,y)) for p in row.trail))
    # A distant observed trail point must not compress the zoom or disappear.
    row=rows[0];rows[0]=replace(row,changed_quadrant=True,
        trail=(replace(row.trail[0],x=80,y=90,quadrant='Leading'),)+row.trail[1:])
    letters=unselected_letters(rows,select_groups(rows));render=core('rendering')
    artifact=render.render_rotation(rows,kind='konglo',publication_session=date(2026,10,5),letters=letters)
    m=artifact.manifest
    assert m['axis_limits']['x'][1]==81.
    assert m['axis_limits']['y'][1]==91.
    assert m['central_zoom']['x_extent']==m['central_zoom']['y_extent']==1.
    assert len(m['central_zoom']['names'])==34
    assert m['central_zoom']['bounds'][1]>m['plot_bounds'][3]
    assert m['secondary_letters']==letters
    assert len(set(m['marker_codes'].values()))==34
    for i,name in enumerate(m['table_names']):assert m['marker_codes'][name]==str(i+1)
    for label in m['labels']:assert label['label']==m['marker_codes'][label['name']]
    for row in rows:
        assert m['groups'][row.name]['coordinates']==[[p.session,p.x,p.y] for p in row.trail]
    for labels in (m['labels'],m['central_zoom']['labels']):
        for i,label in enumerate(labels):
            assert not any(render._intersects(label['bounds'],other['bounds']) for other in labels[i+1:])
    reversed_artifact=render.render_rotation(list(reversed(rows)),kind='konglo',publication_session=date(2026,10,5),letters=letters)
    assert artifact.data==reversed_artifact.data


def test_zoom_discloses_outside_groups_and_sector_layout_stays_named(core):
    rows=list(baskets(11));row=rows[0]
    rows[0]=replace(row,trail=tuple(replace(p,x=100,y=100,quadrant='Leading') for p in row.trail))
    render=core('rendering');letters=unselected_letters(rows,select_groups(rows))
    zoom=render.render_rotation(rows,kind='konglo',publication_session=date(2026,10,5),letters=letters).manifest['central_zoom']
    assert rows[0].name in zoom['outside_names'] and rows[0].name not in zoom['names']
    artifact=render.render_rotation(rows,kind='sectors',publication_session=date(2026,10,5))
    assert (artifact.width,artifact.height)==(5200,3320)
    assert artifact.manifest['central_zoom'] is None
    assert all(label['label'].replace('\n',' ')==label['name'] for label in artifact.manifest['labels'])


def test_asymmetric_ranges_include_drawn_history_and_reposition_zero(core):
    render=core('rendering');row=baskets(1)[0]
    values=[(-14.8,-30.2),(19.,25.3),(2.,1.),(3.,2.),(4.,3.)]
    row=replace(row,trail=tuple(Position(p.session,x,y,quadrant(x,y)) for p,(x,y) in zip(row.trail,values)))
    artifact=render.render_rotation((row,),kind='sectors',publication_session=date(2026,10,5))
    m=artifact.manifest
    assert m['axis_limits']=={'x':[-15.8,20.],'y':[-31.2,26.3]}
    left,top,right,bottom=m['plot_bounds'];zx,zy=m['zero_pixel']
    assert zx==pytest.approx(left+15.8/35.8*(right-left))
    assert zy==pytest.approx(top+26.3/57.5*(bottom-top))
    assert zx!=(left+right)/2 and zy!=(top+bottom)/2
    assert m['groups'][row.name]['coordinates']==[[p.session,p.x,p.y] for p in row.trail]
    x,y=m['labels'][0]['latest_pixel']
    assert x==pytest.approx(left+(4.+15.8)/35.8*(right-left))
    assert y==pytest.approx(bottom-(3.+31.2)/57.5*(bottom-top))
    assert m['pixel_ratio']==2 and m['logical_dimensions']==[2600,1660]
    assert m['coordinate_space']=='logical-pixels'
    assert len(artifact.data)<25*1024*1024


def test_one_sided_data_shrinks_empty_quadrants_and_draws_native_type(core,monkeypatch):
    render=core('rendering');row=baskets(1)[0]
    row=replace(row,trail=tuple(Position(p.session,10.+i,20.+i,'Leading') for i,p in enumerate(row.trail)))
    sizes=[];original=render._font
    def font(size,bold=False):
        sizes.append(size);return original(size,bold)
    monkeypatch.setattr(render,'_font',font)
    artifact=render.render_rotation((row,),kind='sectors',publication_session=date(2026,10,5))
    m=artifact.manifest
    assert m['axis_limits']=={'x':[-1.,15.],'y':[-1.,25.]}
    assert 52 in sizes # Label glyphs are drawn at 2x, not resized afterwards.
    image=Image.open(BytesIO(artifact.data));left,top,right,bottom=m['plot_bounds'];zx,zy=m['zero_pixel']
    green_pixel=(round((zx+right)/2*2),round((top+zy)/2*2))
    assert image.getpixel(green_pixel)==tuple(int(render.FILLS['Leading'][i:i+2],16) for i in (1,3,5))
    assert m['distribution']['Leading']==1
    assert zx-left<(right-left)/10 and bottom-zy<(bottom-top)/10
