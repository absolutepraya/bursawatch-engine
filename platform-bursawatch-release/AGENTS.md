# Bursawatch release-agent instructions

This host-bound platform package defines the VPS-local pull release agent for
eligible Bursawatch `main` commits. The running agent is installed once at
`~/.local/lib/bursawatch-release/`; ordinary releases do not update its code,
systemd units, environment file, sudoers rule, or privileges.

The agent polls GitHub using a dedicated read-only token, requires the exact
current `main` SHA to have a successful `CI / validate` workflow, and may
publish the external `bursawatch/release` commit status through a separate,
optional status-write token. It checks a tracked release manifest and
materializes that SHA from its local bare mirror. It deploys only known runtime
handlers, verifies synchronized checksums, runs the package's isolated no-post
control, and stores sanitized durable release records under
`~/.local/share/bursawatch-release/`.

The Telegram source-ingest pilot's no-post control is synthetic-only. Its
scrubbed environment contains no inherited credentials; the wrapper does not
read `.env` in this mode. It calls `runner.py --verify-synthetic`, which uses
an in-memory catalog row and message, makes no network calls, writes no pilot
state, and reports explicit `network=false`, `secrets=false`, and `writes=false`
evidence. The wrapper's only verification artifact is a log inside the release
agent's disposable temporary directory.

Market News, Phintraco Swing, and Kelas no-post checks still connect to their
Telegram sources. Their disposable watcher state and media paths are isolated,
and the shared Telegram resilience library routes its state and log to the
release temporary directory. It must not mutate the production resilience
state or log.

The existing `#hermes` heartbeat is submitted through the shared Discord
Delivery Owner at `http://127.0.0.1:9140`. The systemd unit exposes the already
installed client package, and the release environment names its mode-0600
Delivery Owner client-token file. This package must never read or receive a
Discord bot token. Delivery remains best effort and does not affect release
state or GitHub status behavior.

No web application credential, Supabase database credential, watcher state,
or scheduler registry belongs in this package. Do not install the timer, add
the environment file, change sudoers, run `--release-manual`, or invoke the
agent against the VPS without explicit operations approval. The checked-in
bootstrap script requires `--apply` and verifies the installed shared client
and private client-token file, but remains an artifact and a runbook, not
authorization to mutate a host.

`release-manifest.json` is fail-closed. Every changed tracked source path must
map to exactly one declared unit. `manual` units are never processed by the
timer. They require a reviewed host operation followed by an explicit
`--release-manual` invocation by an operator. Manual database migrations use
the same gate: the timer blocks them, while the explicit invocation applies
them and records the reviewed release.
