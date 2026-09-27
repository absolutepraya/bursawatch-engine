#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/home/praya/.agents/skills/lib-bursawatch-discord-delivery/bin${PYTHONPATH:+:$PYTHONPATH}"

exec /usr/bin/python3 /home/praya/.local/lib/bursawatch-release/release_agent.py "$@"
