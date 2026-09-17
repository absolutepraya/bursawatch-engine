#!/usr/bin/env bash
set -euo pipefail
export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"
if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export "DISCORD_BOT_TOKEN=$value"
  for name in X_POST_WATCH_PROXY_PRIMARY X_POST_WATCH_PROXY_FALLBACK; do
    value="$(grep -E "^${name}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "$value" ]] && export "$name=$value"
  done
fi
python_bin="${X_POST_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
script="$HOME/.agents/skills/bursawatch-x-account-watch/bin/scan.py"
log="$HOME/.logs/bursawatch-x-account-watch.log"
mkdir -p "$HOME/.logs"
set +e
"$python_bin" "$script" "$@" 2>&1 | tee -a "$log"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
