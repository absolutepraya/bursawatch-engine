# Web deployment

The two web packages target separate Cloudflare Workers in the `absolutepraya`
account (`40ffe81c2b657eebc19edd8558b5f5ba`). Node 24 builds Next.js through
OpenNext; Wrangler publishes the resulting Worker and static assets. Backend
services remain on the VPS, and Supabase Auth and data stay with Supabase.
The VPS release agent never deploys these web packages.

| Package | Worker | Production origin | Purpose |
| --- | --- | --- | --- |
| `web-config` | `bursawatch-dash` | `https://dash.bursawatch.abhipraya.dev` | Supabase sign-in and operator workspace |
| `web-landing` | `bursawatch-landing` | `https://bursawatch.abhipraya.dev` | Public product site |

This is the source deployment contract. A passing local build or this document
is not proof of the initial production cutover. Confirm the deployed version,
custom domain, HTTPS response and authenticated behavior before declaring it
complete. The old Vercel projects may remain paused and disconnected for rollback;
they are not targets of the new workflow. Do not delete them during cutover.

## Configuration and runtime boundaries

Each package owns `wrangler.jsonc` and `open-next.config.ts`. Production uses
only its explicit custom domain. Production `workers_dev` and `preview_urls`
are disabled. PR previews use separately named Workers and generated
`.wrangler-preview.json` files with no production routes or bindings.

The dashboard targets Singapore with `placement.region=aws:ap-southeast-1`.
This minimizes the change from the former Singapore function location, but is
a placement preference rather than a guarantee of a specific data center.
The landing serves through the global Workers network. Images retain their
original static assets; no Cloudflare Images service or new cache datastore is
provisioned. Public pre-rendered pages use OpenNext's read-only Static Assets
incremental cache; authenticated API routes remain dynamic. No private API response may enter a shared cache. `/api/control`
continues forwarding only the signed-in user's token and returns `private,
no-store` responses. No machine token, service-role key or database password
belongs in a web Worker or build.

Development uses `.next-dev`; ordinary Node production checks use `.next-build`.
OpenNext requires `.next` and emits `.open-next`. Keeping these trees separate
prevents Workers builds from replacing an active development server's output.
All generated output, runtime type declarations and local `.dev.vars*` files
are ignored. Run `npm run typegen:workers` after binding changes. It generates
binding declarations without adding Workers runtime globals to browser types.

## GitHub settings

Use the private `absolutepraya/bursawatch-engine` repository. Keep values out of
source code, command arguments and logs. Provision these repository settings
with protected input or stdin:

| Kind | Name | Use |
| --- | --- | --- |
| Actions secret | `BURSAWATCH_CLOUDFLARE_API_TOKEN` | Workers deployment, production domains and preview Access applications |
| Actions secret | `BURSAWATCH_CONTROL_PLANE_API_URL` | Server-only runtime API origin |
| Actions variable | `BURSAWATCH_SUPABASE_URL` | Public Supabase URL embedded during dashboard build |
| Actions variable | `BURSAWATCH_SUPABASE_PUBLISHABLE_KEY` | Public browser publishable key embedded during dashboard build |
| Actions variable | `BURSAWATCH_PREVIEW_EMAIL` | Exact email permitted through preview Access gates |
| Actions variable | `BURSAWATCH_PRODUCTION_ENABLED` | `false` until the approved first DNS cutover; `true` enables production releases |

The Cloudflare token needs the target account's Workers deployment permissions
and Workers Routes access for `abhipraya.dev`. Prefer a token restricted to that
account and zone. Protected PR previews also require account Access Apps and
Policies Write. DNS record changes during first cutover require zone DNS edit
access too. Verify the actual token policy and target before a mutation; being
logged in does not prove the necessary permissions. Never copy an expiring
Wrangler OAuth login into CI.

The landing builds with
`BURSAWATCH_CONFIG_URL=https://dash.bursawatch.abhipraya.dev`; the same public
origin is also a Wrangler runtime variable for server rendering. Public Supabase
settings are build inputs; changes require rebuilding the dashboard. The
server-only control origin is supplied to Wrangler through a temporary mode-0600
JSON secrets file with the deployment, not a separate secret update that would
deploy an intermediate version. Vercel's `NEXT_DIST_DIR` and generated platform
tokens are not migration inputs. Only the four allowlisted app settings above
are carried over; never copy the backend environment wholesale.

## CI/CD

`.github/workflows/web.yml` validates each package with synthetic settings:
formatting, lint, types, unit tests, a Node production build, Chromium smoke,
Workers type generation, OpenNext packaging, Wrangler dry run and local Workers
runtime smoke. Validation jobs receive no Cloudflare or production application
credentials. Same-repository PRs then build and smoke-test separate preview
artifacts with blank Supabase and control-plane settings. Fork PRs only run
validation and cannot access deployment secrets.

Whenever either web package or its preview workflow changes, both packages
produce previews. The deployment job requires both validation jobs to succeed
and verifies that the same-repository PR remains open at the event's head SHA.
It downloads the validated artifacts rather than rebuilding with credentials.
Only its Access/deployment steps receive the Cloudflare token. It never reads
the production application secrets or public Supabase variables.

The Workers are `bursawatch-dash-pr-<number>` and
`bursawatch-landing-pr-<number>`, under `absolutepraya.workers.dev`. The landing
links to its matching dashboard. Both hostnames have email-only Cloudflare
Access applications created and read back before upload; allowlist drift fails
the deployment instead of widening access. The configured reviewer signs in
through Cloudflare Access using `BURSAWATCH_PREVIEW_EMAIL`. Native version URLs
remain disabled, and no production custom domain is attached. Anonymous HTML,
asset and API requests must redirect to Access before links are published. A
failed deployment or protection check removes the preview Workers and retains
their gates.

`BURSAWATCH_PREVIEW_MODE=1` redirects dashboard root and workspace URLs to the
existing fixture-only `/app`. Every control API read/write returns 503 with
`no-store` before any forwarding, including requests carrying a user JWT.
The landing preview adds `noindex`. These settings do not change production
workspace behavior.

One bot comment contains both preview URLs and the source head SHA, updated on
each successful run. `.github/workflows/web-preview-cleanup.yml` runs on every
same-repository PR close or merge, even if web changes were later reverted. It
uses the base branch helper and serializes with preview deployment. The helper
deletes only the two fixed PR Worker names, then their owned Access applications;
missing resources are harmless. A failed Worker deletion leaves Access intact.
Changing the reviewer email requires intentionally updating existing preview
policies or recreating them; routine builds do not silently change access.

`.github/workflows/web-deploy.yml` is the separate production workflow. It runs
only when `BURSAWATCH_PRODUCTION_ENABLED=true`, after successful push-based
Web CI on `main`, or via a manual dispatch from
`main` whose exact SHA already has successful push-based Web CI. It rejects
foreign repositories, PR events, unsuccessful validation and stale commits.
It checks the exact current `main` SHA again immediately before publishing.
Each app builds from its package root with production settings; deployment uses
only the web-specific Cloudflare secret. Production releases are serialized.
The post-deploy step checks public HTTPS availability and verifies that the
unauthenticated control API returns 401 with `no-store` caching.

The old owner-sign workflow is removed. The retained `web_owner_sign.py` helper,
its tests and package markers have no active workflow caller and grant no
Vercel or Cloudflare deployment authority. No owner-authored marker commit is
needed by Workers. Vercel Git connections remain disconnected. The VPS
release agent retains its separate exact-current-main `CI / validate` gate.
Do not wait or poll for CI; inspect a completed run when its result is needed.

## Initial cutover and acceptance

1. Validate both packages locally with Node 24: `npm ci`, `npm run check`,
   `npm run typegen:workers`, `npm run check:workers`, and the browser suites
   against local Workers. In the `web-landing` shell, first export
   `BURSAWATCH_CONFIG_URL=https://config.example.test` for these validation
   commands. Run `bash scripts/test-all` for the repository suite.
2. Review the source and workflow changes. Production cutover remains a
   separately approved action after review. Publishing a feature branch does
   not authorize merging or switching DNS.
3. Verify the Cloudflare token policy, account, zone and existing Worker/domain
   inventory. Confirm GitHub deployment settings are present and compare the
   existing Vercel production app settings without logging their values.
4. Save the exact existing DNS records and Vercel rollback metadata under
   `/Users/absolutepraya/Documents/Backups/bursawatch-web-cutover-yyyymmdd-hhmmss`.
   Do not overwrite or delete unrelated records. The initial observed CNAMEs
   point to Vercel; a Workers Custom Domain cannot be bound over a conflicting
   CNAME. Keep `BURSAWATCH_PRODUCTION_ENABLED=false` while reviewing and merging
   the source. After explicit cutover approval and successful current-main Web
   CI, remove only those exact two CNAME records, set the activation variable
   to `true`, and dispatch Web Deploy from `main` to attach the matching Worker
   custom domains. Reserve a short DNS/TLS transition window and verify both
   origins immediately; existing DNS caches can outlast the record change.
   Record the new Worker version IDs and domain ownership. Preserve Vercel
   deployments unchanged. Later validated main pushes deploy automatically.
5. Verify the landing, active sign-in destination, disabled coming-soon demo
   buttons, HTTPS certificates, security headers, mobile layouts and assets.
   Verify `/workspace` shows its public opening shell, `/app` remains fixture
   only, and unauthenticated `/api/control` calls return 401 and `no-store`.
   Have an authorized operator verify live signed-in reads. Never change a real
   setting, invoke a watcher or send a synthetic message to test hosting.
6. After the reviewed migration reaches `main`, verify one completed Web CI and
   Web Deploy run for the exact source SHA and compare its Worker versions with
   Cloudflare. A manual local upload does not prove unattended CI/CD works.
   Preserve paused Vercel projects until this acceptance is complete.

If cutover fails, set `BURSAWATCH_PRODUCTION_ENABLED=false` and inspect the
failing version. Restore only the saved
DNS records and the prior Vercel serving state under the approved rollback
scope. Workers code rollback does not restore external state, but this web
migration does not move Supabase data or VPS runtime state. Never weaken the
backend API's authorization, reset state or replay alerts to make a hosting
check pass.

## Administrator access

The backend owner controls access provisioning. Copy the Supabase UUID from
`/workspace/settings` and ask the owner to append it to
`CONTROL_PLANE_ADMIN_USER_IDS` in the control service's dedicated environment,
preserving existing UUIDs. The web app has no role-management endpoint or browser
role override. The operator workspace is shared, not a tenant-isolated consumer
service. Sample data and browser fixtures are not proof of real delivery or
administrator access.

## References

- [Cloudflare OpenNext deployment guide](https://developers.cloudflare.com/workers/framework-guides/web-apps/opennext/)
- [Wrangler GitHub Actions authentication](https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/)
- [Workers placement](https://developers.cloudflare.com/workers/configuration/placement/)
- [OpenNext environment variables](https://opennext.js.org/cloudflare/howtos/env-vars)
