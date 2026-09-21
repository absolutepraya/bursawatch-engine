#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT="${WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT:-$HOME/.hermes/state/whatsapp-channel-watch/archive}"
python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="${WHATSAPP_CHANNEL_WATCH_ARCHIVE_SCRIPT:-$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/archive.py}"

exec "$python_bin" "$script" "$@"
