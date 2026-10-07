"""Import a complete official IDX holiday table and checked amendment listing.

This is an explicit import, never a weekday fallback or a freshness flag reset.
Every month must reconcile to the official published trading-session count.
"""
from datetime import date, datetime, timedelta
import hashlib
import re
import subprocess
from urllib.parse import quote

from .calendar import aware
from .store import digest, stamp

LISTING_URL='https://www.idx.co.id/primary/NewsAnnouncement/GetAllAnnouncement?keywords=Kalender+Libur+Bursa&pageNumber=1&pageSize=10&lang=id'
MONTHS=('Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember')


def parse_official_table(text, year):
    if type(text) is not str or len(text.encode())>2_000_000:
        raise ValueError('bounded official extracted calendar required')
    start=text.index('Bulan'); end=text.index('Catatan:',start)
    table=text[start:end]
    if 'Tidak ada hari libur kecuali Sabtu dan Minggu' not in table:
        raise ValueError('explicit official weekend rule unavailable')
    months={}
    pattern=r'^\s*('+'|'.join(MONTHS)+r')\b[^\n]*?\s+(\d{1,2})\s*$'
    rows=list(re.finditer(pattern,table,re.MULTILINE))
    if [m[1] for m in rows]!=list(MONTHS):
        raise ValueError('complete ordered official monthly counts required')
    months={i+1:int(m[2]) for i,m in enumerate(rows)}
    closing_dates=[]
    for raw in re.findall(r'\b\d{2}-\d{2}-\d{4}\b',table):
        day,month,source_year=map(int,raw.split('-'));value=date(source_year,month,day)
        if source_year!=year or value.weekday()>=5 or value in closing_dates:
            raise ValueError('invalid official weekday closure')
        closing_dates.append(value)
    total=re.search(r'Jumlah Hari Bursa\s+(\d{2,3})',table)
    if total is None or sum(months.values())!=int(total[1]):
        raise ValueError('official annual total does not reconcile')
    # This rule is read from this complete official table. Missing source rows or
    # a changed format fail below, rather than falling back to ordinary weekdays.
    cursor=date(year,1,1);end=date(year,12,31);sessions=[]
    while cursor<=end:
        if cursor.weekday()<5 and cursor not in closing_dates:
            sessions.append(cursor)
        cursor+=timedelta(days=1)
    if any(sum(day.month==month for day in sessions)!=count for month,count in months.items()):
        raise ValueError('official monthly session counts do not reconcile')
    return sessions,months,closing_dates


def import_calendar(pdf, listing, *, now, extractor=None):
    now=aware(now)
    if (type(pdf) is not bytes or not pdf.startswith(b'%PDF-') or not 1000<=len(pdf)<=2_000_000
            or listing['source_url']!=LISTING_URL):
        raise ValueError('bounded primary IDX calendar sources required')
    observed=aware(datetime.fromisoformat(listing['retrieved_at'].replace('Z','+00:00')))
    if not timedelta(0)<=now-observed<=timedelta(days=7):
        raise ValueError('cutoff-visible current amendment listing required')
    payload=listing['payload'];items=payload['Items']
    if (type(items) is not list or not 1<=len(items)<=100 or payload['PageCount']!=1
            or payload['PageNumber']!=1 or payload['ItemCount']!=len(items)
            or any(type(payload[key]) is not int for key in ('PageCount','PageNumber','ItemCount'))):
        raise ValueError('complete official amendment listing required')
    if extractor is None:
        output=subprocess.run(['pdftotext','-layout','-','-'],input=pdf,capture_output=True,timeout=5,check=True)
        text=output.stdout.decode('utf-8')
    else:
        text=extractor(pdf)
    years=set(re.findall(r'Kalender Libur Bursa Tahun (\d{4})',text))
    if len(years)!=1:
        raise ValueError('unambiguous official calendar year required')
    year=int(next(iter(years)))
    candidates=[row for row in items if re.search(r'Kalender Libur Bursa.*\b'+str(year)+r'\b',row['Title'])]
    if len(candidates)!=1 or candidates[0]['Title']!='Kalender Libur Bursa Tahun '+str(year):
        raise ValueError('calendar amendment requires separate reviewed import')
    announcement=candidates[0];reference=announcement['AnnouncementNo'].removeprefix('No. ')
    if reference not in text:
        raise ValueError('official PDF announcement reference mismatch')
    attachments=[row for row in announcement['Attachments'] if row['FullSavePath'].casefold().endswith('.pdf')]
    if len(attachments)!=1 or not attachments[0]['FullSavePath'].startswith('https://www.idx.co.id/StaticData/'):
        raise ValueError('single primary official calendar PDF required')
    sessions,months,closed=parse_official_table(text,year)
    return dict(version='idx-'+str(year)+':'+hashlib.sha256(pdf).hexdigest(),
        amendment='checked-listing:'+digest(payload),authority='IDX',verified=True,
        source_url=quote(attachments[0]['FullSavePath'],safe=':/%'),source_digest=hashlib.sha256(pdf).hexdigest(),
        amendment_checked_at=stamp(observed),valid_from=date(year,1,1).isoformat(),
        valid_through=date(year,12,31).isoformat(),sessions=[day.isoformat() for day in sessions],
        review_evidence={'announcement':reference,'listing_url':LISTING_URL,'listing_digest':digest(payload),
            'text_digest':hashlib.sha256(text.encode()).hexdigest(),'monthly_counts':months,
            'closures':[day.isoformat() for day in closed],'method':'complete-official-table-and-weekend-rule'})
