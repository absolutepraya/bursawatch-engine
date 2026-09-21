# Control-plane VPS deployment assets

These files define the reviewed target for the Bursawatch control-plane API.
They are not a deployment command. Do not copy them to the VPS, apply a
migration, create DNS, obtain a certificate, or start a service without an
explicit deployment approval in the current chat.

## Target layout

```text
/home/praya/.hermes/
  bursawatch-control-plane.env           API-only values, mode 0600
  bursawatch-control-plane/
    baseline-configs/
    bin/
    migrations/
    requirements.txt
    validator-sources/
    venv/
```

The API listens only on `127.0.0.1:9120`. Nginx is the sole public entrypoint
for `https://api.bursawatch.abhipraya.dev`. Do not bind the API to a public
address or open port 9120 in UFW.

## Manual recovery releases

Once the separate Bursawatch release agent has been bootstrapped, it owns
ordinary eligible control-plane releases from verified `main`. The package
helper below is retained for an explicitly approved recovery operation only;
never run it concurrently with the release agent:

```bash
./service-bursawatch-control/deploy.sh plan
./service-bursawatch-control/deploy.sh verify
# After explicit deployment approval:
./service-bursawatch-control/deploy.sh release --apply
```

The helper syncs only the API payload, updates the existing virtual environment,
applies migrations, seeds only absent baseline revisions, restarts the existing
service, and verifies health. The automatic agent applies only migrations
classified as automatic and already validated in ephemeral PostgreSQL CI. The
helper does not bootstrap or reconfigure the host:
it never copies `.env`, edits the dedicated environment, systemd unit, Nginx,
DNS, TLS, Hermes scheduler, or reconciler.

## Planned reviewed sequence

1. Compare this source branch and each template with the VPS target.
2. Copy only `baseline-configs/`, `bin/`, `migrations/`, `requirements.txt`,
   and `validator-sources/` into the dedicated runtime directory. Do not copy
   a local `.env` file.
3. Create the dedicated Python virtual environment and install
   `requirements.txt`.
4. Copy the already-approved server-only values into the dedicated
   `~/.hermes/bursawatch-control-plane.env`, with mode `0600`. Set each
   `CONTROL_PLANE_*_CONFIG_VALIDATOR_DIR` to its matching
   `/home/praya/.hermes/bursawatch-control-plane/validator-sources/<watcher-id>`
   directory. Do not point the API at a live watcher runtime directory or add
   these API-only keys to Hermes's shared `.env`.
5. Source the dedicated environment, then run `venv/bin/python bin/migrate.py`
   and `venv/bin/python bin/seed_baseline_configs.py`. The migration runner
   records immutable file checksums and aborts on a changed applied migration.
   The baseline seeder creates config revision 1 only when that watcher has no
   configuration history, so it cannot overwrite dashboard changes.
6. Install the systemd unit, reload systemd, and start the API. Verify only
   `http://127.0.0.1:9120/healthz` first.
7. Create the matching DNS record, install the HTTP Nginx bootstrap vhost, and
   issue a certificate with Certbot. Verify public HTTPS only after the local
   health check succeeds.
8. Keep `CONTROL_PLANE_ALLOWED_ORIGINS` blank until the web app has a real
   deployed origin. Then add only that exact HTTPS origin and restart the API.

The web app uses browser Supabase authentication, while this API uses its own
Postgres connection. Do not expose the database, machine token, reconciler
token, database password, or Supabase service-role key to Nginx or the web app.
