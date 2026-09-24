#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
delivery_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
export PYTHONPATH="$delivery_bin${PYTHONPATH:+:$PYTHONPATH}"
unset DISCORD_BOT_TOKEN
if [[ -r "$HOME/.hermes/.env" ]]; then
  for name in BURSAWATCH_DISCORD_DELIVERY_URL BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE \
    BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
fi

python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="${WHATSAPP_CHANNEL_WATCH_BACKFILL_SCRIPT:-$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/bursawatch-wa-channel-backfill.py}"
exec "$python_bin" "$script" "$@"
