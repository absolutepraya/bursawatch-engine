# idx-ca-watch — VPS deploy runbook

Run from a VPS-side agent session (`mosh vps` → Claude Code/OpenCode). Mirrors
the us-etf-dca-watch deploy. Pre-deploy backup first.

> ⚠️ IMPORTANT (root-cause of the 2026-06-20 loss): the dotfiles `sync.sh` MIRRORS
> `~/.agents/skills/` **FROM the VPS** with `rsync --delete` (sync.sh:542-559). It does
> NOT deploy TO the VPS, and it will DELETE any skill that exists only in the repo and
> not on the VPS. So the skill must live on the VPS first; the repo backup follows.
> Author/stage this skill OUTSIDE the dotfiles tree (currently staged at
> `~/Documents/Projects/Hermes/idx-ca-watch/` on the Mac).

## 0. Backup
```bash
mkdir -p ~/.backups/idx-ca-watch-$(date +%Y%m%d_%H%M%S)
cp -r ~/.agents/skills/idx-ca-watch ~/.backups/idx-ca-watch-*/ 2>/dev/null || true
```

## 1. Get the skill onto the VPS (it does NOT arrive via dotfiles sync)
From the Mac, push the staged skill up:
```bash
rsync -a --exclude '__pycache__' --exclude '.pytest_cache' \
  ~/Documents/Projects/Hermes/idx-ca-watch/ vps:~/.agents/skills/idx-ca-watch/
```
Then on the VPS, place the wrapper + health probe and set perms:
```bash
ssh vps '
  cp ~/.agents/skills/idx-ca-watch/bin/idx-ca-watch.sh ~/.hermes/scripts/idx-ca-watch.sh
  cp ~/.agents/skills/idx-ca-watch/bin/idx-ca-health ~/.local/bin/idx-ca-health
  chmod +x ~/.hermes/scripts/idx-ca-watch.sh ~/.local/bin/idx-ca-health ~/.agents/skills/idx-ca-watch/bin/*.py ~/.agents/skills/idx-ca-watch/bin/idx-ca-health
'
```
After the skill lives on the VPS, the next dotfiles sync backs it up into the repo correctly.

## 2. Python env + deps
Find the env us-etf-dca-watch uses (Yahoo Finance MCP venv, has yfinance/pandas/numpy).
Install the new deps INTO that env, then point the wrapper at that interpreter:
```bash
<that-venv>/bin/pip install curl_cffi cloudscraper pypdf
# Point the wrapper at that interpreter (it defaults to bare python3, which lacks the deps):
sed -i 's|^PY=.*|PY="<that-venv>/bin/python"|' ~/.hermes/scripts/idx-ca-watch.sh
```

## 3. VERIFY-1 — Cloudflare bypass from the datacenter IP
```bash
IDX_CA_PY=<venv>/bin/python; $IDX_CA_PY -c "import sys; sys.path.insert(0,'$HOME/.agents/skills/idx-ca-watch/bin'); import scan; print(scan.fetch_page(1,3).get('ResultCount'))"
```
Expect a large number. If it raises "all IDX fetch methods failed" → CF is blocking
the datacenter IP. Then either (a) install playwright + system chromium for the
headless fallback (`pip install playwright && playwright install chromium`), or
(b) consider Approach B (script-side Anthropic call) + a residential proxy.

## 4. VERIFY-2 — chart + metrics + Discord
```bash
$IDX_CA_PY -c "import sys; sys.path.insert(0,'$HOME/.agents/skills/idx-ca-watch/bin'); import scan; print(scan.render_chart('BBCA')); print(scan.market_metrics('BBCA')['avg_value_idr'])"
IDX_CA_WATCH_NO_POST=1 ~/.hermes/scripts/idx-ca-watch.sh; tail -20 ~/.logs/idx-ca-watch.log
```
Then one real heartbeat to confirm channel perms:
```bash
$IDX_CA_PY -c "import sys; sys.path.insert(0,'$HOME/.agents/skills/idx-ca-watch/bin'); import scan; print(scan.post_discord('1517510484025151538','🫀 idx-ca-watch deploy test'))"
```
Expect the message to appear in channel `1517510484025151538`. (Confirm Yanto's bot
has View+Send there.)

Also confirm **chart-img.com quota/tier headroom** for IDX symbols before going 24/7
(it renders one chart per interesting CA, every hour) — check the chart-img.com dashboard. (DESIGN §6 open item)

## 5. VERIFY-3 — wakeAgent escalation contract
Register the cron and confirm Hermes wakes the agent (and passes `items[]`) when the
script returns `{"wakeAgent": true}`. Check `~/.hermes/logs/`. If Hermes cannot pass
the payload on escalation → fall back to Approach B (DESIGN.md §2): have scan.py call
the Anthropic API directly to score and post, returning `{"wakeAgent": false}`.

## 6. Register the Hermes cron
```bash
hermes cron add --name idx-ca-watch --schedule "0 * * * *" \
  --command "~/.hermes/scripts/idx-ca-watch.sh" --deliver "discord:1517510484025151538"
# exact flags per `hermes cron --help`; raise cron.script_timeout_seconds in
# ~/.hermes/config.yaml if a run nears the limit (already 300 for us-etf-dca-watch).
```
First registered run will BOOTSTRAP (mark current page seen, no alerts).

## 7. System-cron watchdog (gateway-independent)
```bash
crontab -e
# watchdog runs OUTSIDE Hermes (no inherited env), so set HOME so scan.post_discord can read
# ~/.hermes/.env for the Discord token (adjust HOME to the praya user's home dir):
# 30 */3 * * *  HOME=/home/praya IDX_CA_PY=<venv>/bin/python <venv>/bin/python ~/.agents/skills/idx-ca-watch/bin/watchdog.py
```

## 8. Post-deploy
- Watch channel `1517510484025151538` for the next few hourly heartbeats.
- `idx-ca-health` to inspect cache growth.
- Tune `INTERESTING_PATTERNS` / `SKIP_PATTERNS` in scan.py if recall is off.

## 9. Deliver retarget (notification upgrade, 2026-06-27)
The agent now posts alerts itself via `scan.py post-alert`, so the cron's
`deliver` must NOT also dump the wrapped agent reply into the alert channel.
Discover the flag, then retarget:
```bash
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main cron edit --help
```
Do NOT clear delivery with `--deliver ""`: it stores a non-iterable that crashes
`cron list` (`TypeError: can only join an iterable`) and breaks listing for every
job after it. There is no `--no-deliver` flag. Instead retarget to the heartbeat
channel (done 2026-06-28):
```bash
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main cron edit b49432a194d1 \
  --deliver discord:1505162000420835388
```
Effect: alerts go to `1517510484025151538` via `post-alert` (clean, no wrapper);
the agent's leftover wrapped reply lands in #hermes (`1505162000420835388`, the
heartbeat firehose) only when it wakes on interesting CAs. Verify: a real cron
fire posts ONE clean alert per scored item to `1517510484025151538` (no
`Cronjob Response` / `job_id` framing) and NO wrapped duplicate there.
