#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
SWING_FORMAT_BIN="$HOME/.agents/skills/lib-swing-format/bin"
CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  SWING_FORMAT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/lib-swing-format/bin"
fi
if [[ ! -r "$SWING_FORMAT_BIN/swing_format.py" ]]; then
  printf '%s FATAL: shared Swing formatter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SWING_FORMAT_BIN" >&2
  exit 127
fi
if [[ ! -r "$DELIVERY_CLIENT_BIN/bursawatch_discord_delivery/client.py" ]]; then
  DELIVERY_CLIENT_BIN="$(cd "$(dirname "$0")/../.." && pwd)/lib-bursawatch-discord-delivery/bin"
fi
if [[ ! -r "$DELIVERY_CLIENT_BIN/bursawatch_discord_delivery/client.py" ]]; then
  printf '%s FATAL: shared Discord delivery client missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$DELIVERY_CLIENT_BIN" >&2
  exit 127
fi
if [[ -d "$CONTROL_PLANE_BIN" ]]; then
  export PYTHONPATH="$DELIVERY_CLIENT_BIN:$CONTROL_PLANE_BIN:$SWING_FORMAT_BIN:${PYTHONPATH-}"
else
  export PYTHONPATH="$DELIVERY_CLIENT_BIN:$SWING_FORMAT_BIN:${PYTHONPATH-}"
fi

# The Delivery Owner owns bot credentials and Discord API calls. Only its
# loopback client address and private token-file path are passed to the Board.
if [[ -r "$HOME/.hermes/.env" ]]; then
  if [[ "${IDX_SWING_PLAN_BOARD_NO_POST:-}" != "1" ]]; then
    for key in BURSAWATCH_DISCORD_DELIVERY_URL BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE; do
      value="$(grep -E "^${key}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
      [[ -n "$value" ]] && export "${key}=${value}"
    done
  fi
  if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" != "1" ]]; then
    for key in IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL \
      IDX_SWING_PLAN_BOARD_CONTROL_PLANE_WATCHER_ID \
      IDX_SWING_PLAN_BOARD_CONTROL_PLANE_TOKEN \
      IDX_SWING_PLAN_BOARD_CONTROL_PLANE_TIMEOUT_SECONDS \
      IDX_SWING_PLAN_BOARD_CONTROL_PLANE_SPOOL_PATH; do
      value="$(grep -E "^${key}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
      [[ -n "$value" ]] && export "${key}=${value}"
    done
  fi
fi

if [[ "${IDX_SWING_PLAN_BOARD_NO_POST:-}" != "1" ]]; then
  export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9140}"
  export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"
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
