#!/bin/sh
set -eu

PYTHON_BIN=${IDX_MARKET_NEWS_PYTHON:-"$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"}
SCRIPT="$HOME/.agents/skills/bursawatch-tg-market-news/bin/watchdog.py"
RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"
DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"
export IDX_MARKET_NEWS_STATE_PATH="${IDX_MARKET_NEWS_STATE_PATH:-$HOME/.hermes/state/idx-market-news.json}"
export BURSAWATCH_DISCORD_DELIVERY_URL="${BURSAWATCH_DISCORD_DELIVERY_URL:-http://127.0.0.1:9120}"
export BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="${BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE:-$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token}"

if [ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]; then
    printf '%s\n' "idx-market-news watchdog telegram resilience module is unreadable" >&2
    exit 127
fi
export PYTHONPATH="$DELIVERY_CLIENT_BIN:$RESILIENCE_BIN${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON_BIN" "$SCRIPT"
