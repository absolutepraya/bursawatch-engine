#!/usr/bin/env bash
set -uo pipefail

env_file="$HOME/.hermes/.env"
log_file="$HOME/.logs/kelas-investasi-gtw-watch.log"
python_bin="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
mkdir -p "$(dirname "$log_file")"

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    DISCORD_BOT_TOKEN=*|TELEGRAM_API_ID=*|TELEGRAM_API_HASH=*|POLYCOP_SESSION_STRING=*) export "$line" ;;
  esac
done < "$env_file"

export PYTHONPATH="$HOME/.agents/skills/telegram-resilience/bin"
set +e
"$python_bin" "$HOME/.agents/skills/kelas-investasi-gtw-watch/bin/scan.py" "$@" 2>&1 | sed -E 's/(POLYCOP_SESSION_STRING|DISCORD_BOT_TOKEN|TELEGRAM_API_ID|TELEGRAM_API_HASH)=[^[:space:]]+/\1=<redacted>/g' >> "$log_file"
status=${PIPESTATUS[0]}
exit "$status"
