# Web migration — September 2026

## Provenance

The web began in `dafandikri/bursawatch-friend-demo` at reviewed commit
`501c0f896f94b8258325fa7e6e6e0b510ed30692`. On 18 September it was
imported into the user's private `dafandikri/bursawatch-web` repository as
`web-config/` and `web-landing/`. That preparation referenced backend commit
`f36823f` in the former `absolutepraya/bursawatch` repository.

On 23 September, the two tracked web packages and web deployment guide were
imported from `dafandikri/bursawatch-web` at `0c7117b4adb54d2c8cb94708e6c2c16b4dbfbe4d`
into a feature branch of `absolutepraya/bursawatch-engine`. The engine's cron,
control API and runtime packages were not copied from the web repository or
changed by this import. Web validation runs in an additional workflow. The
backend release manifest classifies web files as metadata; Vercel remains the
web deployment path.

Both imports are source snapshots, not merged or cherry-picked histories.
New commits use their actual creation dates. This does not change when the
original work was written, erase authorship, or establish hackathon eligibility.

The user requested the existing two-package structure: `web-config/` owns the
dashboard and `web-landing/` owns the public website. Both install, run and
validate independently. Shared visual conventions retain the approved identity
without coupling either application to the other's build or runtime.

## First import: historical changes

- Apply canonical Bursawatch spelling; retain the approved Signal Fold identity.
- Add Instagram preferences and recommendations aligned with public identities
  reviewed in backend configuration at `f36823f`. Test against a pinned public
  fixture, without importing backend configuration or requiring its checkout.
- Replace writable SQLite with fixed read-only sample records. Deny server
  mutations regardless of environment flags.
- Omit the former worker, credentials, environments, databases, runtime state,
  deployment linkage, dependency trees and generated review outputs.
- Preserve historical timestamps instead of fabricating fresh unattended runs.
- Isolate Next.js build/watch roots; add web CI and ignore local artifacts.

## First import: historical acceptance gates

1. Clean Node 24 installation, types, tests and build without secrets.
2. Desktop/mobile navigation, follow/configure/toasts, drafts and recovery work.
3. Instagram validates and legacy preferences remain readable.
4. Browser preferences cannot mutate live config or send messages.
5. Both independent web packages pass their checks and the configuration
   browser smoke suite passes against an isolated local server.
6. Publish the reviewed feature branch and open a PR when authorized. Do not
   merge, deploy, rewrite history or change the teammate's repository.

The closing paragraph of the original migration is superseded. The current
`/workspace` uses the shared operator control API and Supabase Auth; `/app`
remains a browser-local sample. See [CONTROL_PLANE.md](CONTROL_PLANE.md) for
the implemented boundaries and pending live acceptance evidence. The backend
does not yet offer tenant-isolated consumer accounts or all of the sample's
proposed outbound channels.
