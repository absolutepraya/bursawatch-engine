#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
control_plane_bin="$HOME/.agents/skills/lib-bursawatch-control/bin"
if [[ -d "$control_plane_bin" ]]; then
  export PYTHONPATH="$control_plane_bin${PYTHONPATH:+:$PYTHONPATH}"
fi
if [[ -r "$HOME/.hermes/.env" ]]; then
  for name in WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID \
    WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TOKEN WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS \
    WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_SPOOL_PATH; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
fi
python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/subscriptions.py"

exec "$python_bin" "$script" "$@"
