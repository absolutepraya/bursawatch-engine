# Control-plane VPS deployment assets

These files define the reviewed target for the Bursawatch control-plane API.
They are not a deployment command. Do not copy them to the VPS, apply a
migration, create DNS, obtain a certificate, or start a service without an
explicit deployment approval in the current chat.

## Target layout

```text
/home/praya/.hermes/
  .env                                  scoped values, mode 0600
  bursawatch-control-plane/
    bin/
    migrations/
    requirements.txt
    venv/
```

The API listens only on `127.0.0.1:9120`. Nginx is the sole public entrypoint
for `https://api.bursawatch.abhipraya.dev`. Do not bind the API to a public
address or open port 9120 in UFW.

## Planned reviewed sequence

1. Compare this source branch and each template with the VPS target.
2. Copy only `bin/`, `migrations/`, and `requirements.txt` into the dedicated
   runtime directory. Do not copy a local `.env` file.
3. Create the dedicated Python virtual environment and install
   `requirements.txt`.
4. Copy the already-approved server-only values from the shared local `.env`
   into `~/.hermes/.env`, plus trusted deployed validator directory paths.
5. Run `venv/bin/python bin/migrate.py` once. It records immutable file
   checksums and aborts on a changed applied migration.
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
