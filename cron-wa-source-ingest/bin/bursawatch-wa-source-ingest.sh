#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
RUNTIME_HOME="$HOME/.agents/skills/bursawatch-wa-source-ingest"
SCRIPT="$RUNTIME_HOME/bin/runner.py"
PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
CONTROL_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
PIPELINE_BIN="$HOME/.agents/skills/lib-bursawatch-pipeline-runtime/bin"
SOURCE_INGEST_BIN="$HOME/.agents/skills/lib-bursawatch-source-ingest-pilot/bin"
SOURCE_MEDIA_BIN="$HOME/.agents/skills/lib-bursawatch-source-media/bin"
DELIVERY_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
WATCH_BIN="$HOME/.agents/skills/bursawatch-wa-channel-watch/bin"
RUNTIME_PYTHONPATH="$RUNTIME_HOME/bin:$WATCH_BIN:$CONTROL_BIN:$PIPELINE_BIN:$SOURCE_INGEST_BIN:$SOURCE_MEDIA_BIN:$DELIVERY_BIN"
export PYTHONPATH="$RUNTIME_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  TEMP_ROOT="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}"
  if [[ ! -d "$TEMP_ROOT" ]]; then
    printf '%s\n' "release no-post temporary directory is unavailable" >&2
    exit 2
  fi
  if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
    printf '%s\n' "WhatsApp source-ingest runtime is unavailable" >&2
    exit 127
  fi
  set +e
  env -i PATH="/usr/bin:/bin" HOME="$HOME" TZ="$TZ" LANG="C.UTF-8" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUNTIME_PYTHONPATH" \
    BURSAWATCH_RELEASE_NO_POST=1 BURSAWATCH_RELEASE_NO_POST_TEMP="$TEMP_ROOT" \
    "$PYTHON_BIN" "$SCRIPT" --verify-synthetic 2>&1 | tee "$TEMP_ROOT/whatsapp-source-ingest.log"
  status="${PIPESTATUS[0]}"
  set -e
  exit "$status"
fi

ENV_FILE="$HOME/.hermes/.env"
if [[ -r "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      WHATSAPP_CHANNEL_WATCH_CONFIG_PATH=*|WHATSAPP_CHANNEL_WATCH_STATE_PATH=*|WHATSAPP_CHANNEL_WATCH_QUEUE_DIR=*|WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT=*|WHATSAPP_CHANNEL_WATCH_MEDIA_STAGING_DIR=*|WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL=*|WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID=*|WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TOKEN=*|WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS=*|WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_SPOOL_PATH=*|BURSAWATCH_WA_SOURCE_STATE_ROOT=*|BURSAWATCH_WA_SOURCE_CONTROL_PLANE_URL=*|BURSAWATCH_WA_SOURCE_CONTROL_PLANE_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_URL=*|BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE=*|BURSAWATCH_DISCORD_DELIVERY_URL=*|BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE=*)
        export "$line"
        ;;
    esac
  done < "$ENV_FILE"
fi

export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9140}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
unset DISCORD_BOT_TOKEN

exec "$PYTHON_BIN" "$SCRIPT" "$@"
