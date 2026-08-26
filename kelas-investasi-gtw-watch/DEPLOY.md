# Deployment Runbook

Deployment is approval-gated. Do not SSH-write, copy files, create or enable a Hermes cron, alter a schedule, reset state, or send a test message until the parent has shown the exact VPS diff and received explicit current-session approval.

## Approved source files only

After local tests pass, compare each local target with its VPS counterpart before copying. Deploy executable code only with:

```bash
./deploy.sh kelas-investasi-gtw-watch
```

Synchronize these runtime docs separately to `~/.agents/skills/kelas-investasi-gtw-watch/`: `SKILL.md`, `README.md`, `SPEC.md`, `CONTEXT.md`, and `DEPLOY.md`. Copy only `bin/kelas-investasi-gtw-watch.sh` to `~/.hermes/scripts/kelas-investasi-gtw-watch.sh`, then set its executable mode. Do not modify the dotfiles mirror.

Compare local and VPS SHA-256 checksums for every deployed `bin/` file, every synchronized runtime document, and the wrapper. The exact intended files are listed in the Task 7 report. Never deploy `state/`, media, logs, credentials, or `~/.dotfiles/vps/agents/skills/`.

## No-post verification boundary

The watcher supports isolated temporary paths for its own cursor and captured
media. It does not support overriding the shared Telegram resilience state or
the wrapper's production log path, and it has no force-heartbeat option. A
no-post run can therefore still update
`~/.hermes/state/telegram-resilience-polyclop.json`, its lock, and
`~/.logs/telegram-resilience-polyclop.jsonl` while making no Discord or source
media delivery. Do not describe this as a production-state-free smoke test.

Only after approval and checksum comparison, and only when touching those live
shared control paths is acceptable, run this supported command with isolated
watcher state and media:

```bash
ssh vps 'KELAS_INVESTASI_GTW_NO_POST=1 KELAS_INVESTASI_GTW_STATE_PATH=/tmp/kelas-investasi-gtw-state.json KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-investasi-gtw-media ~/.hermes/scripts/kelas-investasi-gtw-watch.sh'
```

Verify from the output and target history that no Discord message or source-media
delivery occurred. A heartbeat is printed only when the run reaches its normal
no-post rendering path, so authentication, cooldown, or source failures may
produce no heartbeat. This is not permission to manually trigger a Hermes cron,
post directly to Telegram, backfill history, or register the watcher. Cron
creation, schedule, delivery route, and enablement remain a separate explicit
approval.
