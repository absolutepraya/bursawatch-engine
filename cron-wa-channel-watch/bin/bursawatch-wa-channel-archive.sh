#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT="${WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT:-$HOME/.hermes/state/whatsapp-channel-watch/archive}"
python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="${WHATSAPP_CHANNEL_WATCH_ARCHIVE_SCRIPT:-$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/archive.py}"
handoff_script="${WHATSAPP_CHANNEL_WATCH_HANDOFF_SCRIPT:-$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/delivery_handoff.py}"
control_plane_bin="$HOME/.agents/skills/lib-bursawatch-control/bin"
delivery_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
export PYTHONPATH="$control_plane_bin:$delivery_bin${PYTHONPATH:+:$PYTHONPATH}"
unset DISCORD_BOT_TOKEN
if [[ -r "$HOME/.hermes/.env" ]]; then
  for name in WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID \
    WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TOKEN WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS \
    WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_SPOOL_PATH BURSAWATCH_DISCORD_DELIVERY_URL \
    BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
fi

if [[ "${1:-}" == "delivery-handoff" ]]; then
  shift
  exec "$python_bin" "$handoff_script" "$@"
fi

exec "$python_bin" "$script" "$@"
