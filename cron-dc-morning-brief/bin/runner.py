#!/usr/bin/env python3
"""Local no-post review entrypoint. Live transports are separately injected."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
for name in ('lib-sectors','lib-chart-img','lib-bursawatch-control','lib-bursawatch-discord-delivery'):
    sys.path.insert(0,str(ROOT/name/'bin'))
from morning_brief.calendar import SessionCalendar
from morning_brief.runner import MorningRunner, HEARTBEAT_DESTINATION, OWNER
from morning_brief.store import RunStore, canonical


class NoTransport:
    def __getattr__(self,name):
        def unavailable(*args,**kwargs): raise RuntimeError('preview transport unavailable')
        return unavailable


def safe_preview_result(phase, now, directory, *, reason=None):
    local=now.astimezone(ZoneInfo('Asia/Jakarta'))
    if phase=='fatal':
        content=f'❌ {OWNER} · {local:%H:%M} WIB · failed: {reason}'
    else:
        content=f'🫀 {OWNER} · {local:%H:%M} WIB · phase=no_data cache_hits=unknown cache_misses=unknown reserved=unknown spent=unknown uncertain=unknown gaps=unknown fallback=none images_omitted=0 receipts=none late_s=0'
    heartbeat=dict(destination=HEARTBEAT_DESTINATION,simulated=True,text=content)
    if directory:
        try:
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            (directory/'heartbeat.json').write_text(canonical(heartbeat))
        except OSError:
            pass
    result=dict(phase=phase,network=False,credentials=False,heartbeat=heartbeat)
    if reason: result['reason']=reason
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,help='explicit retained input manifest, never discovered')
    parser.add_argument('--state',type=Path,help='explicit private local run database')
    parser.add_argument('--preview-dir',type=Path)
    parser.add_argument('--as-of',help='aware timestamp for explicit synthetic/local fixture review')
    args=parser.parse_args(argv)
    now=datetime.now(timezone.utc)
    try:
        if args.as_of:
            now=datetime.fromisoformat(args.as_of)
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError('aware fixture timestamp required')
        if args.input is None:
            result=safe_preview_result('no_data',now,args.preview_dir)
        else:
            if args.state is None: raise ValueError('explicit private state required')
            fields=json.loads(args.input.read_text())
            calendar=SessionCalendar.from_file(Path(fields['calendar_path']),expected_version=fields['calendar_version'],
                expected_amendment=fields['calendar_amendment'],as_of=now)
            transport=NoTransport()
            runner=MorningRunner(RunStore(args.state),transport,transport,transport,clock=lambda:now)
            result=runner.run(calendar=calendar,numerical=fields.get('numerical',{}),global_inputs=fields.get('global_inputs',[]),
                calendar_snapshots=fields.get('calendar_snapshots',[]),model=None,model_version=fields['model_version'],
                prompt_version=fields['prompt_version'],preview=True,preview_dir=args.preview_dir)
            result.update(network=False,credentials=False)
    except Exception as error:
        result=safe_preview_result('fatal',datetime.now(timezone.utc),args.preview_dir,reason=type(error).__name__)
    print(canonical(result))
    return 1 if result['phase']=='fatal' else 0


if __name__=='__main__': raise SystemExit(main())
