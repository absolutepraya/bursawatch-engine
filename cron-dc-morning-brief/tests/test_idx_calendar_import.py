from datetime import datetime,timedelta,timezone

import pytest

from morning_brief.idx_calendar_import import import_calendar, LISTING_URL


NOW=datetime(2026,10,6,16,tzinfo=timezone.utc)
PDF=b'%PDF-synthetic-test-only\n'+b'x'*1100
TEXT='''Kalender Libur Bursa Tahun 2026
Peng-00171/BEI.POP/09-2025
Bulan Tanggal Hari Keterangan Hari Bursa
Januari 20
01-01-2026 16-01-2026
Februari 18
16-02-2026 17-02-2026
Maret 17
18-03-2026 19-03-2026 20-03-2026 23-03-2026 24-03-2026
April 21
03-04-2026
Mei 16
01-05-2026 14-05-2026 15-05-2026 27-05-2026 28-05-2026
Juni 20
01-06-2026 16-06-2026
Juli Tidak ada hari libur kecuali Sabtu dan Minggu 23
Agustus 19
17-08-2026 25-08-2026
September 22
Oktober 22
November 21
Desember 20
24-12-2026 25-12-2026 31-12-2026
Jumlah Hari Bursa 239
Catatan:
'''


def envelope():
    return {'source_url':LISTING_URL,'retrieved_at':NOW.isoformat(),
        'payload':{'ItemCount':1,'PageNumber':1,'PageCount':1,'Items':[
            {'Title':'Kalender Libur Bursa Tahun 2026','AnnouncementNo':'No. Peng-00171/BEI.POP/09-2025',
             'Attachments':[{'FullSavePath':'https://www.idx.co.id/StaticData/calendar-2026.pdf'}]}]}}


def test_complete_official_table_reconciles_every_month_and_preserves_boundary():
    value=import_calendar(PDF,envelope(),now=NOW,extractor=lambda _:TEXT)
    assert len(value['sessions'])==239 and value['authority']=='IDX'
    assert '2026-01-01' not in value['sessions'] and '2026-12-31' not in value['sessions']
    assert '2026-10-06' in value['sessions'] and '2026-10-07' in value['sessions']
    assert value['review_evidence']['monthly_counts'][10]==22
    assert value['amendment_checked_at']==NOW.isoformat()


@pytest.mark.parametrize('change',['missing_closure','bad_total','missing_month','missing_weekend_rule','wrong_pdf_reference'])
def test_incomplete_or_changed_official_table_never_falls_back_to_weekdays(change):
    text=TEXT
    if change=='missing_closure':text=text.replace('17-02-2026','')
    if change=='bad_total':text=text.replace('Jumlah Hari Bursa 239','Jumlah Hari Bursa 240')
    if change=='missing_month':text=text.replace('Februari 18','')
    if change=='missing_weekend_rule':text=text.replace('Tidak ada hari libur kecuali Sabtu dan Minggu','')
    if change=='wrong_pdf_reference':text=text.replace('Peng-00171/BEI.POP/09-2025','different-reference')
    with pytest.raises(ValueError):import_calendar(PDF,envelope(),now=NOW,extractor=lambda _:text)


@pytest.mark.parametrize('change',['amendment','partial_listing','stale_listing','future_listing'])
def test_new_amendment_or_incomplete_current_listing_rejects_old_pdf(change):
    source=envelope()
    if change=='amendment':
        source['payload']['Items'].append({'Title':'Perubahan Kalender Libur Bursa Tahun 2026'})
        source['payload']['ItemCount']=2
    if change=='partial_listing':source['payload']['PageCount']=2
    if change=='stale_listing':source['retrieved_at']=(NOW-timedelta(days=7,seconds=1)).isoformat()
    if change=='future_listing':source['retrieved_at']=(NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):import_calendar(PDF,source,now=NOW,extractor=lambda _:TEXT)
