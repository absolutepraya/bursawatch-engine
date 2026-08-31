# Hermes development repository

## Scope

This private repository is the canonical Mac development home for Hermes cron skills, Cobalt, and Yanto's lifecycle-voice plugin. These rules apply throughout the repository, including new and renamed crons. Cobalt is part of the parent Git history, while its service-specific workflow remains documented under `cobalt/`.

`hermes-agent-starter/` is a separate repository with its own remote and workflow. It is intentionally ignored by the parent repository. Never stage, commit, rewrite, or deploy it through Hermes repository commands.

## Child project instructions

When working inside a project or cron directory, read its local `AGENTS.md` before changing anything. A child file supplements this root contract and may add project-specific rules, but it cannot weaken root safety, approval, deployment, or credential rules.

Current child instruction files:

- `x-post-watch/AGENTS.md`: X account intake, profile configuration, classifier boundaries, promotion exclusions, and watcher deployment.

## Conversation language

- Use English by default for questions, status updates, explanations, and final responses, including when the user mixes English and Indonesian.
- Use Indonesian only when the user explicitly asks for it or when producing an Indonesian-facing deliverable.
- This policy applies only to the interactive agent conversation. It does not change a cron's rendered message, summary, prompt, notification, or delivery-language contract.
- Preserve each cron's specified output language. An Indonesian cron summary remains Indonesian unless the user explicitly changes that cron's contract.

## Terms

- **Dev source**: the cron directory in this repository, for example `us-etf-dca-watch/`.
- **Runtime skill**: the deployed VPS directory at `~/.agents/skills/<cron>/`.
- **Live state**: the runtime `state/` files that own cursors, deduplication, alert suppression, retries, and checkpoints.
- **Dotfiles mirror**: `~/.dotfiles/vps/agents/skills/`, a backup mirror pulled from the VPS. It is never an authoring or deployment target.
- **Published commit**: a clean commit reachable from the configured `origin` remote. Only published commits are eligible for deployment.

## Repository and dotfiles boundaries

- Track reviewed development source in this repository. Do not track credentials, runtime state, caches, generated previews, local backfills, virtual environments, or worktrees.
- `CONTEXT.md` files are temporary agent working knowledge, not repository source. Never stage or commit them, even when an existing `CONTEXT.md` is modified.
- `.worktrees/` and other repository scratch space are local-only. They must not be added to Git or dotfiles capture coverage.
- Dotfiles owns machine configuration and scrubbed VPS runtime snapshots. It does not own duplicate Hermes development source.
- `Documents/Projects/Hermes/**`, including this `AGENTS.md` and `yanto-gateway-voice/`, is intentionally absent from the dotfiles Mac capture map. Do not restore the retired `mac/hermes/` snapshot.
- Herdr `*.sock` files are runtime IPC artifacts and must remain excluded from dotfiles captures.
- Live files and runtime state remain canonical on their owning machine. Before any Mac/VPS copy, compare the exact files and obtain approval for the first VPS write in the conversation.

## Source of truth and deployment

1. Develop code in `<cron>/bin/` here, not by editing the VPS runtime or dotfiles mirror.
2. GitHub Actions is validation only. It has read-only repository permissions, no secrets, no VPS access, and no deployment authority. A push must never deploy automatically.
3. Before deployment, commit the intended scope, push it to `origin`, and use a clean checkout. Deployment guards must reject dirty or local-only source.
4. Deploy executable cron changes with `./deploy.sh <cron>` from this repository. Deploy one file with `./deploy.sh <cron> <file>` only when the smaller scope is intentional.
5. `deploy.sh` copies only `bin/`. If `SKILL.md` changes, sync that exact file separately to `vps:~/.agents/skills/<cron>/SKILL.md` after its local review.
6. Use `cobalt/deploy.sh` for Cobalt and `yanto-gateway-voice/deploy.sh --apply` for the voice plugin. Their deployment guards enforce the same published-commit boundary.
7. Never overwrite between this Mac and the VPS without first comparing the relevant files. A newer timestamp is not evidence that a version is correct.
8. Confirm deployment by comparing the local and VPS checksums of each changed runtime file.
9. Never edit `~/.dotfiles/vps/agents/skills/<cron>/`. The scheduled dotfiles sync mirrors the VPS into that path.
10. Never deploy, reset, delete, or hand-edit live `state/`. State is production data, not source code.

## Post-deployment dotfiles capture

The deployed VPS runtime remains canonical. Dotfiles is the scrubbed backup that captures it afterward, never a second deployment target.

1. After deploying and verifying a cron, confirm the VPS `dotfiles-sync` job can reach the Mac with `~/.hermes/scripts/dotfiles-sync.sh --check`.
2. The registered Hermes job is `804f44f0be6e`. Let its normal schedule perform the capture unless the user explicitly asks for an immediate run in the current conversation. For an approved immediate run, use `/home/praya/.local/bin/hermes cron run 804f44f0be6e`; never invoke the wrapper as a substitute for the registered run.
3. Verify the registered execution record is `completed`, the saved output contains `mac=ok vps=ok` plus `git=push` or `git=noop`, and the job remains enabled with a valid next run.
4. Verify `~/dotfiles` is clean and its `config` HEAD equals `origin/config`. A scheduler `ok` label without saved output and Git parity is not sufficient evidence.
5. Confirm each changed runtime source is present in the expected snapshot path. Cron skills map from `~/.agents/skills/<cron>/` to `vps/agents/skills/<cron>/`; Hermes wrappers map from `~/.hermes/scripts/` to `vps/hermes/scripts/`; the registry maps to `vps/hermes/cron/jobs.json`.
6. Compare VPS runtime and dotfiles snapshot checksums for changed source files when they are expected to be byte-identical. For intentionally scrubbed files, verify the scrubbed content and path instead of requiring an identical checksum.
7. State, credentials, databases, logs, virtual environments, caches, and other capture-map exclusions must remain absent. Never weaken exclusions merely to make a snapshot look complete.

## Required development loop

1. Read the cron's `SKILL.md`, scanner, wrapper, tests, and current VPS behavior that the change affects.
2. Preserve the cron's deterministic boundary. Fetching, parsing, scoring, deduplication, gating, persistence, rendering, and direct platform posting belong in the deterministic script. LLM work is limited to the explicit wake-on-findings contract, if the cron has one.
3. Add or update a behavioral regression test for every bug fix or user-visible change. Test output, transitions, boundaries, suppression, and failure handling. Do not test source text or incidental implementation details.
4. Run the focused test first, then the cron's complete test suite using the shared project environment:
   ```bash
   ../.venv/bin/python -m pytest -q
   ```
5. Deploy only after tests pass. Then run the cron's documented no-post / dry-run control and verify the affected live path.
6. A smoke test must not create a Discord, Telegram, or market-order side effect. Set the cron's no-post flag and use force controls only for deterministic verification.
7. Report the exact test result, deploy result, and live verification evidence. Do not claim a future scheduled execution was observed before it has run.

## Network and runtime boundaries

- Use `~/Documents/Projects/Hermes/.venv` for local tests. Do not create watcher-specific Mac virtual environments.
- Market watcher runtime uses `~/.local/share/uv/tools/yahoo-finance-mcp/bin/python` on the VPS. Do not reinstall its `uv` tool without restoring shared dependencies required by other watchers.
- Verify `idx-ca-watch`, `polymarket-signal-watch`, and `idx-swing-watch-phintraco-daily` against the VPS. Their relevant data sources are not reliably verifiable from the Mac.
- Treat upstream data as delayed and fallible. Surface source health, rate limits, timeouts, and stale data. Do not invent missing news, prices, disclosures, or successful delivery.
- Keep every cron's time-zone and market-window logic explicit and test its boundaries. Cron cadence must land inside, not merely adjacent to, the intended window.

## Shared PolyCop Telegram session

- `idx-market-news-watch`, `idx-swing-watch-phintraco-daily`, `idx-ssf-watch-phintraco-weekly`, `kelas-investasi-gtw-watch`, and `polymarket-signal-watch` share exactly one Telegram user session: `POLYCOP_SESSION_STRING`. Do not add watcher-specific Telegram session variables or auth files.
- The shared control plane is `~/.hermes/state/telegram-resilience-polyclop.json`, owned only by `telegram-resilience`. It serializes healthy probes, coordinates transport backoff, and records an authorization hold. Never reset, edit, or copy this state as source code.
- Before creating a Telegram client, each watcher must acquire the shared probe through `acquire_probe_after_active_lease`. A peer's active healthy lease may be waited briefly; a transport cooldown or authorization hold must exit cleanly without advancing provider cursors, queues, outboxes, or delivery state.
- An unauthenticated session is an `auth_required` incident, not a transport retry. Transport failures use the shared bounded backoff and one claimed operational notification. Do not log session strings, API hashes, or other credentials.
- Cron wrappers and the Market News agent submission command must use the supported wrapper or export the `telegram-resilience/bin` path. Do not invoke a resilience-dependent scanner directly without its import path.
- For a change to this contract, add shared resilience regressions and each affected watcher regression, deploy the changed files, compare VPS checksums, run no-post verification with isolated state, then inspect the shared control state and target delivery path.

## Job Watcher

- Develop Job Watcher in `job-watcher/`. Its live runtime resolves from `~/.agents/skills/job-watcher/` on the VPS, and its Hermes wrapper is `~/.hermes/scripts/job-watcher.sh`.
- Hermes is the primary scheduler. The intended schedule is daily at 08:00 WIB, but the live Hermes registry is authoritative for its current enabled state and next run. Job cards are direct-posted to `#notification`; every non-dry run must also emit a deterministic `#hermes` heartbeat. Delivery is Indonesia-only, including Indonesia-based remote roles. Foreign and unknown-location roles are excluded.
- Job Watcher source is captured as a dereferenced, scrubbed VPS dotfiles snapshot. Do not treat `~/.dotfiles` as an authoring or deployment target for it. Preserve VPS `state.db*`, `state/`, logs, virtual environment, and credentials as live runtime data; those are excluded from capture.
- Job Watcher uses deterministic fast paths for obvious Indonesia-based senior/leadership, internship, entry-level, and Staff roles. Only ambiguous candidates reach the Hermes LLM, in batches of up to six, where it makes the final `send` / `exclude` / `review` seniority-and-experience decision and produces one concise paragraph each for Experience and Job description for `send`. Staff technical roles remain eligible. `exclude` and `review` never post. Fast-path summaries use complete source-text segments without a model call. The legacy SQLite column names `exp_bullets` and `jobdesc_bullets` are retained for compatibility and store one paragraph per section. Discord delivery uses one embed per role, with jobs as fields inside it.
- For Job Watcher changes, run the focused parser, renderer, matching, and scoring tests locally and on the VPS, compare deployment checksums, then use a no-post dry run. Do not manually trigger the Hermes schedule as a smoke test because the scanner posts directly to Discord.

## Security Audit

- Develop the VPS Security Audit in `security-audit/`. Its Hermes wrapper runs daily at 07:30 WIB but gates the full deterministic audit to an exact three-day cadence. Every invocation posts one operational heartbeat to `#heartbeat` (`1505162000420835388`); only actionable findings are delivered to `#security` (`1535121748129873940`), without a heartbeat line.
- The daily APT security-update timer is a separate remediation path. The Hermes audit reports its health and must never reboot the VPS. Package-managed service restarts are allowed.
- Preserve the separation: the audit scans the Debian-packaged RKHunter database and inspects state, but it must not alter firewall rules, accounts, SSH policy, package selections, or the RKHunter property baseline. System configuration files live under `security-audit/system-config/` and require reviewed, approved `sudo install` deployment plus a preserved backup and SSH preflight.
- Keep exposure expectations in `security-audit/config/baseline.json`. A new listener or UFW rule is a finding, never an implicitly accepted baseline. Do not manually run the scheduled Hermes job as a smoke test because it runs RKHunter and posts to Discord.

## Operational changes require explicit approval

Do not make any of the following changes without the user's explicit approval in the current conversation:

- Add, remove, rename, enable, disable, or reschedule a Hermes cron.
- Change delivery platform, Discord channel, Telegram destination, or posting cadence.
- Restart or reconfigure Hermes gateway or other runtime services.
- Reset state, replay alerts, backfill messages, or delete externally posted messages.
- Place, cancel, or modify a market order.

When an approved cron schedule must change, use the supported Hermes cron command from a VPS-local agent. Do not hand-edit `~/.hermes/cron/jobs.json`.

## Cron delivery format

Hermes `cron.wrap_response` is intentionally set to `false` globally. Every cron delivery must contain only the cron's raw rendered output, without the built-in `Cronjob Response` header, job ID, separator, or footer. This is a global Hermes setting, not a per-cron option. Obtain explicit approval before changing it.

## New and renamed crons

A cron is not complete until its identity is consistent across:

- local directory and `SKILL.md` front matter
- `bin/` scanner and wrapper names
- VPS runtime skill path
- `~/.hermes/scripts/` wrapper
- registered Hermes cron job
- root `README.md` inventory
- tests, fixtures, and deployment instructions

Every new Hermes cron must emit a heartbeat to Discord `#hermes` (`1505162000420835388`) on every run, including no-hit and no-op runs:

```text
🫀 <name> · HH:MM WIB · <tokens>[ ⚠️]
```

Use a trailing warning marker for degraded runs. Use this fatal form when the run cannot complete:

```text
❌ <name> · HH:MM WIB · failed: …
```

## Review checklist

Before yielding a cron change, confirm:

- Scope is limited to the requested behavior.
- Every caller, wrapper, skill instruction, and deployment target reflects the same contract.
- No deprecated payload key, alias, or renamed path remains.
- Tests prove the changed behavior and all affected tests pass.
- The VPS runtime matches the reviewed local source.
- The changed VPS runtime source has been captured into dotfiles, or the handoff explicitly says the next scheduled capture is still pending. Verification includes saved output and `config`/`origin/config` parity, not only scheduler status.
- No-post verification exercised the real rendering and posting path without producing an external message.
- Live state and dotfiles mirror were not edited as source.
