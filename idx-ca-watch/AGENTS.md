# IDX CA Watch instructions

This file supplements the repository root `AGENTS.md`. It is the development and domain source of truth for the agent-backed `idx-ca-watch` cron. `SKILL.md` is the concise Hermes runtime prompt and must not add rules absent here.

## Runtime and ownership

- Development source: this directory. The deployed runtime is `~/.agents/skills/idx-ca-watch/`; the wrapper is `~/.hermes/scripts/idx-ca-watch.sh`.
- The deterministic `bin/scan.py` fetches IDX disclosures, classifies candidate types, extracts PDFs and financial context, applies hard red flags, owns `state/state.json`, creates the chart attachment, records scores, sends Discord messages, and emits the heartbeat. Hermes is woken only with bounded unscored items.
- The live agent-backed job attaches `SKILL.md`. Do not rename it to `CRON.md`, edit production state, or use the dotfiles mirror as source.
- Verify source-network behavior on the VPS. IDX Cloudflare does not make a Mac result representative.

## Screening and scoring boundary

The feed is for high-conviction corporate-action catalysts over approximately one to 20 trading days, not a general disclosure or technical-analysis feed. The agent evaluates only supplied evidence and never fetches, browses, or adds outside facts.

- Missing price, size, counterparty, denominator, funding, approval, or other material term is missing evidence, not a favourable assumption.
- Routine financial results, ordinary dividends, generic material-fact notices, administrative updates, vague cooperation or joint-venture announcements, and disclosures lacking materiality or economic-effect detail are suppressed and recorded.
- Severe dilution, defensive refinancing, financial distress, UMA, suspension, PKPU, FCA/PPK, and other overriding adverse conditions cannot post. Negative trailing net income, an approximate 50 percent or larger net-income collapse, or current ratio below one without net cash is also disqualifying.
- Never score or describe RSI, moving averages, ATR, volume, price momentum, liquidity, or chart patterns. The chart is visual context only.

The score has four integer components: `materiality` (0 to 3), `fundamental_impact` (0 to 3), `structure_alignment` (0 to 2), and `execution_certainty` (0 to 2). Its total must equal `score`. Materiality uses the most relevant disclosed base, such as market capitalization, annual revenue, assets, shares outstanding, free float, or another directly relevant company base. Without a usable denominator or key transaction term, it is at most one.

Publish only when all gates hold: total score 7 to 10, materiality at least two, fundamental impact at least two, execution certainty at least one, a usable `fundamental_context` denominator, and no red flag or financial-distress condition. Score seven means a material catalyst with one meaningful remaining uncertainty, eight has a clear benefit and credible execution, and nine or 10 is highly material or transformative with measured impact and little uncertainty. A label alone never qualifies. Record every evaluated item, including a suppression, so it cannot re-escalate.

## Agent submission and delivery

For a qualifying item, the agent writes one or two short factual Bahasa Indonesia paragraphs. It starts with the core action, names parties and material numbers, and states only supported economic implication and remaining uncertainty. It adds no heading, bullets, technical metrics, disclaimer, or conclusion. The agent copies supplied `ticker`, `company_name`, `fundamental_context`, `health`, `red_flags`, `pdf_url`, and `chart_path` verbatim; it supplies only `ca_label`, `summary`, and the four score components through `scan.py post-alert`, then records the same evaluated total through `scan.py record-score`.

The scanner validates the gates and renders the alert to Discord `1517510484025151538` with the chart attached. Operational heartbeats and failures go only to `1505162000420835388`. Agent replies must never be posted directly to either channel.

## State, safety, and verification

- `state/state.json` is production data. It contains disclosure deduplication and score records. Never reset, deploy, hand-edit, or backfill it.
- Use `IDX_CA_WATCH_NO_POST=1` with `IDX_CA_STATE_PATH` set to an isolated path for a deterministic smoke test. `IDX_CA_WATCH_BOOTSTRAP_RESET=1` is permitted only for that isolated state, never production state.
- Do not manually run the scheduled production scan as a smoke test. It can post alerts and perform chart work.
- After an approved deployment, compare local and VPS SHA-256 checksums for every changed `bin/` file, `SKILL.md`, and wrapper; then inspect the no-post output, target-channel heartbeat and alert path, and a natural scheduler record. The deployed runtime, not the dotfiles snapshot, is authoritative.

## Development and deployment

Run the focused scanner tests, then the repository suite with `../.venv/bin/python -m pytest -q idx-ca-watch/tests`. Publish a clean reviewed commit before deployment. Use `./deploy.sh idx-ca-watch` only for executable changes, synchronize the reviewed runtime prompt separately after comparing it with the VPS copy, and never recreate, retarget, enable, or reschedule the existing job without explicit approval.

## Historical references

- [IDX CA notification upgrade design](../docs/specs/2026-06-27-idx-ca-notif-upgrade-design.md) records the earlier delivery migration and its rationale.
