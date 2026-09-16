#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/idx-swing-plan-board.sh}"
RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"
SWING_FORMAT_BIN="$HOME/.agents/skills/swing-format/bin"
if [[ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]]; then
  printf '%s FATAL: telegram resilience module missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$RESILIENCE_BIN" >&2
  exit 127
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  SWING_FORMAT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/swing-format/bin"
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  printf '%s FATAL: shared Swing formatter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SWING_FORMAT_BIN" >&2
  exit 127
fi
export PYTHONPATH="$SWING_FORMAT_BIN:$RESILIENCE_BIN:${PYTHONPATH-}"

if [[ -r "$HOME/.hermes/.env" ]]; then
  for k in DISCORD_BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH POLYCOP_SESSION_STRING; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
fi

PYTHON_BIN="${IDX_SWING_WATCH_PHINTRACO_DAILY_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="$HOME/.agents/skills/idx-swing-watch-phintraco-daily/bin/scan.py"
LOG="$HOME/.logs/idx-swing-watch-phintraco-daily.log"
mkdir -p "$HOME/.logs"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "$(ts) FATAL: python missing at $PYTHON_BIN" | tee -a "$LOG" >&2
  exit 127
fi

echo "$(ts) START idx-swing-watch-phintraco-daily $*" >> "$LOG"
set +e
out="$("$PYTHON_BIN" "$SCRIPT" "$@" 2> >(tee -a "$LOG" >&2))"
rc=$?
set -e
printf '%s\n' "$out" | tee -a "$LOG"
echo "$(ts) END rc=$rc" >> "$LOG"
exit "$rc"
