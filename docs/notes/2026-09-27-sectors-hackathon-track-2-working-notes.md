# Sectors Hackathon Track 2: working design notes

Status: draft discussion record, 27 September 2026. This is not an approved implementation spec or permission to change BursaWatch production. Keep the hackathon submission in a new, independent repository created within the event's eligible build window. Recheck the current rules before implementation or submission.

## Intent

Build a useful autonomous Indonesian market research workflow that makes Sectors data essential. A reader should understand the day's likely IHSG conditions and, when a broker publishes a complete swing setup, understand the issuer and the surrounding market context. The output is information and analysis, not individualized financial advice or trade execution.

The connected demo story is: scheduled morning brief -> complete broker setup arrives -> Sectors-enriched issuer research card -> after-close check of the morning call. The morning brief is the first build priority because it can be developed independently of the current BursaWatch architecture migration. The broker alert is the connected extension.

## Decisions agreed in conversation

1. **Track and centerpiece.** Target Automation & Workflows, Track 2. Present the scheduled morning brief and broker-triggered alert as one connected experience. Show unattended runs, timestamps, input provenance, output, and delivery evidence from the new submission itself.
2. **Sectors is core.** Use its dated IDX index, sector, issuer, price/volume, foreign-flow, company, and corporate-action data where applicable. A Sectors outage or missing required response must visibly degrade the core brief or research card; a decorative single API call is insufficient.
3. **Morning brief first.** Lead with an IHSG base case, supporting evidence, counterevidence, and what would change the view. Add an after-close self-audit comparing the morning scenario with the observed outcome. Do not claim a calibrated probability or win rate without measured evidence.
4. **Broker owns the setup.** A complete Phintraco setup, including its original entry, stop, targets, reasons, and chart, triggers the enriched alert. Keep those broker-authored fields and attribution intact. Sectors and other verified sources add issuer identity, sector, affiliation where supported, dated market context, corporate actions, and caution flags. Incomplete chart commentary is context, not a generated trading plan.
5. **Source roles stay visible.** Separate broker setup, Sectors context, other source claims, and system observations. Show dates, links, conflicts, missing fields, and stale data. Do not silently reconcile conflicting facts.
6. **Jev is optional and narrow.** If used, Jev classifies bounded questions such as relevance, source stance, or conflict. Deterministic code owns arithmetic, time ordering, freshness, and invariants. A generative model writes concise human-readable Indonesian text. Jev confidence is not the probability of an IHSG move.
7. **Sentiment addition.** Include a compact X narrative pulse in the morning brief. Expand the selected X source panel beyond currently watched accounts, with a deliberate mix of market perspectives. Show main optimistic and cautious narratives, source links, timestamps, and disagreement with Sectors market evidence. One frequent poster must not dominate. This panel is curated commentary, not a representative poll of all traders. Stockbit is excluded from this sentiment section because the user considers it noise.

## Proposed morning brief content

- **IHSG scenario:** base case such as up, down, range-bound, or a more precise conditional description; key evidence and invalidation conditions.
- **Rotation:** sector and conglomerate themes in a four-quadrant view. Do not imply Sectors has a comprehensive conglomerate directory; any mapping needs an explicit source and coverage limit. Individual-stock rotation is not required for the first brief.
- **Global lead:** relevant overnight indices such as S&P 500, Nasdaq/QQQ, and KOSPI, only from verified external feeds because the reviewed Sectors documentation does not establish broad global-index coverage.
- **Today and this week:** anticipated macro or market events, expected scenarios, and source links. Distinguish a scheduled event from a speculative outcome.
- **Corporate actions:** short today/this-week dividend and other material corporate-action reminders.
- **Market status:** UMA, suspensions, and FCA entries/exits only where current source coverage is verified. Sectors suspension history alone is not a complete feed for all three.
- **X narrative pulse:** a few distinct, fresh themes with links and disagreement notes, compared with Sectors price/flow/sector evidence.
- **Research context:** relevant broker and other existing-source technical IHSG commentary when available, with attribution and freshness checks.

The brief should say when a source is unavailable. It should not fill gaps by presenting old commentary as today's view. The proposed suppression of separate morning macro-news posts is still only an idea; changing an existing production destination or cadence would need its own later review and approval.

## Data and eligibility boundaries to preserve

- Existing BursaWatch adapters, Discord output, and operational records help identify the problem and source formats. They are not the new hackathon project's execution evidence. The current control-plane source inbox was not a populated searchable research corpus when inspected, so the design must not depend on historical semantic retrieval being ready.
- Use new submission-owned run records for scheduler execution, source freshness, decisions, output, delivery, and after-close audit. Reuse of existing code or private infrastructure for the competition entry requires a rules check; assume the submission must stand on its own.
- The first swing card enriches a broker-originated plan. A separately generated swing candidate would require distinct labeling, tested strategy rules, and its own validation. It is outside the initial demo.
- Public presentation should frame the product as research/analysis. No automated orders.

## Open design choices

1. Define the expanded X panel: active trader chatter versus analyst/broker commentary, account selection criteria, source access, and minimum fresh independent voices before displaying a pulse. The current recommendation is to lean toward active trader chatter because broker research already covers the analyst view. The user has not selected the panel or individual accounts yet.
2. Define the exact morning cut-off time, trading calendar, and late-data behavior.
3. Choose reliable external feeds for global indices, events, UMA, and FCA. Verify licensing, timestamps, and coverage before promising them in the demo.
4. Specify the four rotation quadrants and the permitted conglomerate mapping.
5. Decide whether the after-close audit is a same-day follow-up message, a dashboard view, or both.
6. Select one realistic demo day and broker setup with complete source provenance, then ensure the new project's scheduled and triggered runs can demonstrate them without replaying existing BursaWatch alerts.

## Reference starting points

- [Hackathon rules](https://hackathon.sectors.app/rules)
- [Track 2: Automation & Workflows](https://hackathon.sectors.app/tracks/automation-workflows)
- [Sectors API documentation index](https://docs.sectors.app/llms.txt)
- [TypeSafe Jev documentation](https://docs.typesafe.ai/introduction)
- Current BursaWatch source contracts: `cron-tg-phintraco-swing/AGENTS.md`, `cron-x-account-watch/AGENTS.md`, and `cron-stockbit-snips/AGENTS.md`. These describe the existing system, not an approved reuse path for the competition entry.
