# Bursawatch development repository

## Scope and split boundary

This private repository is the canonical Mac development source for
Bursawatch market automation. It retains full pre-split Git history, while
Hermes Personal is a separate repository at
`~/Documents/Projects/Hermes-Personal`.

Packages use these names:

- `cron-<surface>-<purpose>` is a scheduled development package.
- `bursawatch-<surface>-<purpose>` is its VPS runtime identity.
- `lib-<purpose>` is shared imported code.
- `skill-<purpose>` is a reusable non-scheduled skill.
- `service-<purpose>` is a deployable daemon or service definition.
- `platform-<purpose>` is host-bound supporting code.

The current scheduled packages are `cron-tg-market-news`,
`cron-tg-phintraco-swing`, `cron-tg-kelas-investasi-gtw`,
`cron-dc-swing-board`, `cron-x-account-watch`, `cron-ig-account-watch`, and
`cron-wa-channel-watch`. `idx-ca-watch` and `yanto-gateway-voice` are retired
and must not be recreated.

The first production cutover changes source, runtime, wrapper, and scheduler
identities while retaining established production state locations. A later,
separately approved state migration must stop each writer and watchdog, prove
integrity, move atomically, and verify the resumed runtime. Never hand-edit,
reset, replay, or copy live state as source.

VPS-only retained runtime material has one canonical backup tree:
`~/backup/hermes/`. Store state-cutover rollback archives at
`runtime-cutovers/<YYYY-MM-DD>/<runtime-identity>/` and release snapshots at
`runtime-releases/<runtime-identity>/`. Archive inactive legacy logs only after
proving that no active wrapper or process references them, at
`legacy-logs/<YYYY-MM-DD>/`; current runtime logs remain in `~/.logs/`.
Preserve every archive type for at least 30 days, exclude it from Git and
dotfiles, and require separate approval before deletion.

## Child instructions

Read a package `AGENTS.md` before modifying it. These child files supplement
this contract:

- `service-cobalt/AGENTS.md`
- `service-bursawatch-control/AGENTS.md`
- `cron-tg-market-news/AGENTS.md`
- `cron-dc-swing-board/AGENTS.md`
- `cron-tg-phintraco-swing/AGENTS.md`
- `cron-ig-account-watch/AGENTS.md`
- `cron-tg-kelas-investasi-gtw/AGENTS.md`
- `skill-guess-stock/AGENTS.md`
- `skill-profile-emoji/AGENTS.md`
- `cron-wa-channel-watch/AGENTS.md`
- `cron-x-account-watch/AGENTS.md`
- `platform-bursawatch-release/AGENTS.md`

## Documentation model

Each scheduled package has `AGENTS.md` and exactly one root contract:
`CRON.md` for a deterministic no-agent package, or `SKILL.md` for an
agent-backed package. Reusable skills retain their own `SKILL.md`. Keep
documentation aligned with the code, runtime identity, wrapper, scheduler,
tests, and deployment instructions in the same change.

[`docs/README.md`](docs/README.md) distinguishes active operating guidance
from retained design and implementation history. A historical record may name
a pre-split directory or runtime identity and must never override a current
package contract.

`CONTEXT.md` is ignored local scratch. Do not read, stage, commit, deploy, or
delete it in ordinary work. `.worktrees/` is local-only and must not be moved,
cleaned, committed, or included in dotfiles capture.

## Collaboration workflow

Both Hermes repositories use the identical `.wt/config.toml` configuration.
Use isolated managed feature worktrees through `wt` by default; never use a
raw Git worktree when the repository is WT-configured. An explicit current-chat
request from the human user to work on `main` overrides that default: work
directly on `main` until the user asks to use a worktree again.

T3 Code keeps its own worktree manager. In `t3.json`,
`defaultThreadEnvMode = "worktree"` is a repository fallback, so T3 project or
environment settings take precedence. WT and T3 worktree creation both call
`scripts/prepare-control-plane-worktree.sh` to share the ignored
`service-bursawatch-control/.env` only when the package is present and the
worktree has no conflicting path. T3 project actions from `t3.json` require an
explicit import in T3 before `runOnWorktreeCreate` runs; a tracked file alone
does not enable the action. T3's project file does not configure WT's worktree
directory, slot allocation, port offsets, branch template, or base branch.

The repository-local `.agents/skills/finish-workflow/` skill is an optional
review and pull-request handoff. Do not create a pull request automatically;
use that skill only when the user asks for a review or pull request. It retains
its branch and worktree for collaboration. Production work remains a separate
explicitly approved action after review.

## Source, runtime, and deployment

1. Develop in this repository, never in the VPS runtime or dotfiles mirror.
2. Run focused tests, then the package suite and `bash scripts/test-all`.
3. Commit the intended scope and push it to the Bursawatch `origin` remote.
4. `./deploy.sh cron-<slug>` copies only `bin/` to
   `~/.agents/skills/bursawatch-<slug>/bin/`. It supports a deliberate single
   file deployment as `./deploy.sh cron-<slug> <file>`.
5. Contract files, scheduler wrappers, services, and skill runtime prompts are
   separate deploy inputs. Compare every changed file against the VPS before
   the first write, receive current-session approval, then compare checksums.
   A scheduler wrapper under `~/.hermes/scripts/` must retain mode `0755` and
   pass a direct executability check before a cron is retargeted to it.
6. GitHub Actions validates only and has no production credential or VPS
   access. After the exact current `main` SHA passes `CI / validate`, the
   separately bootstrapped VPS-local release agent may deploy only the
   allowlisted units in `platform-bursawatch-release/release-manifest.json`.
   It is the sole automatic deployment authority. A normal push never gives
   GitHub Actions deployment access.

`service-cobalt/deploy.sh` owns Cobalt deployment. `skill-profile-emoji/deploy.sh`
owns its skill deployment. The generic deploy helper supports cron and library
packages only.

`service-bursawatch-control/deploy.sh` owns repeat releases of the already
bootstrapped Bursawatch control-plane API. Before deployment approval, use its
read-only `plan`, `status`, or `verify` commands to inspect the target. After
focused tests, `bash scripts/test-all`, a clean published commit, and explicit
current-chat approval, use `release --apply` for its bounded source sync,
dependency update, migration and baseline seed, restart, and health checks.
It never copies `.env`, changes the dedicated service environment, systemd
unit, Nginx, DNS, TLS, Hermes schedules, or the schedule reconciler. Those
remain separate reviewed deployment work.

After the reviewed release agent is bootstrapped, it owns ordinary eligible
control-plane releases instead. The helper remains a manually approved
recovery path and must never run concurrently with the release agent. The
release agent itself is host-bound platform infrastructure: its code, token
file, systemd assets, and sudo boundary change only through the explicit VPS
bootstrap process, never through an ordinary automated release.

The dotfiles mirror is a scrubbed VPS backup, not an authoring or deployment
target. Do not edit `~/.dotfiles/vps/agents/skills/`. After an approved runtime
deployment, use `sync-mac --check` before an explicitly approved capture. A
successful scheduler label alone is not capture proof: verify saved output and
`config` branch parity.

## Shared dependencies

`lib-telegram-resilience` owns the shared `POLYCOP_SESSION_STRING` control
plane at `~/.hermes/state/telegram-resilience-polyclop.json`. Bursawatch
Market News, Phintraco Swing, and Kelas Investasi GTW use it, and Hermes
Personal Polymarket uses the same Bursawatch-owned runtime library. Do not
create a second session or resilience state.

`lib-swing-format` is shared by Phintraco Swing, Kelas Investasi GTW, the
Swing board, and X Swing context. `service-rsshub` documents the one VPS-hosted
RSSHub instance that serves Bursawatch social watchers and Hermes Personal US
ETF DCA. Its credentials, cookies, proxy configuration, compose files, and
runtime data remain VPS-owned until a separate reviewed import is approved.

## Safety

- Do not add, remove, rename, enable, disable, or reschedule a live Hermes job
  without explicit current-chat approval and the supported Hermes CLI.
- Do not change delivery destinations or cadence without explicit approval.
- Outside the approved release agent, do not restart services, manually
  trigger production schedules, post test messages, place orders, reset state,
  or replay alerts as a smoke test. The release agent may restart only the
  scoped control-plane service through its reviewed sudoers rule after a
  verified eligible release.
- Use a package's documented isolated no-post control for runtime verification.
- Never commit credentials, runtime state, caches, logs, media, local virtual
  environments, generated artifacts, worktrees, or service cookies.
- Preserve the universal RSSHub route-specific `IG_PROXY`; do not replace it
  with a global proxy setting.

## Repository boundaries

The Bursawatch web application is maintained in a separate repository and
integrates with `service-bursawatch-control` through its versioned API
contract. This repository has no web application or web deployment authority.
`hermes-agent-starter/` is an ignored independent repository.

Use English for this interactive engineering work unless the user asks for
Indonesian. Preserve each watcher's output-language contract.
