"""Synthetic source fixtures: recovery must never replace a captured corpus."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import pytest

FREEZE = datetime.fromisoformat('2026-10-05T07:30:00+07:00')
LOWER = '2026-10-02T00:30:00+00:00'
UPPER = '2026-10-05T00:30:00+00:00'


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def source(n, publisher='collector', text=None, platform='rss', **extras):
    row = dict(event_key=f'{n:064x}', version=1, kind='original', accepted_at=UPPER,
               published_at='2026-10-04T09:00:00+00:00', observed_at=UPPER,
               endpoint_id=f'{platform}:{n}', publisher_id=publisher, platform=platform,
               source_url=f'https://example.com/story/{n}', parser_version='synthetic-1',
               content_hash=checksum(text or f'IHSG fakta sintetis {n}.'), payload_hash=f'{n+1:064x}',
               original_publisher_id=None, origin_status='unknown', text=text or f'IHSG fakta sintetis {n}.',
               text_truncated=False, content_unavailable=False, media_refs=[])
    row.update(extras)
    row['evidence_hash'] = checksum(row)
    row['version_ref'] = base64.urlsafe_b64encode(json.dumps([row['event_key'], row['version'], row['payload_hash']], separators=(',', ':')).encode()).decode().rstrip('=')
    return row


def manifest(rows, **extras):
    result = dict(api_version=1, previous_cutoff=LOWER, cutoff=UPPER, captured_at=UPPER,
                  capture_status='on_time', capture_gap_seconds=0, history_available_from=LOWER,
                  history_status='available', overflow=False, candidate_limit=1000, complete=True,
                  items=[{k: v for k, v in row.items() if k not in {'text', 'media_refs'}} for row in rows])
    result.update(extras)
    result['manifest_hash'] = checksum(result)
    return result


def owner(core, tmp_path):
    store = core('store').RunStore(tmp_path/'runs.sqlite3')
    run = store.create_run('2026-10-05', freeze_at=FREEZE)
    lease = store.acquire_lease(run.run_id, 'fixture', now=FREEZE, seconds=3600)
    return store, run, lease


class CapturedClient:
    def __init__(self, store, run_id, rows, capture=None):
        self.store, self.run_id, self.rows = store, run_id, deepcopy(rows)
        self.capture = capture or manifest(rows)
    def capture_window(self, previous, cutoff, limit=1000):
        assert (previous, cutoff) == (LOWER, UPPER)
        return deepcopy(self.capture)
    def read_versions(self, refs):
        # A fake transport asserts the durable boundary, the result is real owner state.
        frozen = self.store.get_frozen(self.run_id, 'source_manifest')
        assert frozen is not None and refs == [r['version_ref'] for r in frozen.payload['items']][:len(refs)]
        return [deepcopy(row) for row in self.rows if row['version_ref'] in refs]


def test_manifest_persisted_before_selection_and_recovery_never_recaptures(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    first = source(1)
    client = CapturedClient(store, run.run_id, [first])
    result = module.freeze_source_evidence(store, run.run_id, client, previous_cutoff=LOWER, lease=lease, now=FREEZE)
    assert result.payload['items'][0]['text'] == 'IHSG fakta sintetis 1.'
    assert result.dependencies == {'source_manifest': store.get_frozen(run.run_id, 'source_manifest').digest}
    class Recovery(CapturedClient):
        def capture_window(self, *_args, **_kwargs):
            pytest.fail('recovery recaptured changing database')
        def read_versions(self, *_args):
            pytest.fail('complete evidence freeze needlessly reread')
    assert module.freeze_source_evidence(store, run.run_id, Recovery(store, run.run_id, []), previous_cutoff=LOWER, lease=lease, now=FREEZE).digest == result.digest


@pytest.mark.parametrize('change', ['correction', 'hash', 'tombstone', 'missing'])
def test_recovery_rejects_changed_manifest_payloads_or_missing_history(core, tmp_path, change):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    first = source(1)
    store.freeze(run.run_id, 'source_manifest', manifest([first]), lease=lease, now=FREEZE)
    changed = deepcopy(first)
    if change == 'correction':
        changed = source(1, text='Koreksi sintetis.', version=2, kind='correction')
    elif change == 'hash':
        changed['evidence_hash'] = 'a'*64
    elif change == 'tombstone':
        changed['kind'] = 'tombstone'
    client = CapturedClient(store, run.run_id, [] if change == 'missing' else [changed])
    result = module.freeze_source_evidence(store, run.run_id, client, previous_cutoff=LOWER, lease=lease, now=FREEZE)
    assert result.payload['facts_only'] is True and result.payload['items'] == []
    assert 'immutable_versions_unavailable' in result.payload['degraded_reasons']
    assert store.get_frozen(run.run_id, 'source_manifest').payload['items'][0]['version'] == 1


def test_caps_apply_to_publisher_across_routes_and_copied_text_is_one_story(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(i+1, publisher='same', platform=['x', 'rss', 'telegram', 'whatsapp'][i]) for i in range(4)]
    rows += [source(10, publisher='other', text=rows[0]['text'], content_hash='f'*64)]
    rows += [source(i+20, publisher=f'pub{i}') for i in range(40)]
    client = CapturedClient(store, run.run_id, rows)
    result = module.freeze_source_evidence(store, run.run_id, client, previous_cutoff=LOWER, lease=lease, now=FREEZE).payload
    assert len(result['items']) == 30
    assert sum(item['publisher_id'] == 'same' for item in result['items']) == 3
    assert 'other' not in [item['publisher_id'] for item in result['items']]
    assert result['omissions']['copied_story'] == 1 and result['omissions']['publisher_cap'] == 1
    assert result['items'][0]['origin_status'] == 'unknown'


@pytest.mark.parametrize('extras,reason', [
    ({'capture_status':'late','captured_at':'2026-10-05T00:30:01+00:00','capture_gap_seconds':1,'complete':False}, 'late_capture'),
    ({'capture_status':'early','captured_at':'2026-10-05T00:29:59+00:00','capture_gap_seconds':-1,'complete':False}, 'early_capture'),
    ({'overflow':True,'complete':False}, 'corpus_overflow'),
    ({'history_status':'unknown','history_available_from':None,'complete':False}, 'history_unknown'),
    ({'history_status':'unavailable','history_available_from':UPPER,'complete':False}, 'history_unavailable'),
])
def test_capture_gaps_are_preserved_and_force_facts_only(core, tmp_path, extras, reason):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(1)]
    result = module.freeze_source_evidence(store, run.run_id, CapturedClient(store,run.run_id,rows,manifest(rows,**extras)), previous_cutoff=LOWER,lease=lease,now=FREEZE).payload
    assert reason in result['degraded_reasons'] and result['facts_only']
    assert result['capture_status'] == extras.get('capture_status','on_time')


def test_verified_original_used_only_when_verified_and_invalid_media_never_valid(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(1, original_publisher_id='rumor', origin_status='unknown', media_refs=['bad'])]
    result = module.freeze_source_evidence(store, run.run_id, CapturedClient(store,run.run_id,rows), previous_cutoff=LOWER,lease=lease,now=FREEZE).payload
    assert result['items'][0]['publisher_id'] == 'collector'
    assert result['items'][0]['media_refs'] == []
    assert 'invalid_media_metadata' in result['degraded_reasons'] and result['facts_only']
    selected = module.select_evidence([source(2, original_publisher_id='verified-origin', origin_status='verified')])
    assert selected['items'][0]['publisher_id'] == 'verified-origin'


def test_truncated_or_unavailable_content_cannot_authorize_outlook(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core,tmp_path)
    rows = [source(1,text_truncated=True), source(2,text='',content_unavailable=True)]
    result = module.freeze_source_evidence(store,run.run_id,CapturedClient(store,run.run_id,rows),previous_cutoff=LOWER,lease=lease,now=FREEZE).payload
    assert result['facts_only'] and 'truncated_content' in result['degraded_reasons']
    assert len(result['items']) == 1


def test_valid_durable_media_preserved_but_kind_size_and_uuid_malformed_rejected(core):
    module = core('evidence')
    valid = dict(ref='12345678-abcd-4abc-8abc-123456789abc',sha256='a'*64,kind='image',content_type='image/png',size_bytes=1024,filename='synthetic.png',durable=True)
    result = module.select_evidence([source(1,media_refs=[valid])])
    assert result['items'][0]['media_refs'] == [valid] and result['degraded_reasons'] == []
    for changes in ({'kind':'video'},{'size_bytes':9*1024*1024},{'ref':'source-media:fake'},{'filename':'../x.png'},{'durable':False}):
        malformed = dict(valid,**changes)
        result = module.select_evidence([source(1,media_refs=[malformed])])
        assert result['items'][0]['media_refs'] == [] and 'invalid_media_metadata' in result['degraded_reasons']


@pytest.mark.parametrize('malformed',[{'kind':[]},{'sha256':{}},{'content_type':[]},{'filename':None}])
def test_malformed_media_entry_types_degrade_safely(core,malformed):
    module=core('evidence')
    media=dict(ref='12345678-abcd-4abc-8abc-123456789abc',sha256='a'*64,kind='image',content_type='image/png',size_bytes=1024,filename='test.png',durable=True)
    media.update(malformed)
    result=module.select_evidence([source(1,media_refs=[media])])
    assert result['items'][0]['media_refs']==[] and 'invalid_media_metadata' in result['degraded_reasons']


def test_manifest_batches_all_saved_refs_before_caps_and_handles_second_page_failure(core,tmp_path):
    module=core('evidence'); store,run,lease=owner(core,tmp_path)
    rows=[source(i+1,publisher=f'p{i}') for i in range(101)]
    class Paged(CapturedClient):
        def read_versions(self,refs):
            frozen=self.store.get_frozen(self.run_id,'source_manifest')
            all_refs=[r['version_ref'] for r in frozen.payload['items']]
            assert refs in (all_refs[:100],all_refs[100:])
            if len(refs)==1: raise OSError('synthetic missing immutable second page')
            return deepcopy(self.rows[:100])
    result=module.freeze_source_evidence(store,run.run_id,Paged(store,run.run_id,rows),previous_cutoff=LOWER,lease=lease,now=FREEZE).payload
    assert result['items']==[] and result['facts_only']
    assert 'immutable_versions_unavailable' in result['degraded_reasons']
    assert len(store.get_frozen(run.run_id,'source_manifest').payload['items'])==101


def test_owner_consumes_actual_stdlib_client_and_keeps_preselection_durable_boundary(core,tmp_path,monkeypatch):
    from io import BytesIO
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'lib-bursawatch-control/bin'))
    from source_evidence_client import SourceEvidenceClient
    module=core('evidence'); store,run,lease=owner(core,tmp_path)
    rows=[source(1)]; captured=manifest(rows)
    class Response:
        def __init__(self,body): self.body=BytesIO(json.dumps(body).encode())
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def read(self,size): return self.body.read(size)
    def transport(request,timeout):
        fields=json.loads(request.data)
        if request.full_url.endswith('/capture'):
            assert fields['previous_cutoff']==LOWER and fields['cutoff']==UPPER
            return Response(captured)
        saved=store.get_frozen(run.run_id,'source_manifest')
        assert saved is not None and fields['version_refs']==[saved.payload['items'][0]['version_ref']]
        return Response({'api_version':1,'items':rows})
    client=SourceEvidenceClient('http://127.0.0.1:9120','synthetic-reader',opener=transport)
    result=module.freeze_source_evidence(store,run.run_id,client,previous_cutoff=LOWER,lease=lease,now=FREEZE)
    assert result.payload['facts_only'] is False and result.payload['items'][0]['evidence_hash']==rows[0]['evidence_hash']


def test_missing_collecting_publisher_retains_unknown_and_is_incomplete(core):
    result=core('evidence').select_evidence([source(1,publisher=None)])
    assert result['items'][0]['publisher_id']=='unknown'
    assert result['items'][0]['origin_status']=='unknown' and result['items'][0]['independent_opinion'] is False
    assert 'missing_publisher' in result['degraded_reasons']


def _grace_extras(gap, status):
    from datetime import datetime, timedelta
    captured = (datetime.fromisoformat(UPPER) + timedelta(seconds=gap)).isoformat()
    return dict(capture_status=status, captured_at=captured, capture_gap_seconds=gap)


def test_realistic_capture_gap_within_grace_is_on_time_and_reaches_generated_path(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(1)]
    capture = manifest(rows, **_grace_extras(4.2, 'on_time'))
    result = module.freeze_source_evidence(store, run.run_id, CapturedClient(store, run.run_id, rows, capture),
                                           previous_cutoff=LOWER, lease=lease, now=FREEZE).payload
    assert result['capture_status'] == 'on_time' and result['capture_gap_seconds'] == 4.2
    assert result['degraded_reasons'] == [] and result['facts_only'] is False


def test_capture_gap_beyond_grace_stays_late_and_facts_only(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(1)]
    capture = manifest(rows, complete=False, **_grace_extras(121, 'late'))
    result = module.freeze_source_evidence(store, run.run_id, CapturedClient(store, run.run_id, rows, capture),
                                           previous_cutoff=LOWER, lease=lease, now=FREEZE).payload
    assert 'late_capture' in result['degraded_reasons'] and result['facts_only']
    assert result['capture_gap_seconds'] == 121


class FlakyCapture(CapturedClient):
    def __init__(self, *args, failures):
        super().__init__(*args)
        self.failures, self.calls = failures, 0
    def capture_window(self, previous, cutoff, limit=1000):
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError('transient')
        return super().capture_window(previous, cutoff, limit)


def test_transient_capture_failure_freezes_facts_only_without_retry(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    rows = [source(1)]
    client = FlakyCapture(store, run.run_id, rows, failures=2)
    result = module.freeze_source_evidence(store, run.run_id, client, previous_cutoff=LOWER, lease=lease, now=FREEZE).payload
    assert client.calls == 1 and result['facts_only'] is True and result['items'] == []


def test_capture_unavailable_is_frozen_after_first_failure(core, tmp_path):
    module = core('evidence')
    store, run, lease = owner(core, tmp_path)
    client = FlakyCapture(store, run.run_id, [source(1)], failures=99)
    result = module.freeze_source_evidence(store, run.run_id, client, previous_cutoff=LOWER, lease=lease, now=FREEZE).payload
    assert client.calls == 1
    assert 'capture_unavailable' in result['degraded_reasons'] and result['facts_only']
    assert store.get_frozen(run.run_id, 'source_manifest').payload['status'] == 'unavailable'
