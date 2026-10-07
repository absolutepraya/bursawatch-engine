#!/usr/bin/env python3
"""Explicit production dispatcher. --check is read-only and never posts."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for name in ('lib-sectors', 'lib-chart-img', 'lib-yahoo-market-data', 'lib-bursawatch-control', 'lib-bursawatch-discord-delivery'):
    sys.path.insert(0, str(ROOT / name / 'bin'))

from morning_brief.host import HostConfig, CONTROL_URL, failure_heartbeat, production_runtime, readiness, token
from morning_brief.config import OWNER
from morning_brief.store import canonical


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-config', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    config = None
    try:
        config = HostConfig.from_file(args.runtime_config)
        if args.check:
            from control_plane_client import fetch_config
            snapshot = {'api_version': 1, **asdict(fetch_config(CONTROL_URL, OWNER, token(config.config_token_file)))}
            result = readiness(config, snapshot=snapshot, now=datetime.now(timezone.utc))
            status = 0 if result['ready'] else 2
        else:
            result = production_runtime(config).tick()
            status = 1 if result['phase'] == 'fatal' else 0
    except Exception as error:
        result = {'ready': False, 'reason': type(error).__name__, 'posts': False}
        if args.live and config is not None:
            try:
                result = failure_heartbeat(config, error)
            except Exception:
                result['heartbeat'] = {'status': 'unresolved'}
        status = 2
    print(canonical(result))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
