# Kelas GTW submission error classification and recovery plan

## Goal

Stop agent submission rejections from being reported as Telegram outages, expose a safe rejection reason, and let the existing BNBR outbox item recover on the next ordinary scheduled run. Preserve the current source, lease, retry, and one-header-image delivery contracts.

## Decisions already agreed

- Scope is `kelas-investasi-gtw-watch` only. The IDX market-news warning is a separate fix.
- Provider/source, agent submission, and Discord delivery failures remain distinct.
- Submission rejections remain retryable and do not introduce quarantine, starvation prevention, state reset, replay, backfill, or manual cron execution.
- Safe stable reason codes may appear in logs and warning heartbeats. Raw agent output, credentials, URLs, and paths must not be exposed.
- Recovery is successful only when the event is accepted, the text and exactly one header image are delivered, the outbox item is removed, and the next event can proceed.
- Update the GTW working glossary. Do not add an ADR unless the retry policy changes.

## Current failure boundary

`scan.py::_fatal_reason` classifies by searching exception text for `source` or `telegram`. `RetryableSubmissionError` messages can contain those words, so `--submit-analysis` currently emits `Telegram source is unavailable` even when the source probe authenticated and the validator rejected the agent response. The rejection leaves the event claimed, which repeatedly blocks the oldest outbox item.

The actual BNBR rejection reason is not yet known. The first implementation must make that reason observable without weakening validation. Any later content or prompt correction must be based on the observed stable code and a deterministic regression fixture.

## Non-goals

- Do not modify `idx-market-news-watch`.
- Do not change Telegram resilience, Hermes schedules, delivery destinations, or lease duration.
- Do not edit, reset, replay, backfill, or manually trigger production state.
- Do not loosen source grounding, safety, normalized-plan, or exact JSON validation without a failing regression test that proves the intended contract.

## Implementation tasks

### 1. Add typed, safe failure categories

Files:

- `kelas-investasi-gtw-watch/bin/agent_protocol.py`
- `kelas-investasi-gtw-watch/bin/telegram_source.py`
- `kelas-investasi-gtw-watch/bin/scan.py`
- `kelas-investasi-gtw-watch/bin/discord.py` only if a delivery category needs a small typed wrapper

Steps:

- Give `RetryableSubmissionError` a stable rejection code and a sanitized public representation. Map schema, event-key, title, summary, forbidden-formatting, instruction-leakage, advice/certainty, ungrounded-claim, and noncanonical-plan failures to explicit codes.
- Preserve the existing exception class and retry semantics so a rejected event remains `claimed` and no Discord delivery occurs.
- Distinguish Telegram source access failures from Telegram media failures using exception type or an explicit category, while preserving the existing sanitized public messages.
- Replace substring-based `_fatal_reason` dispatch with type/category dispatch. A submission rejection must never become a provider fatal. Unknown failures remain the generic watcher-operation failure.
- Keep Discord rate-limit and durable delivery retry behavior unchanged. Persist only safe delivery error categories and ensure delivery failures cannot be classified as source or submission failures.

### 2. Emit safe submission diagnostics

Files:

- `kelas-investasi-gtw-watch/bin/scan.py`
- `kelas-investasi-gtw-watch/tests/test_scan.py`

Steps:

- Add a dedicated warning heartbeat for a rejected submission, containing the event key and stable rejection code, with the existing warning marker. Use a distinct stable nonce from the ordinary hourly heartbeat so the warning does not collide with the normal status message.
- Keep the CLI exit status nonzero for a rejected submission so Hermes records the failed agent submission, but make the visible reason `submission rejected: <code>` rather than `failed: Telegram source is unavailable`.
- Ensure no raw payload, exception chain, source URL, token, or filesystem path reaches stderr, the log, the heartbeat, or persisted state.
- Mark delivery retries with the existing warning convention when an accepted event remains incomplete after a Discord failure. Do not change retry timing or delivery cursors.

### 3. Add regression coverage before implementation

Files:

- `kelas-investasi-gtw-watch/tests/test_agent_protocol.py`
- `kelas-investasi-gtw-watch/tests/test_scan.py`
- `kelas-investasi-gtw-watch/tests/test_telegram_source.py`
- `kelas-investasi-gtw-watch/tests/test_discord.py` if delivery classification changes

Required behaviors:

- Every validator rejection has the expected stable code and contains no sensitive detail.
- A rejection containing words such as `source` or `telegram` is still classified as submission rejection.
- Real `TelegramSourceError` and media failures retain their provider fatal categories.
- A rejected `10031:BNBR`-shaped event remains claimed, has no title or summary, produces no delivery, and emits only the safe warning.
- A valid retry for the same event transitions to delivery and posts text followed by exactly one header image, then removes the event.
- A Discord failure retains the event and unfinished delivery cursor, reports a delivery warning, and does not report a provider or submission failure.
- Existing exact heartbeat, fatal sanitization, lease expiry, stale-plan reparsing, and no-post tests remain valid.

### 4. Keep the runtime contract documented

Files:

- `kelas-investasi-gtw-watch/SKILL.md` if the submission failure behavior needs to be stated at the agent boundary
- `kelas-investasi-gtw-watch/SPEC.md` for the provider, submission, delivery, and warning-heartbeat contract
- `kelas-investasi-gtw-watch/CONTEXT.md` as ignored working knowledge, not a committed source file

Document that a submission rejection is an agent-output warning, not a Telegram outage; the event remains eligible for retry; and only the scanner owns delivery. Preserve the agreed glossary terms for Provider Failure, Submission Rejection, Delivery Retry, and Natural Recovery Observation.

### 5. Run focused and complete verification

From the repository root:

```bash
./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_agent_protocol.py kelas-investasi-gtw-watch/tests/test_scan.py kelas-investasi-gtw-watch/tests/test_telegram_source.py kelas-investasi-gtw-watch/tests/test_discord.py
./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests telegram-resilience/tests/test_documentation.py
./.venv/bin/python -m pytest -q
```

Then run the documented isolated no-post control only after the reviewed source is published and VPS deployment is explicitly approved. Confirm that it exercises the wrapper and real rendering path without posting to Discord or advancing delivery state. Accept the documented shared Telegram-resilience control-plane mutation as part of that smoke test.

### 6. Publish, deploy, and observe natural recovery

- Review the exact worktree diff, commit only the GTW source and approved documentation, and push `absolutepraya/kelas-gtw-fix` with `-u origin` on its first push.
- Compare the local files with their VPS counterparts before the first VPS write. Obtain current-session approval for the exact diff, then deploy through `./deploy.sh kelas-investasi-gtw-watch` and synchronize the approved runtime documents separately.
- Compare SHA-256 checksums for every deployed executable, wrapper, and synchronized document. Do not touch live state, logs, media, credentials, or the dotfiles mirror.
- Run the supported no-post control with isolated watcher state and media.
- Wait for the next ordinary Hermes execution. Inspect the saved cron output, sanitized watcher log, shared resilience result, live outbox state, `#hermes`, and `#id-stocks-news`.
- Confirm that the BNBR event no longer reports a false Telegram outage. If its stable rejection code shows a genuine deterministic contract mismatch, reproduce that exact case locally and make only the smallest tested correction. If the submission is correctly rejected, preserve the validator and report the code rather than weakening it.
- Confirm BNBR delivery completes as one text plus one header image, the outbox item is removed, and HRUM becomes eligible to proceed on a subsequent ordinary run.

## Completion criteria

- No submission validation error can produce the public reason `Telegram source is unavailable`.
- Provider, submission, and Discord delivery failures have separate safe diagnostics.
- The full GTW and repository test suites pass.
- The deployed runtime matches the reviewed source by checksum.
- No-post verification is complete without an external message.
- Natural scheduled execution provides live recovery evidence for the existing BNBR state, without state reset or replay.
