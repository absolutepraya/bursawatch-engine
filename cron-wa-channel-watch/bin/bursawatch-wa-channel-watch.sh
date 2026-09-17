#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export "DISCORD_BOT_TOKEN=$value"
fi

python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/scan.py"
config_path="${WHATSAPP_CHANNEL_WATCH_CONFIG_PATH:-$HOME/.agents/skills/bursawatch-wa-channel-watch/config/watches.json}"
state_path="${WHATSAPP_CHANNEL_WATCH_STATE_PATH:-$HOME/.hermes/state/whatsapp-channel-watch/state.json}"
queue_dir="${WHATSAPP_CHANNEL_WATCH_QUEUE_DIR:-$HOME/.hermes/state/whatsapp-channel-watch/queue}"

if [[ "${WHATSAPP_CHANNEL_WATCH_NO_POST:-}" == "1" ]]; then
  case "$state_path" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute state path" >&2; exit 2 ;; esac
  case "$queue_dir" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute queue path" >&2; exit 2 ;; esac
fi

exec "$python_bin" "$script" "$@" --config "$config_path" --state "$state_path" --queue-dir "$queue_dir"
