# Bursawatch Source Media Owner

This loopback FastAPI service stores source attachments in a private Supabase Storage bucket and serves them to authorized Bursawatch clients by stable opaque reference. The service owns the privileged Storage credential, upload idempotency ledger, media validation, and private object access. Callers receive no Storage credentials, public URLs, or signed URLs.

The service binds to `127.0.0.1:9130`. Platform adapters use the upload token for `POST /v1/objects`; domain owners use the separate read token for `GET /v1/objects/{ref}`. Both calls go through [`lib-bursawatch-source-media`](../lib-bursawatch-source-media/README.md). The public API returns metadata in the agreed source event form:

```json
{
  "ref": "a30e9f61-6e21-5eea-9d9f-833087870d5c",
  "sha256": "hex-digest",
  "kind": "image",
  "content_type": "image/jpeg",
  "size_bytes": 1234,
  "filename": "chart.jpg",
  "durable": true
}
```

References are identifiers, not capabilities. Each request still requires the service's scoped bearer token. The UUID ref and private object path are derived deterministically from the caller's idempotency key; the raw key, bytes, and privileged Storage credential are not exposed in a URL or ref.

## API and invariants

| Route | Access | Purpose |
|---|---|---|
| `GET /healthz` | Loopback | Minimal service health, without credentials or object data |
| `POST /v1/objects` | Upload token | Store one validated object using an idempotency key |
| `GET /v1/objects/{ref}` | Read token | Retrieve bytes and validated metadata by opaque ref |

Uploads use `application/octet-stream`; metadata is carried in `X-Idempotency-Key`, `X-Media-Kind`, `X-Media-Content-Type`, and `X-Media-Filename`. Each object must be nonempty and at most 8 MiB. The service checks the byte signature against an allowlisted MIME type and kind, calculates SHA-256 itself, and stores only the validated content type. Filenames are normalized to a bounded ASCII label accepted by the Control Plane. The source event caller separately enforces no more than 16 refs and 25 MiB total per event.

The idempotency key is immutable. Repeating a key with the same byte digest and metadata returns the original reference. Changing bytes or metadata under the same key returns `409`. A deterministic private object path, private metadata marker, and no-overwrite behavior safely handle a crash after Storage accepts an object but before the local ledger commits. Existing objects and markers are read back and digest-checked before they are treated as the same upload.

There is no delete endpoint and no implicit retention cleanup. Object lifecycle, retention, and backup/restore policy need separate approval before implementation.

## Local development and tests

Run tests from this package with the repository's Python environment:

```bash
python -m pytest -q tests
```

Tests inject an in-memory storage provider. They do not read service credentials, contact Supabase, provision resources, or write production storage.

## Deployment boundary

See [`deployment/README.md`](deployment/README.md) for the private bucket, service credential, host bootstrap, and manual release contract. This source package is documentation for a future reviewed service bootstrap; it does not provision Storage or install anything on a host.
