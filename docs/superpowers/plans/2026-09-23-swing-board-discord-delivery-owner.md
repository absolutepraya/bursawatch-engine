# Swing Board Discord Delivery Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every Bursawatch Discord API operation through one durable Python delivery service while preserving each watcher's source behavior and the Swing Board owner's canonical episode decisions.

**Architecture:** Add a dedicated VPS service that durably accepts idempotent operations, owns Discord API access, retries, reconciliation, and receipts. Add a shared Python client library for source watchers, the Board owner, and the release agent. Migrate every current Discord client to submit or query through this boundary, retaining source cursors and domain state with their existing owners.

**Tech Stack:** Python 3, FastAPI and Uvicorn for the loopback service, SQLite for the durable queue and operation ledger, a standard-library HTTP client for callers, existing Discord API v10, pytest, and systemd for the service process.

**Spec:** [Swing Board shared architecture design](../specs/2026-09-23-swing-board-shared-architecture-design.md)

## Global Constraints

- Every Bursawatch Discord API access used by clients, including reads needed to verify or reconcile delivery, passes through the Discord Delivery Owner.
- The Delivery Owner owns Discord operation keys, durable queues, retries, ambiguous-result reconciliation, Discord IDs, and delivery receipts.
- Source watchers keep source cursors and validation; their local pending records are handoff buffers until the Delivery Owner accepts an idempotent operation.
- The Board owner keeps canonical Swing Board state, routing, episode decisions, and desired Board operations. It does not call Discord directly.
- `lib-swing-format` remains a renderer and is not changed to send messages. Existing public message layouts and source semantics remain unchanged in this phase.
- A reused operation key with the same canonical payload returns the existing operation. Reuse with different content is rejected without a Discord request.
- Every logical create, edit, or delete revision gets its own stable operation key. Retrying repeats that exact key and payload; a corrected source message uses the next canonical revision key.
- Existing pending direct-send records are marked for read-back before first service-owned create; known delivered operations are carried forward by their existing Discord IDs and are never replayed.
- An ambiguous create is reconciled by bounded read-back. An inconclusive result stays pending and is never blindly created again.
- Discord message `nonce` with `enforce_nonce` is only a short-window duplicate guard. Durable recovery still uses the service ledger and destination read-back; forum thread creation has no nonce in its create contract.
- Credentials and live state remain outside Git. Local tests use temporary SQLite/media paths and a fake Discord API; no test posts to Discord.
- Live VPS state is never copied into this worktree or hand-edited. The implementation creates migration tooling only; running a production plan/apply remains separately reviewed and approved.
- Production bootstrap, secrets, state migration, schedule changes, release, deployment, merge, push, and commit remain separate approval gates.

## Review Focus

- The service accepted an operation but the client lost the HTTP response; resubmission with the same key must return the existing operation without a second Discord create.
- Discord accepted a create but the service lost the response; bounded read-back must recover a unique match or leave the operation ambiguous and pending.
- An operation key is reused with changed rendered text, destination, or attachment bytes; the service must reject the conflict without replacing or resending the first payload.
- A media upload is accepted by the service and the service restarts before Discord delivery; persisted private bytes and ordered attachments must survive and be delivered once.
- A destination returns a 403, 404, or 429; the service must preserve work, honor Discord retry delay, report a blocked destination safely, and avoid leaking tokens, message bodies, or local paths.

## Scope and rollout boundary

This plan covers subproject 1 only: the shared Discord Delivery Owner and transport, plus migration of every existing Bursawatch Discord caller onto it. It does not implement multi-forum Board management or the Swing renderer changes; those are separate approved subprojects. Existing source formatting and Board episode behavior stay fixed during delivery migration.

The service listens only on `127.0.0.1:9140`. The Control Plane uses 9120 and Source Media uses 9130. Callers use the shared client library and a mode-0600 client-token file. The service reads its own Discord bot token and durable paths from a dedicated environment file, stores SQLite at `~/.hermes/state/bursawatch-discord-delivery.sqlite3`, and stores retryable attachment copies under `~/.hermes/state/bursawatch-discord-delivery-media/`. The live port, environment, secret files, unit installation, and first state directory must be reviewed during a separate production bootstrap.

The service accepts a typed operation rather than a raw URL. Initial operation kinds cover channel message create/edit/delete, forum thread create/read/update/archive, thread message create/read/edit/delete, forum-channel read/edit/create/delete, and bounded channel/thread message listing. Read requests are synchronous and read-only. Mutations enter the durable queue before the API reports acceptance. The operation key is caller-supplied and stable across retries. Media arrives as request bytes, is copied into the service media directory, and is never loaded from a caller-supplied filesystem path.

Existing local outboxes require a safe handoff during a separately approved state cutover. Each package preserves known Discord IDs as completed receipts. Pre-cutover creates with unknown outcomes are submitted with `reconcile_before_first_create=true`, using their persisted exact payload, old nonce where supported, and, for Board forum topics, the existing create snapshot. A unique read-back match is adopted; the service sends only when its bounded query has sufficient coverage to prove no match. If old state cannot establish that coverage, the item remains ambiguous and is reported for review. The cutover runbook requires pausing each writer/watchdog, snapshotting source state, planning the migration, applying owner-specific state upgrades, checking event/operation counts and hashes, then resuming. This plan creates the tooling and no-post coverage; it does not execute the live cutover.

## File map

| Area | Files and responsibility |
| --- | --- |
| New delivery service | `service-bursawatch-discord-delivery/bin/discord_delivery/{api.py,config.py,discord_gateway.py,models.py,store.py,worker.py}`; `bin/serve.py`; durable typed API, SQLite ledger, Discord adapter, and worker. |
| Service operations | `service-bursawatch-discord-delivery/{AGENTS.md,README.md,env.example,requirements.txt,deploy.sh,bin/manage.py,deployment/README.md,deployment/systemd/bursawatch-discord-delivery.service}`; runtime contract, least-privilege environment, loopback service, safe blocked-operation retry, read-only plan/status/verify, and explicitly gated repeat release. |
| Service tests | `service-bursawatch-discord-delivery/tests/{conftest.py,test_api.py,test_store.py,test_worker.py,test_discord_gateway.py,test_manage.py,test_deploy.py}`; isolated queue, fake Discord, conflict, retry, and recovery coverage. |
| Shared caller library | `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/{__init__.py,client.py,handoff.py,models.py}` and its test package; authenticated local API client, typed operations/receipts, polling, safe multipart requests, deterministic operation keys, and resumable handoff primitives. |
| Market News | `cron-tg-market-news/bin/{delivery.py,scan.py,watchdog.py,bursawatch-tg-market-news.sh,watchdog-wrapper.sh}`, `tests/{test_delivery.py,test_scan.py,test_watchdog.py,test_delivery_handoff.py}`, `AGENTS.md`, and `SKILL.md`; retain formatting and source queue, move Discord delivery and post-acceptance retry state to the Delivery Owner. |
| Phintraco and Kelas | `cron-tg-phintraco-swing/bin/{scan.py,watchdog.py,bursawatch-tg-phintraco-swing.sh}` and `cron-tg-kelas-investasi-gtw/bin/{discord.py,scan.py,bursawatch-tg-kelas-investasi-gtw.sh}`, package tests, and their `AGENTS.md`/`CRON.md` or `SKILL.md`; preserve message/media ordering and Board handoff semantics. |
| Swing Board | `cron-dc-swing-board/bin/{discord_forum.py,engine.py,bootstrap.py,board.py,bursawatch-dc-swing-board.sh,bursawatch-dc-swing-board-close.sh,bursawatch-dc-swing-board-retry.sh}`, Board tests, and `AGENTS.md`/`CRON.md`; persist Board intents locally, use the shared service for all Discord reads/writes, and apply returned receipts. |
| X and Instagram | `cron-x-account-watch/bin/{discord.py,scan.py,bursawatch-x-account-watch.sh,bursawatch-x-account-watch-queue.sh}` and `cron-ig-account-watch/bin/{discord.py,scan.py,bursawatch-ig-account-watch.sh}`, package tests, and `AGENTS.md`/`SKILL.md`; preserve post/media sequencing, existing message edits/deletes, and no-post controls. |
| WhatsApp and Stockbit | `cron-wa-channel-watch/bin/{discord.py,scan.py,archive.py,bursawatch-wa-channel-watch.sh,bursawatch-wa-channel-archive.sh,bursawatch-wa-channel-backfill.py,bursawatch-wa-channel-backfill.sh}` and `cron-stockbit-snips/bin/{discord.py,scan.py,bursawatch-stockbit-snips.sh}`, package tests, and `AGENTS.md`/`SKILL.md`; route channel reads, message mutations, media, posts, and heartbeats through the owner. |
| Host-bound release agent | `platform-bursawatch-release/bin/release_agent.py`, `deployment/{bootstrap-release-agent.sh,env.example}`, `deployment/systemd/bursawatch-release-agent.service`, `release-manifest.json`, tests, and `AGENTS.md`; submit the existing heartbeat through the shared client while retaining its manual bootstrap boundary. |
| Repository integration | Root `AGENTS.md`, `docs/README.md`, `platform-bursawatch-release/release-manifest.json`, and `scripts/test-all`; document the new shared dependency, enforce the manual service boundary, order client runtime dependencies, and register new suites. |

## Task 1: Define and persist typed delivery operations

**Files:**
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/__init__.py`
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/models.py`
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/config.py`
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/store.py`
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/api.py`
- Create: `service-bursawatch-discord-delivery/bin/serve.py`
- Create: `service-bursawatch-discord-delivery/tests/conftest.py`
- Create: `service-bursawatch-discord-delivery/tests/test_store.py`
- Create: `service-bursawatch-discord-delivery/tests/test_api.py`
- Create: `service-bursawatch-discord-delivery/bin/manage.py`
- Create: `service-bursawatch-discord-delivery/tests/test_manage.py`
- Create: `service-bursawatch-discord-delivery/requirements.txt`

**Interfaces:**
- `DeliveryStore(database_path: Path, media_root: Path)` persists accepted operations and their attachments.
- `OperationIntent` contains `key`, `kind`, `ordering_key`, typed `target`, typed `payload`, attachment bytes/metadata, and `reconcile_before_first_create: bool = False`.
- `DeliveryStore.accept(intent: OperationIntent) -> OperationRecord` inserts once by operation key, returns the existing row for the same key and payload digest, and raises `OperationKeyConflict` for the same key with a different digest.
- `DeliveryStore.adopt_completed(intent: OperationIntent, receipt: Mapping[str, str]) -> OperationRecord` imports an existing successful receipt without calling Discord; `DeliveryStore.adopt_pending(intent: OperationIntent) -> OperationRecord` inserts pending legacy work with pre-create reconciliation enabled.
- `DeliveryStore.retry_blocked(operation_key: str, expected_digest: str) -> OperationRecord` releases only an exact blocked operation after destination repair; digest mismatch or non-blocked state is rejected.
- `DeliveryStore.get_by_key(key: str) -> OperationRecord | None` returns the canonical current operation status and receipt.
- `POST /v1/operations` authenticates a typed multipart operation, durably stores it, and returns its stable ID and status.
- `POST /v1/operations/adopt` accepts only a typed import action: an existing receipt or an old pending intent. Completed imports never call Discord; pending creates are accepted only with `reconcile_before_first_create=true`. Both are idempotent by key/digest.
- `POST /v1/admin/operations/{operation_key}/retry` releases an unchanged blocked operation only after separate admin authentication and digest confirmation; it cannot edit or retarget the payload.
- `GET /v1/admin/operations` lists bounded, paginated sanitized operation summaries using the separate admin token; it never returns message or media content.
- `GET /v1/operations/by-key/{operation_key}` returns accepted operation status and receipt.
- `POST /v1/queries` performs one allowlisted synchronous read through the Discord gateway.
- `GET /healthz` returns process health and sanitized pending/blocked counts without exposing payloads or credentials.

- [x] **Step 1: Write the failing store contract tests**

Create these cases in `test_store.py` before implementing the store:

```python
def make_operation(key, content="Example"):
    return OperationIntent(
        key=key,
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=(),
        reconcile_before_first_create=False,
    )


def test_accept_persists_and_deduplicates_identical_operation(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    intent = make_operation("news:event-1:text")

    first = store.accept(intent)
    reopened = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    second = reopened.accept(intent)

    assert second.id == first.id
    assert reopened.get_by_key(intent.key).status == "pending"


def test_accept_rejects_changed_payload_for_existing_operation_key(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3", tmp_path / "media")
    original = make_operation(key="swing:event-7:text", content="Original")
    changed = make_operation(key="swing:event-7:text", content="Corrected")
    store.accept(original)

    with pytest.raises(OperationKeyConflict):
        store.accept(changed)
```

- [x] **Step 2: Run the store tests and confirm they fail because the contract is not implemented**

Run from the repository root:

```bash
../../.venv/bin/python -m pytest -q service-bursawatch-discord-delivery/tests/test_store.py
```

Expected: collection or assertion failure naming the missing `DeliveryStore`, `OperationIntent`, or conflict behavior.

- [x] **Step 3: Implement the SQLite operation ledger and private attachment staging**

Create a `discord_operations` table with a unique validated `operation_key`, canonical payload digest, operation kind, destination/order key, payload JSON, state (`pending`, `pending_reconciliation`, `retrying`, `delivering`, `delivered`, `rejected`, `blocked`, or `ambiguous`), attempt count, next-attempt timestamp, sanitized error category, receipt JSON, and create-recovery snapshot JSON. Use a private `0700` state directory, `0600` database and files, SQLite WAL with `synchronous=FULL`, and a single worker lock. Store attachment names, MIME types, SHA-256 digests, and service-owned relative paths; copy bytes atomically before marking the operation accepted. Use transactions for claims and receipt updates. `blocked` and `ambiguous` operations hold later work only in their own ordering chain; unrelated chains continue. Definite non-retryable Discord rejections are recorded as `rejected` with no automatic resend. Reject reused keys whose digest differs.

- [x] **Step 4: Add authenticated FastAPI submission, status, query, and health routes**

Require a constant-time bearer-token comparison using `DISCORD_DELIVERY_API_TOKEN`; validate snowflake IDs, operation enums, bounded content, allowed mentions, query pagination, filenames, MIME metadata, and total attachment bytes before accepting work. The API accepts host/port, client/admin tokens, bot-token path, state path, and media path only from environment configuration. It returns sanitized request errors and never returns raw Discord headers or response bodies.

Add `/v1/operations/adopt` for the separately gated legacy cutover. Validate imported message/thread IDs and the canonical payload digest. Importing an existing success creates only a local `delivered` row with its old receipt. Importing pending work creates a `pending_reconciliation` row and rejects the request unless the explicit reconcile-before-create flag is true.

Add an admin-only `POST /v1/admin/operations/{operation_key}/retry` guarded by a separate `DISCORD_DELIVERY_ADMIN_TOKEN`. It accepts the expected immutable payload digest and only releases a `blocked` operation with its existing destination, revision, and payload. It cannot edit or retarget an operation. A shared admin CLI first displays a sanitized preview and requires `--apply` plus the expected digest; normal watcher clients cannot unblock work.

`bin/manage.py status` calls the admin list endpoint and shows operation keys, destination IDs, digests, state, age, and sanitized error categories without message content or media paths. `bin/manage.py retry <key> --expected-digest <digest>` previews the exact blocked operation and only applies after `--apply`.

- [x] **Step 5: Run the focused store and API tests**

Run:

```bash
../../.venv/bin/python -m pytest -q service-bursawatch-discord-delivery/tests/test_store.py service-bursawatch-discord-delivery/tests/test_api.py service-bursawatch-discord-delivery/tests/test_manage.py
```

Expected: same-key/same-payload is idempotent across store reopen, changed payload is a conflict, client/admin authentication is separate, invalid operation/query shapes are rejected before queue insertion, attachments persist under the private media root, completed imports create no Discord request, pending creates require read-back, blocked operations retry only with the matching digest, and accepted work remains queryable.

## Task 2: Implement the Discord gateway, queue worker, and ambiguity recovery

**Files:**
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/discord_gateway.py`
- Create: `service-bursawatch-discord-delivery/bin/discord_delivery/worker.py`
- Modify: `service-bursawatch-discord-delivery/bin/discord_delivery/api.py`
- Modify: `service-bursawatch-discord-delivery/bin/discord_delivery/store.py`
- Create: `service-bursawatch-discord-delivery/tests/test_discord_gateway.py`
- Create: `service-bursawatch-discord-delivery/tests/test_worker.py`
**Interfaces:**
- `DiscordGateway.execute(intent: OperationIntent, attachments: Sequence[StoredAttachment]) -> dict[str, str]` is the only code that calls `https://discord.com/api/v10`.
- `DiscordGateway.query(query: DiscordQuery) -> object` executes only the allowlisted read operations.
- `DeliveryWorker.run_once(now: datetime) -> WorkerResult` claims due operations in acceptance order within their `ordering_key`, processes one operation at a time, and persists every receipt or retry state before releasing the claim.
- `DeliveryWorker.reconcile(operation: OperationRecord) -> ReconcileResult` performs bounded read-back for a prior ambiguous create and returns `matched`, `not_found`, or `inconclusive`.

- [x] **Step 1: Add failing adapter tests for create, edit, delete, upload, and query calls**

Test each operation kind against a fake `requests.Session`; assert the exact API v10 path, JSON body, file part name, allowed-mentions policy, and parsed IDs. Verify ordinary message creates use a stable `nonce` with `enforce_nonce`, while forum-thread creates use the typed forum contract and do not assume nonce support. Verify callers cannot pass arbitrary REST paths and queries cannot mutate Discord. Run the new adapter tests and confirm they fail before implementing the gateway.

- [x] **Step 2: Add failing worker tests for acceptance, retry, and ambiguous creates**

Cover successful create receipt persistence, 429 delay preservation, transient network retry scheduling, permission rejection entering `blocked`, explicit admin retry with a matching and mismatching digest, process restart between acceptance and send, and accepted-create timeout. For timeout, the fake Discord read-back returns exactly one matching resource, sufficient-coverage no-match, or multiple/inconclusive matches. Only a unique match completes; inconclusive recovery leaves the operation pending and the gateway receives no second create. Run both new test modules and confirm the new contracts fail before implementing the worker.

- [x] **Step 3: Implement typed Discord v10 request construction and safe result categories**

Use a dedicated `requests.Session`, service-owned bot token, bounded connect/read timeouts, rate-limit parsing from the JSON `retry_after` and `Retry-After` header, and sanitized error categories. Treat a repeated delete returning 404 as completed. Honor Discord's stated delay. Do not log tokens, message content, attachment paths, or untrusted response bodies.

- [x] **Step 4: Implement the single-owner queue worker and recovery snapshots**

Persist the exact API operation and attachment digest before a create. Derive a stable Discord nonce from the operation key for ordinary message creates and set `enforce_nonce`; treat it only as a short-window duplicate guard. For an interrupted or timed-out create, read only the typed target and the bounded page/thread range recorded in its snapshot. For a forum create, reconcile from forum thread metadata plus its starter message because the forum-create contract does not accept a nonce. For migrated work, run this preflight before the service's first create. Send only when the read-back scope has adequate coverage to prove no match; if the scope is incomplete or multiple objects match, leave the operation pending as `ambiguous`, alert, and never blindly create again. Apply bounded exponential retry for transient failures, honor Discord's 429 delay, and keep permanent destination failures blocked until an admin explicitly retries the same immutable operation after repair.

- [x] **Step 5: Run service adapter and worker tests**

Run:

```bash
../../.venv/bin/python -m pytest -q service-bursawatch-discord-delivery/tests/test_discord_gateway.py service-bursawatch-discord-delivery/tests/test_worker.py
```

Expected: gateway requests use only typed paths and validated inputs; successful IDs survive restart; 429 uses the server delay; blocked failures are visible without exposing content; admin retry cannot change payloads; and ambiguous operations never issue an unsafe second create.

## Task 3: Build the shared Python caller library

**Files:**
- Create: `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/__init__.py`
- Create: `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/client.py`
- Create: `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/handoff.py`
- Create: `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/models.py`
- Create: `lib-bursawatch-discord-delivery/tests/conftest.py`
- Create: `lib-bursawatch-discord-delivery/tests/test_client.py`
- Create: `lib-bursawatch-discord-delivery/README.md`
- Create: `lib-bursawatch-discord-delivery/AGENTS.md`

**Interfaces:**
- `DeliveryClient(base_url: str, token_file: Path, timeout_seconds: float = 20)` reads only the client token, never the Discord bot token.
- `DeliveryClient.submit(operation: OperationIntent) -> OperationReceipt` submits a typed idempotent operation and returns the durable service ID/state.
- `DeliveryClient.status(operation_key: str) -> OperationReceipt | None` looks up a previously accepted operation.
- `DeliveryClient.adopt_completed(operation: OperationIntent, receipt: Mapping[str, str]) -> OperationReceipt` records an old successful receipt without Discord I/O.
- `DeliveryClient.adopt_pending(operation: OperationIntent) -> OperationReceipt` records old pending work, requiring pre-create reconciliation.
- `DeliveryClient.query(query: DiscordQuery) -> object` performs an authenticated allowlisted read.
- `DeliveryClient.wait(operation_key: str, timeout_seconds: float) -> OperationReceipt` polls at bounded intervals and returns pending state when the caller deadline expires; it never resubmits a Discord request.
- `DeliveryClientError` exposes a stable category and sanitized message, with no secret, body, media path, or response-header values.

- [x] **Step 1: Write failing client tests against a local fake HTTP server**

Test bearer-token loading, operation JSON, multipart attachment bytes, operation-key lookup, wait timeout, successful receipt parsing, 401/409/429/5xx categories, malformed JSON, and sanitization. Ensure `status()` on a lost submission response can safely be followed by resubmission of the exact same key and payload. Run the library tests and confirm the new contract tests fail before implementing the client.

- [x] **Step 2: Implement the standard-library HTTP client, typed result models, and handoff primitives**

Use `urllib.request` and `urllib.error`, read the client token from the configured mode-0600 secret file, encode multipart file bytes without following redirects to another host, and expose only typed submit/status/adopt/query functions. The handoff primitives hash source state, emit counts plus operation-key digests without payloads, create a private pre-migration backup, import completed receipts and pending preflight intents idempotently, and acknowledge each source item only after durable service acceptance. The package-level CLI requires both `--apply` and `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1`. The library contains no Discord API URL, bot token, or direct Discord REST implementation.

- [x] **Step 3: Run the library tests**

Run:

```bash
../../.venv/bin/python -m pytest -q lib-bursawatch-discord-delivery/tests
```

Expected: requests reach only the configured loopback Delivery Owner, request identity and attachment bytes are stable, and failures are sanitized and retryable by operation status/key.

## Task 4: Add crash-safe, owner-specific sender-state handoff

**Files:**
- Modify: `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/handoff.py`
- Create: `lib-bursawatch-discord-delivery/tests/test_handoff.py`
- Add to each owner-specific test file listed in Tasks 5-9: `delivery_handoff.py` plan/apply coverage and `test_delivery_handoff.py`
- Modify: `service-bursawatch-discord-delivery/tests/test_api.py`
- Modify: `service-bursawatch-discord-delivery/tests/test_worker.py`

**Interfaces:**
- Each producer package implements a pure `build_handoff_snapshot()` adapter that reads its current local delivery/outbox state and yields typed operation intents plus known Discord receipts. Planning never edits state.
- `plan_handoff(adapter) -> HandoffPlan` returns a private plan file containing the source-state hash, counts, operation keys, payload digests, known destination/message IDs, and unknown-outcome counts. It omits message text, source payloads, attachment bytes, tokens, and absolute private paths.
- `apply_handoff(plan, adapter, client) -> HandoffResult` rechecks the source-state hash, writes a mode-0600 backup, and imports operations in stable source order. During any separately approved VPS cutover, archives stay on the VPS under `~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/<runtime-identity>/`, remain excluded from Git/dotfiles, and are retained for at least 30 days. The source owner records each item as handed off only after the Delivery Owner durably acknowledges its key and digest. A rerun after a crash resumes safely at the first unacknowledged item.
- Every `delivery_handoff.py` provides read-only `--plan <path>` and state-mutating `--apply <path>` modes. Apply requires both the flag and `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1`; it runs only during a separately approved cutover while that package's writers and watchdogs are paused.

- [x] **Step 1: Write failing generic handoff tests**

Test that planning leaves source bytes unchanged, omits payload content and media paths, and records deterministic counts and digests. Test that apply refuses a changed source hash, creates a private backup, imports each key/digest once, records source acknowledgement only after service acceptance, and resumes after a simulated crash. Completed rows must use `adopt_completed` with their existing IDs and make zero Discord requests. Pending creates enter preflight reconciliation: a unique match is adopted, proven absence can create once, and insufficient or multiple matches remain ambiguous without creating. Run these tests and confirm they fail before implementing the handoff protocol.

- [x] **Step 2: Implement the generic handoff protocol and package adapters**

Keep package-specific schema decoding inside each package's `delivery_handoff.py`; keep backup, hashing, plan validation, and crash-resume mechanics in the shared library. Derive keys from existing immutable event/leg identities or Board outbox identities, never rendered text alone. Preserve exact pending payloads and media bytes, and reject a package adapter that cannot prove its state snapshot or destination. For Swing Board, use stored forum/thread/starter/reply IDs and its persisted `create_snapshot`; never find an old thread by ticker title alone. If old state cannot distinguish a prior successful create from no create, leave it ambiguous for review and do not create a duplicate Discord object.

- [x] **Step 3: Run handoff tests with fake owners and temporary legacy state**

Run:

```bash
../../.venv/bin/python -m pytest -q lib-bursawatch-discord-delivery/tests/test_handoff.py service-bursawatch-discord-delivery/tests/test_api.py service-bursawatch-discord-delivery/tests/test_worker.py
```

Expected: reruns are idempotent, changed source state refuses apply, completed IDs remain unchanged, ambiguous creates stay pending, and the test harness makes no external Discord request.

## Task 5: Migrate Market News and its watchdog

**Files:**
- Modify: `cron-tg-market-news/bin/delivery.py`
- Modify: `cron-tg-market-news/bin/scan.py`
- Modify: `cron-tg-market-news/bin/watchdog.py`
- Create: `cron-tg-market-news/bin/delivery_handoff.py`
- Modify: `cron-tg-market-news/bin/bursawatch-tg-market-news.sh`
- Modify: `cron-tg-market-news/bin/watchdog-wrapper.sh`
- Modify: `cron-tg-market-news/tests/test_delivery.py`
- Modify: `cron-tg-market-news/tests/test_scan.py`
- Modify: `cron-tg-market-news/tests/test_watchdog.py`
- Create: `cron-tg-market-news/tests/test_delivery_handoff.py`
- Modify: `cron-tg-market-news/{AGENTS.md,SKILL.md}`

**Interfaces:**
- `delivery.format_news_item()` and all existing market/news layout functions remain unchanged.
- Text and cached-image legs submit `channel_message_create` operations using the existing stable event key and leg identity.
- The scanner's durable payload remains the exact rendered text and private cached image bytes; local delivery retry metadata records only handoff state and the shared operation key/receipt.
- Watchdog, normal heartbeat, and fatal heartbeat use the same DeliveryClient API.

- [x] **Step 1: Add failing tests for service-accepted delivery and lost acknowledgements**

Preserve existing formatting tests. Add tests that first persist the rendered payload, submit it once, simulate an accepted operation with a lost response, look up/resubmit the same operation key, receive the original message ID, and mark the item delivered without a second Discord create. Add a test proving 429/backoff belongs to the service after acceptance while local retries occur only when service acceptance is unknown. Run these targeted tests and confirm the new cases fail before replacing the sender.

- [x] **Step 2: Replace direct Discord calls while preserving News ordering and preparing state handoff**

Remove `requests` calls and bot-token reads from `delivery.py` and the watchdog path. Keep renderer functions, source image capture, candidate queue, and exact persisted payload. Implement this package's read-only handoff plan and gated apply adapter: preserve known Discord message IDs as completed receipts, derive stable operation keys from existing event/leg identities, and never resubmit a known delivered leg. Keep source rows intact until the Delivery Owner acknowledges each item. The separately approved cutover applies the plan while the scanner and watchdog are paused. Update both wrappers to load only the Delivery Owner client-token path.

- [x] **Step 3: Run Market News delivery and scanner tests**

Run:

```bash
../../.venv/bin/python -m pytest -q cron-tg-market-news/tests
```

Expected: message layout is byte-for-byte unchanged, cached media remains source-identical, pending work resumes through operation keys, successful legs never replay, and no direct Discord request or Discord bot token is used by the cron.

## Task 6: Migrate Phintraco Swing and Kelas Investasi

**Files:**
- Modify: `cron-tg-phintraco-swing/bin/scan.py`
- Modify: `cron-tg-phintraco-swing/bin/watchdog.py`
- Create: `cron-tg-phintraco-swing/bin/delivery_handoff.py`
- Modify: `cron-tg-phintraco-swing/bin/bursawatch-tg-phintraco-swing.sh`
- Modify: `cron-tg-phintraco-swing/tests/test_scan.py`
- Modify: `cron-tg-phintraco-swing/tests/test_wrapper.py`
- Create: `cron-tg-phintraco-swing/tests/test_delivery_handoff.py`
- Modify: `cron-tg-phintraco-swing/tests/test_watchdog.py`
- Modify: `cron-tg-phintraco-swing/{AGENTS.md,CRON.md}`
- Modify: `cron-tg-kelas-investasi-gtw/bin/discord.py`
- Modify: `cron-tg-kelas-investasi-gtw/bin/scan.py`
- Create: `cron-tg-kelas-investasi-gtw/bin/delivery_handoff.py`
- Modify: `cron-tg-kelas-investasi-gtw/bin/bursawatch-tg-kelas-investasi-gtw.sh`
- Modify: `cron-tg-kelas-investasi-gtw/tests/test_discord.py`
- Modify: `cron-tg-kelas-investasi-gtw/tests/test_scan.py`
- Modify: `cron-tg-kelas-investasi-gtw/tests/test_wrapper.py`
- Create: `cron-tg-kelas-investasi-gtw/tests/test_delivery_handoff.py`
- Modify: `cron-tg-kelas-investasi-gtw/{AGENTS.md,SKILL.md}`

**Interfaces:**
- Phintraco ticker-first rendering and the All Swing + chart pairing remain unchanged.
- Kelas source chunks and images remain in source order with the same Board-owner handoff contract.
- Board handoff continues only after All delivery succeeds; Board retries never replay successful All legs.
- Text, chart, link edit, normal heartbeat, fatal heartbeat, and watchdog heartbeat use typed DeliveryClient operations with one stable key per existing event/leg.

- [x] **Step 1: Add failing delivery-handoff tests for accepted operations, ordered media, and Board-link edits**

Verify exact source event keys become operation keys, successful IDs are persisted before advancing to the next leg, an unavailable Delivery Owner preserves only unfinished work, and Kelas/Phintraco Board link edits use the original message ID without reposting All content. Run the new targeted tests and confirm the new cases fail before migrating either sender.

- [x] **Step 2: Replace embedded Discord HTTP and token code and prepare each state handoff**

Adapt Phintraco's `post_discord_text`, `post_discord_file`, `edit_discord_board_link`, fatal/heartbeat, and watchdog paths to `DeliveryClient`. Adapt Kelas's post, image, link-read/edit, retry, and heartbeat paths. Keep the existing `lib-swing-format` renderer, source statuses, parser, Telegram resilience behavior, Board handoff wrapper, and no-post output unchanged. Implement both read-only handoff plans and gated apply adapters; only the separately approved paused-writer cutover imports pending work, and completed text/image legs are never replayed.

- [x] **Step 3: Run Phintraco and Kelas package tests**

Run:

```bash
../../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests cron-tg-kelas-investasi-gtw/tests
```

Expected: existing output and ordering contracts remain unchanged, no direct Discord request remains, and accepted operation receipts preserve all existing message IDs and Board handoff behavior.

## Task 7: Migrate the Swing Board owner

**Files:**
- Modify: `cron-dc-swing-board/bin/discord_forum.py`
- Modify: `cron-dc-swing-board/bin/engine.py`
- Create: `cron-dc-swing-board/bin/delivery_handoff.py`
- Modify: `cron-dc-swing-board/bin/bootstrap.py`
- Modify: `cron-dc-swing-board/bin/board.py`
- Modify: `cron-dc-swing-board/bin/bursawatch-dc-swing-board.sh`
- Modify: `cron-dc-swing-board/tests/test_discord_forum.py`
- Modify: `cron-dc-swing-board/tests/test_create_recovery.py`
- Modify: `cron-dc-swing-board/tests/test_engine.py`
- Modify: `cron-dc-swing-board/tests/test_board_cli.py`
- Modify: `cron-dc-swing-board/tests/test_bootstrap.py`
- Create: `cron-dc-swing-board/tests/test_delivery_handoff.py`
- Modify: `cron-dc-swing-board/{AGENTS.md,CRON.md}`

**Interfaces:**
- `BoardEngine` remains the only writer of its SQLite episode/domain state and Board intent outbox.
- `DiscordForumClient.execute()`, forum/channel reads, tag-catalog reads, heartbeat, and create recovery use `DeliveryClient`; this adapter contains no Discord REST URL or bot token.
- Before any remote mutation, the Board owner persists its current desired operation and stable key. It submits the same key until the Delivery Owner accepts it, then records the receipt/status without issuing a second create.
- The Delivery Owner owns the exact remote create snapshot and bounded read-back. The Board owner retains source/episode decision state and applies the returned thread, starter-message, and reply IDs.

- [x] **Step 1: Add failing restart and receipt-application tests**

Adapt existing create-recovery tests so a Board owner restart after Delivery Owner acceptance recovers the same thread/starter IDs by operation key. Cover service timeout before acknowledgement, service unavailable, definite Discord rejection, unique forum read-back match, sufficient-coverage no-match, and inconclusive read-back. Assert that no code path calls Discord directly and no ambiguous case submits a new create key. Handoff tests preserve the existing forum, thread, starter, and reply IDs and use each persisted create snapshot; ticker title search is not a recovery strategy. Run the new targeted tests and confirm failure before moving Discord calls.

- [x] **Step 2: Move all Board API work behind the DeliveryClient**

Replace `discord_forum.py` with a typed Board adapter over the shared client. Move REST calls and create snapshot/recovery out of `engine.py` into the Delivery Owner. Keep Board's SQLite outbox as canonical desired-operation/handoff state. Apply receipts before advancing episode projections. Route three existing heartbeat paths through the shared service. Preserve `IDX_SWING_PLAN_BOARD_NO_POST=1` by using the fake client in isolated local tests, never by reaching the service.

- [x] **Step 3: Run the Swing Board suite**

Run:

```bash
../../.venv/bin/python -m pytest -q cron-dc-swing-board/tests
```

Expected: every existing recovery invariant still passes, the Board owner never makes a direct Discord API call, operation status survives Board/service restart, and receipt application updates existing stored IDs exactly once.

## Task 8: Migrate X Account Watch and Instagram Account Watch

**Files:**
- Modify: `cron-x-account-watch/bin/discord.py`
- Modify: `cron-x-account-watch/bin/scan.py`
- Create: `cron-x-account-watch/bin/delivery_handoff.py`
- Modify: `cron-x-account-watch/bin/bursawatch-x-account-watch.sh`
- Modify: `cron-x-account-watch/tests/test_discord.py`
- Modify: `cron-x-account-watch/tests/test_scan.py`
- Modify: `cron-x-account-watch/tests/test_supersession.py`
- Create: `cron-x-account-watch/tests/test_delivery_handoff.py`
- Modify: `cron-x-account-watch/{AGENTS.md,SKILL.md}`
- Modify: `cron-ig-account-watch/bin/discord.py`
- Modify: `cron-ig-account-watch/bin/scan.py`
- Create: `cron-ig-account-watch/bin/delivery_handoff.py`
- Modify: `cron-ig-account-watch/bin/bursawatch-ig-account-watch.sh`
- Create: `cron-ig-account-watch/tests/test_discord_delivery.py`
- Create: `cron-ig-account-watch/tests/test_delivery_handoff.py`
- Modify: `cron-ig-account-watch/tests/test_scan.py`
- Modify: `cron-ig-account-watch/{AGENTS.md,SKILL.md}`

**Interfaces:**
- X media URL retrieval remains in the X watcher. Only Discord create/edit/read/delete requests move to DeliveryClient.
- X forum link edits and verified source supersession deletes use explicit existing message IDs and idempotent operation keys.
- Instagram archive, source validation, local media-path validation, text/media order, cleanup state, and no-post control remain watcher-owned; remote posts and heartbeats use DeliveryClient.

- [x] **Step 1: Add failing migration tests for X reconciliation and Instagram staged media**

Verify X source downloads remain separate from Discord requests, message verification/edit/deletion goes through typed queries/operations, and a retried X/Instagram message returns its original remote ID. Verify Instagram local media symlink/path checks still happen before upload bytes are sent to the service. Run these targeted tests and confirm the new cases fail before migrating either client.

- [x] **Step 2: Replace Discord HTTP in both clients**

Keep each watcher’s rendering, queues, source events, Board link protocol, and source media handling. Use stable keys already derived from profile/event/leg. Implement each watcher's read-only handoff plan and gated apply adapter. Update wrappers and runtime contracts to load the client-token file and report service-accepted pending work through each watcher heartbeat. Do not run live apply or let cron/watchdog jobs migrate their own persisted outboxes.

- [x] **Step 3: Run both watcher suites**

Run:

```bash
../../.venv/bin/python -m pytest -q cron-x-account-watch/tests cron-ig-account-watch/tests
```

Expected: link-edit, delete-verification, private media, and ordered delivery tests pass without a Discord HTTP call from either watcher.

## Task 9: Migrate WhatsApp Channel Watch and Stockbit Snips

**Files:**
- Modify: `cron-wa-channel-watch/bin/discord.py`
- Modify: `cron-wa-channel-watch/bin/scan.py`
- Create: `cron-wa-channel-watch/bin/delivery_handoff.py`
- Modify: `cron-wa-channel-watch/bin/bursawatch-wa-channel-watch.sh`
- Modify: `cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh`
- Modify: `cron-wa-channel-watch/bin/bursawatch-wa-channel-backfill.py`
- Modify: `cron-wa-channel-watch/bin/bursawatch-wa-channel-backfill.sh`
- Modify: `cron-wa-channel-watch/tests/test_discord.py`
- Modify: `cron-wa-channel-watch/tests/test_archive.py`
- Modify: `cron-wa-channel-watch/tests/test_backfill.py`
- Modify: `cron-wa-channel-watch/tests/test_scan.py`
- Create: `cron-wa-channel-watch/tests/test_delivery_handoff.py`
- Modify: `cron-wa-channel-watch/{AGENTS.md,SKILL.md}`
- Modify: `cron-stockbit-snips/bin/discord.py`
- Modify: `cron-stockbit-snips/bin/scan.py`
- Create: `cron-stockbit-snips/bin/delivery_handoff.py`
- Modify: `cron-stockbit-snips/bin/bursawatch-stockbit-snips.sh`
- Modify: `cron-stockbit-snips/tests/test_scan.py`
- Create: `cron-stockbit-snips/tests/test_delivery_handoff.py`
- Modify: `cron-stockbit-snips/{AGENTS.md,SKILL.md}`

**Interfaces:**
- WhatsApp archival, media identity, bounded reads, source/Board backfill manifest, and historical records remain watcher-owned. Discord message listing/read/edit, All text/media delivery, and heartbeat use DeliveryClient.
- Stockbit source polling, state, rendering, and event identity remain unchanged; text messages and heartbeats use DeliveryClient.

- [x] **Step 1: Add failing tests for query proxying, media order, and backfill safety**

Verify WhatsApp bounded list/read operations and backfill edits use the Delivery Owner without changing manifest selection or reposting historical messages. Verify media operations preserve filenames and source order. Verify Stockbit duplicate submission recovers the same message ID and no direct token is read. Run the targeted new tests and confirm failure before replacing either sender.

- [x] **Step 2: Replace Discord REST clients and token paths**

Route all WhatsApp and Stockbit Discord operations through the shared library. Retain existing business retries only for handoff until service acceptance. Keep Delivery Owner retry state authoritative after acceptance. Implement read-only plans and gated apply adapters for both existing delivery stores; no watcher, archive, subscription, backfill, or Stockbit cron performs state migration on startup. Update wrapper setup and contracts.

- [x] **Step 3: Run WhatsApp and Stockbit suites**

Run:

```bash
../../.venv/bin/python -m pytest -q cron-wa-channel-watch/tests cron-stockbit-snips/tests
```

Expected: media naming, message reads, backfill guardrails, All feed order, heartbeats, and no-post behavior remain intact with no direct Discord request.

## Task 10: Route the host-bound release-agent heartbeat through the owner

**Files:**
- Modify: `platform-bursawatch-release/bin/release_agent.py`
- Modify: `platform-bursawatch-release/deployment/env.example`
- Modify: `platform-bursawatch-release/deployment/bootstrap-release-agent.sh`
- Modify: `platform-bursawatch-release/deployment/systemd/bursawatch-release-agent.service`
- Modify: `platform-bursawatch-release/tests/test_release_agent.py`
- Modify: `platform-bursawatch-release/AGENTS.md`

**Interfaces:**
- The release agent submits only its existing `#hermes` heartbeat through the shared client and never receives or reads the Discord bot token.
- Release status GitHub credentials, release operations, installation directory, and service privilege boundary are unchanged.
- Any change to the live agent, token file, bootstrap, or systemd unit remains a separate explicitly approved host bootstrap operation.

- [x] **Step 1: Add failing heartbeat contract tests**

Verify success and failure status heartbeat content is byte-for-byte unchanged, submission uses a stable heartbeat operation key, service unavailability remains best-effort without changing release state, and no Discord API URL or token file is read by `release_agent.py`. Run the new tests and confirm failure before changing the release agent.

- [x] **Step 2: Use the shared runtime client path and remove direct Discord credential loading**

Update the checked-in bootstrap/service template to make the already-installed shared client importable and pass only the Delivery Owner client-token file. Preserve `manual-release-agent-bootstrap` and require `--apply` for bootstrap mutation. Do not change sudoers, agent permissions, timer cadence, or GitHub status-token behavior.

- [x] **Step 3: Run release-agent tests**

Run:

```bash
../../.venv/bin/python -m pytest -q platform-bursawatch-release/tests
```

Expected: heartbeats are submitted to the shared owner, GitHub status behavior stays unchanged, and existing manual/bootstrap protections remain enforced.

## Task 11: Register package boundaries and prove no direct Discord API callers remain

**Files:**
- Modify: root `AGENTS.md`
- Modify: `docs/README.md`
- Modify: `platform-bursawatch-release/release-manifest.json`
- Modify: `scripts/test-all`
- Create: `service-bursawatch-discord-delivery/AGENTS.md`
- Create: `service-bursawatch-discord-delivery/README.md`
- Create: `service-bursawatch-discord-delivery/env.example`
- Create: `service-bursawatch-discord-delivery/deploy.sh`
- Create: `service-bursawatch-discord-delivery/deployment/README.md`
- Create: `service-bursawatch-discord-delivery/deployment/systemd/bursawatch-discord-delivery.service`
- Create: `service-bursawatch-discord-delivery/tests/test_deploy.py`
- Create: `lib-bursawatch-discord-delivery/AGENTS.md`
- Create: `lib-bursawatch-discord-delivery/README.md`

**Interfaces:**
- Root shared-dependency docs name the Discord Delivery Owner and client library as the only Bursawatch Discord API path.
- Release manifest maps every new tracked path exactly once; the new service and release-agent bootstrap remain manual rollout boundaries, while client runtime units depend on the shared client library.
- `scripts/test-all` runs both new service and client-library suites before existing watcher suites.

- [x] **Step 1: Add failing repository-policy tests for the new package boundary**

Extend `tests/test_repository_policy.py` to verify every Discord API base URL, bot-token construction, and raw `/channels/` API path in Bursawatch code occurs only in `service-bursawatch-discord-delivery/bin/discord_delivery/discord_gateway.py`. Verify every changed tracked path maps to exactly one release-manifest unit and the service path is manual. Verify each migrated cron runtime declares the shared client library dependency.

- [x] **Step 2: Add package docs, service read-only commands, and release mapping**

Document service API, operation states, safe retry/recovery, client handoff, no-post isolation, secret paths, state/media paths, and bootstrap gates. The service `deploy.sh plan/status/verify` commands are read-only; every service sync, migration, or restart requires `--apply`, a clean published commit, and current approval. Add client library dependency to all migrated runtime units. Map new service code and host-bound bootstrap to manual units so the release agent cannot deploy them automatically. Add new tests to `scripts/test-all`.

- [x] **Step 3: Run repository-policy and manifest tests**

Run:

```bash
../../.venv/bin/python -m pytest -q tests/test_repository_policy.py platform-bursawatch-release/tests/test_release_agent.py
```

Expected: only the dedicated Discord gateway owns Discord REST access, new package paths are mapped exactly once, service and bootstrap changes are manual, and client dependencies are ordered.

- [x] **Step 4: Run focused service/library suites and the full repository suite**

Run:

```bash
../../.venv/bin/python -m pytest -q service-bursawatch-discord-delivery/tests lib-bursawatch-discord-delivery/tests
bash scripts/test-all
```

Expected: both commands pass, all existing package tests pass without external Discord traffic, and repository policy finds no remaining direct Discord API client outside the Delivery Owner.

## Completion checks

- `rg -n 'discord.com/api/v10|Authorization.*Bot|/channels/' cron-* platform-* lib-* service-*` finds Discord API URL construction only in the shared Discord gateway; test fixtures may mention URLs but do not issue live requests.
- Every migrated package retains its current source output format, state/cursor boundary, ordering, media, Board handoff, and heartbeat semantics.
- Operation keys, canonical payload digests, persisted attachment bytes, pending receipts, and destination failures survive service restart in temporary local tests.
- Only the new service owns a Discord bot token. Clients read the Delivery Owner client token and cannot contact Discord directly.
- The test suites, root/package instructions, release-manifest mapping, runtime import paths, and no-post controls agree.
- No commit, push, merge, release, service bootstrap, live configuration, Hermes schedule edit, production test message, production state migration, or Discord replay is performed by this plan.
