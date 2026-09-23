# Web deployment

Deploy the web packages independently to the user's Vercel account. The
repository root is not a Next.js project; the sibling backend packages have
their own release path. The source repository stays private. Publishing a
feature branch does not automatically deploy it.

| Package | Vercel project | Purpose |
| --- | --- | --- |
| `web-config` | `bursawatch-web-config` | Supabase sign-in and operator workspace |
| `web-landing` | `bursawatch-web-landing` | Public product site |

Both use Node 24, `npm ci`, `npm run build`, and `.next-build` output. Set
`NEXT_DIST_DIR=.next-build` in the Vercel environment as well: the platform's
Next.js adapter also reads configuration outside the npm build subprocess.
The package-level `.vercelignore` files exclude local environment files, build
output, test artifacts and databases. Inspect upload inputs with
`vercel deploy --dry --json` before a release.

`web-config` functions run in Singapore (`sin1`) to avoid the default US hop
for the Indonesian workspace. Its six public opening shells are pre-rendered;
private API responses remain `no-store` and user-token authorized. Supabase
public settings are embedded at build time, so changes require a new deployment.
The backend API origin remains a server-only runtime setting. Do not move or
replicate the teammate's database as part of web hosting changes.

## Environment

Configure only these application settings in Vercel, never the backend `.env`:

- Config: `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `CONTROL_PLANE_API_URL`.
- Landing: `BURSAWATCH_CONFIG_URL`, the exact HTTPS production workspace origin
  with no path or trailing slash. This is embedded at build time.
- Both: `NEXT_DIST_DIR=.next-build`.

The publishable key is public browser configuration. A database password,
service-role key, machine token or reconciler credential must never be added.
The API origin is server-only; all protected requests forward the signed-in
user's Supabase token. Hosting does not grant administrator permissions.

## Release sequence

1. Run both packages' checks and isolated browser suites on the feature branch.
2. Commit and push with the actual commit date; keep the review PR open.
3. Verify Vercel project identity and production environment names. Stage
   `web-config` first using `vercel deploy --prod --skip-domain` from its directory.
   Check the ready deployment's login shell and unauthenticated API rejection
   with `vercel curl`, then promote that exact deployment with `vercel promote`.
4. Set the landing's workspace origin to the verified config production alias,
   then stage, check and promote `web-landing` the same way.
5. Check both production aliases, landing-to-workspace links, the login screen,
   mobile layout, keyboard controls, reduced motion, security headers and
   unauthenticated API rejection. Never put credentials in smoke-test output.
6. Have an authorized operator sign in for live read verification. Any live
   config/schedule write needs approval for the exact target and change. Never
   run a watcher or send a message as a smoke test.

The existing `bursawatch-friend-demo` project is not a deployment target and is
left unchanged. Keep Git auto-deploy disconnected unless separately approved.
If a release fails, do not promote it; keep the last healthy production alias.

## Administrator access

The teammate owns access provisioning. Copy the Supabase UUID from
`/workspace/settings` and ask the owner to append it to
`CONTROL_PLANE_ADMIN_USER_IDS` in the control service's dedicated environment,
preserving existing UUIDs. The setting accepts comma-separated unique UUIDs,
without empty entries. The owner restarts `bursawatch-control-plane.service`
afterward; the web app has no role-management endpoint or browser role override.

The authenticated workspace is a shared team-operator interface, not a
tenant-isolated consumer service. Sample charts and automated browser fixtures
are not proof of real delivery, administrator access or unattended runs.
