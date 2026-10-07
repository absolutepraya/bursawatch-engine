"""Local integration contracts, no runtime activation or credentials."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def test_unprovisioned_morning_and_provider_units_are_manual_and_depend_on_owners():
    manifest=json.loads((ROOT/'platform-bursawatch-release/release-manifest.json').read_text())
    units={unit['id']:unit for unit in manifest['units']}
    for name in ['lib-sectors','lib-chart-img','lib-yahoo-market-data','cron-dc-morning-brief']:
        assert name in units
        assert units[name]['handler']=='manual'
    assert {'lib-sectors','lib-chart-img','lib-yahoo-market-data','lib-bursawatch-control','lib-bursawatch-discord-delivery','manual-discord-delivery-owner'} <= set(units['cron-dc-morning-brief']['depends_on'])
    assert sum('GLOSSARY.md' in unit['paths'] for unit in units.values())==1

def test_provider_env_links_preserve_conflicts_without_reading_contents(tmp_path):
    main=tmp_path/'main'; work=tmp_path/'work'
    for name in ['service-bursawatch-control','lib-sectors','lib-chart-img']:
        (main/name).mkdir(parents=True);(work/name).mkdir(parents=True)
        (main/name/'.env').write_text('synthetic-placeholder')
    helper=ROOT/'scripts/prepare-control-plane-worktree.sh'
    first=subprocess.run(['bash',str(helper),str(main),str(work)],capture_output=True,text=True)
    assert first.returncode==0
    for name in ['service-bursawatch-control','lib-sectors','lib-chart-img']:
        assert (work/name/'.env').is_symlink()
    (work/'lib-chart-img/.env').unlink();(work/'lib-chart-img/.env').write_text('keep-local')
    conflict=subprocess.run(['bash',str(helper),str(main),str(work)],capture_output=True,text=True)
    assert conflict.returncode==1
    assert (work/'lib-chart-img/.env').read_text()=='keep-local'

def test_new_package_suites_and_postgres_source_contract_are_registered():
    suites=(ROOT/'scripts/test-all').read_text()
    for name in ['lib-sectors','lib-chart-img','lib-yahoo-market-data','cron-dc-morning-brief']:
        assert f'run_suite {name} {name} tests' in suites
    assert 'test_source_evidence_postgres.py' in (ROOT/'.github/workflows/ci.yml').read_text()

def test_default_cli_no_data_is_no_post_and_does_not_discover_credentials(tmp_path):
    import sys
    cli=ROOT/'cron-dc-morning-brief/bin/runner.py'
    result=subprocess.run([sys.executable,str(cli),'--preview-dir',str(tmp_path/'preview')],capture_output=True,text=True)
    assert result.returncode==0
    summary=json.loads(result.stdout)
    assert summary['phase']=='no_data' and summary['heartbeat']['simulated'] is True
    assert summary['network'] is False and summary['credentials'] is False


def test_cli_invalid_input_and_naive_time_emit_safe_fatal_heartbeat(tmp_path):
    import sys
    cli=ROOT/'cron-dc-morning-brief/bin/runner.py'
    bad=tmp_path/'bad.json'; bad.write_text('{"secret":"do-not-print"')
    invalid_calendar=tmp_path/'calendar.json'
    invalid_calendar.write_text(json.dumps({'calendar_path':str(tmp_path/'missing-calendar'),
        'calendar_version':'invalid','calendar_amendment':'invalid'}))
    for extra in (["--input",str(bad),"--state",str(tmp_path/'runs')],
                  ["--input",str(invalid_calendar),"--state",str(tmp_path/'runs')],
                  ["--as-of","2026-10-05T07:56:00"]):
        result=subprocess.run([sys.executable,str(cli),'--preview-dir',str(tmp_path/'preview'),*extra],
                              capture_output=True,text=True)
        assert result.returncode==1
        summary=json.loads(result.stdout)
        assert summary['phase']=='fatal'
        assert summary['heartbeat']['simulated'] is True
        assert summary['heartbeat']['destination']=='1505162000420835388'
        assert 'failed:' in summary['heartbeat']['text']
        assert 'do-not-print' not in result.stdout+result.stderr
