"""Pure local branded composition. No provider retrieval or numerical smoothing."""
from dataclasses import asdict, dataclass
from datetime import date, datetime
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
REVISION = 'bursawatch-render-v4'
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


class _ScaledDraw:
    """Draw geometry at native pixel density while keeping layout units logical."""
    def __init__(self,image,scale):
        self.native=ImageDraw.Draw(image);self.scale=scale

    def __getattr__(self,name):
        if name not in {'line','ellipse','rectangle','rounded_rectangle','polygon'}:
            return getattr(self.native,name)
        def draw(coords,**kwargs):
            def scaled(value):
                return tuple(scaled(v) for v in value) if isinstance(value,(tuple,list)) else value*self.scale
            for key in ('width','radius'):
                if key in kwargs:kwargs[key]=round(kwargs[key]*self.scale)
            return getattr(self.native,name)(scaled(coords),**kwargs)
        return draw


class _Canvas:
    def __init__(self,width,height,*,scale=1):
        self.width,self.height,self.scale=width,height,scale
        self.image=Image.new('RGB',(width*scale,height*scale),BG)
        self.draw=_ScaledDraw(self.image,scale)
        self.bounds=[]

    def text(self,x,y,value,size=24,color=FG,bold=False,anchor='lt'):
        font=_font(size*self.scale,bold)
        x*=self.scale;y*=self.scale
        draw=self.draw.native
        if '\n' in value:
            if anchor!='lt':raise ValueError('multiline text requires left alignment')
            anchor='la'
            offset=draw.multiline_textbbox((0,0),value,font=font,anchor=anchor,spacing=2*self.scale)
            x-=offset[0];y-=offset[1]
        bounds=draw.textbbox((x,y),value,font=font,anchor=anchor,spacing=2*self.scale)
        if not (0<=bounds[0]<bounds[2]<=self.image.width and 0<=bounds[1]<bounds[3]<=self.image.height):
            raise ValueError('text exceeds composition bounds')
        draw.text((x,y),value,font=font,fill=color,anchor=anchor,spacing=2*self.scale)
        logical=tuple(v/self.scale for v in bounds)
        self.bounds.append(list(logical))
        return logical

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
    # translate(-2 -2) group. Sample its cubic Beziers for the logo.
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
    width=canvas.width
    scale=min(1.,width/1600)
    canvas.text(80,88,title,round(54*scale),FG,True)
    canvas.text(82,161,publication_label(session),max(18,round(25*scale)),MUTED)
    _logo(canvas,width-80-round(270*scale),87,round(52*scale))
    canvas.text(width-80,94,'Bursawatch',round(40*scale),GOLD,True,anchor='rt')


def _artifact(canvas,manifest):
    output=BytesIO();canvas.image.save(output,format='PNG')
    data=output.getvalue()
    manifest.update(renderer_revision=REVISION,text_bounds=canvas.bounds,
                    pixel_ratio=canvas.scale,coordinate_space='logical-pixels',logical_dimensions=[canvas.width,canvas.height],
                    asset_sha256={key:sha256((ASSETS/name).read_bytes()).hexdigest() for key,name in
                                  [('font_regular','HankenGrotesk-400.ttf'),('font_bold','HankenGrotesk-700.ttf'),('logo','bursawatch.svg'),('font_license','OFL.txt')]})
    # Detach caller-owned nested dictionaries and verify the freeze-ready shape.
    manifest=json.loads(json.dumps(manifest,sort_keys=True,allow_nan=False))
    return RenderedArtifact(data,'image/png',sha256(data).hexdigest(),canvas.image.width,canvas.image.height,manifest)


def _intersects(a,b):
    return a[0]<b[2]+7 and a[2]+7>b[0] and a[1]<b[3]+7 and a[3]+7>b[1]


def _smooth_trail(points, samples=48):
    """Display-only cubic curves through observed points, without overshoot.

    Each coordinate's tangent is zero at reversals and bounded by both adjacent
    steps. Controls stay inside the segment rectangle, so a curve cannot invent
    an excursion outside either pair of observed coordinates.
    """
    if len(points)<2:return list(points)
    tangents=[]
    for i,p in enumerate(points):
        tangent=[]
        for axis in (0,1):
            before=p[axis]-points[i-1][axis] if i else points[1][axis]-p[axis]
            after=points[i+1][axis]-p[axis] if i<len(points)-1 else before
            tangent.append(math.copysign(min(abs(before),abs(after)),before) if before*after>0 else 0.)
        tangents.append(tangent)
    curve=[points[0]]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        c1=tuple(a[k]+tangents[i][k]/3 for k in (0,1))
        c2=tuple(b[k]-tangents[i+1][k]/3 for k in (0,1))
        for n in range(1,samples+1):
            if n==samples:curve.append(b);continue
            t=n/samples;u=1-t
            curve.append(tuple(u**3*a[k]+3*u*u*t*c1[k]+3*u*t*t*c2[k]+t**3*b[k] for k in (0,1)))
    return curve


def _faded(color, strength=.55):
    rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
    bg=tuple(int(BG[i:i+2],16) for i in (1,3,5))
    return tuple(round(a*strength+b*(1-strength)) for a,b in zip(rgb,bg))


def _label_box(canvas,x,y,label,size,bounds,occupied):
    left,top,right,bottom=bounds
    measured=canvas.draw.multiline_textbbox((0,0),label,font=_font(size,True),spacing=2)
    width,height=measured[2],measured[3]
    candidates=[]
    for distance in (12,35,65,100,145,210,280,360,450):
        for dx,dy in ((distance,-height-8),(distance,8),(-width-distance,-height-8),(-width-distance,8),(-width/2,-height-distance),(-width/2,distance)):
            bx=min(max(left+8,x+dx),right-width-8);by=min(max(top+55,y+dy),bottom-height-55)
            candidates.append((bx,by,bx+width,by+height))
    box=next((b for b in candidates if not any(_intersects(b,other) for other in occupied)),None)
    if box is None:
        # Corner clusters need candidates across the plot, not just a few rays.
        grid=[(bx,by,bx+width,by+height)
              for bx in range(math.ceil(left+8),math.floor(right-width-8)+1,math.ceil(width+15))
              for by in range(math.ceil(top+55),math.floor(bottom-height-55)+1,math.ceil(height+15))]
        grid.sort(key=lambda b:((b[0]+width/2-x)**2+(b[1]+height/2-y)**2,b))
        box=next((b for b in grid if not any(_intersects(b,other) for other in occupied)),None)
    if box is None:raise ValueError('collision-free labels unavailable; omit unsupported visual')
    occupied.append(box)
    if abs(box[0]-x)>18 or abs(box[1]-y)>18:
        endpoint=(min(max(x,box[0]),box[2]),min(max(y,box[1]),box[3]))
        canvas.draw.line(((x,y),endpoint),fill=MUTED,width=1)
    return box


def _axis_limits(values):
    # One percentage point on each side, with outward decimal rounding.
    return (math.floor((min(0.,min(values))-1.)*10)/10,
            math.ceil((max(0.,max(values))+1.)*10)/10)


def _axis_ticks(low,high):
    target=(high-low)/6
    unit=10**math.floor(math.log10(target))
    step=next(v*unit for v in (1,2,2.5,5,10) if v*unit>=target)
    return tuple(n*step for n in range(math.ceil(low/step),math.floor(high/step)+1))


def _map_position(x,y,bounds,x_limits,y_limits):
    left,top,right,bottom=bounds
    xmin,xmax=x_limits;ymin,ymax=y_limits
    return (left+(x-xmin)/(xmax-xmin)*(right-left),
            bottom-(y-ymin)/(ymax-ymin)*(bottom-top))


def _central_zoom(canvas,groups,codes,axis_limits):
    # A separate lower panel cannot obscure the full-range observations.
    left,top,width,height=160,1770,1260,560
    def extent(axis):
        values=sorted(abs(getattr(r,axis)) for r in groups)
        return min(max(abs(v) for v in axis_limits[axis]),max(1.,values[max(0,math.ceil(.8*len(values))-1)]*1.15))
    ex,ey=extent('x'),extent('y')
    rows=[r for r in groups if abs(r.x)<=ex and abs(r.y)<=ey]
    canvas.text(left,1700,'ZOOM PUSAT: POSISI TERAKHIR',25,FG,True)
    canvas.text(left,1737,f'X ±{ex:.1f} pp · Y ±{ey:.1f} pp · {len(rows)}/{len(groups)} kelompok dalam zoom',21,MUTED)
    for box,q in [((left,top,left+width/2,top+height/2),'Improving'),
                  ((left+width/2,top,left+width,top+height/2),'Leading'),
                  ((left,top+height/2,left+width/2,top+height),'Lagging'),
                  ((left+width/2,top+height/2,left+width,top+height),'Weakening')]:
        canvas.draw.rectangle(box,fill=FILLS[q])
    canvas.draw.line((left,top+height/2,left+width,top+height/2),fill=MUTED,width=1)
    canvas.draw.line((left+width/2,top,left+width/2,top+height),fill=MUTED,width=1)
    canvas.draw.rounded_rectangle((left,top,left+width,top+height),radius=12,outline=GOLD,width=2)
    occupied=[];labels=[]
    for r in sorted(rows,key=lambda r:r.name):
        x=left+width/2+width*r.x/(2*ex);y=top+height/2-height*r.y/(2*ey)
        canvas.draw.ellipse((x-7,y-7,x+7,y+7),fill=COLORS[r.quadrant],outline=BG,width=2)
        label=codes[r.name]
        box=_label_box(canvas,x,y,label,26,(left,top,left+width,top+height),occupied)
        canvas.text(box[0],box[1],label,26,COLORS[r.quadrant],True)
        labels.append(dict(name=r.name,label=label,bounds=list(box),latest_pixel=[x,y]))
    for value in (-ex,0,ex):
        canvas.text(left+width/2+width*value/(2*ex),top+height+12,f'{value:.1f}',20,MUTED,anchor='mt')
    for value in (-ey,0,ey):
        canvas.text(left-12,top+height/2-height*value/(2*ey),f'{value:.1f}',20,MUTED,anchor='rm')
    canvas.text(1500,1780,'Cara membaca',25,FG,True)
    canvas.text(1500,1830,'Nomor sesuai tabel sorotan; huruf sesuai kelompok lain.',22,MUTED)
    canvas.text(1500,1870,'Zoom memperbesar posisi terakhir di sekitar titik nol.',22,MUTED)
    canvas.text(1500,1910,'Kelompok di luar zoom tetap terlihat pada plot utama.',22,MUTED)
    return dict(bounds=[left,top,left+width,top+height],x_extent=ex,y_extent=ey,
        names=[r.name for r in rows],outside_names=sorted(r.name for r in groups if r not in rows),
        mode='latest-observed-position',labels=labels)


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
        if len(row.trail)!=5 or not row.name or len(row.name)>180 or not math.isfinite(row.coverage) or not 0<row.coverage<=1:
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
    limits={axis:_axis_limits([getattr(p,axis) for p in visible]) for axis in ('x','y')}
    canvas=_Canvas(2600,2400 if kind=='konglo' else 1660,scale=2);_header(canvas,'Rotasi Sektor' if kind=='sectors' else 'Rotasi Konglo',publication_session)
    partial=sum(bool(r.excluded) for r in groups)
    stale=any(r.provenance.get('cap_collection_status')=='stale' for r in groups)
    coverage=min(r.coverage for r in groups)
    unknown=sum(len(r.provenance.get('missing_cap_members',())) for r in groups)
    caption=f'Basket parsial: {partial}/{len(groups)} | Cakupan cap diketahui: min. {coverage:.1%} | Cap tidak tersedia: {unknown}'
    cap_dates=sorted({datetime.fromisoformat(r.provenance['cap_collected_at']).astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d/%m/%Y')
        for r in groups if r.provenance.get('cap_collected_at')})
    if cap_dates:
        caption+=' | Cap: '+(cap_dates[0] if len(cap_dates)==1 else cap_dates[0]+' sampai '+cap_dates[-1])
    if stale: caption+=' | Snapshot cap lama (stale)'
    canvas.text(82,210,caption,24,MUTED)
    left,top,size=160,260,1260
    bounds=(left,top,left+size,top+size)
    zero=_map_position(0,0,bounds,limits['x'],limits['y'])
    zx,zy=zero[0]-left,zero[1]-top
    plot=Image.new('RGB',(size*canvas.scale,size*canvas.scale),BG);draw=_ScaledDraw(plot,canvas.scale)
    quadrants=[((0,0,zx,zy),'Improving'),((zx,0,size,zy),'Leading'),
               ((0,zy,zx,size),'Lagging'),((zx,zy,size,size),'Weakening')]
    for box,q in quadrants:draw.rectangle(box,fill=FILLS[q])
    draw.line((0,zy,size,zy),fill='#655D51',width=2);draw.line((zx,0,zx,size),fill='#655D51',width=2)
    mask=Image.new('L',plot.size)
    _ScaledDraw(mask,canvas.scale).rounded_rectangle((0,0,size-1,size-1),radius=20,fill=255)
    canvas.image.paste(plot,(left*canvas.scale,top*canvas.scale),mask)
    def point(position):return _map_position(position.x,position.y,bounds,limits['x'],limits['y'])
    occupied=[]
    for (x0,y0,x1,y1),q in quadrants:
        available=x1-x0-40
        if available<60 or y1-y0<65:continue
        title_size=next((n for n in range(30,13,-1) if _font(n,True).getlength(q)<=available),None)
        if title_size is None:continue
        width=_font(title_size,True).getlength(q)
        x=left+x0+20 if x0==0 else left+x1-20-width
        y=top+y0+18 if y0==0 else top+y1-45
        occupied.append(canvas.text(x,y,q,title_size,COLORS[q],True))
    codes={r.name:str(i+1) for i,r in enumerate(ordered)} if kind=='konglo' else {}
    codes.update(expected)
    plotted={};labels=[];visual_trails={}
    for row in sorted(groups,key=lambda r:(r.name not in chosen,r.name)):
        xy=[point(p) for p in row.trail];x,y=xy[-1];color=COLORS[row.quadrant]
        if row.name in chosen:
            curve=_smooth_trail(xy)
            visual_trails[row.name]=curve
            canvas.draw.line(curve,fill=_faded(color) if kind=='konglo' else color,width=2 if kind=='konglo' else 3)
            for n,(hx,hy) in enumerate(xy[:-1]):canvas.draw.ellipse((hx-3-n,hy-3-n,hx+3+n,hy+3+n),fill=_faded(color) if kind=='konglo' else color)
            # The arrow follows the displayed tangent and ends at the actual point.
            dx,dy=x-curve[-2][0],y-curve[-2][1];length=math.hypot(dx,dy)
            if length>0:
                ux,uy=dx/length,dy/length
                head=min(14,math.hypot(x-xy[-2][0],y-xy[-2][1])/2)
                canvas.draw.polygon([(x,y),(x-ux*head-uy*5,y-uy*head+ux*5),(x-ux*head+uy*5,y-uy*head-ux*5)],fill=color)
        radius=(10 if row.name in chosen else 7) if kind=='konglo' else 7
        canvas.draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color,outline=BG,width=2)
        label=codes[row.name] if kind=='konglo' else _wrap(row.name,235,_font(26,True))
        label_size=26
        box=_label_box(canvas,x,y,label,label_size,(left,top,left+size,top+size),occupied)
        canvas.text(box[0],box[1],label,label_size,FG if row.name in chosen else '#BDB9B1',True)
        plotted[row.name]=[[p.session,p.x,p.y] for p in row.trail]
        labels.append({'name':row.name,'label':label,'bounds':list(box),'latest_pixel':[x,y]})
    canvas.draw.rounded_rectangle(bounds,radius=20,outline=GOLD,width=3)
    for value in _axis_ticks(*limits['x']):
        x,_=_map_position(value,0,bounds,limits['x'],limits['y'])
        canvas.text(x,1536,f'{value:g}',24,MUTED,anchor='mt')
    for value in _axis_ticks(*limits['y']):
        _,y=_map_position(0,value,bounds,limits['x'],limits['y'])
        canvas.text(145,y,f'{value:g}',24,MUTED,anchor='rm')
    canvas.text(790,1580,'Kekuatan relatif terhadap IHSG (pp)',28,MUTED,anchor='mt')
    canvas.text(160,1630,'Garis lengkung hanya visual; titik menunjukkan sesi aktual.',18,MUTED)
    # Rotate the Y-axis label outside the plot.
    label=Image.new('RGBA',(600*canvas.scale,40*canvas.scale))
    ImageDraw.Draw(label).text((0,0),'Momentum relatif (pp)',font=_font(30*canvas.scale),fill=MUTED)
    label=label.rotate(90,expand=True)
    canvas.image.paste(label,(65*canvas.scale,650*canvas.scale),label)
    x,y=zero
    canvas.draw.ellipse((x-3,y-3,x+3,y+3),fill=MUTED)
    # Keep the benchmark label inside the plot even when zero is near an edge.
    canvas.text(min(x+12,left+size-60),min(y+12,top+size-30),'IHSG',20,MUTED)
    distribution={q:sum(r.quadrant==q for r in groups) for q in COLORS}
    canvas.text(1500,260,'DISTRIBUSI',22,MUTED,True)
    for i,q in enumerate(FILLS):
        x=1500+i*259
        canvas.draw.rounded_rectangle((x,307,x+243,425),radius=14,fill=FILLS[q])
        canvas.text(x+20,327,q,25,COLORS[q],True);canvas.text(x+20,367,str(distribution[q]),37,FG,True)
    if distribution['Neutral']:canvas.text(1500,447,f"Neutral: {distribution['Neutral']}",22,MUTED)
    canvas.text(1500,475,f"X: {limits['x'][0]:+g} hingga {limits['x'][1]:+g} pp | Y: {limits['y'][0]:+g} hingga {limits['y'][1]:+g} pp",21,MUTED)
    canvas.text(1500,514,'SOROTAN SEKTOR' if kind=='sectors' else 'SOROTAN KONGLO',22,MUTED,True)
    for x,value in zip((1520,1950,2180,2370),('ID / Kelompok' if kind=='konglo' else 'Kelompok','Kuadran','Kekuatan (pp)','Momentum (pp)')):canvas.text(x,568,value,21,MUTED,True)
    row_height=42 if kind=='konglo' else min(68,720//len(ordered))
    for i,row in enumerate(ordered):
        y=626+i*row_height
        if i%2==0:canvas.draw.rounded_rectangle((1500,y-8,2520,y+row_height-9),radius=7,fill=PANEL)
        if kind=='konglo':
            canvas.text(1520,y,codes[row.name],25,COLORS[row.quadrant],True)
        canvas.fitted(1560 if kind=='konglo' else 1520,y,row.name,360 if kind=='konglo' else 400,row_height-3,25,True)
        canvas.text(1950,y,row.quadrant,25,COLORS[row.quadrant])
        canvas.text(2180,y,f'{row.x:+.2f}',25);canvas.text(2370,y,f'{row.y:+.2f}',25)
    if expected:
        canvas.text(1500,1390,'KELOMPOK LAIN',22,MUTED,True)
        for i,(name,letter) in enumerate(sorted(expected.items(),key=lambda pair:pair[1])):
            col=i//8;line=i%8;x=1500+col*520;y=1433+line*27
            canvas.text(x+12,y,letter,20,COLORS[next(r.quadrant for r in groups if r.name==name)],True)
            canvas.fitted(x+48,y,name,460,26,21,color=MUTED)
    zoom=_central_zoom(canvas,groups,codes,limits) if kind=='konglo' else None
    manifest=dict(kind=kind,publication_session=publication_session.isoformat(),trail_sessions=list(sessions),
                  plot_bounds=list(bounds),axis_limits=limits,axis_padding_pp=1.,zero_pixel=list(zero),
                  axis_policy='independent-asymmetric-linear/full-visible-trails',colors=COLORS.copy(),distribution=distribution,
                  selection_names=[r.name for r in selected],table_names=[r.name for r in ordered],
                  secondary_letters=dict(expected),marker_codes=codes,central_zoom=zoom,
                  curve_policy='bounded-cubic/display-only/observed-points-unchanged',visual_trails=visual_trails,trails_drawn=[r.name for r in selected],labels=labels,
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


def render_yahoo_ihsg(series, *, publication_session: date) -> RenderedArtifact:
    """Draw actual daily candles and locally calculated SMA/Wilder RSI values."""
    bars = series['bars']; averages = series['averages']; rsi = series['rsi']
    if not 1 <= len(bars) <= 100 or any(len(values) != len(bars) for values in (*averages.values(), rsi)):
        raise UnsupportedImage('bounded aligned chart values required')
    canvas = _Canvas(1600, 1160)
    _header(canvas, 'IDX Composite Index', publication_session)
    left, right, top, bottom = 100, 1450, 300, 790
    rsi_top, rsi_bottom = 860, 1060
    ink = '#343B39'; muted = '#66706C'
    up, down = '#159C75', '#D84951'
    colors = {'10': '#D78019', '20': '#2775C9', '50': '#8B56B5', '100': '#3D8D77'}
    for bounds in ((80, 240, 1520, 825), (80, 845, 1520, 1080)):
        canvas.draw.rounded_rectangle(bounds, radius=16, fill='#F8FAF9', outline=GOLD, width=2)
    for index, (period, color) in enumerate(colors.items()):
        canvas.text(110 + 325 * index, 259, f'MA {period}  {averages[period][-1]:,.2f}', 22, color, True)
    values = [value for bar in bars for value in (bar.low, bar.high)]
    values.extend(value for row in averages.values() for value in row)
    low, high = min(values), max(values)
    padding = max((high - low) * .08, high * .003)
    low -= padding; high += padding
    step = (right - left) / len(bars)
    xs = [left + (index + .5) * step for index in range(len(bars))]
    def price_y(value): return bottom - (value - low) / (high - low) * (bottom - top)
    body_width = min(12, step * .65)
    for x, bar in zip(xs, bars):
        color = up if bar.close >= bar.open else down
        canvas.draw.line((x, price_y(bar.high), x, price_y(bar.low)), fill=color, width=2)
        y0, y1 = sorted((price_y(bar.open), price_y(bar.close)))
        canvas.draw.rectangle((x - body_width / 2, y0, x + body_width / 2, max(y1, y0 + 1)), fill=color)
    for period, color in colors.items():
        canvas.draw.line([(x, price_y(value)) for x, value in zip(xs, averages[period])], fill=color, width=3)
    for fraction in (0, .25, .5, .75, 1):
        value = low + fraction * (high - low)
        canvas.text(1500, price_y(value), f'{value:,.0f}', 19, muted, anchor='rm')
    def rsi_y(value): return rsi_bottom - value / 100 * (rsi_bottom - rsi_top)
    for level in (30, 70):
        y = rsi_y(level)
        for x in range(left, right, 16):
            canvas.draw.line((x, y, min(x + 8, right), y), fill='#CAD3CE', width=1)
        canvas.text(1500, y, str(level), 19, muted, anchor='rm')
    canvas.draw.line([(x, rsi_y(value)) for x, value in zip(xs, rsi)], fill='#8656A5', width=3)
    canvas.text(110, 870, f'RSI (14)  {rsi[-1]:.2f}', 22, ink, True)
    indexes = sorted({round(index * (len(bars) - 1) / 4) for index in range(5)})
    for index in indexes:
        canvas.text(xs[index], 1095, bars[index].session.strftime('%d %b'), 20, MUTED, anchor='mt')
    canvas.text(80, 1130, f'Yahoo Finance · Daily · Close {bars[-1].session.isoformat()}', 18, MUTED)
    manifest = dict(kind='ihsg', provider='yahoo', publication_session=publication_session.isoformat(),
        price_bounds=[left, top, right, bottom], rsi_bounds=[left, rsi_top, right, rsi_bottom],
        candles=[dict(session=bar.session.isoformat(), open=bar.open, high=bar.high,
                      low=bar.low, close=bar.close) for bar in bars],
        moving_averages={key: list(values) for key, values in averages.items()}, rsi=list(rsi),
        ma_colors=colors, provenance=series['provenance'])
    return _artifact(canvas, manifest)
