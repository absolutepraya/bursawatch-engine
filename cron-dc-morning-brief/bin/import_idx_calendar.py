#!/usr/bin/env python3
"""Explicit, no-network import of retained official IDX calendar evidence."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
for name in ('lib-sectors','lib-chart-img','lib-bursawatch-control','lib-bursawatch-discord-delivery'):
    sys.path.insert(0,str(ROOT/name/'bin'))

from morning_brief.host import private_file
from morning_brief.idx_calendar_import import import_calendar
from morning_brief.store import canonical
from morning_brief.public_collector import write_once


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--listing-envelope',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        value=import_calendar(private_file(args.pdf,max_bytes=2_000_000),
            json.loads(private_file(args.listing_envelope,max_bytes=2_000_000)),now=datetime.now(timezone.utc))
        if not args.output.is_absolute():
            raise ValueError('explicit absolute new calendar output required')
        write_once(args.output,canonical(value).encode())
        result={'imported':True,'version':value['version'],'sessions':len(value['sessions']),
                'amendment_checked_at':value['amendment_checked_at'],'posts':False,'network':False}
    except Exception as error:
        result={'imported':False,'reason':type(error).__name__,'posts':False,'network':False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result['imported'] else 2


if __name__=='__main__':
    raise SystemExit(main())
