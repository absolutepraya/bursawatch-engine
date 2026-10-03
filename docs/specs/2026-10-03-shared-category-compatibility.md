# Shared category implementation compatibility

This development follow-up extends the shared news component with Macro,
Industry and Swing guidance. It does not change release authority, destinations,
schedules, receipts, retry identities or Board lifecycle decisions.

## Writing and categories

`lib-news-format/bin/writing_contract.py` owns common direct Indonesian prose,
meaningful attribution and flexible paragraph guidance. Category instructions
are category-only, so callers compose common rules once. The compatible legacy
`news_format.WRITING_INSTRUCTION` export includes Macro and Industry guidance
conditional on the selected category. Relevance and routing stay with each
source owner. Tuntun Industry guidance follows its source kind, independently
of its existing `macro_news` result-route representation.

Macro retains period, unit, basis, actual/forecast/consensus/prior roles,
revisions and uncertainty. Industry implications need supplied specific
exposure evidence and a direct mechanism; unsupported impacts are omitted.
Swing preserves source levels, dates, status and conditions with canonical
Entry, Stop-loss and Target n labels. Style deviations do not reject eligible
content. Existing schemas, source grounding and transport bounds still apply.

## Optional image protocol

Telegram Market News, X, Instagram and WhatsApp expose
`prepare-summary-images --json '<request>'` through their existing wrappers.
The unchanged initial news item contains no image pixels. Ordinary X news
skips upfront vision preparation; mixed profiles retain their specialized Swing
image handling, which cannot establish ordinary-news eligibility. Instagram
runtime news claims use caption text without upfront OCR or reel sampling.
Original delivery attachments, specialized Swing/PDF and raw-forward policies
remain source-owned. Stockbit remains text-only.

The exact request fields are `protocol`, `owner_event_key`, `claim_id`,
`text_eligible` and `asset_indexes`. Protocol is `summary-images-v1`, eligibility
must be boolean `true`, and indexes are one to four distinct nonnegative
original-image ordinals. The trusted instruction supplies the owner key and
opaque claim digest. The tool derives refs internally from the immutable owner
binding, verifies the active lease before and after I/O, and exposes no paths
when that binding changes. Old events without verifiable refs return unavailable.

The exact response fields are `protocol`, `status`, `assets` and
`unavailable_count`. Status is ready, partial or unavailable. Each returned
asset has `asset_id`, `path`, `sha256`, `association` and `index`. The LLM first
decides text eligibility, then optionally requests images and uses the actual
viewer on returned paths in the same workflow. Availability is not inspection.
Images can clarify only the supplied story, including when Tuntun splits a
publication into several company candidates. Source content is untrusted.
Unavailable context goes directly to a supported text submission, with no
additional model stage, delivery hold or optional-image retry.

Source Media client preparation defaults to four images, 8 MiB per image,
25 MiB per call, eight seconds per read and twenty seconds overall. The helper
uses at most four process-local download workers, verifies digest, size, MIME
and signature, and writes atomic mode-0600 files under a mode-0700
binding-derived directory. It accepts no provider URL or LLM-selected ref/path.
Guarded cleanup acts only within the private binding root.

## Compatible Swing records

Kelas accepts the legacy closed `{event_key,title,summary}` result and version 2
`{schema_version:2,event_key,title,summary,plan_fields}`. Each optional field is
closed `{label,value,source_start,source_end}`, with Python character offsets
into unchanged source text. Approved Watch on/Buy area map to Entry; bare
Support utama maps to Stop-loss `<level`. An explicit comparator stays exact.
Generic support cannot become a stop. Invalid/conflicting optional fields are
omitted without discarding a supported summary. Base Entry, Stop-loss and
Target 1 use `-` when absent; additional numbered fields exist only if supplied.
No target renumbering or range midpoint is introduced.

New version-2 Kelas presentations and new Phintraco BUY/SELL presentations save
exact message chunks and destination before delivery. The optional closed
record is `{version:2,fields,messages,destination}`. Phintraco keeps authoritative
typed fields and uses no LLM extraction. Existing records receive no new default
presentation: absence retains legacy rendering and chunking, and already saved
Phintraco text output takes precedence. Handoff, publication and Board context
reuse the saved presentation. Board-link edits remain separate stable operations.

The Board reads canonical field numbers only when the source values match its
existing typed plan. Its typed comparisons, target order and status evaluation
are unchanged. Kelas stays Supporting setup, X stays Chart context, and only
qualifying complete Phintraco plans become Primary. The 16:30 initial pass and
17:00 retry remain deterministic, with retry scoped to the unavailable plan and
session.

## Release and rollback boundary

Ship compatible binaries and runtime prompts from one reviewed commit:

- `lib-news-format`: common plus Macro/Industry/Swing writing API.
- `lib-bursawatch-source-media`: bounded downloads and `summary-images-v1` API.
- `lib-swing-format`: source-span validator and version-2 saved-presentation reader.
- Telegram Market News, X, Instagram and WhatsApp: bound optional-image commands,
  wrappers, provenance readers and matching SKILL prompts.
- Kelas, Phintraco and Board: compatible Swing readers and presentation adoption.
- Telegram source ingest: compatible Market News and Kelas runtime prompt.

Manifest dependencies install libraries before consumers. Existing `bin/**`
units include the helpers; no service, credential, job or CI gate is added.
An older binary is not a safe rollback reader for new saved records. Preserve
compatible readers, or separately plan draining before restoring older code.
Never strip records, regenerate frozen payloads, reset state or replay sources.

Local suites use supplied model-shaped fixtures and isolated owner state. They
verify deterministic contracts and retry behavior, not live model adherence or
production source-to-delivery health. Deployment and natural-run verification
remain separately authorized work.
