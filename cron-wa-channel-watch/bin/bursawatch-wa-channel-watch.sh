#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
control_plane_bin="$HOME/.agents/skills/lib-bursawatch-control/bin"
delivery_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
export PYTHONPATH="$control_plane_bin:$delivery_bin${PYTHONPATH:+:$PYTHONPATH}"
unset DISCORD_BOT_TOKEN

if [[ -r "$HOME/.hermes/.env" ]]; then
  if [[ "${BURSAWATCH_RELEASE_NO_POST:-}" != "1" ]]; then
    for name in WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_URL WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_WATCHER_ID \
      WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TOKEN WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TIMEOUT_SECONDS \
      WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_SPOOL_PATH BURSAWATCH_DISCORD_DELIVERY_URL \
      BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE; do
      value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
      [[ -n "$value" ]] && export "$name=$value"
    done
  fi
fi

python_bin="${WHATSAPP_CHANNEL_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/bursawatch-wa-channel-watch/bin/scan.py"
config_path="${WHATSAPP_CHANNEL_WATCH_CONFIG_PATH:-$HOME/.agents/skills/bursawatch-wa-channel-watch/config/watches.json}"
state_path="${WHATSAPP_CHANNEL_WATCH_STATE_PATH:-$HOME/.hermes/state/whatsapp-channel-watch/state.json}"
queue_dir="${WHATSAPP_CHANNEL_WATCH_QUEUE_DIR:-$HOME/.hermes/state/whatsapp-channel-watch/queue}"
archive_dir="${WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT:-$HOME/.hermes/state/whatsapp-channel-watch/archive}"
media_staging_dir="${WHATSAPP_CHANNEL_WATCH_MEDIA_STAGING_DIR:-$HOME/.hermes/state/whatsapp-channel-watch/media-staging}"

if [[ "${WHATSAPP_CHANNEL_WATCH_NO_POST:-}" == "1" ]]; then
  case "$state_path" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute state path" >&2; exit 2 ;; esac
  case "$queue_dir" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute queue path" >&2; exit 2 ;; esac
  case "$archive_dir" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute archive path" >&2; exit 2 ;; esac
  case "$media_staging_dir" in /*) ;; *) echo "WHATSAPP_CHANNEL_WATCH_NO_POST=1 requires an absolute media staging path" >&2; exit 2 ;; esac
fi

exec "$python_bin" "$script" "$@" --config "$config_path" --state "$state_path" --queue-dir "$queue_dir" --archive-dir "$archive_dir" --media-staging-dir "$media_staging_dir"
