"""Pure local branded composition. No provider retrieval or numerical smoothing."""
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
from .rotation import quadrant, select_groups, table_order, unselected_letters

ASSETS = Path(__file__).parent/'assets'
REVISION = 'bursawatch-render-v1'
BG, PANEL, GOLD, FG, MUTED = '#111311', '#1C1F1D', '#DEA777', '#EEEAE3', '#9C978E'
COLORS = {'Leading':'#2EE65F','Improving':'#78ACF2','Weakening':'#F0BE91','Lagging':'#F23F43','Neutral':MUTED}
FILLS = {'Leading':'#17271D','Improving':'#19232F','Weakening':'#2B241C','Lagging':'#2A1C20'}


class UnsupportedImage(ValueError):
    """Caller records an explicit omission and continues text publication."""


@dataclass(frozen=True)
class RenderedArtifact:
    data: bytes
    content_type: str
    sha256: str
    width: int
    height: int
    manifest: dict


def publication_label(session: date) -> str:
    if type(session) is not date:
        raise ValueError('publication date required')
    days=('Mon','Tue','Wed','Thu','Fri','Sat','Sun')
    months=('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
    return f'{days[session.weekday()]}, {session.day} {months[session.month-1]} {session.year}'


def _font(size, bold=False):
    return ImageFont.truetype(str(ASSETS/('HankenGrotesk-700.ttf' if bold else 'HankenGrotesk-400.ttf')),size)


class _Canvas:
    def __init__(self,width,height):
        self.image=Image.new('RGB',(width,height),BG)
        self.draw=ImageDraw.Draw(self.image)
        self.bounds=[]

    def text(self,x,y,value,size=24,color=FG,bold=False,anchor='lt'):
        font=_font(size,bold)
        if '\n' in value:
            if anchor!='lt':raise ValueError('multiline text requires left alignment')
            anchor='la'
            offset=self.draw.multiline_textbbox((0,0),value,font=font,anchor=anchor,spacing=2)
            x-=offset[0];y-=offset[1]
        bounds=self.draw.textbbox((x,y),value,font=font,anchor=anchor,spacing=2)
        if not (0<=bounds[0]<bounds[2]<=self.image.width and 0<=bounds[1]<bounds[3]<=self.image.height):
            raise ValueError('text exceeds composition bounds')
        self.draw.text((x,y),value,font=font,fill=color,anchor=anchor,spacing=2)
        self.bounds.append(list(bounds))
        return bounds

    def fitted(self,x,y,value,width,height,size=24,bold=False,color=FG):
        for candidate in range(size,13,-1):
            wrapped=_wrap(value,width,_font(candidate,bold))
            bounds=self.draw.multiline_textbbox((0,0),wrapped,font=_font(candidate,bold),spacing=2)
            if bounds[2]<=width and bounds[3]<=height:
                return self.text(x,y,wrapped,candidate,color,bold)
        raise ValueError('name exceeds readable table bounds')


def _wrap(value,width,font):
    lines=[];line=''
    for word in value.split():
        combined=(line+' '+word).strip()
        if font.getlength(combined)>width and line:
            lines.append(line);line=word
        else:line=combined
    lines.append(line)
    return '\n'.join(lines)


def _logo(canvas,x,y,size=52):
    # The packaged supplied SVG has only absolute M/H/V/L/C/Z paths and one
    # translate(-2 -2) group. Sample its cubic Beziers, never market trails.
    for node in ET.parse(ASSETS/'bursawatch.svg').getroot().iter():
        if not node.tag.endswith('path'):continue
        tokens=re.findall(r'[A-Za-z]|-?\d+(?:\.\d+)?',node.attrib['d'])
        points=[];index=0;px=py=0
        while index<len(tokens):
            command=tokens[index];index+=1
            count={'M':2,'L':2,'H':1,'V':1,'C':6,'Z':0}[command]
            values=list(map(float,tokens[index:index+count]));index+=count
            if command in ('M','L'):px,py=values;points.append((px,py))
            elif command=='H':px=values[0];points.append((px,py))
            elif command=='V':py=values[0];points.append((px,py))
            elif command=='C':
                x0,y0=px,py;x1,y1,x2,y2,px,py=values
                for n in range(1,25):
                    t=n/24;u=1-t
                    points.append((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*px,u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*py))
            elif command=='Z':pass
        canvas.draw.polygon([(x+(a-2)*size/96,y+(b-2)*size/96) for a,b in points],fill='#DDA778')


def _header(canvas,title,session):
    width=canvas.image.width
    scale=min(1.,width/1600)
    canvas.text(80,88,title,round(54*scale),FG,True)
    canvas.text(82,161,publication_label(session),max(18,round(25*scale)),MUTED)
    _logo(canvas,width-80-round(270*scale),87,round(52*scale))
    canvas.text(width-80,94,'Bursawatch',round(40*scale),GOLD,True,anchor='rt')


def _artifact(canvas,manifest):
    output=BytesIO();canvas.image.save(output,format='PNG')
    data=output.getvalue()
    manifest.update(renderer_revision=REVISION,text_bounds=canvas.bounds,
                    asset_sha256={key:sha256((ASSETS/name).read_bytes()).hexdigest() for key,name in
                                  [('font_regular','HankenGrotesk-400.ttf'),('font_bold','HankenGrotesk-700.ttf'),('logo','bursawatch.svg'),('font_license','OFL.txt')]})
    # Detach caller-owned nested dictionaries and verify the freeze-ready shape.
    manifest=json.loads(json.dumps(manifest,sort_keys=True,allow_nan=False))
    return RenderedArtifact(data,'image/png',sha256(data).hexdigest(),canvas.image.width,canvas.image.height,manifest)


def _intersects(a,b):
    return a[0]<b[2]+7 and a[2]+7>b[0] and a[1]<b[3]+7 and a[3]+7>b[1]


def render_rotation(groups, *, kind: str, publication_session: date, letters=None) -> RenderedArtifact:
    """Render validated BasketResults without modifying their observed positions.

    Konglo letters are mandatory frozen owner inputs, checked against upstream
    alphabetical mapping. Labels/leaders are display geometry, never trail data.
    The artifact manifest is JSON-compatible and must be frozen by the caller.
    """
    publication_label(publication_session)
    groups=tuple(groups)
    if kind not in ('sectors','konglo') or not groups or len(groups)>(18 if kind=='sectors' else 34):
        raise ValueError('bounded qualifying groups and known rotation kind required')
    selected=groups if kind=='sectors' else select_groups(groups)
    ordered=table_order(selected)
    expected={} if kind=='sectors' else unselected_letters(groups,selected)
    if (letters or {})!=expected or (kind=='konglo' and letters is None):
        raise ValueError('frozen secondary letters mismatch')
    sessions=None
    for row in groups:
        if len(row.trail)!=5 or not row.name or len(row.name)>180 or not math.isfinite(row.coverage) or not .9<=row.coverage<=1:
            raise ValueError('five positions and qualifying coverage required')
        current=tuple(p.session for p in row.trail)
        if current!=tuple(sorted(set(current))) or (sessions is not None and current!=sessions):
            raise ValueError('consistent ordered trail sessions required')
        for position in row.trail:
            date.fromisoformat(position.session)
            if position.quadrant!=quadrant(position.x,position.y):raise ValueError('position quadrant mismatch')
        sessions=current
    chosen={r.name for r in selected}
    visible=[p for r in groups for p in (r.trail if r.name in chosen else r.trail[-1:])]
    extent=max(1.,max(max(abs(p.x),abs(p.y)) for p in visible)*1.22)
    canvas=_Canvas(2600,1660);_header(canvas,'Rotasi Sektor' if kind=='sectors' else 'Rotasi Konglo',publication_session)
    left,top,size=160,260,1260
    plot=Image.new('RGB',(size,size),BG);draw=ImageDraw.Draw(plot)
    for box,q in [((0,0,630,630),'Improving'),((630,0,1260,630),'Leading'),((0,630,630,1260),'Lagging'),((630,630,1260,1260),'Weakening')]:
        draw.rectangle(box,fill=FILLS[q])
    draw.line((0,630,1260,630),fill='#655D51',width=2);draw.line((630,0,630,1260),fill='#655D51',width=2)
    mask=Image.new('L',(size,size));ImageDraw.Draw(mask).rounded_rectangle((0,0,size-1,size-1),radius=20,fill=255)
    canvas.image.paste(plot,(left,top),mask)
    def point(position):return (left+size/2+size*position.x/(2*extent),top+size/2-size*position.y/(2*extent))
    plotted={};labels=[]
    occupied=[(160,260,420,310),(1140,260,1420,310),(160,1470,420,1520),(1140,1470,1420,1520)]
    for row in sorted(groups,key=lambda r:(r.name not in chosen,r.name)):
        xy=[point(p) for p in row.trail];x,y=xy[-1];color=COLORS[row.quadrant]
        if row.name in chosen:
            canvas.draw.line(xy,fill=color,width=3)
            for n,(hx,hy) in enumerate(xy[:-1]):canvas.draw.ellipse((hx-3-n,hy-3-n,hx+3+n,hy+3+n),fill=color)
            # An arrow follows only the actual final segment, without adding points.
            dx,dy=x-xy[-2][0],y-xy[-2][1];length=math.hypot(dx,dy)
            if length>0:
                ux,uy=dx/length,dy/length
                head=min(14,length/2)
                canvas.draw.polygon([(x,y),(x-ux*head-uy*5,y-uy*head+ux*5),(x-ux*head+uy*5,y-uy*head-ux*5)],fill=color)
        radius=7 if row.name in chosen else 5
        canvas.draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color,outline=BG,width=2)
        label=_wrap(row.name,220,_font(23,True)) if row.name in chosen else expected[row.name]
        label_size=23 if row.name in chosen else 21
        bounds=canvas.draw.multiline_textbbox((0,0),label,font=_font(label_size,True),spacing=2)
        width,height=bounds[2],bounds[3]
        candidates=[]
        for distance in (12,35,65,100,145,210,280,360,450):
            for dx,dy in ((distance,-height-8),(distance,8),(-width-distance,-height-8),(-width-distance,8),(-width/2,-height-distance),(-width/2,distance)):
                bx=min(max(left+8,x+dx),left+size-width-8);by=min(max(top+55,y+dy),top+size-height-55)
                candidates.append((bx,by,bx+width,by+height))
        box=next((b for b in candidates if not any(_intersects(b,other) for other in occupied)),None)
        if box is None:raise ValueError('collision-free labels unavailable; omit unsupported visual')
        occupied.append(box)
        if abs(box[0]-x)>18 or abs(box[1]-y)>18:
            endpoint=(min(max(x,box[0]),box[2]),min(max(y,box[1]),box[3]))
            canvas.draw.line(((x,y),endpoint),fill=MUTED,width=1)
        canvas.text(box[0],box[1],label,label_size,FG if row.name in chosen else '#BDB9B1',True)
        plotted[row.name]=[[p.session,p.x,p.y] for p in row.trail]
        labels.append({'name':row.name,'label':label,'bounds':list(box),'latest_pixel':[x,y]})
    for x,y,q in [(180,278,'Improving'),(1400,278,'Leading'),(180,1475,'Lagging'),(1400,1475,'Weakening')]:
        canvas.text(x,y,q,28,COLORS[q],True,anchor='rt' if x==1400 else 'lt')
    canvas.draw.rounded_rectangle((left,top,left+size,top+size),radius=20,outline=GOLD,width=3)
    for value in (-extent,-extent/2,0,extent/2,extent):
        x=left+size/2+size*value/(2*extent);y=top+size/2-size*value/(2*extent)
        canvas.text(x,1536,f'{value:.1f}',22,MUTED,anchor='mt')
        canvas.text(145,y,f'{value:.1f}',22,MUTED,anchor='rm')
    canvas.text(790,1580,'Kekuatan relatif terhadap IHSG (pp)',28,MUTED,anchor='mt')
    # Rotate the Y-axis label outside the plot.
    label=Image.new('RGBA',(600,40));ImageDraw.Draw(label).text((0,0),'Momentum relatif (pp)',font=_font(28),fill=MUTED)
    canvas.image.paste(label.rotate(90,expand=True),(65,650),label.rotate(90,expand=True))
    canvas.draw.ellipse((787,887,793,893),fill=MUTED)
    canvas.text(802,899,'IHSG',18,MUTED)
    distribution={q:sum(r.quadrant==q for r in groups) for q in COLORS}
    canvas.text(1500,260,'DISTRIBUSI',22,MUTED,True)
    for i,q in enumerate(FILLS):
        x=1500+i*259
        canvas.draw.rounded_rectangle((x,307,x+243,425),radius=14,fill=FILLS[q])
        canvas.text(x+20,327,q,25,COLORS[q],True);canvas.text(x+20,367,str(distribution[q]),37,FG,True)
    if distribution['Neutral']:canvas.text(1500,447,f"Neutral: {distribution['Neutral']}",22,MUTED)
    canvas.text(1500,514,'SOROTAN SEKTOR' if kind=='sectors' else 'SOROTAN KONGLO',22,MUTED,True)
    for x,value in zip((1520,1950,2180,2370),('Kelompok','Kuadran','Kekuatan (pp)','Momentum (pp)')):canvas.text(x,568,value,19,MUTED,True)
    row_height=40 if kind=='konglo' else min(68,720//len(ordered))
    for i,row in enumerate(ordered):
        y=626+i*row_height
        if i%2==0:canvas.draw.rounded_rectangle((1500,y-8,2520,y+row_height-9),radius=7,fill=PANEL)
        canvas.fitted(1520,y,row.name,400,row_height-3,22,True)
        canvas.text(1950,y,row.quadrant,22,COLORS[row.quadrant])
        canvas.text(2180,y,f'{row.x:+.2f}',22);canvas.text(2370,y,f'{row.y:+.2f}',22)
    if expected:
        canvas.text(1500,1367,'KELOMPOK LAIN',19,MUTED,True)
        for i,(name,letter) in enumerate(sorted(expected.items(),key=lambda pair:pair[1])):
            col=i//8;line=i%8;x=1500+col*520;y=1412+line*27
            canvas.text(x+12,y,letter,20,COLORS[next(r.quadrant for r in groups if r.name==name)],True)
            canvas.fitted(x+48,y,name,460,26,18,color=MUTED)
    manifest=dict(kind=kind,publication_session=publication_session.isoformat(),trail_sessions=list(sessions),
                  plot_bounds=[160,260,1420,1520],axis_extent=extent,colors=COLORS.copy(),distribution=distribution,
                  selection_names=[r.name for r in selected],table_names=[r.name for r in ordered],
                  secondary_letters=dict(expected),trails_drawn=[r.name for r in selected],labels=labels,
                  groups={r.name:dict(coordinates=plotted[r.name],coverage=r.coverage,excluded=dict(r.excluded),
                                     weights=dict(r.weights),aligned_closes=r.aligned_closes,
                                     action_decisions=[asdict(a) for a in r.action_decisions],provenance=dict(r.provenance)) for r in groups})
    return _artifact(canvas,manifest)


def render_ihsg(image, *, publication_session: date, latest_close: date) -> RenderedArtifact:
    """Wrap an externally attested chart at native size, retaining every pixel.

    Matching request/proof fields are necessary, never independent chart or
    indicator validation. The caller owns approved profile/window and rights gates.
    """
    from chart_img_client.models import validate_image
    publication_label(publication_session)
    try:
        checked=validate_image(image.data,image.content_type,image.request,image.retrieved_at)
        if (checked.sha256!=image.sha256 or (image.format,image.width,image.height)!=(checked.format,checked.width,checked.height)):
            raise ValueError('artifact mismatch')
        checked=checked.with_verification(image.verification)
        cutoff=checked.request.cutoff.astimezone(ZoneInfo('Asia/Jakarta'))
        if (date.fromisoformat(checked.verification.last_bar_date)!=latest_close or latest_close>=publication_session
                or cutoff.date()!=publication_session
                or checked.request.symbol!='IDX:COMPOSITE' or checked.request.interval!='1D'
                or checked.request.time_range!='3M'):
            raise ValueError('unsupported chart window')
        provider=Image.open(BytesIO(checked.data)).convert('RGB')
    except Exception:
        raise UnsupportedImage('verified current IHSG image unavailable') from None
    # Never resize, recolor, mask or overlay the provider panel. The rounded frame
    # is outside its exact rectangle, including attribution-bearing corner pixels.
    width=provider.width+160;height=provider.height+320
    if width<960:raise UnsupportedImage('provider panel too small for readable branded header')
    canvas=_Canvas(width,height);_header(canvas,'IDX Composite Index',publication_session)
    x=(width-provider.width)//2;y=240
    canvas.draw.rounded_rectangle((x-4,y-4,x+provider.width+4,y+provider.height+4),radius=16,fill='white',outline=GOLD,width=3)
    canvas.image.paste(provider,(x,y))
    proof=asdict(checked.verification);proof['verified_at']=checked.verification.verified_at.isoformat()
    return _artifact(canvas,dict(kind='ihsg',publication_session=publication_session.isoformat(),
                                provider_bounds=[x,y,x+provider.width,y+provider.height],
                                provider_sha256=checked.sha256,request_identity=checked.request.identity,
                                request_cutoff=checked.request.cutoff.isoformat(),retrieved_at=checked.retrieved_at.isoformat(),
                                profile_revision=checked.request.profile_revision,layout_revision=checked.request.layout_revision,
                                as_of=proof,provider_pixels='native unchanged',external_profile_validation='caller gate'))
