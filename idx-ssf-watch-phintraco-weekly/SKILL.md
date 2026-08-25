---
name: idx-ssf-watch-phintraco-weekly
description: Deterministic Hermes cron that polls Phintraco Telegram every 30 minutes and forwards each valid Weekly SSF Review underlying with the source-PDF Telegram link and native analyst chart.
user-invocable: false
---

# idx-ssf-watch-phintraco-weekly

Runs as a Hermes `no_agent` cron every 30 minutes. It reads Phintraco Sekuritas Official through the existing cron Telethon session, accepts valid Weekly SSF Review PDFs, and forwards every underlying as source-only text followed immediately by its native analyst chart.

The runtime calls no LLM and performs no market analysis. Delivery is strict FIFO. Every alert anchors `Phintraco Sekuritas` in its existing source footer to the exact Telegram PDF message parsed for the review. The source PDF and extracted analyst charts remain private runtime artifacts.

The wrapper pins production state to `~/.hermes/state/idx-ssf-watch-phintraco-weekly.json`, independent of its working directory. Do not override that path in the registered cron or reset it to replay a report.

## Runtime

```bash
~/.hermes/scripts/idx-ssf-watch-phintraco-weekly.sh
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
without advancing its Telegram cursor or mutating its PDF and delivery outbox.
It does not authenticate through any other Telegram profile.

## Dry run

- `IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST=1`
- `IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH=/tmp/idx-ssf-watch-state.json`
- `IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT=1`
