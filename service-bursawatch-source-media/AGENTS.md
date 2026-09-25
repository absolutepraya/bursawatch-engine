# Bursawatch Source Media Owner instructions

- Read the repository root `AGENTS.md` and this file before changing this package.
- This service alone holds the privileged Supabase Storage credential and resolves stable opaque media references to bytes.
- Keep the Supabase bucket private. Never return public or signed URLs, log credentials, or give the Storage credential to a caller.
- Bind only to `127.0.0.1`. The service exposes distinct upload and read bearer tokens; they must differ.
- Accept only bounded, validated media bytes. Keep the 8 MiB per-object limit here. Aggregate event limits of 16 refs and 25 MiB belong to the source event/caller contract.
- Inject the storage provider. All tests must use an in-memory fake and must never contact Supabase.
- Persist idempotency and media metadata in a private service-owned SQLite database. An idempotency retry with changed bytes or metadata conflicts and must never overwrite the original object.
- Do not add retention or automatic deletion. Do not change production storage, create a bucket, set policies, or install credentials from this package without a separate reviewed deployment approval.
- Keep service secrets in a dedicated mode-0600 VPS environment/token file. Never commit secret values.
