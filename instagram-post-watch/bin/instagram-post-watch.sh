#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export "DISCORD_BOT_TOKEN=$value"
fi

python_bin="${INSTAGRAM_POST_WATCH_PY:-$HOME/.local/share/instagram-post-watch/paddleocr-venv/bin/python}"
script="$HOME/.agents/skills/instagram-post-watch/bin/scan.py"
log="$HOME/.logs/instagram-post-watch.log"
mkdir -p "$HOME/.logs"

set +e
"$python_bin" "$script" "$@" 2>&1 | tee -a "$log"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
