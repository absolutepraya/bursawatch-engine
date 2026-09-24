#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
if [[ ! -r "$CONTROL_PLANE_BIN/control_plane_client.py" ]]; then
  printf '%s FATAL: Bursawatch control-plane client library is missing\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >&2
  exit 127
fi
export PYTHONPATH="$CONTROL_PLANE_BIN${PYTHONPATH:+:$PYTHONPATH}"
unset STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH

if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -n 1 | cut -d= -f2- || true)"
  if [[ -n "$value" ]]; then
    export DISCORD_BOT_TOKEN="$value"
  fi
  # A release no-post run still needs the mandatory read-only config GET.
  for key in STOCKBIT_SNIPS_CONTROL_PLANE_URL \
    STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID \
    STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN \
    STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS; do
    value="$(grep -E "^${key}=" "$HOME/.hermes/.env" | head -n 1 | cut -d= -f2- || true)"
    if [[ -n "$value" ]]; then
      export "${key}=${value}"
    fi
  done
fi

PYTHON_BIN="${STOCKBIT_SNIPS_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="${STOCKBIT_SNIPS_BIN:-$HOME/.agents/skills/bursawatch-stockbit-snips/bin/scan.py}"
STATE_PATH="${STOCKBIT_SNIPS_STATE_PATH:-$HOME/.hermes/state/stockbit-snips.json}"
export STOCKBIT_SNIPS_STATE_PATH="$STATE_PATH"
install -d -m 700 "$(dirname "$STATE_PATH")"

if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  LOG_DIR="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}"
else
  LOG_DIR="$HOME/.logs"
fi
LOG="$LOG_DIR/bursawatch-stockbit-snips.log"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '%s FATAL: python interpreter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$PYTHON_BIN" >> "$LOG"
  exit 127
fi

set +e
"$PYTHON_BIN" "$SCRIPT" "$@" 2>&1 | tee -a "$LOG"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
