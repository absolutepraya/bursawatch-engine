# ADR 0032: Shared category guidance with stable delivery contracts

Status: Accepted design boundaries, 2026-10-03. The implementation plan is written for review; implementation and release remain separate.

Extend shared writing guidance in the order Macro, Industry, then Swing,
outside the universal stock-news format PR. Start with guidance over existing
payloads: the shared component owns common writing rules and category-specific
presentation obligations, while domain owners retain source interpretation,
relevance decisions, routing, and delivery preparation. Owners supply the
presentation category from their existing context; a route name alone is
insufficient because Tuntun Industry uses the `macro_news` route. Remove
duplicated common writing rules from adapters as each category adopts the
shared guidance, keeping source-specific requirements with their owners.

New mandatory or optional figure/evidence output fields would require a
coordinated compatibility change to closed submission and prepared-card
schemas. Defer that alternative. Image inputs and approved Swing normalization
require separate bounded owner-input/result compatibility work, enumerated
in the implementation plan. Missing optional evidence or a writing-style deviation
must not add a delivery gate for otherwise eligible news. Preserve periods,
units, attribution, uncertainty, and the distinction between reported facts
and interpretation; never supply missing figures or context by guessing.
Macro distinguishes actual figures from forecasts. Industry distinguishes
reported developments from evidence-backed company impacts. Swing preserves
source levels, dates, and status, while the Board retains deterministic
lifecycle decisions and its existing specialized presentation.

Source-plan cards use the canonical labels Entry, Stop-loss, and Target n.
Always display Entry, Stop-loss, and Target 1, using `-` for each missing base
value. An explicitly unnumbered primary target maps to Target 1. Additional
numbered targets or stops appear only when supplied. These are display slots,
not new eligibility or Board-plan completeness requirements. Preserve source
numbering, operators, ranges, dates, and status; no generated midpoint or
renumbering may fill a gap. Status-only and reminder messages keep their
existing event-specific presentation.

The source-analysis LLM recognizes approved synonyms through the shared Swing
instruction: Watch on and Buy area map to Entry, Support utama maps to
Stop-loss, and TP1/Target 1 and TP2/Target 2 map to the corresponding Target n.
An unqualified Support utama value of 260 becomes Stop-loss `<260` under the
user's explicit rule; preserve an explicitly supplied comparator. Retain the
raw source wording and any additional conditions as provenance/context.
This approved normalization does not alter deterministic Board lifecycle or
effective-stop rules.

Industry uses supplied publication evidence and optional image context,
without new external research or related-company discovery in this extension.
It may describe clearly qualified qualitative company implications when
supplied evidence establishes specific exposure and the connecting mechanism.
Preserve source attribution and assumptions, omit unsupported implications,
and do not invent effect size, contract awards, or share-price predictions.

For news summaries, decide eligibility from source text first. Only an
eligible item may use associated images as additional summary context.
Do not add image-only news analysis or scan images to establish eligibility.
Image preparation or inspection failure must not withhold text-supported
eligible news. Load images on demand in the same analysis workflow after
text eligibility rather than attaching them during initial screening.
This policy preserves existing specialized Swing source-plan
intake; it does not redefine images or PDFs used by those source contracts.

Apply later guidance only when preparing new eligible work. Reuse existing
frozen messages and destinations verbatim on retries. Preserve routing,
payload schemas, item identity and ordering rules, operation keys, receipts,
and retry identities. This decision authorizes design discussion, not an
implementation, schema migration, replay, or deployment. The
[consolidated design](../specs/2026-10-03-shared-category-contracts.md) records
the agreed category and image rules. See the
[working notes](../notes/2026-10-03-shared-category-contracts-working-notes.md)
for discussion context and checked-in source evidence.
