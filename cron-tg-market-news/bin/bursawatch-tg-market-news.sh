#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"
CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
if [[ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]]; then
  printf '%s FATAL: telegram resilience module missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$RESILIENCE_BIN" >&2
  exit 127
fi
if [[ -d "$CONTROL_PLANE_BIN" ]]; then
  export PYTHONPATH="$CONTROL_PLANE_BIN:$RESILIENCE_BIN:${PYTHONPATH-}"
else
  export PYTHONPATH="$RESILIENCE_BIN:${PYTHONPATH-}"
fi

# Hermes does not pass its environment file through to cron subprocesses. Import
# only this watcher's four runtime secrets, preserving values verbatim after '='.
if [[ -r "$HOME/.hermes/.env" ]]; then
  for key in DISCORD_BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH POLYCOP_SESSION_STRING \
    IDX_MARKET_NEWS_CONTROL_PLANE_URL \
    IDX_MARKET_NEWS_CONTROL_PLANE_WATCHER_ID \
    IDX_MARKET_NEWS_CONTROL_PLANE_TOKEN \
    IDX_MARKET_NEWS_CONTROL_PLANE_TIMEOUT_SECONDS \
    IDX_MARKET_NEWS_CONTROL_PLANE_SPOOL_PATH; do
    value="$(grep -E "^${key}=" "$HOME/.hermes/.env" | head -n 1 | cut -d= -f2- || true)"
    if [[ -n "$value" ]]; then
      export "${key}=${value}"
    fi
  done
fi

PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
SCRIPT="$HOME/.agents/skills/bursawatch-tg-market-news/bin/scan.py"
STATE_PATH="${IDX_MARKET_NEWS_STATE_PATH:-$HOME/.hermes/state/idx-market-news.json}"
export IDX_MARKET_NEWS_STATE_PATH="$STATE_PATH"
install -d -m 700 "$(dirname "$STATE_PATH")"
LOG_DIR="$HOME/.logs"
LOG="$LOG_DIR/bursawatch-tg-market-news.log"
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
