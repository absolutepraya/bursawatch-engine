#!/usr/bin/env python3
"""Reviewed scheduler entrypoint; check mode never creates state or posts."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

ROOT=Path(__file__).resolve().parents[2]
for name in ('lib-sectors','lib-chart-img','lib-yahoo-market-data','lib-bursawatch-control','lib-bursawatch-discord-delivery'):
    sys.path.insert(0,str(ROOT/name/'bin'))

from collect_rotation_inputs import load_references
from morning_brief.config import OWNER, load_operator_config_data, weekday_delivery
from morning_brief.host import HostConfig, CONTROL_URL, readiness, token, production_runtime, failure_heartbeat
from morning_brief.public_collector import collect_public
from morning_brief.rotation_collector import collect_rotation
from morning_brief.scheduled import ProducerConfig, ScheduledRuntime
from morning_brief.store import canonical


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-config',type=Path,required=True)
    parser.add_argument('--producer-config',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--live',action='store_true')
    args=parser.parse_args(argv);config=None
    try:
        config=HostConfig.from_file(args.runtime_config);producer=ProducerConfig.from_file(args.producer_config)
        if args.check:
            from control_plane_client import fetch_config
            snapshot={'api_version':1,**asdict(fetch_config(CONTROL_URL,OWNER,token(config.config_token_file)))}
            reference_gap=False
            try:load_references(producer.references)
            except (OSError,ValueError,KeyError,TypeError):
                if not weekday_delivery(load_operator_config_data(snapshot['config'])):raise
                reference_gap=True
            result=readiness(config,snapshot=snapshot,now=datetime.now(timezone.utc))
            if reference_gap:result['gaps'].append('rotation_membership_references_unavailable')
            status=0 if result['ready'] else 2
        else:
            cache=Path(producer.source_cache)
            if cache.is_symlink():raise ValueError('private scheduler cache required')
            cache.mkdir(mode=0o700,parents=True,exist_ok=True)
            if cache.stat().st_mode & 0o077:raise ValueError('private scheduler cache required')
            fd=os.open(cache/'scheduled-owner.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'r+b') as lock:
                details=os.fstat(lock.fileno())
                if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
                    raise ValueError('private scheduler owner lock required')
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    result=production_runtime(config).beat(dict(phase='owner_busy',reason='scheduled_owner_busy'))
                    status=0
                else:
                    clock=lambda:datetime.now(timezone.utc)
                    host=production_runtime(config,clock=clock)
                    result=ScheduledRuntime(host,producer,collect_rotation=collect_rotation,collect_public=collect_public,
                        load_memberships=load_references,clock=clock).tick()
                    status=1 if result['phase']=='fatal' else 0
    except Exception as error:
        result=dict(ready=False,reason=type(error).__name__,posts=False);status=2
        if args.live and config is not None:
            try:result=failure_heartbeat(config,error)
            except Exception:result['heartbeat']={'status':'unresolved'}
    print(canonical(result));return status


if __name__=='__main__':raise SystemExit(main())
