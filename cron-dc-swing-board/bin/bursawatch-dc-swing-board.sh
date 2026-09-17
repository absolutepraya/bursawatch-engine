#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
SWING_FORMAT_BIN="$HOME/.agents/skills/lib-swing-format/bin"
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  SWING_FORMAT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/lib-swing-format/bin"
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  printf '%s FATAL: shared Swing formatter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SWING_FORMAT_BIN" >&2
  exit 127
fi
export PYTHONPATH="$SWING_FORMAT_BIN:${PYTHONPATH-}"

# The owner needs only the Discord bot identity. Do not source an environment
# file wholesale because watcher credentials do not belong in this process.
if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export DISCORD_BOT_TOKEN="$value"
fi

# Bootstrap is an explicitly invoked historical read/backfill command. It
# alone needs the Phintraco parser and its Telegram-resilience credentials.
if [[ "${1:-}" == "bootstrap" ]]; then
  for key in TELEGRAM_API_ID TELEGRAM_API_HASH POLYCOP_SESSION_STRING; do
    value="$(grep -E "^${key}=" "$HOME/.hermes/.env" 2>/dev/null | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "${key}=${value}"
  done
  resilience_bin="$HOME/.agents/skills/lib-telegram-resilience/bin"
  phintraco_bin="$HOME/.agents/skills/bursawatch-tg-phintraco-swing/bin"
  if [[ ! -r "$resilience_bin/telegram_resilience.py" || ! -r "$phintraco_bin/scan.py" ]]; then
    printf '%s FATAL: bootstrap dependencies unavailable\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >&2
    exit 127
  fi
  export PYTHONPATH="$resilience_bin:$phintraco_bin:${PYTHONPATH}"
fi

export IDX_SWING_PLAN_BOARD_STATE_PATH="${IDX_SWING_PLAN_BOARD_STATE_PATH:-$HOME/.hermes/state/idx-swing-board.sqlite3}"
export IDX_SWING_PLAN_BOARD_MEDIA_ROOT="${IDX_SWING_PLAN_BOARD_MEDIA_ROOT:-$HOME/.hermes/state/idx-swing-board-media}"

PYTHON_BIN="${IDX_SWING_PLAN_BOARD_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="${IDX_SWING_PLAN_BOARD_SCRIPT:-$HOME/.agents/skills/bursawatch-dc-swing-board/bin/board.py}"
exec "$PYTHON_BIN" "$SCRIPT" "$@"
