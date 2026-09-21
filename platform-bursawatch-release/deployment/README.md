# Bursawatch release-agent VPS bootstrap

This directory is a reviewed bootstrap artifact for the VPS-local release
agent. It is not a deployment command in normal development work. The agent
is deliberately installed outside its Git checkout, so routine successful
releases cannot change its code, systemd timer, token file, or sudo privilege.

## What it releases

The timer polls GitHub once a minute. It acts only when the exact current
`main` SHA has a successful `CI / validate` push workflow. It creates an
isolated worktree below `~/.local/share/bursawatch-release/worktrees/`, checks
`release-manifest.json`, then deploys only the mapped Bursawatch runtime units.
Each runtime copy receives a checksum comparison and its existing isolated
no-post verification. Control-plane releases additionally install Python
dependencies, apply automatic migrations, seed only absent baselines, restart
the scoped API service through one sudoers command, and check loopback health.
An explicit operations release also applies reviewed manual migrations.

The agent stores sanitized per-SHA records and durable state below
`~/.local/share/bursawatch-release/records/`. It sends a concise success,
retry, or blocked heartbeat to `#hermes`. It never stores source content,
credentials, or database values in those records.

## Explicit bootstrap sequence

Do this only in an approved VPS operations session, from a clean published
checkout of this repository:

1. Create `/home/praya/.hermes/bursawatch-release-agent.env` from
   `env.example`, populate the dedicated fine-grained read-only GitHub token,
   and set mode `0600`. The token needs this private repository's Contents and
   Actions read access only. Do not reuse `gh` authentication.
2. Compare every source asset in this directory against its target. In
   particular, review the one-command sudoers rule before copying it.
3. Run `./platform-bursawatch-release/deployment/bootstrap-release-agent.sh --apply`.
   This is the only operation that installs or changes the agent boundary.
4. Inspect `systemctl status bursawatch-release-agent.timer`, then inspect
   `~/.local/share/bursawatch-release/state.json` and its per-SHA record. The
   first candidate intentionally reports a manual release requirement because
   this platform bootstrap is a host-bound manifest unit or a changed manual
   migration.
5. After the host bootstrap has been reviewed and applied, explicitly run the
   agent with its private environment in that one shell process:

   ```bash
   set -a
   . /home/praya/.hermes/bursawatch-release-agent.env
   set +a
   /home/praya/.local/lib/bursawatch-release/bursawatch-release-agent.sh --release-manual
   ```

   It applies reviewed manual migrations, skips host-bound manual units,
   deploys eligible workload units, and records that SHA as released. The timer
   handles later eligible workload-only commits.

## Failure handling

Network or GitHub API failures back off automatically. A failure after a
deployment starts, including migration, checksum, no-post, restart, or health
failure, blocks that SHA and posts a Hermes alert. Inspect its record before
acting. After remediation, an operator may run:

```bash
/home/praya/.local/lib/bursawatch-release/bursawatch-release-agent.sh --clear-block
```

The next timer run reevaluates the current eligible SHA. Never edit the state
JSON, migration ledger, live watcher state, or Hermes scheduler registry by
hand. A newer verified `main` SHA supersedes an older blocked SHA naturally.
