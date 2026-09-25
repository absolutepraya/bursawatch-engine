# Shared delivery client package

- Read the repository root `AGENTS.md` and this file before changing the package.
- Keep this package as a standard-library caller of the loopback Delivery Owner. Do not add direct Discord REST calls or Discord endpoint URLs.
- Use `token_file` for ordinary submit, status, query, and wait. Guild emoji creation loads the separately configured `emoji_token_file` only for its submit; guild emoji reads and receipt polling keep the client token. Adoption must use the separately configured `admin_token_file`; never reuse the admin token for submit, status, query, or wait.
- Keep credentials and operation payloads out of exceptions, logs, documentation examples, and test output. Token files must be regular files with mode `0600`.
- Preserve the operation, query, receipt, digest, and status contract in `service-bursawatch-discord-delivery/bin/discord_delivery/models.py` and `api.py`. A pending `legacy_nonce` is part of its digest and is only for admin pending adoption, never a new submit.
- Use loopback fake HTTP servers in tests. Tests must not call Discord or use any bot credential.
- Keep handoff plan summaries free of operation payloads, attachment bytes, secrets, and absolute private paths. Source acknowledgement follows a matching durable receipt.
