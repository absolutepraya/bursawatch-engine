#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"
if [[ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]]; then
  printf '%s FATAL: telegram resilience module missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$RESILIENCE_BIN" >&2
  exit 127
fi
export PYTHONPATH="$RESILIENCE_BIN:${PYTHONPATH-}"

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
