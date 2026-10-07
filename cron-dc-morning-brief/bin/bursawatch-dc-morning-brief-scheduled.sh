#!/usr/bin/env bash
set -euo pipefail
export TZ='Asia/Jakarta'
RUNTIME_HOME="$HOME/.agents/skills/bursawatch-dc-morning-brief"
HERMES_ROOT="$HOME/.hermes/hermes-agent"
PYTHON_BIN="$HERMES_ROOT/venv/bin/python"
export PYTHONPATH="$RUNTIME_HOME/bin:$HOME/.agents/skills/lib-sectors/bin:$HOME/.agents/skills/lib-chart-img/bin:$HOME/.agents/skills/lib-yahoo-market-data/bin:$HOME/.agents/skills/lib-bursawatch-control/bin:$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin:$HERMES_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" "$RUNTIME_HOME/bin/scheduled_runner.py" \
  --runtime-config "$HOME/.hermes/bursawatch-morning-runtime.json" \
  --producer-config "$HOME/.hermes/bursawatch-morning-producer.json" "$@"
