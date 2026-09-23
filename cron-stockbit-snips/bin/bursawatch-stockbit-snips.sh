#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -n 1 | cut -d= -f2- || true)"
  if [[ -n "$value" ]]; then
    export DISCORD_BOT_TOKEN="$value"
  fi
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
