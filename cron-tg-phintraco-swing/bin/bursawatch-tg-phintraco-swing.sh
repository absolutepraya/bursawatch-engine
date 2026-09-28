#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"
SWING_FORMAT_BIN="$HOME/.agents/skills/lib-swing-format/bin"
CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
SOURCE_MEDIA_BIN="$HOME/.agents/skills/lib-bursawatch-source-media/bin"
if [[ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]]; then
  printf '%s FATAL: telegram resilience module missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$RESILIENCE_BIN" >&2
  exit 127
fi
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
if [[ ! -r "$SOURCE_MEDIA_BIN/bursawatch_source_media/client.py" ]]; then
  SOURCE_MEDIA_BIN="$(cd "$(dirname "$0")/../.." && pwd)/lib-bursawatch-source-media/bin"
fi
if [[ ! -r "$SOURCE_MEDIA_BIN/bursawatch_source_media/client.py" ]]; then
  printf '%s FATAL: shared Source Media client missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$SOURCE_MEDIA_BIN" >&2
  exit 127
fi
if [[ -d "$CONTROL_PLANE_BIN" ]]; then
  export PYTHONPATH="$DELIVERY_CLIENT_BIN:$SOURCE_MEDIA_BIN:$CONTROL_PLANE_BIN:$SWING_FORMAT_BIN:$RESILIENCE_BIN:${PYTHONPATH-}"
else
  export PYTHONPATH="$DELIVERY_CLIENT_BIN:$SOURCE_MEDIA_BIN:$SWING_FORMAT_BIN:$RESILIENCE_BIN:${PYTHONPATH-}"
fi

if [[ -r "$HOME/.hermes/.env" ]]; then
  for k in TELEGRAM_API_ID TELEGRAM_API_HASH POLYCOP_SESSION_STRING; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
  for k in BURSAWATCH_DISCORD_DELIVERY_URL BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE \
    BURSAWATCH_SOURCE_MEDIA_URL BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
  for k in IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
  if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" != "1" ]]; then
    for k in IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL \
      IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_WATCHER_ID \
      IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_TOKEN \
      IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_TIMEOUT_SECONDS \
      IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_SPOOL_PATH; do
      v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
      [[ -n "${v:-}" ]] && export "${k}=${v}"
    done
  fi
fi

if [[ -n "${IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH:-}" ]]; then
  IFS=: read -r -a PHINTRACO_EXTRA_PYTHONPATH_ENTRIES <<< "$IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH"
  for pythonpath_entry in "${PHINTRACO_EXTRA_PYTHONPATH_ENTRIES[@]}"; do
    if [[ -z "$pythonpath_entry" || ! -d "$pythonpath_entry" ]]; then
      printf '%s FATAL: configured Phintraco Python path is missing or invalid\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >&2
      exit 127
    fi
  done
  export PYTHONPATH="$IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH:$PYTHONPATH"
fi

export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9140}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"
export BURSAWATCH_SOURCE_MEDIA_URL="${BURSAWATCH_SOURCE_MEDIA_URL:-http://127.0.0.1:9130}"
export BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE="${BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-source-media-upload-token}"

PYTHON_BIN="${IDX_SWING_WATCH_PHINTRACO_DAILY_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="$HOME/.agents/skills/bursawatch-tg-phintraco-swing/bin/scan.py"
LOG="$HOME/.logs/bursawatch-tg-phintraco-swing.log"
if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  LOG="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}/bursawatch-tg-phintraco-swing.log"
fi
mkdir -p "$HOME/.logs"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "$(ts) FATAL: python missing at $PYTHON_BIN" | tee -a "$LOG" >&2
  exit 127
fi

echo "$(ts) START bursawatch-tg-phintraco-swing $*" >> "$LOG"
set +e
out="$("$PYTHON_BIN" "$SCRIPT" "$@" 2> >(tee -a "$LOG" >&2))"
rc=$?
set -e
printf '%s\n' "$out" | tee -a "$LOG"
echo "$(ts) END rc=$rc" >> "$LOG"
exit "$rc"
