#!/usr/bin/env bash
set -uo pipefail

env_file="$HOME/.hermes/.env"
log_file="$HOME/.logs/bursawatch-tg-kelas-investasi-gtw.log"
if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  log_file="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}/bursawatch-tg-kelas-investasi-gtw.log"
fi
python_bin="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
mkdir -p "$(dirname "$log_file")"

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    DISCORD_BOT_TOKEN=*|TELEGRAM_API_ID=*|TELEGRAM_API_HASH=*|POLYCOP_SESSION_STRING=*) export "$line" ;;
    KELAS_INVESTASI_GTW_CONTROL_PLANE_URL=*|KELAS_INVESTASI_GTW_CONTROL_PLANE_WATCHER_ID=*|KELAS_INVESTASI_GTW_CONTROL_PLANE_TOKEN=*|KELAS_INVESTASI_GTW_CONTROL_PLANE_TIMEOUT_SECONDS=*|KELAS_INVESTASI_GTW_CONTROL_PLANE_SPOOL_PATH=*)
      [[ "${BURSAWATCH_RELEASE_NO_POST:-}" != "1" ]] && export "$line"
      ;;
  esac
done < "$env_file"

SWING_FORMAT_BIN="$HOME/.agents/skills/lib-swing-format/bin"
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  SWING_FORMAT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/lib-swing-format/bin"
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  printf '%s FATAL: shared Swing formatter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SWING_FORMAT_BIN" >&2
  exit 127
fi
if [[ -d "$CONTROL_PLANE_BIN" ]]; then
  export PYTHONPATH="$CONTROL_PLANE_BIN:$SWING_FORMAT_BIN:$HOME/.agents/skills/lib-telegram-resilience/bin:${PYTHONPATH-}"
else
  export PYTHONPATH="$SWING_FORMAT_BIN:$HOME/.agents/skills/lib-telegram-resilience/bin:${PYTHONPATH-}"
fi
set +e
"$python_bin" "$HOME/.agents/skills/bursawatch-tg-kelas-investasi-gtw/bin/scan.py" "$@" 2>&1 | sed -E 's/(POLYCOP_SESSION_STRING|DISCORD_BOT_TOKEN|TELEGRAM_API_ID|TELEGRAM_API_HASH)=[^[:space:]]+/\1=<redacted>/g' | tee -a "$log_file"
status=${PIPESTATUS[0]}
exit "$status"
