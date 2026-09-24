# Web deployment

The production web applications are Git-connected projects in Daffa
Abhipraya's `personalpraya` Vercel account. The repository root is not a
Next.js project; sibling backend packages have a separate VPS release path.
The source repository stays private. Both Vercel projects track `main` and
build from their own package roots.

| Package | Vercel project | Production origin | Purpose |
| --- | --- | --- | --- |
| `web-config` | `personalpraya/bursawatch-dash` | `https://dash.bursawatch.abhipraya.dev` | Supabase sign-in and operator workspace |
| `web-landing` | `personalpraya/bursawatch-landing` | `https://bursawatch.abhipraya.dev` | Public product site |

The older `bursawatch-web-config` and `bursawatch-web-landing` projects in
`erdafas-projects` can serve isolated previews; they are not these production
targets. The `bursawatch-friend-demo` project is not a deployment target.
Do not promote a preview on any of those projects as a substitute for a
`personalpraya` release.

Both use Node 24, `npm ci`, `npm run build`, and `.next-build` output. Set
`NEXT_DIST_DIR=.next-build` in the Vercel environment as well: the platform's
Next.js adapter also reads configuration outside the npm build subprocess.
The package-level `.vercelignore` files exclude local environment files, build
output, test artifacts and databases. Inspect upload inputs with
`vercel deploy --dry --json` before any separately approved manual CLI release.

`web-config` functions run in Singapore (`sin1`). Its public opening shells
are pre-rendered; private API responses remain `no-store` and user-token
authorized. Supabase public settings are embedded at build time, so changes
require a new deployment.
The backend API origin remains a server-only runtime setting. Do not move or
replicate the teammate's database as part of web hosting changes.

## Environment

Configure only these application settings in the corresponding Vercel
project, never the backend `.env`:

- Config: `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `CONTROL_PLANE_API_URL`.
- Landing: `BURSAWATCH_CONFIG_URL=https://dash.bursawatch.abhipraya.dev`.
  It must be the exact HTTPS workspace origin, with no path or trailing slash,
  and is embedded at build time.
- Both: `NEXT_DIST_DIR=.next-build`.

The publishable key is public browser configuration. A database password,
service-role key, machine token or reconciler credential must never be added.
The API origin is server-only; all protected requests forward the signed-in
user's Supabase token. Hosting does not grant administrator permissions.

## Owner sign Action

Vercel has blocked preview deployments for non-owner-authored commits in the
friend-owned projects. The visible deployment list alone does not establish
the precise block reason. The web-only
`.github/workflows/web-owner-sign.yml` workaround is a production-path
experiment, not proof that Vercel will accept a new commit: verify the actual
Vercel result before calling the release complete.

After a successful `Web CI` run caused by a `main` push changing
`web-config/` or `web-landing/`, the separate Action checks that the run was a
successful `push` on `main`, that the token belongs to `absolutepraya`, and
that the current `main` web trees still match the validated run's head SHA.
`scripts/web_owner_sign.py` compares each package's tracked-tree fingerprint
without its marker. On its first successful run it initializes both
`web-config/absolutepraya-sign.md` and `web-landing/absolutepraya-sign.md`,
even if the source push changed only one package. That commit can trigger
both Vercel projects. Later runs update whichever marker is stale. Each run
makes at most one owner-authored commit using Daffa's token. A sign-only push
leaves the fingerprints unchanged and must not make another sign commit. The
new push starts CI for its own SHA; the original source SHA's CI result does
not validate the resulting `main`.
Vercel's existing Git integration, not the Action, builds and deploys the web
projects. The Action has no Vercel or VPS credential and must never check out
or execute code or artifacts from an untrusted PR with its write token.

Daffa sets up the repository secret himself:

1. As `absolutepraya`, create a fine-grained GitHub personal access token
   restricted to the `bursawatch-engine` repository, with only repository
   **Contents: Read and write** beyond GitHub's mandatory metadata access.
   Choose an expiry and rotate or revoke it when no longer needed.
2. In the GitHub repository, open **Settings → Secrets and variables → Actions**
   and save it as `ABSOLUTEPRAYA_WEB_SIGN_TOKEN`. Never paste it into chat,
   a PR, a commit, logs, or a local `.env` file for this handoff.
3. Confirm that `absolutepraya` is the GitHub account linked to the owner of
   the `personalpraya` Vercel projects. After the first sign run, inspect the
   resulting commit's GitHub author attribution and Vercel deployment status.

Without that secret, the Action fails and there is no owner sign push or
verified release through this path. Do not replace the token with a broad
GitHub or Vercel credential.
The ordinary `GITHUB_TOKEN` is insufficient to trigger follow-on `push`
workflows from an Action-created commit.

## Review and release sequence

1. Run both packages' checks and isolated browser suites on the feature
   branch. Review the PR and its source changes. A separate user-owned preview
   may help review the UI, but does not prove the friend-owned project will
   deploy or that its production environment is correct.
2. Have Daffa verify the project roots, Git connection, `main` production
   branch and environment variable names in both `personalpraya` projects.
   Confirm the owner sign secret is configured directly in GitHub. Merging a
   web PR can cause a production deployment, so obtain the owner's release
   approval before merging.
3. Merge the reviewed PR. Confirm `Web CI` passed for the source push, the
   owner sign Action produced one commit with the required package marker
   changes, and the sign-only push did not create a loop. The first run should
   initialize both markers. Record the sign commit SHA.
   The merge SHA may itself show a blocked Vercel deployment; inspect the
   owner-authored sign SHA instead.
4. Wait for `CI / validate` and the relevant `Web CI` checks on the **exact
   current `main` SHA**, including the sign commit. In Daffa's Vercel account,
   inspect each project triggered by that SHA; check both projects when the
   markers are first created. Confirm the build logs, `Ready` state and
   production domain assignment. A green web build or sign Action is not
   delivery proof.
5. Check both production origins, the landing-to-workspace links, login
   screen, mobile layout, keyboard controls, reduced motion, security headers
   and unauthenticated API rejection. Never put credentials in smoke-test
   output. Have an authorized operator sign in for live read verification.
   Any live config or schedule write needs approval for the exact target and
   change. Never run a watcher or send a message as a smoke test.

If a sign run or Vercel deployment fails, stop and inspect that exact run and
deployment. Keep the last healthy production deployment; Daffa can use Vercel's
project rollback controls if the new production deployment is unhealthy. Do
not manually append timestamps, repeatedly re-run the Action, change Vercel
plan or move Git credentials into the app to force a deployment.

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
