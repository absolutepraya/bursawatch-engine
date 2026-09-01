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

The score has four integer components and its total must equal `score`:

1. `materiality`, 0 to 3: zero is unquantified or below five percent of the relevant base; one is five percent to below 10 percent; two is 10 percent to below 25 percent; three is at least 25 percent or a material control or free-float change. Use the relevant disclosed denominator, such as market capitalization, annual revenue, assets, shares outstanding, free float, or another directly relevant company base. Without a usable denominator or key transaction term, it is at most one.
2. `fundamental_impact`, 0 to 3: score only a disclosed, supportable path to revenue, earnings, cash flow, productive assets, capital structure, control, or free float. Broad management language without a specific economic path is zero or one.
3. `structure_alignment`, 0 to 2: score disclosed terms that protect or improve public-shareholder economics, including a credible controller commitment. Pure dilution, opaque related-party economics, or unaligned rescue financing is zero.
4. `execution_certainty`, 0 to 2: score disclosed price, size, parties, funding, approvals, timetable, and other material terms. An early plan without key terms is zero.

Publish only when all gates hold: total score 7 to 10, materiality at least two, fundamental impact at least two, execution certainty at least one, a usable `fundamental_context` denominator, and no red flag or financial-distress condition. Score seven means a material catalyst with one meaningful remaining uncertainty, eight has a clear benefit and credible execution, and nine or 10 is highly material or transformative with measured impact and little uncertainty. A label alone never qualifies. Record every evaluated item, including a suppression, so it cannot re-escalate.

## Agent submission and delivery

For a qualifying item, the agent writes one or two short factual Bahasa Indonesia paragraphs. It starts with the core action, names parties and material numbers, and states only supported economic implication and remaining uncertainty. It adds no heading, bullets, technical metrics, disclaimer, or conclusion. The agent copies supplied `ticker`, `company_name`, `fundamental_context`, `health`, `red_flags`, `pdf_url`, and `chart_path` verbatim; it supplies only `ca_label`, `summary`, and the four score components through `scan.py post-alert`, then records the same evaluated total through `scan.py record-score`.

The scanner validates the gates and renders the alert to Discord `1517510484025151538` with the chart attached. Operational heartbeats and failures go only to `1505162000420835388`. Agent replies must never be posted directly to either channel.

## State, safety, and verification

- `state/state.json` is production data. It contains disclosure deduplication and score records. Never reset, deploy, hand-edit, or backfill it.
- Use `IDX_CA_WATCH_NO_POST=1` with `IDX_CA_STATE_PATH` set to an isolated path for a deterministic smoke test. `IDX_CA_WATCH_BOOTSTRAP_RESET=1` is permitted only for that isolated state, never production state.
- Do not manually run the scheduled production scan as a smoke test. It can post alerts and perform chart work.
- After an approved deployment, compare local and VPS SHA-256 checksums for every changed `bin/` file, `SKILL.md`, and wrapper; then inspect the no-post output, target-channel heartbeat and alert path, and a natural scheduler record. The deployed runtime, not the dotfiles snapshot, is authoritative.

## VPS capability checks and watchdog

The wrapper uses `$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python`. Its IDX fetch and PDF-extraction dependencies are `curl_cffi`, `cloudscraper`, and `pypdf`; inspect the existing runtime before any approved dependency change. The scanner uses the shared chart script at `~/.agents/skills/chart/bin/chart.sh` and the `CHART_IMG_API_KEY` loaded only by its wrapper.

On an approved VPS verification path, use these read-only probes with that runtime interpreter, not a Mac substitute:

```bash
IDX_CA_PY="$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"
$IDX_CA_PY -c "import sys; sys.path.insert(0,'$HOME/.agents/skills/idx-ca-watch/bin'); import scan; print(scan.fetch_page(1,3).get('ResultCount'))"
$IDX_CA_PY -c "import sys; sys.path.insert(0,'$HOME/.agents/skills/idx-ca-watch/bin'); import scan; print(scan.render_chart('BBCA')); print(scan.market_metrics('BBCA')['avg_value_idr'])"
```

`idx-ca-health` is the safe operational probe for cache growth. The gateway-independent `bin/watchdog.py` checks for a stale successful scan and prunes old chart and log artifacts; it is separate from Hermes and must retain the VPS runtime interpreter and `HOME` environment. Do not create, change, or run its scheduler entry without explicit approval.

## Development and deployment

Run the focused scanner tests, then the repository suite with `../.venv/bin/python -m pytest -q idx-ca-watch/tests`. Publish a clean reviewed commit before deployment. Use `./deploy.sh idx-ca-watch` only for executable changes, synchronize the reviewed runtime prompt separately after comparing it with the VPS copy, and never recreate, retarget, enable, or reschedule the existing job without explicit approval.

## Historical references

- [IDX CA notification upgrade design](../docs/specs/2026-06-27-idx-ca-notif-upgrade-design.md) records the earlier delivery migration and its rationale.
