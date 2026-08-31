# Hermes crons (Mac dev home)

Source-of-truth dev dirs for the Hermes cron skills that deploy to the VPS at
`~/.agents/skills/<cron>/`. **One workflow for all:** edit here → `./deploy.sh <cron>` → verify.

| Cron | What it is | Mac-runnable? |
|---|---|---|
| `polymarket-signal-watch` | Polymarket PolyCop signal screener (Telegram) | tests yes; a live run needs the VPS Telethon session |
| `idx-ca-watch` | IDX corporate-action screener | edit on Mac, **verify on the VPS** because IDX Cloudflare blocks non-datacenter IPs |
| `us-etf-dca-watch` | US ETF DCA timing monitor for SPY, QQQ, and SMH | yes |
| `idx-swing-watch-phintraco-daily` | Phintraco Daily Swing Call forwarder (Telegram text then source chart) | tests yes; a live run needs the VPS Telethon session |
| `idx-ssf-watch-phintraco-weekly` | Phintraco Weekly SSF Review forwarder (source-only text then native analyst chart) | tests yes; a live run needs the VPS Telethon session |
| `kelas-investasi-gtw-watch` | Future-only Kelas Investasi `#GTW` bundle watcher, source-grounded summary then source images to Discord | tests yes; a live run needs the VPS Telethon session |
| `scele-digest` | University SCELE daily digest (LLM agent job; `bin/send-digest` is the deterministic renderer) | renderer yes |
| `x-post-watch` | Configuration-driven RSSHub X post forwarder with optional Hermes titles and summaries | tests yes; live source and Discord no-post smoke run on the VPS |
| `dotfiles-sync` | VPS-owned staged backup of Mac and VPS configuration | VPS only; Mac is read over SSH |
| `marka-backup` | VPS-scheduled, Mac-local Marka Netscape HTML export | Mac command only, triggered by VPS SSH |
| `skills-update` | VPS-scheduled, Mac-local global skills update | Mac command only, triggered by VPS SSH |
| `sharing-cleanup` | No-agent weekly cleanup of Nextcloud `Sharing/` contents, retaining the folder | VPS only; WebDAV DELETE moves items to Nextcloud Trash |
| `security-audit` | VPS RKHunter, SSH, UFW, listener, Fail2ban, patch, and reboot-state audit | local parser/config tests yes; live dry run and scheduled verification on the VPS |
| `mm-weekly-log-normalizer` | MM weekly-log DRAFT normalizer and Review Bundle renderer | local tests yes; VPS runtime code deployed, active `every 14d` Hermes interval currently anchored around Sunday 16:05 WIB, with a Sunday 15:45 WIB Evidence Week boundary |

`mm` is the paired owner-only Hermes skill for saving explicitly supplied Manual Activity Records. It is not a scheduled cron.

## Workflow
1. Edit the skill under `<cron>/bin/`.
2. `./deploy.sh <cron>` copies `bin/` to the VPS. Single file: `./deploy.sh <cron> scan.py`.
3. Verify with the watcher's dry-run controls. Run network verification on the VPS for `idx-ca-watch`, `polymarket-signal-watch`, and `idx-swing-watch-phintraco-daily`.
4. The VPS uses `~/.local/share/uv/tools/yahoo-finance-mcp/bin/python` for market watchers.

## Don't
- Don't edit `~/.dotfiles/vps/agents/skills/<cron>/`. It is an `rsync --delete` backup mirror pulled **from** the VPS.
- Don't replace or initialize `state/` during deployment. Live state owns cursors, suppression, retries, and deduplication.
- Don't create watcher-owned Mac virtual environments. Shared local verification uses `~/Documents/Projects/Hermes/.venv`.

## Tests
From any watcher directory: `../.venv/bin/python -m pytest -q`.

Run every deterministic focused suite from the repository root:

```bash
bash scripts/test-all
```

## Repository boundaries

- This private repository is the canonical development source for Hermes cron skills, Cobalt, and Yanto's lifecycle-voice plugin.
- `hermes-agent-starter/` remains an independent repository and is intentionally ignored here.
- Runtime state, credentials, caches, worktrees, generated previews, and MM backfill outputs are never tracked.
- Cobalt cookies remain machine-local at `cobalt/compose/cookies.json`; the reviewed compose definition stays tracked.
- Dotfiles owns machine configuration and scrubbed VPS runtime snapshots, not duplicate Hermes development source.

## Validation and deployment

GitHub Actions runs read-only tests, shell syntax checks, and tracked-file policy checks. It has no secrets, VPS access, or deployment authority. A GitHub push never deploys anything.

All deployments remain explicit local commands. The deploy scripts refuse a dirty worktree or a commit that is not published to `origin`, then copy only their documented source paths to the VPS. Continue to verify deployed checksums and the cron-specific no-post path after every manual deployment.

## Docs
`docs/specs/` and `docs/plans/` — design + implementation plans (e.g. the cron heartbeat unification).
