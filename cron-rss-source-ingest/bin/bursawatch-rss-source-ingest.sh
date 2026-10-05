#!/usr/bin/env bash
set -euo pipefail
# Keep temporary verification logs and runtime-created files private.
umask 077

export TZ="Asia/Jakarta"
RUNTIME_HOME="$HOME/.agents/skills/bursawatch-rss-source-ingest"
SCRIPT="$RUNTIME_HOME/bin/runner.py"
PYTHON_BIN="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
CONTROL_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"
PIPELINE_BIN="$HOME/.agents/skills/lib-bursawatch-pipeline-runtime/bin"
SOURCE_INGEST_BIN="$HOME/.agents/skills/lib-bursawatch-source-ingest-pilot/bin"
DELIVERY_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
STOCKBIT_OWNER_BIN="$HOME/.agents/skills/bursawatch-stockbit-snips/bin"
RUNTIME_PYTHONPATH="$RUNTIME_HOME/bin:$CONTROL_BIN:$PIPELINE_BIN:$SOURCE_INGEST_BIN:$DELIVERY_BIN:$STOCKBIT_OWNER_BIN"
export PYTHONPATH="$RUNTIME_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  TEMP_ROOT="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}"
  if [[ ! -d "$TEMP_ROOT" ]]; then
    printf '%s\n' "release no-post temporary directory is unavailable" >&2
    exit 2
  fi
  if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
    printf '%s\n' "RSS source-ingest runtime is unavailable" >&2
    exit 127
  fi
  set +e
  env -i PATH="/usr/bin:/bin" HOME="$HOME" TZ="$TZ" LANG="C.UTF-8" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUNTIME_PYTHONPATH" \
    BURSAWATCH_RELEASE_NO_POST=1 BURSAWATCH_RELEASE_NO_POST_TEMP="$TEMP_ROOT" \
    "$PYTHON_BIN" "$SCRIPT" --verify-synthetic 2>&1 | tee "$TEMP_ROOT/rss-source-ingest.log"
  status="${PIPESTATUS[0]}"
  set -e
  exit "$status"
fi

ENV_FILE="$HOME/.hermes/.env"
if [[ -r "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      BURSAWATCH_RSS_SOURCE_CONTROL_PLANE_URL=*|BURSAWATCH_RSS_SOURCE_CONTROL_PLANE_TOKEN_FILE=*|STOCKBIT_SNIPS_CONTROL_PLANE_URL=*|STOCKBIT_SNIPS_CONTROL_PLANE_WATCHER_ID=*|STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN=*|STOCKBIT_SNIPS_CONTROL_PLANE_TIMEOUT_SECONDS=*|BURSAWATCH_DISCORD_DELIVERY_URL=*|BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE=*)
        export "$line"
        ;;
    esac
  done < "$ENV_FILE"
fi

export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9140}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"

if [[ ! -x "$PYTHON_BIN" || ! -r "$SCRIPT" ]]; then
  printf '%s\n' "RSS source-ingest runtime is unavailable" >&2
  exit 127
fi

# Agent output contains source text and is returned to the scheduled skill only.
# Do not persist it in a local log file.
exec "$PYTHON_BIN" "$SCRIPT" "$@"
