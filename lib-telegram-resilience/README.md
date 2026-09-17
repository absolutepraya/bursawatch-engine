# PolyCop Telegram Resilience

This directory owns shared, deterministic connection coordination for the four
market watchers that use `POLYCOP_SESSION_STRING`:

- `bursawatch-tg-market-news`
- `bursawatch-tg-phintraco-swing`
- `bursawatch-tg-kelas-investasi-gtw`
- `personal-polymarket-signal`

It does not own a Hermes cron, persistent connection, Telegram destination,
Discord destination, or session login flow. The Hermes gateway `telegram-mcp`
and SCELE's `tg-window` use the separate `TELEGRAM_SESSION_STRING` profile and
are outside this component's scope.

## Runtime contract

The deployed module lives at:

```text
~/.agents/skills/lib-telegram-resilience/bin/telegram_resilience.py
```

It stores only safe control-plane metadata:

```text
~/.hermes/state/telegram-resilience-polyclop.json
~/.logs/telegram-resilience-polyclop.jsonl
```

The state file is mode `0600`. The JSONL log retains 30 calendar days and
contains timestamps, watcher names, state transitions, error classes, and safe
connection metadata only. It must never contain credentials, session strings,
tokens, source text, or raw exception messages.

Each scanner obtains a probe decision before opening its Telethon connection.
A watcher in cooldown, blocked by another watcher's probe lease, or waiting for
manual re-login returns cleanly without advancing its own cursor or outbox.

## Hermes Personal CI dependency

`action.yml` provisions the reviewed Bursawatch module into a caller-provided
test dependency root. Hermes Personal pins the producing commit in its CI
workflow and receives only GitHub Actions' short-lived, read-only repository
access. No personal access token is required.

## Deployment and safe verification

After the local test matrix passes and the user has approved the VPS write,
deploy the shared module before the scanner changes:

```bash
./deploy.sh lib-telegram-resilience
./deploy.sh cron-tg-phintraco-swing scan.py
./deploy.sh cron-tg-market-news scan.py
```

Compare SHA-256 checksums for `telegram_resilience.py`,
`telegram-resilience-probe.py`, all remaining scanner files, and the changed
wrappers before considering the deployment complete. Do not edit live watcher
state, reset a cursor, replay alerts, or send a Discord test message.

From an already credentialed VPS shell, run only this isolated safe probe:

```bash
~/.local/share/uv/tools/yahoo-finance-mcp/bin/python \
  ~/.agents/skills/lib-telegram-resilience/bin/telegram-resilience-probe.py \
  --state-path /tmp/telegram-resilience-probe-state.json \
  --log-path /tmp/telegram-resilience-probe.jsonl \
  --no-notify
```

The probe may only connect, check authorization, call `get_me`, and disconnect.
Do not manually trigger a Hermes cron, and do not run a Polymarket scanner smoke
test. Observe normal scheduled runs after deployment instead.

## Manual authorization recovery

An `auth_required` incident means the existing PolyCop session must be renewed
through the approved interactive login path. Do not automatically regenerate a
session string, reset watcher state, or restart Hermes services. A later
authenticated connection closes the incident.
