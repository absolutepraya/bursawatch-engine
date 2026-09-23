# Bursawatch landing

Independent Next.js landing page. The interactive market example uses fixed
sample figures; it does not request prices, run jobs or deliver messages.
The workspace and all configuration live in [`../web-config/`](../web-config/README.md)
in this repository. The backend packages remain separate deployment units;
this app does not require their services to run locally.

## Local development

Use Node 24. Start `web-config` on port 3100, then run:

```bash
cd web-landing
npm ci
npm run dev
```

Open `http://localhost:3200`. Workspace links default to
`http://localhost:3100` in development. Set `BURSAWATCH_CONFIG_URL` in the
server environment or an untracked `.env.local` for another origin. It must
be an origin only: no credentials, path, query or fragment. HTTP is accepted
only for local development loopback addresses.

## Validation and deployment boundary

```bash
BURSAWATCH_CONFIG_URL=https://config.example.test npm run check
```

That example is a validation placeholder, not a deployment destination.
Production builds fail unless `BURSAWATCH_CONFIG_URL` names an HTTPS workspace
origin (not localhost). Set the real origin before building: the static landing
embeds its navigation URLs at build time. Rebuild to change destinations.
`npm start` serves the production build on port 3200. The independent Vercel
project is `bursawatch-web-landing`; Git auto-deployment stays disconnected.
See [DEPLOYMENT.md](../DEPLOYMENT.md) for environment and release checks.

## Source and brand provenance

For browser checks, install Chromium with `npx playwright install chromium`,
start the local server, then run `npm run test:browser`. When checking a
production build, pass the same `BURSAWATCH_CONFIG_URL` used at build time.
The smoke test checks preview interactions, all workspace URLs, three viewport
sizes and 200% text. It never follows links to an external deployment.

Migrated as a fresh source snapshot on 2026-09-18 from the team's prior web
implementation at commit `501c0f896f94b8258325fa7e6e6e0b510ed30692`. Original
history was not imported or rewritten. This extraction is not a claim that
the original work was created on the migration date. The destination is the
user's standalone web repository; the web packages were then imported into
`absolutepraya/bursawatch-engine` on 23 September 2026.
See the [migration record](../web-config/docs/MIGRATION.md) for the source
snapshot, public catalog review and backend boundary.

`src/components/brand.tsx`, `src/app/icon.svg`, `src/app/apple-icon.png` and
the landing styles retain the approved Signal Fold identity. They are
intentionally mirrored with the sibling application, not pulled from private
Hermes media. Coordinate future brand changes across both packages. The
landing ships no broker or social profile photographs and imports no private
watcher configuration. See [DESIGN.md](DESIGN.md) and [AGENTS.md](AGENTS.md)
for the active visual and engineering contracts.
