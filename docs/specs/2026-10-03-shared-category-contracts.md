# Shared category contracts: Macro, Industry, Swing

Status: Consolidated design from the agreed discussion, 2026-10-03.
The [implementation plan](../superpowers/plans/2026-10-03-shared-category-contracts.md)
is written for review and execution-method selection. Implementation and
release remain separate steps. This follow-up is outside PR #48.

The [working discussion](../notes/2026-10-03-shared-category-contracts-working-notes.md)
contains the interview and source evidence. The
[boundary ADR](../adr/0032-shared-category-contract-boundaries.md) records the
ownership decision, and the [glossary](../glossaries/category-news.md) defines
the category vocabulary. Checked-in source observations use base commit
`6623dd4aaadc7904d0c6274e228a66ca9edcf901`; this document makes no current
production claims.

## Ownership and adoption order

Extend shared guidance in the order Macro, Industry, then Swing. Common
writing rules belong in the shared component. Category-specific guidance
composes with those rules; adapters retain source interpretation, identities,
relevance requirements, typed submissions, and destination selection. Remove
duplicated generic writing rules from adapters and runtime prompts during
their coordinated adoption.

Owners supply the presentation category from their existing context. Do not
derive it solely from a route name: Tuntun Industry uses `macro_news` while
source kind selects its Industry destination. This extension does not rename
routes or change destinations or cadence.

## Common writing contract

Report directly in factual Bahasa Indonesia. Preserve meaningful attribution
for research, estimates, forecasts, guidance, and interpretation. Use flexible
paragraphs: prefer two short paragraphs for longer summaries, while a short
or cohesive item may remain one paragraph. Do not pad or invent facts to meet
a layout rule. Style deviations do not make eligible news undeliverable.

Keep the existing marker, heading, source-link, item splitting, deduplication,
and quote-enrichment ownership. The LLM does not generate latest prices or
the deterministic 1D/1W/1M/3M stock tracker. Swing composes common narrative
rules with its specialized structured renderer.

## Macro

For each retained figure, preserve supplied period, unit, comparison basis,
attribution, and provisional or revised qualification. Distinguish actual,
forecast, consensus, prior-period values, and revisions. YoY and MoM are
different bases; percent and percentage points are different units.

Missing source context stays missing. Use source-supported wording, noting
material ambiguity without guessing a period, unit, or comparison. Actual
and forecast values are not conflicting merely because they differ. Preserve
an explicit revision explanation. If two source values genuinely conflict,
briefly acknowledge a central discrepancy; omit a peripheral disputed claim
while retaining supported news.

Dense releases may be summarized around material indicators rather than
reproducing every number. Keep the supplied context for each retained figure.
No mandatory table, paragraph count, or structured figure output is added.

## Industry

Use evidence supplied to the owner: the publication, eligible-post image
context, and any explicitly provided source context. This extension adds no
external research or related-company discovery.

Separate reported developments from company implications through clear
attribution and qualified wording. A qualitative implication is allowed when
supplied evidence establishes specific company exposure and a direct
connecting mechanism, even without a quantified effect. Preserve source
forecasts and their assumptions. Do not invent impact size, turn a policy
target into a contract award, or predict a share-price move.

When evidence does not support a company implication, omit that implication
and deliver the eligible industry news. Company impact is optional context,
without a mandatory output field or dedicated block. Owner instructions
must explicitly accommodate the agreed qualified-implication scope while
retaining source grounding.

## Additional image context

The news LLM first assesses source text for eligibility. Ineligible text and
image-only news receive no new image analysis. After text establishes
eligibility, images may clarify its summary. They do not supply an unrelated
primary story or rescue ineligible text.

Load images on demand through the analysis runtime's image viewer in the same
agent workflow. Do not attach images during initial screening, run OCR over
every incoming image, or require a second extraction model. A shared
preparation component obtains verified image bytes through the existing
Source Media Owner/client, stages private local assets, and retains source
version, association, and order. A textual path alone does not establish
that an image was inspected. Source content remains untrusted evidence.

Use bounded preparation and inspection resources. Image failure falls back
to the text-supported summary without waiting or retrying merely for optional
context. Missing labels or figures remain missing. Do not claim complete
image coverage if assets were unavailable or not inspected.

Exact resource defaults and input protocol details belong in the subsequent
implementation plan. Existing closed agent inputs, source-version binding,
runtime image-viewer permissions, and available media paths require
coordinated compatibility work. This is not a prompt-only guarantee.
Specialized Swing image/PDF intake, required source-media delivery, and
raw-forwarding contracts retain their existing requirements.

## Swing source-plan presentation

Use canonical labels Entry, Stop-loss, and Target n. Always show Entry,
Stop-loss, and Target 1; use `-` when a base value remains missing after
recognizing approved synonyms. An explicitly unnumbered primary target maps
to Target 1. Show additional supplied targets or stop information; omit
absent additional slots. Preserve target numbering, range endpoints,
comparators, dates, status, and extra source conditions. Do not fill a missing
TP1 with TP2 or replace an entry range with a calculated midpoint.

The source-analysis LLM recognizes these synonyms through shared Swing
guidance:

| Source term | Canonical output |
|---|---|
| Watch on, Buy area | Entry |
| Stoploss, Stop-loss | Stop-loss |
| Support utama with unqualified level `x` | Stop-loss `<x` |
| TP1, Target 1 | Target 1 |
| TP2, Target 2, and subsequent numbered targets | Corresponding Target n |

Preserve a source's explicit comparator. The Support utama rule is the user's
approved normalization, not permission to choose arbitrary chart support as
a stop. Retain raw source wording and any additional invalidation conditions
as evidence/context. Structured fields carry the exact normalized reference;
prose covers source rationale and conditions, repeating levels only when
needed to explain a condition. Status-only/reminder events retain their
event-specific presentation.

For [PWON](https://t.me/kelasinvestasiid/10759), the agreed normalization is:

```text
Entry: 270–282
Stop-loss: <260
Target 1: 288
Target 2: 298
```

Its additional failed-reclaim condition remains source context. Display
placeholders do not establish complete plan data or add an eligibility gate.
Implementing normalization requires compatible owner input/results and
source-grounding validation, rather than unchecked generation of levels.

## Deterministic Board boundary

The user confirmed the existing tier and market-check boundary:

| Source role | Board tier | Scheduled market-price evaluation |
|---|---|---|
| Qualifying complete Phintraco setup | Primary plan | Active Primary plans only |
| Kelas GTW | Supporting setup | No |
| X/social charts | Chart context | No |

Supporting setup ranks above Chart context. Standardizing presentation does
not promote Kelas to Primary. Existing Board rules govern a qualifying
Phintraco setup's promotion of an applicable source-only episode, retaining
previous context.

Checked-in `after_close` code evaluates the current session close at its
16:30 WIB initial phase. The 17:00 WIB retry applies only to an exact active
Primary plan whose initial close was unavailable for that session. Board
code owns calculated market state, tags, stop/final-target resolution, other
lifecycle transitions, and their durable operations. The LLM does not make
these decisions. Preserve the existing trading-calendar, level-validation,
required-media, receipt, and retry contracts.

## Compatibility and validation expectations

Start news category guidance over existing summary outputs. Keep accepted
schemas closed; do not add optional evidence fields without a reviewed
compatibility design. Image inputs and Swing normalization may require
bounded typed input/result changes, which must be enumerated in the plan and
remain compatible with stored records.

Preserve frozen messages and destinations verbatim on delivery retries.
Do not re-analyze source text/images or reprice a prepared card during a
delivery retry. Preserve source/item identities, ordering and deduplication
rules, routes, receipts, operation keys, payload digests, and retry identities.
No historical replay, backfill, or in-place rewrite of prepared payloads is
part of this extension.

Implementation verification should exercise meaningful cases: Macro actual
versus forecast and revisions; Industry supported versus unsupported effects;
eligible text with failed optional images; no image inspection for ineligible
or image-only news; Swing synonyms, missing base/extra fields, source ranges
and operators; unchanged Board tiers; and verbatim frozen-message retries.
Tests must also cover retained owner compatibility rather than only compare
prompt wording. The implementation plan must identify package-specific
checks, followed by applicable repository checks. Production verification
and deployment remain separately authorized operations.
