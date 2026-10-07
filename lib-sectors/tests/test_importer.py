from datetime import timedelta
import json
import pytest
import sectors_client as sc
from test_cache_client import NOW, page, identity, config, Fake


def retained(tmp_path):
    path=tmp_path/'retained.json'
    data={'started_at':'2026-10-05T00:00:00+00:00','dates':['2026-10-02','2026-09-11'],
          'sessions':{'2026-10-02':[page(),page(2)],'2026-09-11':[page(session='2026-09-11')]},
          'complete_dates':['2026-10-02'], 'successful_requests':1}
    path.write_text(json.dumps(data))
    return path,data


def importer():
    return sc.import_retained


def test_offline_import_is_idempotent_unbilled_and_reports_partial_sessions(tmp_path):
    path,data=retained(tmp_path)
    store=sc.CacheStore(tmp_path/'cache.sqlite3')
    report=importer()(path,store,imported_at=NOW)
    assert report.pages_imported==3
    assert report.complete_sessions==('2026-10-02',)
    assert report.partial_sessions=={'2026-09-11':(2,)}
    assert report.missing_sessions==()
    assert store.usage('oct','morning')=={'host_reserved':0,'caller_reserved':0}
    assert importer()(path,store,imported_at=NOW).pages_imported==0
    client=sc.SectorsClient(config(tmp_path,cache_only=True),store=store,transport=Fake([]),clock=lambda:NOW)
    assert client.close_session('2026-10-02',cutoff=NOW,page_limit=2).complete
    with pytest.raises(sc.CacheMiss):
        store.get(identity(),cutoff=NOW-timedelta(seconds=1))
    assert store.get(identity(),cutoff=NOW).imported


@pytest.mark.parametrize('mutate',[
    lambda d:d['sessions']['2026-10-02'][0]['results'][0].update(date='2026-10-01'),
    lambda d:d['sessions']['2026-10-02'][0]['pagination'].update(total_count=99),
    lambda d:d.update(complete_dates=['2026-09-11']),
    lambda d:d.update(started_at='not a timestamp'),
    lambda d:d['sessions']['2026-10-02'].append(page()),
    lambda d:d.update(origin='https://evil.test'),
])
def test_invalid_retained_provenance_or_pagination_rejects_entire_import(tmp_path,mutate):
    path,data=retained(tmp_path);mutate(data);path.write_text(json.dumps(data))
    store=sc.CacheStore(tmp_path/'cache.sqlite3')
    with pytest.raises(sc.ValidationError):
        importer()(path,store,imported_at=NOW)
    with pytest.raises(sc.CacheMiss):
        store.get(identity(),cutoff=NOW)


def test_directory_import_selects_known_history_file_without_reading_other_artifacts(tmp_path):
    path,data=retained(tmp_path)
    directory=tmp_path/'retained';directory.mkdir()
    path.rename(directory/'bursawatch-preview-history-20261005.json')
    (directory/'unrelated.json').write_text('private invalid JSON')
    data['dates'].append('2026-09-10')
    (directory/'bursawatch-preview-history-20261005.json').write_text(json.dumps(data))
    report=importer()(directory,sc.CacheStore(tmp_path/'cache.sqlite3'),imported_at=NOW)
    assert report.ignored_artifacts==1
    assert report.missing_sessions==('2026-09-10',)


def test_repeated_import_at_later_time_preserves_original_availability(tmp_path):
    path,_=retained(tmp_path)
    store=sc.CacheStore(tmp_path/'cache.sqlite3')
    importer()(path,store,imported_at=NOW)
    report=importer()(path,store,imported_at=NOW+timedelta(hours=1))
    assert report.pages_imported==0
    assert store.get(identity(),cutoff=NOW+timedelta(hours=1)).available_at==NOW
