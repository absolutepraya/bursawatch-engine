# idx-ca-watch explained alerts design

## Context

`idx-ca-watch` watches IDX corporate-action disclosures, deterministically filters and escalates interesting items, then wakes Hermes to score eligible items and post a chart-backed Discord alert. The alert renderer currently uses a compact heading and two underspecified one-line fields:

```md
🟢 **ANTM** · Rights issue (HMETD) · `8/10`

**Deal:** ...
**Owner:** `BULLISH`, ...
```

The alert is hard to understand without prior corporate-action knowledge. Its internal field names (`deal`, `owner_intent`, `owner_why`) also do not match the clearer reader-facing questions a user needs answered.

This design replaces the alert payload contract and presentation only. It does not alter scanning, scoring, posting gates, chart generation, technical metrics, financial-health caps, or channels.

## Goals

1. Make the alert header a Discord H2 with the score emoji at the far right.
2. Explain the disclosure in clear, plain English under `What happened:`.
3. Explain the practical, evidence-based investment implication under `Why it may matter:`.
4. Distinguish verified filing facts, reasoned implications, and uncertainty.
5. Use corporate-action mechanics and fundamental tests from the Klinik Penyesalan materials without presenting speculation as fact.

## Non-goals

- No changes to the 0 to 10 scoring rubric, 🟢/🟡 posting bar, hard-disqualifier vetoes, or financial-distress cap.
- No changes to `scan.py` fetch, deduplication, classification, data extraction, chart generation, or Discord channel IDs.
- No changes to the chart attachment behavior, metrics, fundamentals, or PDF URL.
- No new automatic owner, proxy, UBO, or price-manipulation inference.
- No compatibility aliases for retired alert fields.

## Research inputs

### Day 1, Capital Market Basics

`Day 1 - Capital Market Basics/Module 1 - Class Introduction & Capital Market Basics (unlocked).pdf` directly covers the mechanics used by `What happened:`:

- PMHMETD / rights issue: new shares offered first to existing holders, often at a discount.
- Rights ratio, exercise price, use of funds, trading/exercise dates, dilution, and standby-buyer allotment.
- PMTHMETD / private placement, dividends, buybacks, stock splits, tender offers, and corporate-action mechanics.

### Day 3, Fundamental Analysis

`Day 3 - Fundamental Analysis/Module - Fundamental Analysis 101.pdf` and `MARKET SENSE - QnA Session #3.pdf` establish the economic test for `Why it may matter:`:

- A corporate action is a trigger, not a thesis by itself. Explain its plausible path to future net income, recurring earnings, margin, capacity, backlog, operating cash flow, or balance-sheet improvement.
- Prefer operating fundamentals and cash generation over a headline or a one-off accounting gain.
- Treat expansion, contracts, acquisitions, and funding as constructive only when the stated use can plausibly improve the business and financial evidence does not contradict it.

### Day 7, Proxy & Owner’s Interest

`Day 7 - Proxy & Owner's Interest/Module - Proxy & Owner's Interest.pdf` informs the ownership and group-context checks:

- Formal ownership can differ from economic interest or effective control.
- A corporate action can change control, voting rights, capital structure, or group positioning.
- Proxy, UBO, and group-network conclusions require a mosaic of evidence. The alert may state only disclosed or independently verified relationships as fact. It must label any plausible owner incentive as an inference and never claim hidden control, manipulation, price support, wash sales, or markup without evidence.

## New alert JSON contract

### Retired fields

```json
{
  "deal": "<one line>",
  "owner_intent": "BULLISH",
  "owner_why": "<one clause>"
}
```

### Replacement fields

```json
{
  "what_happened": "<2 to 4 short sentences of plain-English disclosure facts and shareholder mechanics>",
  "why_it_matters": "<2 to 4 short sentences of evidence-based implication and uncertainty>"
}
```

This is a clean cutover. The `post-alert` CLI accepts only the replacement names. The wake-up agent is the sole producer, and `SKILL.md` will be migrated in the same change. No aliases, compatibility parsing, or deprecated documentation remain.

All unchanged fields remain required and retain their current semantics:

```json
{
  "emoji": "🟢",
  "ticker": "ANTM",
  "ca_label": "Rights issue (HMETD)",
  "score": 8,
  "metrics": {},
  "health": {},
  "pdf_url": "https://...",
  "chart_path": "/tmp/...png"
}
```

## New rendered alert

```md
## **ANTM** · Rights issue (HMETD) · `8/10` 🟢

**What happened:**
ANTM plans a rights issue at Rp820 per share, below its recent VWAP of about Rp1,100. The company says the proceeds will fund the stated project, while the named standby buyer can absorb shares that existing holders do not take up. This increases the share count, so holders face dilution unless the funds create enough value.

**Why it may matter:**
The disclosed buyer or controlling group has the verified relationship stated in the filing. If the proceeds add recurring capacity and execution is on plan, the action could support future earnings. That is an inference, not proof of future price support. If the disclosure does not establish a credible incentive, say so directly.

**Fundamentals:** healthy
- ROE `14%`
- net cash
- margin `21%`
- NI `+5%`

**Tech:**
- above MA200
- RSI `58`
- liq `Rp180B/d`
- ATR `3.4%`

PDF: https://www.idx.co.id/StaticData/.../file.pdf
```

The header has exactly one emoji, at the far right. It is the existing score emoji. Lowercase persona voice remains disabled for this structured research signal.

## Renderer behavior

`render_alert(f: dict) -> str` changes only its header and explanation block:

```python
def render_alert(f: dict) -> str:
    head = f"## **{f['ticker']}** · {f['ca_label']} · `{f['score']:g}/10` {f['emoji']}"
    what_happened = f"**What happened:**\n{f['what_happened']}"
    why_it_matters = f"**Why it may matter:**\n{f['why_it_matters']}"
    verdict = health_verdict(f.get("health", {}))[0]
    fund_block = "**Fundamentals:** " + verdict
    fstats = fund_stats(f.get("health", {}))
    if fstats:
        fund_block += "\n" + "\n".join(f"- {s}" for s in fstats)
    tech_block = "**Tech:**\n" + "\n".join(f"- {s}" for s in tech_stats(f.get("metrics", {})))
    pdf = f"PDF: {f.get('pdf_url', '')}"
    return "\n".join([head, "", what_happened, "", why_it_matters, "", fund_block, "", tech_block, "", pdf])
```

The function preserves newlines inside `what_happened` and `why_it_matters`, so the wake-up agent can use short paragraphs or a concise fact list when that is clearer. The renderer does not summarize, score, infer relationships, or validate the investment thesis.

## Writing rules for wake-up agent

### What happened

Write 2 to 4 short sentences. Begin with verified disclosure facts, then explain practical shareholder mechanics in plain language.

- Explain unfamiliar terms on first use: "rights issue, meaning existing shareholders can buy newly issued shares."
- Include material terms when disclosed: ratio, exercise or placement price, price discount versus VWAP/market price, buyer or standby buyer, size, timeline, and use of funds.
- State the shareholder effect: dilution, opportunity to exercise or sell HMETD, cash distribution, altered ownership, or reduced floating supply.
- State missing terms plainly. Do not infer undisclosed buyers, prices, proceeds, relationships, or motives.

### Why it may matter

Write 2 to 4 short sentences. State verified ownership/group context first, then a qualified economic implication, then the main uncertainty.

- Connect the action to a concrete path: recurring net income, margin, capacity, backlog, operating cash flow, debt reduction, liquidity, or capital structure.
- Explain the counter-risk: dilution, debt rescue, weak cash flow, one-off gain, affiliate transfer, deep discount, execution risk, or unproven use of funds.
- Treat group/controller/affiliate links as facts only when disclosed or independently verified. For any non-proven relationship, write it as an inference.
- Never claim hidden control, manipulation, wash sales, markup, price support, future rerating, or owner intent as fact.
- If evidence is insufficient, use: "The filing does not establish a clear owner incentive, so this is not a standalone bullish catalyst."

### Corporate-action mechanics by type

| Type | Required points in `What happened:` |
|---|---|
| Rights issue / HMETD | Ratio, exercise price, discount when supplied, stated use of funds, standby buyer, holder choice, dilution. |
| Private placement / PMTHMETD | Recipient, price/discount, size relative to capital, stated use of funds, dilution without HMETD compensation, disclosed affiliate/control effect. |
| Buyback | Amount/period, stated reason, funding source, difference between authorisation and actual purchases, likely supply effect. |
| Cash dividend | Amount per share, total/payout if supplied, relevant dates, relationship to cash generation. |
| M&A, asset sale, contract, restructuring | Counterparty, consideration, asset/business affected, rationale, funding, expected operating effect. |
| Tender offer / go-private | Offeror, offer price, ownership objective, participation being optional, practical shareholder choice. |

The existing PP six-point check remains in the scoring rubric. This design only makes its relevant factual conclusion readable to an alert recipient.

## Error handling

- Missing `what_happened` or `why_it_matters` is a caller error. `render_alert()` accesses them by key, matching existing required-field behavior for `deal`, `owner_intent`, and `owner_why`.
- Empty explanation strings render their headings with a blank body. The wake-up agent instructions prohibit that for posted alerts.
- Longer multiline explanations are passed through unchanged. Discord applies its normal message limit; the agent must keep each explanation to 2 to 4 short sentences.
- Existing `post_discord()` error handling and chart attachment behavior remain unchanged.

## Tests

Modify `idx-ca-watch/tests/test_scan.py` with focused renderer tests:

1. Update `_alert_fields()` to use `what_happened` and `why_it_matters`; remove the retired keys.
2. Replace `test_render_alert_exact` with `test_render_alert_explained_header_and_blocks`.
   - Assert the exact first line is `## **ANTM** · Rights issue (HMETD) · `8/10` 🟢`.
   - Assert the emoji is right-aligned at the end of the heading.
   - Assert `What happened:` and `Why it may matter:` each render on their own heading line with the supplied multiline explanation directly below.
   - Assert Fundamentals, Tech, and PDF blocks remain.
3. Update `test_render_alert_score_float`: assert the first line contains the correctly formatted score immediately before the right-aligned emoji, for both `7.5` and `8.0`.
4. Add `test_render_alert_does_not_accept_retired_explanation_fields`.
   - Omit `what_happened` / `why_it_matters` while supplying only retired keys.
   - Assert `KeyError`, proving the clean cutover has no compatibility alias.
5. Preserve and run all existing `idx-ca-watch` tests, especially scoring/posting and chart behavior tests.

## Documentation

Update `idx-ca-watch/SKILL.md`:

- Replace `deal`, `owner_intent`, and `owner_why` in the `post-alert` JSON example with `what_happened` and `why_it_matters`.
- Replace one-line / never-paragraph instructions with the 2 to 4 short sentence contract.
- Update the rendered example to use the exact H2 header and renamed sections.
- Add the fact, implication, uncertainty rules and corporate-action-type checklist in a compact form.
- Preserve all scoring, posting-gate, record-score, channel, dry-run, and no-extra-emoji instructions.

## Deployment and verification

Development home: `~/Documents/Projects/Hermes/idx-ca-watch/`

Deploy source scripts:

```bash
cd ~/Documents/Projects/Hermes
./deploy.sh idx-ca-watch
```

The deploy helper syncs `bin/` to `vps:.agents/skills/idx-ca-watch/bin`. Sync the modified skill instruction separately:

```bash
rsync -a ~/Documents/Projects/Hermes/idx-ca-watch/SKILL.md vps:.agents/skills/idx-ca-watch/SKILL.md
```

Run local tests using the project convention:

```bash
cd ~/Documents/Projects/Hermes/idx-ca-watch
python3 -m pytest tests/ -v
```

On the VPS, invoke the renderer without posting:

```bash
IDX_CA_WATCH_NO_POST=1 python ~/.agents/skills/idx-ca-watch/bin/scan.py post-alert --json '{
  "emoji":"🟢",
  "ticker":"ANTM",
  "ca_label":"Rights issue (HMETD)",
  "score":8,
  "what_happened":"ANTM plans a rights issue at Rp820 per share. Existing holders may exercise or sell their HMETD, while non-participants are diluted.",
  "why_it_matters":"The stated use of funds is expansion. If the project adds recurring earnings and execution is on plan, it could support future profits, but the filing does not prove future price support.",
  "metrics":{},
  "health":{},
  "pdf_url":"https://example.com/disclosure.pdf"
}'
```

Verify the dry-run output has:

- H2 header with ticker first and emoji last.
- `What happened:` and `Why it may matter:` headings with readable multi-sentence explanations.
- Existing Fundamentals, Tech, and PDF sections.
- No retired `Deal:` / `Owner:` labels and no old explanation keys.
