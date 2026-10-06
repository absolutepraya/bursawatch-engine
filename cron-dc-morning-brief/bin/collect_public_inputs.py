#!/usr/bin/env python3
"""Explicit public-source collection; never calls the publication dispatcher."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
for name in ('lib-sectors','lib-chart-img','lib-bursawatch-control','lib-bursawatch-discord-delivery'):
    sys.path.insert(0,str(ROOT/name/'bin'))

from morning_brief.host import HostConfig, CONTROL_URL, token, private_file
from morning_brief.config import OWNER
from morning_brief.public_collector import collect_public


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-config',type=Path,required=True)
    parser.add_argument('--calendar-snapshot',type=Path,required=True)
    parser.add_argument('--source-cache',type=Path,required=True)
    parser.add_argument('--economic-snapshot',type=Path,action='append',default=[])
    parser.add_argument('--collect-public',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        from control_plane_client import fetch_config
        config=HostConfig.from_file(args.runtime_config)
        snapshot={'api_version':1,**asdict(fetch_config(CONTROL_URL,OWNER,token(config.config_token_file)))}
        result=collect_public(config,snapshot=snapshot,calendar_path=args.calendar_snapshot,
            source_cache=args.source_cache,now=datetime.now(timezone.utc),
            economic_snapshots=[json.loads(private_file(path,max_bytes=2_000_000)) for path in args.economic_snapshot])
    except Exception as error:
        result={'manifest_written':False,'reason':type(error).__name__,'posts':False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result['manifest_written'] else 2


if __name__=='__main__':
    raise SystemExit(main())
