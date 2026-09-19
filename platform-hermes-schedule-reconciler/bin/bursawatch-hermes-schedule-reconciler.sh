#!/usr/bin/env bash
set -euo pipefail

export TZ="Asia/Jakarta"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Hermes does not pass its environment file through to subprocesses. Import
# only the reconciler's scoped runtime values, preserving text after '='.
if [[ -r "$HOME/.hermes/.env" ]]; then
  for key in \
    BURSAWATCH_SCHEDULE_RECONCILER_CONTROL_PLANE_URL \
    BURSAWATCH_SCHEDULE_RECONCILER_TOKEN \
    BURSAWATCH_SCHEDULE_RECONCILER_TIMEOUT_SECONDS \
    BURSAWATCH_SCHEDULE_RECONCILER_JOBS_PATH \
    BURSAWATCH_SCHEDULE_RECONCILER_HERMES_CLI \
    BURSAWATCH_SCHEDULE_RECONCILER_PYTHON \
    BURSAWATCH_SCHEDULE_RECONCILER_LOG_PATH; do
    value="$(grep -E "^${key}=" "$HOME/.hermes/.env" | head -n 1 | cut -d= -f2- || true)"
    if [[ -n "$value" ]]; then
      export "${key}=${value}"
    fi
  done
fi

PYTHON_BIN="${BURSAWATCH_SCHEDULE_RECONCILER_PYTHON:-/usr/bin/python3}"
LOG_PATH="${BURSAWATCH_SCHEDULE_RECONCILER_LOG_PATH:-$HOME/.logs/bursawatch-schedule-reconciler.log}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '%s FATAL: python interpreter missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$PYTHON_BIN" >&2
  exit 127
fi

mkdir -p "$(dirname "$LOG_PATH")"
set +e
"$PYTHON_BIN" "$SCRIPT_DIR/reconcile.py" "$@" 2>&1 | tee -a "$LOG_PATH"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
