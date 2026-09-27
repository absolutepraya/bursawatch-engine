#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
RUNTIME_HOME="$HOME/.agents/skills/bursawatch-x-source-ingest"
SCRIPT="$RUNTIME_HOME/bin/runner.py"
PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
CONTROL_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
PIPELINE_BIN="$HOME/.agents/skills/lib-bursawatch-pipeline-runtime/bin"
SOURCE_INGEST_BIN="$HOME/.agents/skills/lib-bursawatch-source-ingest-pilot/bin"
SOURCE_MEDIA_BIN="$HOME/.agents/skills/lib-bursawatch-source-media/bin"
DELIVERY_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
RUNTIME_PYTHONPATH="$RUNTIME_HOME/bin:$CONTROL_BIN:$PIPELINE_BIN:$SOURCE_INGEST_BIN:$SOURCE_MEDIA_BIN:$DELIVERY_BIN"
export PYTHONPATH="$RUNTIME_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  TEMP_ROOT="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}"
  if [[ ! -d "$TEMP_ROOT" ]]; then
    printf '%s\n' "release no-post temporary directory is unavailable" >&2
    exit 2
  fi
  if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
    printf '%s\n' "X source-ingest runtime is unavailable" >&2
    exit 127
  fi
  # Never load .env or pass inherited credentials to synthetic verification.
  set +e
  env -i PATH="/usr/bin:/bin" HOME="$HOME" TZ="$TZ" LANG="C.UTF-8" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUNTIME_PYTHONPATH" \
    BURSAWATCH_RELEASE_NO_POST=1 BURSAWATCH_RELEASE_NO_POST_TEMP="$TEMP_ROOT" \
    "$PYTHON_BIN" "$SCRIPT" --verify-synthetic 2>&1 | tee "$TEMP_ROOT/x-source-ingest.log"
  status="${PIPESTATUS[0]}"
  set -e
  exit "$status"
fi

# Import only documented X, Control Plane, Source Media, and Delivery Owner
# settings. Values are never written to logs.
ENV_FILE="$HOME/.hermes/.env"
if [[ -r "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      X_POST_WATCH_PROXY_PRIMARY=*|X_POST_WATCH_PROXY_FALLBACK=*|X_POST_WATCH_CONTROL_PLANE_URL=*|X_POST_WATCH_CONTROL_PLANE_WATCHER_ID=*|X_POST_WATCH_CONTROL_PLANE_TOKEN=*|X_POST_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS=*|X_POST_WATCH_CONTROL_PLANE_SPOOL_PATH=*|BURSAWATCH_X_SOURCE_CONTROL_PLANE_URL=*|BURSAWATCH_X_SOURCE_CONTROL_PLANE_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_URL=*|BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE=*|BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE=*|BURSAWATCH_DISCORD_DELIVERY_URL=*|BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE=*)
        export "$line"
        ;;
    esac
  done < "$ENV_FILE"
fi

export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9140}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"
LOG_DIR="$HOME/.logs"
install -d -m 700 "$LOG_DIR"
LOG_FILE="$LOG_DIR/bursawatch-x-source-ingest.log"
if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
  printf '%s\n' "X source-ingest runtime is unavailable" >> "$LOG_FILE"
  exit 127
fi

set +e
"$PYTHON_BIN" "$SCRIPT" "$@" 2>&1 | tee -a "$LOG_FILE"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
