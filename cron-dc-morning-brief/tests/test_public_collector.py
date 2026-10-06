from datetime import datetime, timedelta, timezone
from pathlib import Path

from morning_brief.public_collector import collect_public
from morning_brief.host import load_inputs
from test_host import setup_host, snapshot, FREEZE
from test_public_sources import native


class Transport:
    def __init__(self, observed, *, fail_benchmark=False):
        self.observed=observed;self.fail_benchmark=fail_benchmark;self.calls=[]

    def get(self,name,interval):
        self.calls.append((name,interval))
        if name=='IHSG' and self.fail_benchmark:
            raise TimeoutError('synthetic transport fixture')
        symbol,zone=('^JKSE','Asia/Jakarta') if name=='IHSG' else ('SPY','America/New_York')
        payload=native(symbol,zone,interval)
        if name=='IHSG':
            rows=[dict(start=int(datetime(2026,10,d,2,tzinfo=timezone.utc).timestamp()),
                       end=int(datetime(2026,10,d,9,tzinfo=timezone.utc).timestamp())) for d in (1,2)]
            result=payload['chart']['result'][0]
            result['meta'].update(tradingPeriods=[[r] for r in rows],currentTradingPeriod={'regular':rows[-1]})
            result.update(timestamp=[r['start'] for r in rows])
        return dict(source_url='https://fixture.test/native',retrieved_at=self.observed.isoformat(),
                    source_sha256='0'*64,payload=payload)


def prepared(tmp_path):
    config,_=setup_host(tmp_path);snap=snapshot();snap['config']['instruments']=['SPY']
    from morning_brief.store import digest
    snap['config_sha256']=digest(snap['config'])
    import json
    reference=json.loads(Path(config.input_manifest).read_text())['calendar']['path']
    value=json.loads(Path(reference).read_text())
    value['sessions']=[day for day in value['sessions'] if day not in ('2026-10-03','2026-10-04')]
    Path(reference).write_text(json.dumps(value));Path(reference).chmod(0o600)
    return config,snap,reference


def test_collector_writes_actual_retained_inputs_without_posting_or_run_state(tmp_path):
    config,snap,reference=prepared(tmp_path);observed=FREEZE-timedelta(minutes=1)
    transport=Transport(observed)
    result=collect_public(config,snapshot=snap,calendar_path=reference,
        source_cache=tmp_path/'sources',now=observed,transport=transport,clock=lambda:observed)
    assert result['manifest_written'] and result['posts'] is False and result['paid_requests']==0
    assert len(transport.calls)==4 and not Path(config.run_store).exists()
    official,manifest=load_inputs(config.input_manifest,cutoff=FREEZE)
    assert manifest['provenance']=='live-retained'
    assert manifest['numerical']['benchmark']['2026-10-02']==102.
    # Native schedule coverage is insufficient for Sunday US time. Never fill it
    # with guessed hours, but keep the configured instrument's unavailable row.
    assert manifest['global_inputs'][0]['name']=='SPY'
    assert manifest['global_inputs'][0]['sessions']['verified'] is False
    assert 'SPY:verification:ValueError' in result['gaps']
    assert Path(config.input_manifest).stat().st_mode & 0o077==0
    assert len(list((tmp_path/'sources').glob('manifest-*.json')))==1


def test_failed_or_post_cutoff_benchmark_does_not_replace_existing_manifest(tmp_path):
    config,snap,reference=prepared(tmp_path);previous=Path(config.input_manifest).read_bytes()
    for transport in [Transport(FREEZE-timedelta(seconds=30),fail_benchmark=True),Transport(FREEZE+timedelta(seconds=1))]:
        result=collect_public(config,snapshot=snap,calendar_path=reference,
            source_cache=tmp_path/'sources',now=FREEZE-timedelta(minutes=1),transport=transport,
            clock=lambda:FREEZE-timedelta(seconds=10))
        assert not result['manifest_written'] and Path(config.input_manifest).read_bytes()==previous
        assert result['posts'] is False and not Path(config.run_store).exists()


def test_collection_after_a_freeze_never_backfills_that_session(tmp_path):
    import pytest
    config,snap,reference=prepared(tmp_path);transport=Transport(FREEZE)
    # Fixture coverage ends on this session, so there is no authorized future
    # session. A collector must not change its cutoff to rescue today's data.
    with pytest.raises(ValueError):
        collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
            now=FREEZE+timedelta(minutes=1),transport=transport)
    assert transport.calls==[] and not Path(config.run_store).exists()


def test_late_preparation_never_backdates_manifest_availability(tmp_path):
    config,snap,reference=prepared(tmp_path);previous=Path(config.input_manifest).read_bytes()
    observed=FREEZE-timedelta(seconds=30)
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=Transport(observed),clock=lambda:FREEZE+timedelta(seconds=1))
    assert not result['manifest_written'] and 'preparation_not_visible_at_cutoff' in result['gaps']
    assert Path(config.input_manifest).read_bytes()==previous
