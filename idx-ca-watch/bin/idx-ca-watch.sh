#!/usr/bin/env bash
set -euo pipefail

# Deterministic environment for the cron subprocess.
export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

# self-source secrets (Hermes does not propagate .env to subprocesses)
if [[ -r "$HOME/.hermes/.env" ]]; then
  for k in DISCORD_BOT_TOKEN CHART_IMG_API_KEY; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
fi

PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
SCRIPT="$HOME/.agents/skills/idx-ca-watch/bin/scan.py"
LOG_DIR="$HOME/.logs"; LOG="$LOG_DIR/idx-ca-watch.log"; mkdir -p "$LOG_DIR"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "$(ts) FATAL: python interpreter missing at $PYTHON_BIN" | tee -a "$LOG" >&2
  exit 127
fi

# Mirror stderr (diagnostics) to a durable log; capture stdout (the wakeAgent JSON
# contract) so it is both logged AND handed to Hermes unchanged for the wake gate.
echo "$(ts) START idx-ca-watch $*" >> "$LOG"
set +e
out="$("$PYTHON_BIN" "$SCRIPT" "$@" 2> >(tee -a "$LOG" >&2))"
rc=$?
set -e
printf '%s\n' "$out" | tee -a "$LOG"
echo "$(ts) END rc=$rc" >> "$LOG"
exit "$rc"
