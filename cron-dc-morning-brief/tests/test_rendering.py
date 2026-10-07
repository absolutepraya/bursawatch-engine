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
    assert (artifact.width,artifact.height)==(2600,1660)
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
    assert all(0<=x0<x1<=2600 and 0<=y0<y1<=1660 for x0,y0,x1,y1 in manifest['text_bounds'])
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
