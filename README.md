# Bursawatch

[![CI](https://github.com/absolutepraya/bursawatch-engine/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/absolutepraya/bursawatch-engine/actions/workflows/ci.yml)

Bursawatch is the Mac development source for market-focused Hermes automation
and its two web applications.
Its scheduled packages deploy to the VPS as `bursawatch-<slug>`. Hermes
Personal is a separate repository at `~/Documents/Projects/Hermes-Personal`,
where personal crons deploy as `personal-<slug>`.

Every scheduled package has `AGENTS.md` and exactly one contract file:
`CRON.md` for deterministic packages or `SKILL.md` for agent-backed packages.

| Development package | Runtime identity | What it is |
|---|---|---|
| `cron-tg-market-news` | `bursawatch-tg-market-news` | Telegram IDX company and macro-news watcher |
| `cron-tg-phintraco-swing` | `bursawatch-tg-phintraco-swing` | Phintraco Daily cash-Swing forwarder |
| `cron-tg-kelas-investasi-gtw` | `bursawatch-tg-kelas-investasi-gtw` | Kelas Investasi GTW bundle watcher |
| `cron-dc-swing-board` | `bursawatch-dc-swing-board` | Discord Swing board owner and close reconciler |
| `cron-x-account-watch` | `bursawatch-x-account-watch` | X-account watcher and queue worker |
| `cron-ig-account-watch` | `bursawatch-ig-account-watch` | Instagram account and reel watcher |
| `cron-wa-channel-watch` | `bursawatch-wa-channel-watch` | WhatsApp Channel watcher and queue |
| `cron-stockbit-snips` | `bursawatch-stockbit-snips` | Stockbit Snips RSS news watcher |

`lib-swing-format` is the shared cash-Swing renderer. `lib-telegram-resilience`
owns the shared PolyCop Telegram control plane. Hermes Personal's Polymarket
cron consumes that library at runtime, so its control state remains single-owner.

`service-bursawatch-control` owns the Bursawatch configuration and
observability API. `lib-bursawatch-control` is the standard-library runtime
client used by migrated crons. The web workspace integrates through the
service's versioned OpenAPI contract. The service can store a catalogued job's
desired interval schedule, but only a separately approved VPS reconciler may
apply that intent to Hermes.

`skill-guess-stock` and `skill-profile-emoji` are reusable, non-scheduled
market skills. `service-cobalt` is the tracked media-download service.
`service-rsshub` records the VPS-owned shared RSSHub boundary without copying
its compose files, credentials, cookies, proxy configuration, or runtime data
into source control.

## Web applications

| Package | Purpose | Local guide |
|---|---|---|
| `web-landing` | Public product site and sample market walkthrough | [Landing setup](web-landing/README.md) |
| `web-config` | Signed-in operator workspace for configuration, schedules and run evidence | [Workspace setup](web-config/README.md) |

The current sites are [the landing page](https://bursawatch-web-landing.vercel.app/)
and [the workspace](https://bursawatch-web-config.vercel.app/workspace).
These URLs are existing Vercel deployments; this pull request only moves and
reviews their source until a separate web release publishes the new revision.

Each package installs and builds independently with Node 24. The workspace
uses a signed-in user's Supabase token to call the control API through a
same-origin proxy. The backend owns authorization, persistence, automation and
delivery. The public `/app` concept uses local sample data; `/workspace` reads
the control API. See the [web deployment guide](DEPLOYMENT.md) and
[source migration record](web-config/docs/MIGRATION.md). The web source was
previously developed in `dafandikri/bursawatch-web`; this import preserves
that provenance and does not rewrite its history.

## Workflow
1. Read the package `AGENTS.md` and its `CRON.md` or `SKILL.md`, then edit source under `cron-<slug>/bin/`.
2. `./deploy.sh cron-<slug>` copies `bin/` to `~/.agents/skills/bursawatch-<slug>/bin/`. Single file: `./deploy.sh cron-<slug> scan.py`.
3. For a changed contract file, commit and push first, compare it with the VPS copy, obtain approval for the first VPS write, then sync only that file and compare checksums.
4. Verify with the watcher's isolated no-post controls. Live source and Telegram verification run on the VPS.
5. The VPS uses `~/.local/share/uv/tools/yahoo-finance-mcp/bin/python` for market watchers.

For collaboration, create feature worktrees through the tracked `.wt/config.toml`.
The repository-local `finish-workflow` skill validates, commits, pushes, and
opens or updates a pull request. It leaves the branch and worktree intact and
does not deploy or merge changes. Deployment and post-merge cleanup need
separate explicit approval.

The two web applications stay in separate Vercel projects rooted at their
package directories. Web CI validates them without credentials or deployment
authority. The VPS release manifest treats web paths as metadata; it never
copies web files to the VPS. A change to the release manifest itself remains
subject to the release agent's manual review gate.

## Don't
- Don't edit `~/.dotfiles/vps/agents/skills/<runtime>/`. It is an `rsync --delete` backup mirror pulled **from** the VPS.
- Don't replace or initialize `state/` during deployment. Live state owns cursors, suppression, retries, and deduplication.
- Don't create watcher-owned Mac virtual environments. Shared local verification uses `~/Documents/Projects/Hermes/.venv`.

## Tests
From a package directory: `../.venv/bin/python -m pytest -q`.

From the repository root, `./.venv/bin/python -m pytest -q` runs the repository policy tests only. Cron projects intentionally use isolated script-local imports, so `bash scripts/test-all` is the canonical command for the complete suite.

Run every deterministic focused suite from the repository root:

```bash
bash scripts/test-all
```

GitHub Actions exposes separate checks for `CI / validate`,
`CI / Deterministic package suites`, and `CI / WhatsApp Channel Watch`. The
last check runs the full WhatsApp Channel Python suite and JavaScript sink
suite directly, while the complete local command still runs every suite in
one pass. The VPS release agent can additionally publish the exact production
state as the `bursawatch/release` commit status.

`Web CI` runs formatting, lint, type checks, unit tests, production builds and
synthetic Chromium interaction tests for both web packages. It does not use
production credentials or prove a live watcher run.

## Repository boundaries

- This private repository is the canonical development source for Bursawatch market automation, its web applications, shared libraries, reusable skills, and Cobalt.
- `hermes-agent-starter/` remains an independent repository and is intentionally ignored here.
- Runtime state, credentials, caches, worktrees, generated previews, and MM backfill outputs are never tracked.
- Cobalt cookies remain machine-local at `service-cobalt/compose/cookies.json`; the reviewed compose definition stays tracked.
- Dotfiles owns machine configuration and scrubbed VPS runtime snapshots, not duplicate Hermes development source.

## Validation and deployment

GitHub Actions runs read-only tests, shell syntax checks, and tracked-file policy checks. It has no secrets, VPS access, or deployment authority. A GitHub push never deploys anything.

All deployments remain explicit local commands. The deploy scripts refuse a dirty worktree or a commit that is not published to `origin`, then copy only their documented source paths to the VPS. Continue to verify deployed checksums and the cron-specific no-post path after every manual deployment.

The first split cutover changes source and runtime identities while retaining
established production state locations. Physical state migration is a separate,
stopped-writer and integrity-checked operation.

## Docs

Read the [documentation guide](docs/README.md) first. Current cron guidance lives in each cron's `AGENTS.md` plus its single contract file. Historical decisions and implementation records remain under [`docs/adr/`](docs/adr/), [`docs/specs/`](docs/specs/), and [`docs/superpowers/`](docs/superpowers/), including the [documentation-governance design](docs/superpowers/specs/2026-08-22-hermes-documentation-governance-and-dotfiles-boundary-design.md) and [implementation plan](docs/superpowers/plans/2026-08-22-hermes-documentation-governance-and-dotfiles-boundary.md).
