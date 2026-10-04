# Shared category contracts: working discussion

Status: Category and image discussion decisions agreed, 2026-10-03.
The [consolidated design](../specs/2026-10-03-shared-category-contracts.md)
records the resulting contract. Implementation planning and deployment remain
separate steps. This follow-up is outside PR #48.

The [boundary decision](../adr/0032-shared-category-contract-boundaries.md)
records the accepted direction. The [glossary](../glossaries/category-news.md)
records the vocabulary. Accepted decisions below supersede earlier proposals;
resource defaults and typed protocol details remain implementation-plan work.

## Confirmed direction

- Work in the order Macro, Industry, then Swing.
- Keep common writing rules in the shared component and remove their
  duplicates from source adapters during each category's adoption.
- Start with shared category guidance over existing payloads. Flexibility and
  reliable delivery take priority over adding required fields or style gates.
- Macro preserves periods, units, and actual versus forecast distinctions.
- The user accepted the three Macro content policies after the concrete
  examples: retain source-supported wording for incomplete context, explain
  central unresolved discrepancies, and select material indicators with
  their supplied context intact.
- For news summaries, assess source text for eligibility first. Only eligible
  items may use images as additional summary context. The user rejected
  image-only news analysis because of credit cost, and rejected scanning
  images before the text eligibility decision.
- Unavailable or unreadable additional images must not prevent delivery of
  text-supported eligible news. Images do not establish the primary story or
  rescue text that fails eligibility. Existing specialized Swing source-plan
  intake remains governed by its source contracts.
- The user accepted loading images on demand in the same LLM workflow after
  text eligibility. Image failures add no delivery gate, and frozen delivery
  retries do not repeat image inspection.
- Industry separates reported facts from evidence-backed company impacts.
  Optional context must not prevent ordinary eligible news from being sent.
- The user accepted supplied evidence as the Industry scope, without new
  external research or related-company discovery. Clearly qualified
  qualitative implications are allowed when that evidence supports specific
  company exposure and the connecting mechanism, even without a quantified
  effect. Omit unsupported effects while preserving delivery of the news.
- Swing preserves source levels, dates, and status exactly. Board lifecycle
  decisions remain deterministic, and Swing keeps its specialized renderer.
- The user accepted keeping structured levels as the reference and prose for
  rationale, and revised the missing-field proposal: source-plan cards always
  show Entry, Stop-loss, and Target 1, using `-` for missing base values.
  Extra targets or stops appear only when explicitly supplied. This does not
  add an eligibility or Board completeness gate.
- The user approved LLM recognition of Swing synonyms through shared prompt
  guidance, with canonical output labels Entry, Stop-loss, and Target n.
  Watch on/Buy area maps to Entry; Support utama maps to Stop-loss; TPn and
  Target n retain their number. An unqualified Support utama 260 maps to
  Stop-loss `<260`. Preserve source-provided explicit comparators and the raw
  wording and conditions. This resolves the earlier PWON alias question.
- Preserve frozen payloads, routing, receipts, and retry identities. Retries
  reuse prepared content rather than rewriting it under new guidance.

## Checked-in source evidence

Read-only source review used base commit
`6623dd4aaadc7904d0c6274e228a66ca9edcf901`. These observations describe that
source snapshot, not current production health or delivery evidence.

- [`news_format.py`](../../lib-news-format/bin/news_format.py) already supplies
  `WRITING_INSTRUCTION` to all five news owners. It preserves attribution,
  periods, units, and uncertainty, and makes paragraph style flexible.
  `freeze_cards` saves rendered messages and destinations; `validate_cards`
  accepts an exact field set. Even an optional structured evidence field
  needs a deliberate compatibility change.
- Telegram, WhatsApp, and Stockbit prompts still duplicate some common
  headline, language, and summary rules. Their source-specific relevance,
  schemas, attribution identity, and routing requirements belong with the
  owners and must survive consolidation.
- Telegram's [`agent_protocol.py`](../../cron-tg-market-news/bin/agent_protocol.py)
  requires Tuntun Industry to use `macro_news` or `exclude`.
  [`scan.py`](../../cron-tg-market-news/bin/scan.py) selects the Industry
  destination using source kind. Shared presentation must receive an
  owner-selected category rather than infer it only from the route string.
- [`lib-swing-format`](../../lib-swing-format/README.md) already owns specialized
  Swing presentation. The [`Board contract`](../../cron-dc-swing-board/AGENTS.md)
  assigns episode and lifecycle ownership to deterministic Board code.

## Discussion decisions

The settled prerequisite is category guidance first, preserving existing
output schemas and delivery ownership. The user accepted these Macro content
policies after the clarifying examples:

1. **Incomplete context:** a source says inflation is 2.8% without a period
   or YoY/MoM basis. Accepted: preserve source-supported wording,
   disclose ambiguity when material, and never infer a comparison or missing
   label. Other supported news remains deliverable.
2. **Conflicting figures:** a headline says 2.8% and a table says 3.0% for
   the same period, without an explained revision. Accepted: do not
   choose a winner. Disclose a central discrepancy briefly; omit a peripheral
   disputed claim while retaining the supported report.
3. **Dense releases:** a publication contains ten indicators. Accepted:
   summarize the material indicators, keeping each retained figure's supplied
   period, unit, actual/forecast distinction, prior/revision qualification,
   and attribution. No requirement to reproduce every number or force a table
   or paragraph count.

The user settled the image policy: text eligibility first, then optional
image context for summary creation, with no new image-only news analysis.
The user accepted Industry supplied evidence and qualified qualitative
implications, Swing display slots and synonyms, and preservation of the
existing Board tiers and close-check scope. The category discussion is
consolidated in the design spec. Image inputs and Swing normalization require
coordinated typed owner input/results and runtime-prompt compatibility work.
New external enrichment or automated evidence discovery is not included.

Implementation planning remains a separate next step.
No code, runtime state, schedule, destination, or Discord message is changed
by these notes.

## Clarifying examples for Macro

The user requested concrete cases before answering the three questions.
All numbers below are invented examples, not observed economic releases.
The user accepted these policies after reviewing the examples.

1. **Incomplete context:** a caption says only "Inflation 2.8%". If supplied
   source media clearly labels the value "September 2026, YoY, actual", those
   labels are source evidence and can be preserved. If neither the provided
   text nor readable media gives those labels, the model must not invent them
   from general knowledge. The question is how to word genuinely incomplete
   source evidence, not whether to discard labels present in an image.
2. **Conflicting figures:** a headline says "September inflation 2.8% YoY",
   while a table gives "September actual 3.0% YoY". If no source explanation
   reconciles them, choosing one silently would change the report. By
   contrast, "actual 2.8%, forecast 3.0%" is not a conflict. An explicitly
   labeled revision also explains why two values can appear.
3. **Dense releases:** a table gives September actual inflation 2.8% YoY,
   September consensus forecast 3.0% YoY, and August actual 3.1% YoY,
   plus seven other indicators. A focused summary can retain
   the central release as "Inflasi September tercatat 2,8% YoY, di bawah
   konsensus 3,0% dan angka Agustus 3,1%." That comparison is appropriate
   only if the source supplies each label and the periods/bases match.

### Image availability is distinct from classifier input

At the reviewed source snapshot, Telegram intake retains media refs, and the
Market News owner records whether an image exists. However,
`agent_protocol.agent_item` supplies text and metadata without image refs,
image bytes, or an OCR result. A stored or forwarded image therefore does
not prove the news classifier saw it. Other platform owners have their own
media paths; there is no assumed universal image input.

The user requests source images as additional summary evidence only after
text establishes eligibility. The shared category guidance must preserve
labels from evidence actually supplied. Extending an owner's input to make
images available requires compatible preparation and runtime instructions,
not just a writing-prompt edit. Implementation remains unapproved.

## Accepted image policy and mechanism

Accepted policy: the LLM assesses the source text first. Ineligible text and
image-only news receive no image analysis. After text establishes eligibility,
associated images may clarify the summary, such as supplying a period, unit,
or table label. An image must not become the main story or introduce unrelated
stories from elsewhere in a bulletin.

Accepted mechanism: keep the text decision and summary preparation in
the same agent workflow, and load images through the runtime's image viewer
only after the text eligibility decision. Do not attach images to the initial
LLM input, run OCR over every incoming image, or require a separate extraction
model. A shared preparation component retrieves verified bytes through the
existing Source Media Owner and reader client, stages private local files,
and preserves source association and image order. Owners keep interpreting
their source identities and selecting their existing domain work. Source
text and images remain untrusted evidence, not instructions.

Use bounded preparation time, byte and image budgets, and indicate unavailable
or uninspected evidence rather than silently claiming complete coverage.
The subsequent [implementation plan](../superpowers/plans/2026-10-03-shared-category-contracts.md)
proposes bounded defaults and owner-selected image indexes for review. These
were implementation choices left open during the discussion. Failure to
obtain or read additional images falls back to the supported text summary
without a new delivery gate. Do not retry or hold eligible news merely to
obtain optional image context. Missing details remain missing.

At the reviewed source snapshot, Telegram accepts image-only publications
into the Inbox, but both News extractors discard empty text before LLM
analysis (`sources.py`). The user explicitly chose to retain that image-only
news boundary. Tuntun also splits text blocks before classification, so
additional image context must respect the candidate's story scope. The exact
agent-input field set and provenance record need a coordinated compatibility
change to bind image evidence to source work. The output summary and
frozen-card schemas need not gain image fields.

This news-summary policy does not change specialized Swing image/PDF source
extraction, Board lifecycle decisions, or raw-forwarding behavior.

Apply the new input mechanism during analysis of new work, before freezing a
delivery payload. Delivery retries must continue to use frozen messages and
stable operation identities without re-reading images or re-running analysis.
Any owner input-schema changes need explicit compatibility review, while
accepted output schemas, routing and receipt contracts remain intact.

## Accepted Industry policy

Checked-in source review confirms that Telegram instructs the LLM to use
only supplied source facts (`agent_protocol.py`). Its submission has summary,
material facts, dedupe facts, and source evidence, but no dedicated
company-impact or enrichment-provenance field. No related-company discovery
or enrichment implementation was found in the reviewed Telegram owner and
shared news formatter. Source-reported implications can be distinguished in
existing prose; new researched implications would require an explicit source
boundary and compatibility decision.

The user accepted both decisions:

1. **Evidence scope:** use only the original publication, optional images
   after eligibility, and evidence explicitly supplied by the owner, or add
   fresh external research for company impacts? Accepted: use supplied
   evidence in this first extension, with no new external lookups or company
   discovery. Treat broader enrichment as a separate follow-up.
2. **Qualitative implications:** when supplied evidence establishes a
   company's specific exposure and a direct mechanism, may the summary
   explain a potential impact without a quantified effect? Accepted:
   yes, with clear conditional wording and attribution. Do not invent effect
   size, infer a contract award from a policy target, or predict a share-price
   move. If the implication is unsupported, omit it and deliver the news.

Illustrative case, not observed news: the publication reports a natural-gas
price increase and says Company A uses gas as a production input. The fact
is the gas-price development. A qualified implication may describe possible
cost pressure on Company A; it cannot assert an unreported margin decline.
If the publication does not establish Company A's exposure, model memory or
mere sector resemblance is insufficient evidence to add that company.

The original publication's explicit forecast remains attributed to its
author. Any added implication must be distinguishable from a reported fact.
Use existing flexible paragraph guidance rather than requiring a new block,
label, or complete company-impact field on every Industry item. Implementing
the accepted qualified-implication policy requires aligning owner instructions
with that scope; this is not permission for the agent to add external facts.

## Accepted Swing policy

Checked-in source facts at the reviewed base:

- [`swing_format.py`](../../lib-swing-format/bin/swing_format.py) already keeps
  supplied field text and structured provider-specific fields. It converts
  aware timestamps to WIB without changing their instant.
- The [`Board renderer`](../../cron-dc-swing-board/bin/render.py) distinguishes
  source status/date from market checkpoint/state and resolution. Topic date
  remains the opening source date. Level parsing and lifecycle decisions
  belong to existing deterministic owners, not shared writing guidance.
- Existing adapter normalization and missing-field display differ. Kelas
  uses a canonical range representation and missing-field dashes; Phintraco
  status messages omit levels that are not supplied. Preserve values,
  operators, range endpoints, target order, and source dates within existing
  representations. The accepted synonym policy below adds explicit semantic
  normalization in source analysis; it does not permit generated price levels
  or changes to deterministic Board calculations.
- Kelas currently has a one-line prose validator. Adopting flexible common
  writing requires a coordinated adjustment of style-specific rules while
  retaining source linkage, closed schemas, and numerical grounding checks.
- Existing required Swing media capture/delivery rules remain independent
  of the new optional LLM image context. The optional-context fallback must
  not silently relax required source-media or Board handoff contracts.

The user accepted the narrative policy and specified the plan display rule:

1. **Levels in prose:** should a narrative repeat levels already present in
   structured fields? Accepted: keep those fields as the exact reference
   and use prose for the supplied rationale or conditions. Repeat a level
   only when needed to explain a source condition.
2. **Missing-field appearance:** for source-plan cards, always show Entry,
   Stop-loss, and Target 1, using `-`
   for missing base values. Omit TP2, TP3, SL2, and other additional slots when
   those fields are absent. Preserve supplied source numbering, even if a
   numbered field is missing; do not rename TP2 into TP1. This supersedes the
   earlier recommendation to keep differing provider display conventions.
   Follow-up status/reminder layouts and Board completeness rules remain
   unchanged. Missing-field display is not a delivery gate.
3. **Source synonyms:** the LLM recognizes approved source labels using the
   shared Swing instruction and produces the same canonical labels as
   Phintraco: Entry, Stop-loss, and Target n. Watch on/Buy area means Entry;
   Support utama means Stop-loss; TP1/Target 1 means Target 1, and so on.
   An unqualified main-support level maps to a stop below that level under
   the user's explicit rule. Existing explicit comparators and extra source
   conditions remain intact. This is normalization of source evidence, not
   permission to generate a new setup or calculate Board state.

Illustrative source, not an observed setup: Entry `1.000 to 1.050`, Stop-loss
`<950`, Target `1.150`. Preserve the range and operator; prose must not turn
the entry into a newly calculated midpoint or the stop into a different
comparison. Any prose uses only the source's rationale and conditions.

Shared common writing will compose with the structured Swing renderer. It
must not replace deterministic Board state, create or promote a plan, alter
source fields, weaken required media delivery, or reinterpret receipts.

### Bounded Telegram source check

Read through the Telegram skill on 2026-10-03, without posting or changing
Telegram state. Exact message-context reads confirmed the selected BULL,
VKTR, and PWON publications. Searches supplied additional IMPC, PACK, and
HRTA examples. This was a bounded sample, not a complete channel audit or
production pipeline verification.

- [Phintraco BULL](https://t.me/phintasprofits/35566), source plan dated
  2 October 2026 at 06:00 WIB: Entry `>=340`, Stop-loss `<330`, Target 1 `360`,
  Target 2 `380`. TP2 appears before TP1 in the publication, so numbering must
  determine target identity rather than line position.
- [Phintraco IMPC](https://t.me/phintasprofits/35564) supplies Target 1
  `1390-1400` and Target 2 `1460`; preserve the target range.
- [Phintraco HRTA](https://t.me/phintasprofits/35538) supplies Target 1 `2400`,
  Target 2 `2500`, and Target 3 `2600`; additional supplied targets must remain
  visible, without generating absent later targets.
- [Kelas VKTR](https://t.me/kelasinvestasiid/10629) supplies Buy area
  `760–825`, TP1 `930`, TP2 `990`, and Stoploss `<705`. Its separately stated
  assumed average entry `795` must not replace the supplied entry range.
- [Kelas PWON](https://t.me/kelasinvestasiid/10759) supplies "Watch on"
  `270–282`, Target 1 `288`, Target 2 `298`, and "Support utama" `260`, plus a
  conditional invalidation statement. The user subsequently defined these
  as synonyms: canonical Entry `270–282`, Stop-loss `<260`, Target 1 `288`,
  and Target 2 `298`. Keep the additional failed-reclaim condition in source
  context rather than silently deleting it.

No explicit SL2 example was located in the bounded Phintraco search. That
does not prove the field is absent from all source publications. If an
additional stop is supplied, preserve its source label/value as presentation
context without changing the Board's existing effective-stop rules.

The PWON mapping question is resolved by the user's explicit synonym rule.
The earlier recommendation to leave its Entry and Stop-loss empty is
superseded. Incorporate the mapping into shared source-analysis guidance,
with compatible owner input/output validation rather than new per-adapter
writing rules. Display `-` only when a base field remains missing after
recognizing approved synonyms. Retain source eligibility, deterministic
Board acceptance rules, frozen delivery payloads, and retry identities.

### Board tier and close-check clarification

The user asked whether Kelas GTW is secondary and how it relates to scheduled
close-price status/tag updates. Checked-in
[`tags.py`](../../cron-dc-swing-board/bin/tags.py) assigns Kelas/GTW
`Supporting setup`, above social/X `Chart context`. Both are source-only
tiers. Kelas GTW never becomes `Primary plan` merely because its presentation
has Entry, Stop-loss, and Target n fields.

[`engine.py`](../../cron-dc-swing-board/bin/engine.py) selects only
`active_primary_plans()` for `after_close`. Its reviewed phase starts are
16:30 WIB for the initial current-session close check and 17:00 WIB for a
retry. The retry checks only that exact active plan when its initial attempt
recorded an unavailable close for the same session; it is not a second full
pass over every plan. Valid Primary checks may update the market state/card
and tags, with stop-loss or the final target resolving the plan.

Source-only Kelas/Chart-context episodes do not receive those market-price
tags or reinterpret their levels as a tracked Primary plan. A qualifying
Phintraco setup can promote an applicable source-only episode under existing
Board rules, retaining the prior context. Shared writing and synonym
normalization preserve these tiers, promotion rules, and close-check scope.
This is a source-code check, not a live scheduler or production-status check.

The user confirmed this tier and close-check boundary. Formatting and synonym
normalization retain Kelas as Supporting setup and do not expand scheduled
market evaluation beyond active Primary plans.
