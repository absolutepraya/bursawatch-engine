# Source Media Owner deployment contract

These files specify a possible VPS target. They do not authorize a host write, credential creation, Supabase resource change, service installation, or service start. First bootstrap and later releases require a separately approved deployment change.

## Supabase Storage contract

- Create the bucket `bursawatch-source-media` as **private** in the reviewed Bursawatch Supabase project.
- Do not add public bucket access, browser access, signed-URL delivery, or a browser policy for this bucket. The service uses the authenticated Storage object API with its server-only service credential.
- Apply any required Storage SQL/API policies only through a reviewed provisioning plan. Do not infer that a service-role credential or a successful local test provisions a bucket or policy.
- Keep retention, lifecycle deletion, backup, and restore policy undecided until a separate review. This service has no object-delete endpoint and never runs automatic cleanup.
- Keep institution logos/banners, profile images, and source attachments on a future authenticated server-side path. A browser must never receive this service credential.

## Credential ownership and target layout

The privileged Supabase service-role key is owned only by this service. Store the key in a regular mode-0600 file readable only by the `praya` service user. The service environment contains the path, never the key value. Do not reuse the Control Plane database credential, Discord token, or caller API tokens.

```text
/home/praya/.hermes/
  bursawatch-source-media.env                         mode 0600
  secrets/
    bursawatch-source-media-service-role-key          mode 0600
    bursawatch-source-media-upload-token               mode 0600
    bursawatch-source-media-read-token                 mode 0600
  bursawatch-source-media/
    bin/
    requirements.txt
    venv/
  state/
    bursawatch-source-media.sqlite3                   mode 0600
```

The environment file stores distinct service-side upload and read bearer tokens, plus the privileged key path, but never the key value. The files under `secrets/` hold the corresponding mode-0600 client copies, delivered only to the adapter or domain owner that needs that scope. The service binds to `127.0.0.1:9130`; do not add an Nginx route, tunnel, public bind address, or firewall opening. Local clients must reject non-loopback base URLs.

## First bootstrap boundary

Before bootstrap, compare all source and systemd files with the target and verify the approved project, bucket name, private access settings, and secret handling. Then a separate approval must cover the exact host changes, including:

1. Create the private bucket and apply reviewed access policies.
2. Create and install the dedicated privileged key file and distinct upload/read tokens with mode `0600`.
3. Install the service package and Python environment under the dedicated path.
4. Install the systemd unit, reload systemd, and enable/start the service only after the review.
5. Verify loopback health and synthetic authenticated upload/read using a non-production test object only if that operation is explicitly approved.

No production cron may be pointed at this service until a separate end-to-end plan is approved. No production event replay or source cursor movement is implied by this package.
