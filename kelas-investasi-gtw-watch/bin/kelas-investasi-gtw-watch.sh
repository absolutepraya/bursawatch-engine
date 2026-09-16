#!/usr/bin/env bash
set -uo pipefail

env_file="$HOME/.hermes/.env"
log_file="$HOME/.logs/kelas-investasi-gtw-watch.log"
python_bin="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/idx-swing-plan-board.sh}"
mkdir -p "$(dirname "$log_file")"

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    DISCORD_BOT_TOKEN=*|TELEGRAM_API_ID=*|TELEGRAM_API_HASH=*|POLYCOP_SESSION_STRING=*) export "$line" ;;
  esac
done < "$env_file"

SWING_FORMAT_BIN="$HOME/.agents/skills/swing-format/bin"
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  SWING_FORMAT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/swing-format/bin"
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  printf '%s FATAL: shared Swing formatter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SWING_FORMAT_BIN" >&2
  exit 127
fi
export PYTHONPATH="$SWING_FORMAT_BIN:$HOME/.agents/skills/telegram-resilience/bin"
set +e
"$python_bin" "$HOME/.agents/skills/kelas-investasi-gtw-watch/bin/scan.py" "$@" 2>&1 | sed -E 's/(POLYCOP_SESSION_STRING|DISCORD_BOT_TOKEN|TELEGRAM_API_ID|TELEGRAM_API_HASH)=[^[:space:]]+/\1=<redacted>/g' | tee -a "$log_file"
status=${PIPESTATUS[0]}
exit "$status"
