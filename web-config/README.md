# Bursawatch configuration workspace

This independent Next.js package contains the user workspace and configuration
dashboard. The public website is a separate package at `../web-landing/`.
The sibling `cron-*` packages own automation; this app does not start a worker.

## Run locally

Use Node 24 and npm. From the repository root:

```sh
cd web-config
npm ci
npm run dev -- --port 3100
```

Open `http://localhost:3100/workspace`. Create an ignored `.env.local` from
`.env.example` with your Supabase URL, **publishable** key and server-only
`CONTROL_PLANE_API_URL`. Do not copy the backend `.env` or use a database,
service-role, machine or reconciler secret. The owner must provide a Supabase
Auth account; dashboard collaboration alone does not grant app access.

The same-origin Next.js proxy passes the current user's token to the backend,
which enforces shared viewer/admin permissions. It is not a consumer tenancy
system. See [CONTROL_PLANE.md](docs/CONTROL_PLANE.md) for the reviewed contract,
save semantics and live acceptance checks. No CORS access from browsers to the
backend is required by this proxy design.

## Authenticated workspace

- **Overview**: recorded activity chart/table, reconciliation and recent runs.
- **Sources**: Securities, Institutions and People & Org with public references
  and catalog settings. Configuration links require a matching watcher returned
  by the authenticated API.
- **Workflows**: nine schema-specific watcher editors for authorized admins.
  Morning Brief timing and content settings are saved separately from job
  activation and cadence in Jobs.
- **Jobs**: shared schedules, pending/effective state and fixed jobs. Config and
  schedule saves are separate.
- **History**: actual returned run metadata and event timelines.
- **Account**: signed-in identity, UUID sharing and sign-out.

The former `/workspace/schedules` URL remains a compatibility entry point to
workflow configuration. It is no longer a primary navigation destination.

Uncertain saves are never silently retried. Revision preflight is best effort,
not an atomic concurrency lock. Coordinate one editor per record until the API
supports revision preconditions. A completed scan is not proof of delivery.

## Sample workspace (`/app`)

The no-login sample mirrors the seven authenticated destinations and reuses
their workspace components. It renders synthetic in-memory records through a
fixture-backed request function, makes no `/api/control` requests or network
writes, and labels the sample clearly. Supported watcher and Source Catalog
edits confirm through the same read-after-write flow as the authenticated UI.
Jobs and History remain read-only. Legacy consumer URLs redirect to their
closest current destination.

## Validation

```sh
npm run check
npm run start -- --port 3100
```

`check` runs formatting, lint, route/type checks, unit tests and a production
build. Production uses `.next-build`; development uses `.next`. Never delete
either while its server runs. Build/watch roots are confined to this package.
If file-watcher limits persist, stop development and use
`npm run dev:safe -- --port 3100`. Validate `web-landing/` separately before
a PR handoff. Neither app requires Python or running the backend locally.

For browser checks, install Chromium once with `npx playwright install chromium`.
After `npm run check`, start a production server with synthetic public settings:

```sh
NEXT_PUBLIC_SUPABASE_URL=https://workspace-smoke.example.test \
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_workspace_smoke_fixture \
CONTROL_PLANE_API_URL=https://control.example.test \
npm run start -- --hostname 127.0.0.1 --port 3100
```

Then run `BURSAWATCH_TEST_URL=http://127.0.0.1:3100 npm run test:browser` from a
second terminal. Auth and control requests in the live-workspace regression are
fully intercepted; unexpected external requests are blocked. This is not proof
of a real user's access or production scheduler behavior. The smoke suite
checks source follow/configuration, validation, toast feedback, all five delivery
forms, responsive routes, enlarged text and read-only API boundaries. It uses
an isolated browser context and does not send messages or change live services.
The source-editor suite also exercises full-config saves, profile add/remove,
Discord routing, local avatar matching and preservation of unknown fields.
The signed-in browser smoke checks Published records, incomplete publisher
coverage, and the Jobs note that schedule observations do not confirm a
Discord delivery. All auth and publication data in that check are synthetic;
a live source-to-room correlation remains a separate read-only operation.

See [integration](docs/INTEGRATION.md), [migration provenance](docs/MIGRATION.md),
[design](DESIGN.md), and [brand philosophy](docs/BRAND_PHILOSOPHY.md).
Public asset provenance is under `public/brokers/` and `public/sources/`.
Source selection does not certify identity, credentials or investment results.
Catalog tests compare against a pinned allowlisted public fixture reviewed at
backend commit `f36823f`; they do not import live or private watcher settings.

Vercel hosts this package independently as `bursawatch-web-config`; the old demo
project is not reused. See [DEPLOYMENT.md](../DEPLOYMENT.md) for the environment,
release sequence and live acceptance checks. Production deployment requires
explicit approval; pushing the feature branch does not deploy automatically.
Tenant isolation is not implemented by the current backend; keep authenticated
access to team operators. Hosting alone does not verify their permissions.
