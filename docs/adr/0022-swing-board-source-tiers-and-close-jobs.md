# Swing board source tiers and close jobs

Status: accepted

## Context

The Swing Plan Board contains complete executable plans and weaker source
context in the same per-ticker episode. A single generic `Source plan` label
does not distinguish a structured GTW setup from an X chart, while the close
reconciler must continue to operate only on complete Primary Plans.

## Decisions

- Use one visible source/lifecycle tier per episode:
  - `Primary plan`, marked with the Unicode 🥇 emoji, means a complete
    executable cash-equity plan from Phintraco or a future equivalent such as
    BRI Danareksa.
  - `Supporting setup`, marked with 🥈, means structured non-primary context
    from Kelas Investasi GTW.
  - `Chart context`, marked with 🥉, means X or other social/chart-only
    context. It never creates plan levels or market checkpoints.
  - `Resolved`, marked with the custom `check_big` emoji, replaces the tier
    when a Primary Plan reaches its final target or breaches its stop-loss.
- If an episode contains both GTW and social context, apply only the strongest
  source-only tier, `Supporting setup`; retain every source as a normal reply.
- Keep one factual market tag alongside an active or resolved Primary Plan:
  `Below entry`, `Entry zone`, `Above entry`, `TP1 reached` through `TP6
  reached`, or `Stop-loss breached`.
- Run the deterministic close owner at 16:30 WIB on weekdays and retry only
  unavailable plans at 17:00 WIB. Both phases remain gated by the reviewed IDX
  trading-day calendar.

## Consequences

The tier emoji communicates provenance, not confidence or expected return.
Source-only context remains visible without accidentally entering the daily
price-reconciliation set. A future Primary source can reuse the same close
jobs without source-specific scheduler branches.

