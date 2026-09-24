# Bursawatch Discord Delivery Owner instructions

- Read the repository root `AGENTS.md` and this file before changing this package.
- This service is the only Bursawatch code that calls Discord REST. Keep API URL construction, bot-token use, and raw REST routes inside `bin/discord_delivery/discord_gateway.py`.
- Bind only to `127.0.0.1:9120` by default. Do not add a public listener, reverse proxy, firewall rule, or port exposure.
- Keep the client and admin bearer tokens distinct. The service alone reads the Discord bot token from its mode-0600 token file; callers use the shared client library and their separate client-token file.
- Keep the SQLite ledger and staged attachments under private service-owned paths. Never copy production state, media, logs, or secrets into this checkout or use live state as test input.
- Operation keys and payload digests are immutable. A same-key/same-payload retry returns the existing operation; a changed payload conflicts. Never blindly retry an ambiguous create.
- Local tests must use temporary state/media paths and an injected fake Discord transport. Tests and no-post checks must not launch the live worker or contact Discord.
- `deploy.sh plan`, `status`, and `verify` are read-only. Every sync or restart requires `--apply`, a clean commit published to `origin`, and separate current-chat deployment approval. The first host bootstrap, systemd/environment installation, secrets, and source-state handoff remain separate manual gates.
- Do not put credentials or real environment values in Git. Keep operator recovery output limited to operation keys, digests, safe state, and sanitized error categories.
