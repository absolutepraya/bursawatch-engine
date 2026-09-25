---
status: accepted
---

# Route all Bursawatch Discord access through the Delivery Owner

## Context

Bursawatch clients have gradually moved message delivery and Board management
to the shared Discord Delivery Owner. The profile-emoji helper remained a
separate direct REST client for guild emoji reads and creates, leaving one
Discord bot token reader and one retry path outside the shared owner.

## Decision

- The Discord Delivery Owner is the only Bursawatch component that calls the
  Discord API. This includes message and forum operations, guild emoji
  management, and reads used for lookup or reconciliation.
- Callers use typed operations and queries from
  `lib-bursawatch-discord-delivery`. Callers do not hold the Discord bot token
  or implement Discord REST, retry, or receipt handling.
- Emoji lookup is a typed guild query. Emoji creation is a durable operation
  with a stable guild/name key and one bounded PNG attachment. It requires a
  dedicated `DISCORD_DELIVERY_EMOJI_TOKEN`; the general client token cannot
  create emojis, and the emoji token cannot submit other operation kinds. The
  credential is optional at service startup, but creation fails closed until
  it is configured. The service stages attachment bytes in its private media
  directory and stores only the digest and attachment metadata in SQLite.
- The worker checks the target guild before creation and uses bounded
  read-back after an unknown outcome. Since Discord supplies neither an
  idempotency nonce nor an image digest for emoji creation, a matching name
  alone cannot prove that the attempted create succeeded. An uncertain result
  remains ambiguous until it can be reconciled safely; a caller must not
  blindly issue a second create.
- Existing profile-emoji behavior remains: lookup by name, explicit `--apply`
  for creation, and no delete or refresh operation.

## Consequences

The profile-emoji helper uses the shared Delivery Owner client and no longer
reads `DISCORD_BOT_TOKEN` or contains Discord REST code. Lookup uses the normal
client token; creation reads the dedicated emoji token file. Its release
metadata depends on both the shared client library and the manually released
Delivery Owner service. Local tests use fake Discord responses and do not prove
a live deployment. Provisioning the new token remains a separately approved
service-configuration change.

The transport decision in [ADR 0016](0016-profile-emoji-helper.md) is
superseded by this record. Its profile identity validation, image processing,
and output contract remain in force.
