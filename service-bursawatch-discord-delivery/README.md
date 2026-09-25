# Bursawatch Discord Delivery Owner

This loopback FastAPI service is the only Bursawatch path to Discord REST. It accepts typed, idempotent operations, stores them in a private SQLite ledger, stages attachment bytes under a private service-owned media directory, and returns durable receipts after delivery. It also performs the allowlisted Discord reads needed for delivery verification and reconciliation.

The service defaults to `127.0.0.1:9140`. The Control Plane owns 9120 and Source Media owns 9130. It is not a public API and must not be exposed through Nginx, a tunnel, or an open firewall port. Watchers, the Swing Board owner, and the host release agent use [`lib-bursawatch-discord-delivery`](../lib-bursawatch-discord-delivery/README.md); they do not hold the Discord bot token or construct Discord REST requests.

## API

All authenticated requests use a bearer token. `DISCORD_DELIVERY_API_TOKEN` authorizes ordinary client operations, queries, and status lookups. The optional `DISCORD_DELIVERY_EMOJI_TOKEN` authorizes only `guild_emoji_create` submissions; with it unset, emoji creation is unavailable. `DISCORD_DELIVERY_ADMIN_TOKEN` remains a distinct credential for pending-state adoption, sanitized admin listing, and retrying an exactly matching blocked operation.

| Route | Access | Purpose |
|---|---|---|
| `GET /healthz` | Loopback only | Service status and counts for pending, blocked, and ambiguous work |
| `POST /v1/operations` | Client token for ordinary kinds; emoji token for `guild_emoji_create` | Validate and durably accept a typed operation and attachment bytes |
| `GET /v1/operations/by-key/{key}` | Client token | Read the durable receipt or current operation state |
| `POST /v1/queries` | Client token | Perform an allowlisted, read-only Discord query, including bounded guild emoji listing |
| `POST /v1/operations/adopt` | Admin token | Adopt an existing completed receipt or a pending operation during a reviewed cutover |
| `GET /v1/admin/operations` | Admin token | List sanitized operation summaries without message bodies or media bytes |
| `POST /v1/admin/operations/{key}/retry` | Admin token | Retry a blocked operation after exact digest verification |

Mutation kinds are `channel_message_create`, `channel_message_edit`, `channel_message_delete`, `forum_thread_create`, `forum_thread_update`, `forum_thread_archive`, `thread_message_create`, `thread_message_edit`, `thread_message_delete`, `forum_channel_create`, `forum_channel_edit`, `forum_channel_delete`, and `guild_emoji_create`. Query kinds are `forum_thread_read`, `thread_message_read`, `forum_channel_read`, `channel_messages`, `thread_messages`, `forum_threads`, and `guild_emojis`. The service validates identifiers, payload fields, attachment names and sizes, and allowed mentions before accepting work.

## Durable operation and recovery contract

Every operation has a caller-supplied stable key, an ordering key, and a canonical payload digest. Reusing a key with the same payload returns the existing row and receipt. Reusing it with different content returns `409` without replacing the operation or making a Discord request. Accepted attachment bytes are copied to the service media directory; the service does not read caller-supplied filesystem paths.

`guild_emoji_create` accepts a name and one bounded static PNG attachment. The
service builds Discord's image data URI only inside the gateway. SQLite stores
the name, PNG digest, and private media path, never the image bytes. Before the
create, the worker checks that the name is absent. If a response is lost and
the name later appears, the operation stays ambiguous because Discord provides
no nonce or image digest to prove which request created it.

Operations move through these states:

- `pending`: accepted and waiting for its ordered delivery turn.
- `pending_reconciliation`: a create must be checked against Discord before its first create attempt or after an interrupted/ambiguous result.
- `retrying`: a transient failure such as a rate limit or network timeout has a scheduled retry time.
- `delivering`: claimed by the single service worker.
- `delivered`: completed with a durable receipt containing the Discord identifiers needed by the caller.
- `rejected`: Discord definitively rejected the operation for a non-retryable request problem.
- `blocked`: the destination, permission, or local state needs operator repair.
- `ambiguous`: read-back could not safely prove whether a create succeeded.

After a create request has an unknown outcome, the worker uses bounded read-back. A unique match records the receipt; a proven absence may permit one create; an inconclusive or conflicting result stays `ambiguous` and is never blindly recreated. Transient errors use service-owned backoff and honor Discord retry delays. Earlier nonterminal operations with the same ordering key block later operations.

Callers retry only the same immutable key and payload until the service acknowledges acceptance. After acceptance, the service owns retry and recovery; a caller should query the same key and apply a matching receipt before advancing its source outbox. A changed or corrected source operation receives a new canonical revision key. Existing caller-owned outboxes are transferred only through their package's read-only plan and separately approved, paused-writer handoff. This service release helper does not adopt or migrate watcher or Board state.

`bin/manage.py status` prints paginated sanitized rows. For a `blocked` row, repair the destination first, inspect the exact key and digest, then use `bin/manage.py retry <key> --expected-digest <digest>` to preview. Applying the retry additionally requires `--apply` and an operator-approved recovery. This command does not edit the operation payload. `ambiguous` operations require investigation and must not be converted into a new create by operator guesswork.

## Configuration and private data

Copy the tracked field names from [`env.example`](env.example) into the dedicated VPS environment file `/home/praya/.hermes/bursawatch-discord-delivery.env` with mode `0600`. Do not commit or print its values. Keep client, admin, emoji, and bot credentials separate:

- The service environment contains the distinct API and admin bearer token values, and the optional distinct `DISCORD_DELIVERY_EMOJI_TOKEN` value when emoji creation is enabled.
- Callers read the matching API token from `/home/praya/.hermes/secrets/bursawatch-discord-delivery-client-token`.
- The profile emoji helper reads the matching emoji token from `/home/praya/.hermes/secrets/bursawatch-discord-delivery-emoji-token` only for creation; guild emoji reads and receipt polling use the client token.
- Reviewed migration tools read the matching admin token from `/home/praya/.hermes/secrets/bursawatch-discord-delivery-admin-token`.
- The service reads its Discord bot token from `/home/praya/.hermes/secrets/bursawatch-discord-delivery-bot-token`.

Every token file must be a regular file with mode `0600`. The service rejects a bot token file that is a symlink or accessible to group/other users. The intended durable paths are `/home/praya/.hermes/state/bursawatch-discord-delivery.sqlite3` and `/home/praya/.hermes/state/bursawatch-discord-delivery-media/`; the SQLite database, WAL files, worker lock, media directory, and staged bytes are private to the service user. Backups and retention follow the repository's approved VPS runtime archive policy.

## Testing and release boundary

Tests use temporary SQLite/media paths, fake Discord sessions, and loopback fake HTTP servers. Do not start `bin/serve.py` as a test or send test messages to Discord. Watcher, Board, and release-agent no-post controls remain package-owned; they must not enable the live worker or submit a Discord operation during verification. `GET /healthz` does not prove Discord delivery.

`deploy.sh plan`, `status`, and `verify` are read-only. `sync`, `restart`, and `release` require `--apply`; the helper also requires a clean commit published to `origin`. Run those mutating commands only after explicit current-chat deployment approval and after comparing the exact payload and target. The helper assumes a separately installed systemd unit, environment file, secrets, virtual environment, and first service state directory. It does not install those host assets, change network exposure, or migrate source-watcher state. This entire service package is a manual release-manifest unit, outside automatic runtime deployment.
