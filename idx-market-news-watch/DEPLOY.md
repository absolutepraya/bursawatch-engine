# idx-market-news-watch deployment

Run these commands only from a VPS-local agent workflow after the local package has been accepted. Do not perform these deployment, installation, smoke, or scheduler-registration commands from the Mac session. The Hermes runtime operating rule requires the VPS-local agent to own runtime edits and scheduler registration.

## Current shared-resilience rollout

This section supersedes any scanner smoke or cron-registration instruction below
when rolling out `telegram-resilience`. The existing no-agent schedule is not
part of this change and must not be recreated, manually triggered, enabled, or
rescheduled.

After current-session approval of the exact source-to-VPS diff, deploy the
common module first, then the four scanners, including this one. Compare
SHA-256 checksums for the common module, all changed scanners, and all changed
wrappers before accepting the runtime. Do not edit
`~/.hermes/state/idx-market-news.json`, replay candidates, or send a Discord
test message.

Run only the isolated shared probe from an already credentialed VPS shell:

```bash
~/.local/share/uv/tools/yahoo-finance-mcp/bin/python \
  ~/.agents/skills/telegram-resilience/bin/telegram-resilience-probe.py \
  --state-path /tmp/telegram-resilience-probe-state.json \
  --log-path /tmp/telegram-resilience-probe.jsonl \
  --no-notify
```

Observe the next natural run. A handled transport outage or authorization hold
must return no-agent output without advancing the Market News cursor or
delivery state.

```bash
cd ~/Documents/Projects/Hermes
ssh vps 'mkdir -p ~/.agents/skills/idx-market-news-watch/bin'
./deploy.sh idx-market-news-watch
rsync -a idx-market-news-watch/SKILL.md idx-market-news-watch/CONTEXT.md vps:.agents/skills/idx-market-news-watch/
mosh vps
install -m 755 ~/.agents/skills/idx-market-news-watch/bin/idx-market-news-watch.sh ~/.hermes/scripts/idx-market-news-watch.sh
IDX_MARKET_NEWS_NO_POST=1 IDX_MARKET_NEWS_STATE_PATH=/tmp/idx-market-news-smoke.json IDX_MARKET_NEWS_FORCE_HEARTBEAT=1 bash ~/.hermes/scripts/idx-market-news-watch.sh
~/.hermes/hermes-agent/venv/bin/hermes cron create --name idx-market-news-watch --deliver discord:1505162000420835388 --skill idx-market-news-watch --script ~/.hermes/scripts/idx-market-news-watch.sh '* * * * *' 'Process only the supplied idx-market-news-watch items according to the loaded skill. Do not reply in natural language.'
~/.hermes/hermes-agent/venv/bin/hermes cron list
```

## VPS-local smoke acceptance

Before scheduler registration, run the command with `IDX_MARKET_NEWS_NO_POST=1` and the isolated `/tmp/idx-market-news-smoke.json` state path shown above. The smoke must authenticate to the two allowed source entities, initialize both provider cursors without creating historical candidates, print the forced heartbeat payload, and make no Discord request. Confirm its output contains no production Discord message ID.

Only after that non-posting smoke succeeds may the VPS-local agent run the registration and list commands. Do not replace the isolated smoke state path with the production state path.

## Independent watchdog schedule

The watchdog is independent from the minute scanner. Install `bin/watchdog-wrapper.sh` beside the scanner scripts and schedule it once a minute with the local scheduler:

```bash
install -m 755 ~/.agents/skills/idx-market-news-watch/bin/watchdog-wrapper.sh ~/.hermes/scripts/idx-market-news-watch-watchdog.sh
* * * * * IDX_MARKET_NEWS_STATE_PATH=$HOME/.hermes/state/idx-market-news.json IDX_MARKET_NEWS_DISCORD_SECRET_FILE=$HOME/.hermes/secrets/idx-market-news-discord.env $HOME/.hermes/scripts/idx-market-news-watch-watchdog.sh
```

`$HOME/.hermes/secrets/idx-market-news-discord.env` must be mode `0600` and contain only `DISCORD_BOT_TOKEN=<token>`. The wrapper deliberately sources no Telegram, model, or scheduler secret. `watchdog.py` reads scanner state without migration or cursor mutation, emits fatal notices only to `#hermes`, and deduplicates each fatal fingerprint within its hour. `IDX_MARKET_NEWS_NO_POST=1` remains supported for a no-post watchdog smoke.

The wrapper uses the established `$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python` and executes `$HOME/.agents/skills/idx-market-news-watch/bin/watchdog.py`, so copying it into `~/.hermes/scripts/` never changes its code target.
