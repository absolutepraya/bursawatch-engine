# Telegram news summary style discussion

Status: approved by the user on 2026-10-02 and implemented locally. This document records the agreed scope and its rationale; it does not describe a verified production release.

## Settled requirements from the handoff

- Apply the same news-summary style to Phintraco and Tuntun.
- Begin with the issuer, action, or actual news subject. Omit generic publisher introductions for straightforward news; do not add `saya` or `kami`.
- Preserve meaningful attribution for research estimates and forecasts, including period, units, and forward-looking framing.
- Retain one to five factual Indonesian sentences. Prefer two shorter paragraphs for longer summaries, grouped by subject, for both providers. The threshold is flexible: use editorial judgment, not a fixed sentence or character cutoff. Short summaries can remain one paragraph.
- Render exactly one `*(Ringkasan)* ` prefix. The classifier's summary contains no marker.
- Every issuer-routed card has exactly one existing deterministic price tracker and a source link. Preserve provider-specific headings and unavailable-value placeholders. Macro-routed cards omit issuer market data.
- Preserve classification, routing, selection, deduplication, and delivery idempotency. Existing persisted delivery payloads remain verbatim on retry, consistent with [ADR 0018](../adr/0018-tuntun-telegram-news-format.md).
- Scope is Telegram Market News and its shared Telegram classification prompt. WhatsApp and X are separate work.
- Deliverability and reliability take priority over stylistic consistency. Do not add rejection, quarantine, forced regeneration, or delivery blocking for reporting voice, paragraph count, or a paragraph-length threshold. Existing non-style checks remain outside this formatting change.

The [Telegram news glossary](../glossaries/telegram-news.md) defines the terms used here.

## Checked-in source findings

The initial review used base commit `ad088371c3f6398f4ece38980668e9d657ece4ff`.

- Three prompt surfaces carry the news contract: `cron-tg-market-news/SKILL.md`, the News section of `cron-tg-source-ingest/SKILL.md`, and provider instructions in `cron-tg-market-news/bin/agent_protocol.py`.
- Before this change, `_validate_summary()` preserved internal whitespace and checked the one-to-five-sentence constraint, but `SelectionCandidate.__post_init__()` subsequently collapsed paragraph boundaries. Prompt changes alone could not preserve the requested layout.
- Both providers delegate issuer rendering to `_issuer_entry()`. The existing tracker is already shared; consistent coverage should be verified without appending another block.

## Bounded channel review

On 2026-10-02, a read-only `discord read 1525102508714889257 --limit 50 --json` inspected the latest 50 messages returned by the channel. This is a bounded output sample, not a complete history or independent verification of the underlying news.

- Ten messages were Telegram news cards: nine Tuntun and one Phintraco. All ten displayed one Ringkasan marker and one complete four-horizon tracker; WSKT used unavailable-value placeholders. All ten summaries were single paragraphs.
- Phintraco DOOH, message `1555386571191095397`, begins with `Phintraco melaporkan` and combines acquisition, funding, rights issue, and approval details in a dense paragraph. Its existing tracker must not be duplicated.
- Tuntun GIAA, message `1555431563607679088`, reports directly but puts results, financing, and operating context in one paragraph. Tuntun FUTR, message `1555432247979544670`, likewise combines transaction terms and conditional completion in one paragraph. These are examples where a natural paragraph break improves readability.
- The two requested X references appear as messages `1555402424796057653` and `1555414017760301080`. Both have two summary paragraphs and only one Ringkasan marker. They establish layout examples only; their claims, headings, and source-specific presentation are not transferred into Telegram summaries.

The required read-only production snapshot ran before recording these observations, at `2026-10-02T11:23:26+07:00`. It reported published main and the last successful release at `18797bdf622ef7b9732cb66c4ecf809dd7a92abe`. The worktree's initial code review used the earlier base noted above, so recheck changed source before implementation. The snapshot does not prove runtime checksums or the format of future outputs.

## Design tree and decisions

The scope, voice, attribution, sentence bound, and market-data ownership above are settled prerequisites.

1. Paragraph policy, accepted by the user: flexible prompt guidance for both Phintraco and Tuntun; use natural subject grouping rather than a fixed threshold. Do not force a split or pad a short summary to satisfy the preference.
2. Style enforcement, accepted by the user: no new blocking for style violations. Preserve valid supplied paragraph breaks without adding paragraph-count validation or a publisher-name ban. Otherwise valid one-paragraph or unusually structured prose remains deliverable.
3. Discord length boundary, accepted by the user: if paragraph spacing alone pushes the card over the existing 2,000-character limit, fall back to a single-paragraph summary only when the same facts, heading, tracker, and link fit. Do not truncate facts, remove the tracker, add model calls, or rewrite a previously persisted delivery payload. Otherwise retain the existing length-limit behavior.

The user confirmed the remaining fallback and shared understanding with: `yeah agree. make it flexible bro`.

## Local implementation

The worktree was advanced to `6c64a24dd5f79c20a658070ed3c978db63c55636` before implementation; that main update changed only Stockbit receipt projection. The relevant Telegram source was rechecked.

- The three prompt surfaces now share direct reporting, meaningful research attribution, and a flexible preference for two paragraphs without withholding eligible news for style.
- Selection normalizes whitespace within paragraphs and preserves blank-line boundaries, including after durable candidate reload. Titles, material facts, and dedupe facts keep their existing normalization.
- The shared card renderer retains its heading, single marker, deterministic tracker, and link. Its spacing-only fallback uses the already-loaded snapshot and leaves the selection unchanged.
- Existing rendered delivery payloads remain frozen on retry.
- Synthetic regressions exercise both providers, issuer and macro routes, full/partial/unavailable quotes, style variations, whitespace normalization, 1,999/2,000/2,001-character boundaries, and payload retries. No production job was triggered and no test message was sent.

## Local validation

- Focused summary, protocol, selection, delivery, and market-data tests: 115 passed.
- Market News package: 358 passed. Telegram source-ingest package: 59 passed.
- `bash scripts/test-all`: passed, including the JavaScript sink tests; one optional PostgreSQL integration test was skipped by its existing environment gate.
- Repository policy and `git diff --check`: passed.

These checks validate the local implementation. Publication, release checksums,
and a natural subsequent output are separate verification steps.

## Documentation choice

Use this design record and the glossary during the interview. The repository reserves `CONTEXT.md` for ignored scratch, so it is not used for the glossary. A new ADR is unnecessary for reversible wording and paragraph-format changes; revisit that choice if the interview establishes an architectural trade-off.
