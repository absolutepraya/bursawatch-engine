#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/whatsapp-channel-watch/bin/subscriptions.py"

exec "$python_bin" "$script" "$@"
