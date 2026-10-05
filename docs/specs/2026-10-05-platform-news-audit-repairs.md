# Platform news audit repairs

Status: Implemented and locally verified, 2026-10-05. Development branch:
`fix/platform-news-audit`, based on published `main` at `f07cdb7`.
The user confirmed both interview decisions on 2026-10-05.

Repair the five issues established by the cross-platform audit: discarded
Phintraco headlines, generated headline casing, overly broad news advice
vetoes, Swing Board receipt projection, and X legacy correction media failures.
The shared category boundaries in [ADR 0032](../adr/0032-shared-category-contract-boundaries.md)
remain authoritative. This document makes no current production-health claim.

## Settled boundaries

- Shared writing rules remain in the shared component. Source owners retain
  interpretation, eligibility, routes, and specialized Swing handling.
- Style correction is nonblocking, with no extra model call, regeneration,
  quarantine, or delivery hold.
- Preserve existing frozen payloads and destinations, receipt validation,
  operation keys, retry identities, source dates, and Board lifecycle rules.
- Code repair does not authorize production deployment, manual job execution,
  source replay, state edits, or historical Discord message edits.
- Ordinary scheduled retries of saved Board feed-projection intents may
  reconcile existing delivered receipts after the projection code is repaired.
  Projection must never submit a Discord operation or reconstruct source intake.

## Repair behavior

### Descriptive Phintraco titles

Persist a valid supplied headline for either Telegram news provider. Carry
the title through selection and new-card freezing. Preserve compatibility
with older Phintraco submissions that have no title; absence must not become
a new delivery gate. A company-name fallback must not replace a supplied title.

The observed [MDKA card](https://discord.com/channels/940285152335110204/1525102508714889257/1556492112286195813)
repeats `MDKA: MDKA` despite a descriptive source headline. Cover issuer and
macro submissions, legacy absence, and unchanged frozen retries.

### Shared headline casing

When preparing a new generated-news card, uppercase only the first cased
character of its headline body. For issuer cards, leave the exact ticker
prefix intact. Preserve all remaining casing, including names such as
InfraNexia and acronyms. An arbitrary colon in a macro headline is not a
ticker prefix. Empty or unusual input must not cause an additional rejection.
Source-plan labels, stock-status headings, raw forwarding, and already frozen
payloads keep their established presentation.

The observed [TLKM card](https://discord.com/channels/940285152335110204/1525102508714889257/1556515540963430473)
should begin `TLKM: Spin off`, preserving the remaining headline text.
Test issuer and macro headlines, leading punctuation/numerals, names/acronyms,
and frozen retries across news owners.

### News advice filtering

Decision Q1: retire Telegram/Stockbit lexical advice vetoes in favor of the
existing source-analysis LLM. Retain advice/education exclusion in the existing
workflow and preserve structural, identity, routing, and source safeguards.
Do not add another model stage.

Source-reported production targets, transaction descriptions, market price
changes, forecasts, and attributed research can be factual news. A word such
as `target`, `buy`, or `sell` alone does not establish an investment instruction.
Resolve conflicting submission and rendering gates together with adapter
prompts and package contracts. Specialized Kelas plan-grounding and certainty
validation remain outside this semantic news repair.

Cover supported policy/company targets, forecasts and research attribution,
transaction descriptions, and price changes. Wrong identities, invalid
routes, malformed schema, and ungrounded optional plan fields must retain
their existing safeguards.

### Swing Board receipt projection

The Delivery Owner client returns an already parsed OperationReceipt.
Validate that result against the saved operation, including its identity,
digest, terminal status, receipt shape, kind, and destination details.
Do not pass the typed result through a JSON-only parser.

Build the Published Feed snapshot from the saved Board intent and valid
receipt. Keep unavailable, nonterminal, mismatching, or malformed receipts
pending. Preserve idempotent API retries and contiguous checkpoint advancement.
Cover successful starter, reply, edit, and lifecycle projections, API outage
recovery, and zero Discord submissions from the projection path.

### X legacy correction inspection

Read the immutable accepted version and its current-version work before
attempting legacy correction media preparation. Do not infer a verified
historical image baseline from current provider data or retrofit an optional
observation marker into an existing accepted version/index.

Already claimed, executing, or delivered work remains frozen. A bounded
per-event deferred/frozen correction outcome must not stop unrelated new
intake or other correction checks. Keep the authoritative revision guard
against a claim race and retain the original frozen capabilities.

Decision Q2: a genuine edit to pending ordinary news may append a text-only
corrected version when optional images fail. Preserve the original version,
event identity, and frozen capabilities. Required
Swing media, image-only posts, and ambiguous events retain their specialized
media boundary.

Cover completed legacy posts with media failure, genuine pending news edits,
unchanged observations, required Swing media, ambiguous frozen capabilities,
revision races, and continued intake across independent events. Do not
automatically edit already delivered Discord posts.

## Confirmed interview

1. Q1: use the existing LLM semantic advice/relevance decision.
2. Q2: allow appended optional-media corrections for pending legacy ordinary X news.

Implementation must update the affected package contracts, run focused
regressions, consumer suites, and `bash scripts/test-all`. PR creation, merge,
deployment, and message edits remain separate user-directed steps.

Local verification completed: focused regressions and `bash scripts/test-all`
passed, including the repository policy suite and WhatsApp JavaScript sink.
Six isolated-Postgres integration tests were skipped because no isolated test
database was configured. Diff whitespace checks and the change secret scan
passed. This verifies development code, not production deployment or natural
source-to-Discord delivery.

X uses an additive `expected_pending_version` source-revision precondition.
The Control Plane checks current version and work status atomically, before
appending, including a concurrent transition to done. Accepted duplicate
revision IDs reconcile before that guard. Durable retries keep the request and
revision ID unchanged; an unsent correction made ineligible by a competing
claim is retired with an explicit deferred outcome, without changing the
accepted source. Older saved X requests keep their bytes and revision identity;
the upgraded adapter supplies the same atomic guard when retrying them.
Existing source clients can omit the precondition. The
compatible Control Plane endpoint must be released alongside the X client;
an older endpoint rejects guarded corrections rather than silently dropping
the guard. No migration, catalog transition, or manual state repair is needed.
