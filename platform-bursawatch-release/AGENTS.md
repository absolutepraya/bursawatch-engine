# Bursawatch release-agent instructions

This host-bound platform package defines the VPS-local pull release agent for
eligible Bursawatch `main` commits. The running agent is installed once at
`~/.local/lib/bursawatch-release/`; ordinary releases do not update its code,
systemd units, environment file, sudoers rule, or privileges.

The agent polls GitHub using a dedicated read-only token, requires the exact
current `main` SHA to have a successful `CI / validate` run, checks a tracked
release manifest, and materializes that SHA from its local bare mirror. It
deploys only known runtime handlers, verifies synchronized checksums, runs
the package's isolated no-post control, and stores sanitized durable release
records under `~/.local/share/bursawatch-release/`.

No web application credential, Supabase database credential, watcher state,
or scheduler registry belongs in this package. Do not install the timer, add
the environment file, change sudoers, run `--release-manual`, or invoke the
agent against the VPS without explicit operations approval. The checked-in
bootstrap script is an artifact and a runbook, not authorization to mutate a
host.

`release-manifest.json` is fail-closed. Every changed tracked source path must
map to exactly one declared unit. `manual` units are never processed by the
timer. They require a reviewed host operation followed by an explicit
`--release-manual` invocation by an operator.
