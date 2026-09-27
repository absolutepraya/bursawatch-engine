#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
RUNTIME_HOME="$HOME/.agents/skills/bursawatch-tg-source-ingest"
SCRIPT="$RUNTIME_HOME/bin/runner.py"
PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
CONTROL_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
PIPELINE_BIN="$HOME/.agents/skills/lib-bursawatch-pipeline-runtime/bin"
SOURCE_INGEST_BIN="$HOME/.agents/skills/lib-bursawatch-source-ingest-pilot/bin"
SOURCE_MEDIA_BIN="$HOME/.agents/skills/lib-bursawatch-source-media/bin"
DELIVERY_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"
RUNTIME_PYTHONPATH="$RUNTIME_HOME/bin:$CONTROL_BIN:$PIPELINE_BIN:$SOURCE_INGEST_BIN:$SOURCE_MEDIA_BIN:$DELIVERY_BIN:$RESILIENCE_BIN"
export PYTHONPATH="$RUNTIME_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  TEMP_ROOT="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}"
  if [[ ! -d "$TEMP_ROOT" ]]; then
    printf '%s\n' "release no-post temporary directory is unavailable" >&2
    exit 2
  fi
  if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
    printf '%s\n' "Telegram source-ingest runtime is unavailable" >&2
    exit 127
  fi
  # Do not load .env or pass inherited credentials to the synthetic-only path.
  set +e
  env -i PATH="/usr/bin:/bin" HOME="$HOME" TZ="$TZ" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUNTIME_PYTHONPATH" \
    BURSAWATCH_RELEASE_NO_POST=1 BURSAWATCH_RELEASE_NO_POST_TEMP="$TEMP_ROOT" \
    "$PYTHON_BIN" "$SCRIPT" --verify-synthetic 2>&1 | tee "$TEMP_ROOT/telegram-source-ingest.log"
  status="${PIPESTATUS[0]}"
  set -e
  exit "$status"
fi

# Import only documented Telegram, Control Plane, Source Media, and Delivery
# Owner settings. Values are never written to logs.
ENV_FILE="$HOME/.hermes/.env"
if [[ -r "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      TELEGRAM_API_ID=*|TELEGRAM_API_HASH=*|POLYCOP_SESSION_STRING=*|BURSAWATCH_TG_SOURCE_CONTROL_PLANE_URL=*|BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_URL=*|BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE=*|BURSAWATCH_DISCORD_DELIVERY_URL=*|BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE=*)
        export "$line"
        ;;
    esac
  done < "$ENV_FILE"
fi

LOG_DIR="$HOME/.logs"
install -d -m 700 "$LOG_DIR"
LOG_FILE="$LOG_DIR/bursawatch-tg-source-ingest.log"
if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
  printf '%s\n' "Telegram source-ingest runtime is unavailable" >> "$LOG_FILE"
  exit 127
fi

set +e
"$PYTHON_BIN" "$SCRIPT" "$@" 2>&1 | tee -a "$LOG_FILE"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
