<h1 align="center">
  <img src="bursawatch.png" alt="Bursawatch logo" width="44" align="absmiddle">
  Bursawatch
</h1>

<p align="center">
  <a href="https://github.com/absolutepraya/bursawatch-engine/actions/workflows/ci.yml"><img src="https://github.com/absolutepraya/bursawatch-engine/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
</p>

<p align="center">
  <img src="docs/images/overview.png" alt="Bursawatch collects sources, applies your rules and schedule, and delivers a market brief, company news and trading ideas to Discord">
</p>

**Indonesian stock-market information, curated and delivered to Discord.**
Bursawatch watches the places Indonesian retail investors already read
(Telegram channels, X, WhatsApp, Instagram, Stockbit, RSS, IDX disclosures),
filters out the noise with an AI judgment step, writes a short Indonesian
summary with a source link, and posts it to Discord exactly once. It also keeps
a live board of analyst swing-trading plans and publishes a pre-market morning
brief.

Product site: [bursawatch.abhipraya.dev](https://bursawatch.abhipraya.dev/) ·
Operator workspace: [dash.bursawatch.abhipraya.dev](https://dash.bursawatch.abhipraya.dev/workspace)

## What it does

| Product | What you get |
|---|---|
| **News pipeline** | Company, industry and macro news as separate cards, each with a source link. Company news carries 1D, 1W, 1M and 3M price moves. |
| **Swing trading plan** | Analyst calls (Phintraco, Kelas Investasi, X analysts and more) normalized into one format and tracked on a board, one thread per plan, as price moves from entry toward target or stop-loss. |
| **Morning brief** | A frozen-evidence pre-market brief for the IHSG session with sector and conglomerate rotation charts, published only after delivery receipts confirm each step. |

## Architecture

Every product shares one skeleton: **sources, intake, durable inbox, AI
judgment, delivery owner, Discord**. Rules and configuration live in a database
that the web config app edits, so changing a rule in the web app takes effect
on the next run. No send is ever duplicated: every message has an operation key
and a receipt, so retries are safe.

### 1. News pipeline

![News pipeline architecture](docs/images/news-pipeline.png)

Sources are polled by Python cron adapters, saved in a durable SQLite inbox
(timestamped, linked and deduplicated), judged by an AI step for relevance with
an Indonesian title and summary, and sent through the delivery owner to
Discord. A company catalog (Sectors data and filings) lets the impact check
name a company only when it can state a mechanism, which then shapes the
industry, company and macro cards.

### 2. Swing trading plan

![Swing trading plan architecture](docs/images/swing-trading-plan.png)

Source watchers parse qualifying calls from analyst sources and dedupe them.
AI summarizes the X and Kelas Investasi calls, and one shared swing format
renders every alert. The swing board itself is rule-based: it uses no AI and
infers no prices. It updates each plan's status from market data, from entry to
target or stop-loss.

### 3. Morning brief

![Morning brief architecture](docs/images/morning-brief.png)

The morning brief owner freezes its evidence at the 07:30 WIB cutoff, targets
delivery at 08:00 WIB and builds sector and konglo rotation views from cached
Sectors price and market-cap data. Publication is receipt-gated: each step
waits for a confirmed delivery before the next one runs, and the frozen attempt
deadline is 08:15 WIB.

### System map

```mermaid
flowchart LR
  subgraph Config["Configuration"]
    Web["web-config<br/>Next.js on Vercel"] --> API["service-bursawatch-control<br/>config + observability API"]
    API --> DB[("Supabase<br/>rules and schedules")]
  end

  subgraph Sources["Sources"]
    TG[Telegram]
    X[X]
    WA[WhatsApp]
    IG[Instagram]
    RSS[Stockbit RSS]
  end

  subgraph Runtime["VPS runtime (Hermes crons)"]
    Intake["cron-*-source-ingest<br/>adapters"] --> Inbox[("Durable inbox")]
    Inbox --> Owners["Domain owners<br/>news, swing, morning brief"]
    Owners --> Media["service-bursawatch-source-media<br/>private media storage"]
  end

  Sources --> Intake
  DB -. "rules, live" .-> Intake
  DB -. "rules, live" .-> Owners
  Owners --> Delivery["service-bursawatch-discord-delivery<br/>key, retries, receipt"]
  Delivery --> Discord[(Discord)]

  subgraph Release["Release"]
    CI["GitHub Actions CI"] --> Agent["platform-bursawatch-release<br/>VPS release agent"]
  end
  Agent -. "deploys allowlisted units" .-> Runtime
```

## Tech stack

Python (standard-library-first crons and services), Hermes agent scheduler,
SQLite durable inboxes, Supabase (database, auth and private storage),
Next.js web apps (Node 24) on Vercel, Discord bot delivery, Yahoo Finance and Sectors
market data, GitHub Actions CI with a VPS-local pull-based release agent.

## Repository guide

- **Crons** (`cron-<surface>-<purpose>`): one package per source adapter or
  domain owner. See the inventory below.
- **Services** (`service-bursawatch-*`): the control API, Discord delivery
  owner and source-media owner, each with its own README.
- **Libraries** (`lib-*`): shared clients and formatters.
- **Platform** (`platform-*`): release agent, observer and schedule reconciler.
- **Web** (`web-landing`, `web-config`): the public site and operator workspace.
- **Skills** (`.agents/skills/`): reusable, non-scheduled agent skills.
- **Docs** (`docs/`): ADRs, specs and history. Start at the
  [documentation guide](docs/README.md).

## Package inventory and engineering notes

This repository is the Mac development source for market-focused Hermes automation
and its two web applications.
Its scheduled packages deploy to the VPS as `bursawatch-<slug>`. Hermes
Personal is a separate repository at `~/Documents/Projects/Hermes-Personal`,
where personal crons deploy as `personal-<slug>`.

Every cron-oriented package has `AGENTS.md` and exactly one contract file:
`CRON.md` for deterministic packages or `SKILL.md` for agent-backed packages.
Some source-adapter packages run inside an existing Hermes job rather than
owning a separate schedule.

Production roles below were checked against the VPS on 2026-09-30. That
snapshot found 13 Hermes jobs, 8 active and 5 paused, with all 8 desired
interval schedules matching the live registry. Run the
[read-only production snapshot](scripts/production_snapshot.py) before relying
on a current schedule or release claim.

| Development package | Runtime identity | What it is | Production schedule state |
|---|---|---|---|
| `cron-tg-market-news` | `bursawatch-tg-market-news` | Telegram IDX company and macro-news domain owner | Standalone watcher paused; shared Telegram source job dispatches owner work |
| `cron-tg-phintraco-swing` | `bursawatch-tg-phintraco-swing` | Phintraco Daily cash-Swing domain owner | Standalone watcher paused; shared Telegram source job dispatches owner work |
| `cron-tg-kelas-investasi-gtw` | `bursawatch-tg-kelas-investasi-gtw` | Kelas Investasi GTW domain owner | Standalone watcher paused; shared Telegram source job dispatches owner work |
| `cron-dc-swing-board` | `bursawatch-dc-swing-board` | Discord Swing board owner and lifecycle/retry jobs | Active maintenance jobs |
| `cron-x-account-watch` | `bursawatch-x-account-watch` | X-account queue owner | Active source polling and queue-worker jobs |
| `cron-ig-account-watch` | `bursawatch-ig-account-watch` | Instagram account and reel watcher | Paused |
| `cron-wa-channel-watch` | `bursawatch-wa-channel-watch` | WhatsApp Channel queue and domain owner | Active; existing job runs WhatsApp source ingest |
| `cron-stockbit-snips` | `bursawatch-stockbit-snips` | Stockbit Snips domain owner | Active; existing job runs RSS source ingest every 15 minutes |
| `cron-tg-source-ingest` | `bursawatch-tg-source-ingest` | Telegram source, pipeline, and bounded agent handoff | Active standalone job, every minute |
| `cron-x-source-ingest` | `bursawatch-x-source-ingest` | X catalog and inbox adapter | Active through existing X source-polling job |
| `cron-ig-source-ingest` | `bursawatch-ig-source-ingest` | Instagram catalog and inbox adapter | Unscheduled pilot |
| `cron-wa-source-ingest` | `bursawatch-wa-source-ingest` | WhatsApp bridge-queue inbox adapter | Active through existing WhatsApp job |
| `cron-rss-source-ingest` | `bursawatch-rss-source-ingest` | Fixed Stockbit RSS inbox adapter | Active through existing Stockbit job |
| `cron-dc-morning-brief` | `bursawatch-dc-morning-brief` | Local frozen six-step market brief owner | Proposed runtime, rollout and activation separately gated |

Production source intake has one dedicated Telegram job plus X, WhatsApp, and
RSS adapters under existing owner jobs. Instagram source ingest has no
registered job, and its legacy watcher is paused. Standalone Telegram News,
Phintraco, and Kelas watcher jobs are paused while the active Telegram source
job dispatches accepted work to their domain owners. The shared
`lib-bursawatch-source-ingest` code stages bounded endpoint-local events and
advances a private cursor only after an inbox receipt. Media uses the shared
Source Media Owner contract; no live bucket or service bootstrap is claimed.
The [migration inventory](docs/superpowers/specs/2026-09-25-bursawatch-source-pipeline-migration-inventory.md)
lists checked-in endpoint/state contracts and the live evidence still required.

`lib-sectors` and `lib-chart-img` provide shared cache-only provider clients.
`lib-yahoo-market-data` provides pure daily OHLC, native cap/action validation
and local SMA/RSI calculations. The morning producer retains bounded Yahoo
sources for the IHSG chart and fixed-membership rotation, with per-basket
current/previous-week cap fallback and explicit omissions for unsupported data.
The [morning contract](cron-dc-morning-brief/SKILL.md) describes the local owner,
private immutable state, offline preview and receipt-gated publication. These
provider/morning packages and the Yahoo calculation library are manual release
units, with provisioning and activation governed by their package contracts.

`lib-swing-format` is the shared cash-Swing renderer. `lib-telegram-resilience`
owns the shared PolyCop Telegram control plane. Hermes Personal's Polymarket
cron consumes that library at runtime, so its control state remains single-owner.

`service-bursawatch-control` owns the Bursawatch configuration and
observability API. `lib-bursawatch-control` is the standard-library runtime
client used by migrated crons. The web workspace integrates through the
service's versioned OpenAPI contract. The service can store a catalogued job's
desired interval schedule, but only a separately approved VPS reconciler may
apply that intent to Hermes.

`.agents/skills/profile-emoji` is a reusable, non-scheduled skill, and
`.agents/skills/finish-workflow` is the review handoff skill.
`platform-bursawatch-observer` contains read-only VPS job-observation code.
Its first host install, separate credential, and timer activation were
completed as a manual VPS operation on 2026-09-30. The package remains outside
automatic releases.
`service-rsshub` records the VPS-owned shared RSSHub boundary without copying
its compose files, credentials, cookies, proxy configuration, or runtime data
into source control.

The news owners share `lib-news-format` for generated Telegram, X, WhatsApp,
Instagram, and Stockbit cards. Independent issuer stories receive separate
cards with native-currency quotes and 1D/1W/1M/3M changes. Existing saved
payloads, raw-forwarding profiles, and specialized Swing/status output retain
their owner contracts. This describes source behavior, not a live rollout.

## Web applications

| Package | Purpose | Local guide |
|---|---|---|
| `web-landing` | Public product site and sample market walkthrough | [Landing setup](web-landing/README.md) |
| `web-config` | Signed-in operator workspace for configuration, schedules and run evidence | [Workspace setup](web-config/README.md) |

The current sites are [the landing page](https://bursawatch.abhipraya.dev/)
and [the workspace](https://dash.bursawatch.abhipraya.dev/workspace). Source
changes reach them through the separate Vercel web release path.

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

Before making current schedule or release claims, run
`python3 scripts/production_snapshot.py --production`. The read-only helper
checks gateway health, filters the VPS scheduler listing to Bursawatch jobs,
compares desired schedule revisions with the live registry, and compares the
release agent's last successful SHA with `origin/main`. It does not prove
runtime checksums or a natural source-to-delivery event.

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

- This private repository is the canonical development source for Bursawatch market automation, its web applications, shared libraries, and reusable skills.
- `hermes-agent-starter/` remains an independent repository and is intentionally ignored here.
- Runtime state, credentials, caches, worktrees, generated previews, and MM backfill outputs are never tracked.
- Dotfiles owns machine configuration and scrubbed VPS runtime snapshots, not duplicate Hermes development source.

## Validation and deployment

GitHub Actions runs CI and has no VPS credential or deployment authority. The
VPS-local release agent automatically handles allowlisted backend units only
after the exact current `main` SHA passes `CI / validate`. Web deployments stay
under Vercel's separate Git integration. See `DEPLOYMENT.md` for the release
gates and verification boundaries.

Manual deploy helpers remain separate recovery paths with their documented
approval gates. Do not run one concurrently with the release agent.

The initial split cutover changed source and runtime identities while retaining
established production state locations. Physical state migration is a separate,
stopped-writer and integrity-checked operation.

## Docs

Read the [documentation guide](docs/README.md) first. Current cron guidance lives in each cron's `AGENTS.md` plus its single contract file. Historical decisions and implementation records remain under [`docs/adr/`](docs/adr/), [`docs/specs/`](docs/specs/), and [`docs/superpowers/`](docs/superpowers/), including the [documentation-governance design](docs/superpowers/specs/2026-08-22-hermes-documentation-governance-and-dotfiles-boundary-design.md) and [implementation plan](docs/superpowers/plans/2026-08-22-hermes-documentation-governance-and-dotfiles-boundary.md).
