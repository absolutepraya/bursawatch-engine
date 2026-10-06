# Bursawatch Discord Delivery client

This package gives Bursawatch callers a typed, authenticated client for the local Discord Delivery Owner. It uses Python's standard library and sends requests only to a loopback HTTP base URL, normally `http://127.0.0.1:9140`.

## Client setup

Create a private client-token file with mode `0600`, then construct the client:

```python
from pathlib import Path
from bursawatch_discord_delivery import DeliveryClient

client = DeliveryClient(
    "http://127.0.0.1:9140",
    Path("/home/praya/.hermes/secrets/bursawatch-discord-delivery-client-token"),
)
```

The client validates that the token file is a private regular file. The ordinary token is used for ordinary submit, status, query, and wait. Guild emoji creation uses a separate private token file, loaded only for that submit:

```python
emoji_client = DeliveryClient(
    "http://127.0.0.1:9140",
    Path("/home/praya/.hermes/secrets/bursawatch-discord-delivery-client-token"),
    emoji_token_file=Path("/home/praya/.hermes/secrets/bursawatch-discord-delivery-emoji-token"),
)
```

Guild emoji listing and receipt polling still use the ordinary token. State adoption is an administrative migration operation and requires a separately configured private admin-token file:

```python
client = DeliveryClient(
    "http://127.0.0.1:9140",
    Path("/home/praya/.hermes/secrets/bursawatch-discord-delivery-client-token"),
    admin_token_file=Path("/home/praya/.hermes/secrets/bursawatch-discord-delivery-admin-token"),
)
```

An admin token is used only by `adopt_completed` and `adopt_pending`. It does not replace the ordinary token for other methods. Each token file must be a regular file with mode `0600`.

## Typed operations

`OperationIntent` mirrors the service's operation kinds, destinations, payload fields, attachment metadata, immutable digest, and query/status vocabulary. An operation key and payload must stay the same across a retry. The service deduplicates that request and returns the existing durable receipt.

```python
from bursawatch_discord_delivery import OperationIntent

operation = OperationIntent(
    key="market-news:event-123:text",
    kind="channel_message_create",
    ordering_key="channel:123456789012345678",
    target={"channel_id": "123456789012345678"},
    payload={"content": "Market update", "allowed_mentions": {"parse": []}},
)
accepted = client.submit(operation)
current = client.status(operation.key)
```

Attachments are immutable in-memory byte values, not caller paths. `submit` sends the operation as multipart form data so binary bytes survive unchanged. Media adoption also sends the ordered attachment bytes with its administrative envelope, preserving the original payload digest. `query` accepts only the service's seven allowlisted read kinds. `wait` first performs one status lookup using the normal client request timeout. Its `timeout_seconds` value bounds only the polling phase after that lookup; each polling request is capped to the remaining budget, and the latest receipt is returned when that budget expires. It never sends another create.

`attempt_deadline` optionally accepts a timezone-aware Python `datetime` on
`OperationIntent`. The client emits a canonical UTC ISO-8601 timestamp and binds
it into the digest. Equivalent timezone offsets yield the same digest. Keep the
original deadline along with the key, payload, and attachment bytes for retries;
changing or extending it conflicts with an already accepted operation. Omitting
it preserves existing digests and behavior.

The deadline prevents new service mutation attempts at or after that instant;
it does not bound `wait`, cancel an attempt already started, or establish that
an uncertain earlier attempt failed. Such creates can still receive confirmed
receipts through read-only reconciliation. Unresolved results remain pending,
blocked, or ambiguous. Safe expiry uses existing terminal `rejected` status,
so receipt parsing and `DELIVERY_RECEIPT_WAIT_SECONDS` remain unchanged. Advance
dependent publication steps only from matching confirmed receipts.

`legacy_nonce` is accepted only for a pending historical import with `reconcile_before_first_create=True`. It participates in the immutable operation digest, is sent only in `adopt_pending`, and is never included in a new submitted operation.

## Handoff primitives

`handoff.py` provides source hashing, payload-free plan summaries, mode-0600 backup creation, apply-gate validation, and an import helper that acknowledges a source item only after matching durable service acceptance. Each package owns its source schema adapter. An apply command must require both `--apply` and `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1`, and must run only during a separately approved cutover with the source writer paused.

Planning and testing use local files and loopback fake HTTP. This library contains no direct Discord REST implementation or Discord destination URL.

`list_guild_emojis(guild_id)` returns bounded emoji metadata through the
Delivery Owner. `create_guild_emoji(guild_id, name, png_bytes)` submits a
durable keyed create with a PNG attachment; callers can use `wait` for its
receipt. Neither method receives a Discord bot token.
