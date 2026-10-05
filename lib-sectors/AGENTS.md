# Shared Sectors transport and coordination library

Read the repository AGENTS.md before changing this package. This library owns
fixed-origin HTTP, request identity, the host-local provider cache, fetch leases,
and conservative credit reservations. It does not own the morning run database,
publication layout, model calls, Discord delivery or scheduler state.

Importing `sectors_client` must perform no IO. Constructors and configuration
loading are explicit. Load only `SECTORS_API_KEY` from this package's ignored
`.env`, never shell-source a file. The canonical Mac credential file is the main
checkout's `lib-sectors/.env`; worktree links must preserve existing paths and
must not replace conflicting files. Do not copy credentials or state to the VPS.
VPS provisioning remains a separate approved operation.

Use one explicitly configured private host-local SQLite store and the same
billing-window identity for every participating consumer. A store or window
chosen independently by each consumer defeats host coordination. Cache-only
mode is the default. No fetch is authorized by an import, cache miss, preview
regeneration or stale historical setup allowance.

Before any explicitly authorized network request, reserve the caller's declared
conservative maximum cost against both caller and host limits. Preserve uncertain
reservations and expired leases until explicit billing reconciliation. Do not
infer a provider account balance from this ledger. Do not add automatic retries,
redirects or provider-origin overrides.

Tests use fake HTTP and temporary SQLite. Run from the repository root:

```sh
../../.venv/bin/python -m pytest -q lib-sectors/tests
```

Use the main checkout's `.venv/bin/python` when running outside a worktree.
Do not contact a paid endpoint for tests. Keep local state, private retained
responses, credentials and generated previews outside Git.
