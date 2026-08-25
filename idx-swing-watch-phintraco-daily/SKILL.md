---
name: idx-swing-watch-phintraco-daily
description: Deterministic Hermes cron that polls Phintraco Telegram every minute and forwards individual IDX BUY calls, TP/SL outcomes, and active-plan status updates to Discord with the exact Telegram source link and source chart.
user-invocable: false
---

# idx-swing-watch-phintraco-daily

Runs as a Hermes `no_agent` cron every minute. It reads Phintraco Sekuritas Official through the existing cron Telethon session and forwards one-ticker `Trading Buy`, `Buy on Support`, `Speculative Buy`, TP/SL outcomes, and approved active-plan status updates to Discord `#id-stocks-swing`.

The runtime calls no LLM and performs no market analysis. Delivery is strict FIFO. Every alert anchors `Phintraco Sekuritas` in its existing source footer to the exact source Telegram message. A source chart attached to that same Telegram message follows the alert text immediately. A chartless source event is delivered text-only with an explicit chart-unavailable field.

## Runtime

```bash
~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh
```

## Channels

- Telegram source: `1444713822`
- Discord alerts: `1525102458253217803`
- Discord heartbeat and failures: `1505162000420835388`

## Secrets

The wrapper loads `DISCORD_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING` from `~/.hermes/.env`.

## Shared Telegram resilience

This no-agent watcher uses `telegram-resilience` with the shared
`POLYCOP_SESSION_STRING` profile. Its control-plane state is
`~/.hermes/state/telegram-resilience-polyclop.json`. During a shared transport
cooldown, another watcher's active probe, or an authorization hold, it exits
without advancing its Telegram cursor or mutating its delivery outbox. It does
not authenticate through any other Telegram profile.

## Dry run

- `IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1`
- `IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH=/tmp/idx-swing-watch-phintraco-daily-state.json`
- `IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT=1`
