#!/bin/sh
set -eu

PYTHON_BIN=${IDX_MARKET_NEWS_PYTHON:-"$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"}
SCRIPT="$HOME/.agents/skills/idx-market-news-watch/bin/watchdog.py"
RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"
DISCORD_SECRET_FILE=${IDX_MARKET_NEWS_DISCORD_SECRET_FILE:-"$HOME/.hermes/secrets/idx-market-news-discord.env"}
export IDX_MARKET_NEWS_STATE_PATH="${IDX_MARKET_NEWS_STATE_PATH:-$HOME/.hermes/state/idx-market-news.json}"

if [ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]; then
    printf '%s\n' "idx-market-news watchdog telegram resilience module is unreadable" >&2
    exit 127
fi
export PYTHONPATH="$RESILIENCE_BIN${PYTHONPATH:+:$PYTHONPATH}"

# This file must contain only DISCORD_BOT_TOKEN for the watchdog's #hermes fatal post.
if [ ! -r "$DISCORD_SECRET_FILE" ]; then
    printf '%s\n' "idx-market-news watchdog Discord secret is unreadable" >&2
    exit 1
fi
set -a
. "$DISCORD_SECRET_FILE"
set +a

exec "$PYTHON_BIN" "$SCRIPT"
