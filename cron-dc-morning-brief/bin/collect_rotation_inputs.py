#!/usr/bin/env python3
"""Collect a bounded Sectors-cap and Yahoo-price rotation chunk, never publish or invoke a writer."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
for name in ('lib-sectors','lib-chart-img','lib-yahoo-market-data','lib-bursawatch-control','lib-bursawatch-discord-delivery'):
    sys.path.insert(0,str(ROOT/name/'bin'))

from morning_brief.calendar import SessionCalendar
from morning_brief.config import OWNER, load_operator_config_data, timing_for
from morning_brief.host import HostConfig, CONTROL_URL, private_file, token
from morning_brief.inputs import load_sector_membership, load_konglo_csv
from morning_brief.rotation_collector import collect_rotation
from morning_brief.scheduled import ProducerConfig
from morning_brief.sectors_caps import configured_rotation


def load_references(path):
    value=json.loads(private_file(path,max_bytes=16_000))
    if set(value)!={'sectors','konglo'}:
        raise ValueError('explicit fixed membership references required')
    for row in value.values():
        if not Path(row['path']).is_absolute():
            raise ValueError('absolute retained membership path required')
        raw=private_file(row['path'],max_bytes=2_000_000)
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('membership reference digest mismatch')
    sector,konglo=value['sectors'],value['konglo']
    return dict(sectors=load_sector_membership(sector['path'],version=sector['version'],
                    official_check_reference=sector['official_check_reference'],source_url=sector['source_url']),
                konglo=load_konglo_csv(konglo['path'],version=konglo['version'],source_url=konglo['source_url']))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-config',type=Path,required=True)
    parser.add_argument('--calendar-snapshot',type=Path,required=True)
    parser.add_argument('--references',type=Path,required=True)
    parser.add_argument('--source-cache',type=Path,required=True)
    parser.add_argument('--producer-config',type=Path,required=True)
    parser.add_argument('--request-limit',type=int,default=24)
    parser.add_argument('--collect-public',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        from control_plane_client import fetch_config
        config=HostConfig.from_file(args.runtime_config)
        snapshot=fetch_config(CONTROL_URL,OWNER,token(config.config_token_file))
        settings=load_operator_config_data(snapshot.config)
        now=datetime.now(timezone.utc)
        raw=private_file(args.calendar_snapshot,max_bytes=512_000); reference=json.loads(raw)
        calendar=SessionCalendar.from_file(args.calendar_snapshot,expected_version=reference['version'],
            expected_amendment=reference['amendment'],as_of=now)
        candidates=[day for day in calendar.sessions if timing_for(day,settings)['cutoff']>now]
        if not candidates: raise ValueError('verified upcoming publication session unavailable')
        session=candidates[0]
        producer=ProducerConfig.from_file(args.producer_config)
        if str(args.source_cache)!=producer.source_cache:
            raise ValueError('producer source cache must match configured cache')
        result=configured_rotation(producer,collect_rotation)(memberships=load_references(args.references),calendar=calendar,
            publication_session=session,cutoff=timing_for(session,settings)['cutoff'],
            source_cache=args.source_cache,now=now,request_limit=args.request_limit)
    except Exception as error:
        result=dict(manifest_written=False,reason=type(error).__name__,posts=False)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['manifest_written'] else 2


if __name__=='__main__':
    raise SystemExit(main())
