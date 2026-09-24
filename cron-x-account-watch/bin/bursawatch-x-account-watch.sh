#!/usr/bin/env bash
set -euo pipefail
export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
control_plane_bin="$HOME/.agents/skills/lib-bursawatch-control/bin"
delivery_client_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
if [[ -d "$control_plane_bin" ]]; then
  export PYTHONPATH="$delivery_client_bin:$control_plane_bin${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$delivery_client_bin${PYTHONPATH:+:$PYTHONPATH}"
fi
if [[ -r "$HOME/.hermes/.env" ]]; then
  for name in X_POST_WATCH_PROXY_PRIMARY X_POST_WATCH_PROXY_FALLBACK; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
  for name in BURSAWATCH_DISCORD_DELIVERY_URL BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
  if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" != "1" ]]; then
    for name in X_POST_WATCH_CONTROL_PLANE_URL X_POST_WATCH_CONTROL_PLANE_WATCHER_ID \
      X_POST_WATCH_CONTROL_PLANE_TOKEN X_POST_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS \
      X_POST_WATCH_CONTROL_PLANE_SPOOL_PATH; do
      value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
      [[ -n "$value" ]] && export "$name=$value"
    done
  fi
fi
export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9120}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"
python_bin="${X_POST_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/bursawatch-x-account-watch/bin/scan.py"
log="$HOME/.logs/bursawatch-x-account-watch.log"
if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" == "1" ]]; then
  log="${BURSAWATCH_RELEASE_NO_POST_TEMP:?release no-post temporary directory is required}/bursawatch-x-account-watch.log"
fi
mkdir -p "$HOME/.logs"
set +e
"$python_bin" "$script" "$@" 2>&1 | tee -a "$log"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
