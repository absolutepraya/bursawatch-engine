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
`~/.local/share/bursawatch-release/records/`. It submits the existing concise
success, retry, or blocked heartbeat to `#hermes` through the shared Discord
Delivery Owner on loopback. The agent uses the shared client installed at
`~/.agents/skills/lib-bursawatch-discord-delivery/bin` and the mode-0600 client
token file at
`~/.hermes/secrets/bursawatch-discord-delivery-client-token`. It has no Discord
bot token. When the optional
`BURSAWATCH_RELEASE_STATUS_TOKEN` is configured, it also publishes the
`bursawatch/release` commit status for the exact candidate SHA. The polling
token remains read-only; the status token is separate and only needs commit
status write access. Heartbeat and status publication are best effort and
never change the release decision. Release records contain bounded, sanitized
diagnostics and release metadata only; credentials are redacted and live state
is not copied into them.

On this VPS's systemd 252, `RestrictAddressFamilies`, `LockPersonality`, and
`SystemCallArchitectures` implicitly set kernel `NoNewPrivs` for the unit,
although `systemctl show` reports `NoNewPrivileges=no`. That prevents the
agent from using its narrowly scoped sudo restart. The service leaves those
three restrictions unset and retains the other filesystem and temporary-file
sandboxing. The bootstrap also removes the exact
`/etc/sudoers.d/praya` blanket `NOPASSWD:ALL` rule, after saving a root-only
rollback copy. The existing `sudo` group continues to grant passworded admin
access; the release agent retains only its fixed Control Plane restart rule.

## Explicit bootstrap sequence

Do this only in an approved VPS operations session, from a clean published
checkout of this repository:

1. Create `/home/praya/.hermes/bursawatch-release-agent.env` from
   `env.example`, populate the dedicated fine-grained read-only GitHub token,
   and set mode `0600`. The polling token needs this private repository's
   Contents and Actions read access only. If repository-visible release status
   is approved, add a separate token with Commit statuses: write only. Do not
   reuse `gh` authentication. Set up the Delivery Owner separately, install
   its shared client under `/home/praya/.agents/skills/`, and create the
   private client-token file named in the environment file.
2. Compare every source asset in this directory against its target. Confirm
   `/etc/sudoers.d/praya` contains exactly `praya ALL=(ALL) NOPASSWD:ALL`;
   the bootstrap refuses to change any other contents. Confirm the operator
   still has passworded access through the `sudo` group.
3. Run `./platform-bursawatch-release/deployment/bootstrap-release-agent.sh --apply`.
   This is the only operation that installs or changes the agent boundary. To
   retry a release that was blocked by the old boundary, explicitly add
   `--retry-blocked` after `--apply`. If the installed agent code has a
   different reviewed checksum from this checkout, add
   `--preserve-agent-code` to change only its host boundary.
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
Blocked release attempts exit nonzero for systemd visibility. Their per-SHA
record includes the sanitized command, return code, signal details, bounded
stdout and stderr, verification name, and isolated temporary-run path when a
child verification command fails.
