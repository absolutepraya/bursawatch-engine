#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

# The owner needs only the Discord bot identity. Do not source an environment
# file wholesale because watcher credentials do not belong in this process.
if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export DISCORD_BOT_TOKEN="$value"
fi

export IDX_SWING_PLAN_BOARD_STATE_PATH="${IDX_SWING_PLAN_BOARD_STATE_PATH:-$HOME/.hermes/state/idx-swing-board.sqlite3}"
export IDX_SWING_PLAN_BOARD_MEDIA_ROOT="${IDX_SWING_PLAN_BOARD_MEDIA_ROOT:-$HOME/.hermes/state/idx-swing-board-media}"

PYTHON_BIN="${IDX_SWING_PLAN_BOARD_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="${IDX_SWING_PLAN_BOARD_SCRIPT:-$HOME/.agents/skills/idx-swing-plan-board/bin/board.py}"
exec "$PYTHON_BIN" "$SCRIPT" "$@"
