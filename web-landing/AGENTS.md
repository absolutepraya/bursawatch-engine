# Bursawatch landing application

Read root `AGENTS.md` and this package's `DESIGN.md` before editing. This is
an independent Next.js application for the public landing page only. The
workspace is the sibling `web-config/` package in this repository. The backend
packages are separate deployment units; do not recreate their settings,
source catalog, APIs or runtime logic here.

Preserve canonical `Bursawatch` spelling and the approved Signal Fold mark.
Keep keyboard focus, the skip link, sample-data disclosure, readable contrast,
44px targets and reduced-motion support. Check the landing at 375px and 200%
text size after visual changes. Brand SVG paths and semantic tokens are
intentionally mirrored from `web-config/`; review both packages when changing
the shared identity. Do not redesign one application in isolation.

Only server code may read `BURSAWATCH_CONFIG_URL`. Validate it before passing
public destination URLs to client components. Use ordinary anchors across
application origins. Production requires an explicit HTTPS workspace origin
(not localhost); do
not silently route deployed visitors to localhost or the retired demo host.
No credentials, private watcher settings or runtime state belong here.

Run `npm ci` and `npm run check` with `BURSAWATCH_CONFIG_URL` set to the target
workspace origin. CI may use `https://config.example.test` for a build-only
check, never for deployment. Node production output is `.next-build`, development
uses `.next-dev`, and OpenNext reserves `.next` plus `.open-next` for Workers packaging. Never
delete an active server's output. Keep dependencies, local env,
builds and browser screenshots untracked. Publishing is not deployment approval.

Same-repository PR previews point only to their matching dashboard preview.
They use `BURSAWATCH_PREVIEW_MODE=1`, add `noindex` response headers, and require
Cloudflare Access before serving HTML or assets. Production destinations and
domains must never be inherited by generated PR preview configurations.
