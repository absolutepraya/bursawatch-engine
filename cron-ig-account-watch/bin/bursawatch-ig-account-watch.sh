#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Jakarta
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

if [[ "${INSTAGRAM_POST_WATCH_NO_POST:-}" == "1" ]]; then
  case "${INSTAGRAM_POST_WATCH_STATE_PATH:-}" in
    /*) ;;
    *) echo "INSTAGRAM_POST_WATCH_NO_POST=1 requires an absolute INSTAGRAM_POST_WATCH_STATE_PATH" >&2; exit 2 ;;
  esac
  case "${INSTAGRAM_POST_WATCH_MEDIA_ROOT:-}" in
    /*) ;;
    *) echo "INSTAGRAM_POST_WATCH_NO_POST=1 requires an absolute INSTAGRAM_POST_WATCH_MEDIA_ROOT" >&2; exit 2 ;;
  esac
fi

if [[ -r "$HOME/.hermes/.env" ]]; then
  value="$(grep -E '^DISCORD_BOT_TOKEN=' "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
  [[ -n "$value" ]] && export "DISCORD_BOT_TOKEN=$value"
fi

python_bin="${INSTAGRAM_POST_WATCH_PY:-$HOME/.local/share/instagram-post-watch/paddleocr-venv/bin/python}"
script="$HOME/.agents/skills/bursawatch-ig-account-watch/bin/scan.py"
log="$HOME/.logs/bursawatch-ig-account-watch.log"
mkdir -p "$HOME/.logs"

set +e
"$python_bin" "$script" "$@" 2>&1 | tee -a "$log"
status="${PIPESTATUS[0]}"
set -e
exit "$status"
