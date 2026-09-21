#!/usr/bin/env bash
set -euo pipefail

exec /usr/bin/python3 /home/praya/.local/lib/bursawatch-release/release_agent.py "$@"
