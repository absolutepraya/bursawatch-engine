# idx-ca-watch notification upgrade - Design

**Date:** 2026-06-27
**Status:** Approved design, ready for implementation plan
**Scope:** 5 changes to the `idx-ca-watch` Hermes cron (alert channel `1517510484025151538`, cron `b49432a194d1`). Dev home `~/Documents/Projects/Hermes/idx-ca-watch/`; deploy with `./deploy.sh idx-ca-watch`; verify on the VPS (IDX fetch is Cloudflare-gated off non-datacenter IPs, so the fetch/PDF/cron-deliver parts are VPS-only to verify).

**Problem.** Today's alert is a dense, wrapper-wrapped wall of text:
```
Cronjob Response: idx-ca-watch
(job_id: b49432a194d1)
-------------
🟡 LSIP · 4/8 (5.0) · RUPST press release
...
Lenses: owner+1 · purpose+1 · fund+0 · flow/tech+2   (gates: thesis✗ confirm✓)
⚠️ Bukan ajakan beli, DYOR, PDF: ...
To stop or manage this job, send me a new message ...
```
Three faults: (1) the `Cronjob Response / job_id / -------- / To stop or manage this job` cruft is auto-added by Hermes when it delivers an *agent-job* reply (us-etf-dca is `no_agent` and posts directly, so it never gets wrapped); (2) the body has no Discord markdown; (3) low-substance alerts fire because the scanner only reads the IDX cover PDF and has almost no fundamental read on the company.

**Output principle (overrides everything below):** gather rich inputs, post a SHORT message. The agent digests yfinance + attachment PDFs + the financial-statement PDF, then emits one tight line per section. Never paragraphs.

---

## Change 1: Kill the wrapper (post from the skill, not the agent reply)

**Goal:** remove the `Cronjob Response / job_id / -------- / To stop or manage this job` framing.

- New deterministic **`scan.py post-alert`** subcommand renders the markdown template (Change 2) and posts it directly to `1517510484025151538` via the existing `post_discord()` (already supports markdown + chart attachment). No wrapper, full format control.
- The agent's flow when woken with `items[]`: for each item, decide the score, then either call `post-alert` (if it clears the bar, Change 3) or skip the post; always call `record-score`; finally emit a terse one-line status.
- **Stop the double-post.** The agent reply is still delivered by the cron. Retarget so it does not land in the alert channel:
  - Preferred: set the cron `deliver` to none/empty if Hermes supports it for an agent job (verify `hermes cron edit --help` on the VPS). Then nothing extra posts; the skill owns all output.
  - Fallback: retarget `deliver` to the heartbeat channel `1505162000420835388` (#hermes). The agent's wrapped one-line status then lands in the firehose, which is acceptable (it only fires when there are flagged items, not every hour).
- Format ownership: the markdown TEMPLATE lives in `post-alert` (deterministic, drift-free). The agent supplies only content fields; deterministic fields (metrics, fundamentals, chart path, PDF url) come from the item payload. Exact arg/JSON interface for `post-alert` is defined in the plan.

## Change 2: Markdown alert format (simplified output)

**Goal:** read like the us-etf-dca alerts (bold ticker, backtick values, labeled sections, blank lines), but compressed.

Canonical template (a firing 🟢; every value is one token, the whole `Fundamentals` line is the distilled result of reading yfinance + the financial-statement PDF):
```
🟢 **ANTM** · Rights issue (HMETD) · `8.0/10` (raw `6/8`)

**Deal:** 1:5 HMETD at `Rp1,850` (12% under 25-day VWAP), standby buyer MIND ID, proceeds fund nickel-smelter capex.
**Owner:** `BULLISH`, SOE controller funding accretive expansion, not a rescue.
**Fundamentals:** healthy ✅ · ROE `14%` · net cash · margin `21%` · NI +YoY

**Tech:** above MA200 ✅ · RSI `58` · liq `Rp180B/d` · ATR `3.4%`
**Score:** owner `+2` · purpose `+2` · fund `+1` · flow/tech `+1`  (thesis ✅ · confirm ✅)

⚠️ Bukan ajakan beli, DYOR · [PDF](<pdf_url>)
```
Then the chart attached underneath.

Rules:
- Confidence leads with `/10`, raw `/8` in parens (`8.0/10 (raw 6/8)`).
- `Deal`, `Owner`, `Fundamentals` are each ONE line (wrap is fine, but no multi-sentence paragraphs). `Owner` is `BULLISH/BEARISH/NEUTRAL` + a single clause.
- `Score` line kept but readable: backtick lens points + `thesis ✅/❌ · confirm ✅/❌`.
- Emoji are fine here (this is a Discord alert channel, not the blog).
- No `RUPST press release` repeated in both the header and the body; the CA label appears once in the header.
- PDF as a markdown link, not a bare URL.

## Change 3: Higher posting bar

**Goal:** stop neutral/no-thesis filings (like the LSIP `4/8`, `thesis ❌`) from firing.

Gating (applied by the agent per the rubric in SKILL.md):
- 🟢 (raw 6-8): always post.
- 🟡 (raw 4-5): post ONLY if the thesis floor holds (owner + purpose >= 3 of 4). Otherwise suppress.
- 🔴 (raw 0-3): suppress.
- Suppressed items are still `record-score`d (so they do not re-escalate) and still counted in the heartbeat (`flagged` count). Optionally the heartbeat can add a `suppressed` count for visibility.

## Change 4: Open all CA attachments (deal substance)

**Goal:** the alert's `Deal` line carries real ratio / price / use-of-funds, not "no detail in extracted text".

- `scan.py` already collects every attachment URL in `Disclosure.pdf_urls`, but `build_item_payload` extracts only `pdf_urls[0]` (the IDX cover). Extend extraction to ALL attachments of the CA disclosure.
- Per-file: extract more pages (cover pages are short; letters run longer). Prepend a `[filename]` header to each chunk so the agent can attribute detail to a source.
- Total budget generous (gpt-5.5 handles it); cap the concatenation (target ~20k chars for the CA attachments) so a stray huge attachment cannot blow context.

## Change 5: Financial health read (yfinance + laporan keuangan PDF)

**Goal:** the agent knows whether the company is financially healthy, so a CA on a rotting balance sheet is marked down and one on a healthy grower gets credit. Confirmed feasible: yfinance returns rich `.JK` fundamentals, and the IDX `GetFinancialReport` endpoint returns the real financial-statement PDF from the datacenter IP.

- **Health block (deterministic, from yfinance):** add to `market_metrics` (or a sibling `financial_health(ticker)`): ROE, net margin, debt/equity, current ratio, operating CF / FCF sign, net-cash vs debt, revenue YoY trend, net-income YoY trend (from `info` + `quarterly_financials`). Reduce to a compact dict + a rule-based verdict `healthy ✅ / mixed ⚠️ / weak ❌`.
- **Raw laporan keuangan PDF (best-effort):** fetch the latest report via `GetFinancialReport?...&kodeEmiten=<T>&reportType=rdf&year=<Y>&periode=<P>`, pick the `FinancialStatements...pdf` attachment (full url = `https://www.idx.co.id` + `File_Path`), extract a few key pages, cap tightly. Pass as extra agent context for nuances yfinance misses (going-concern notes, one-offs). If it fails (no report, Cloudflare, parse error), fall back to the yfinance-only Health block. It must NEVER block the alert.
- **Distress caps the score.** If the Health block is `weak ❌` (e.g. negative equity, negative trailing NI, NI collapse > ~50% YoY, current ratio < 1 with material debt) or the PDF text flags going-concern, the agent caps the alert (🟡 max, or 🔴 if severe) regardless of the deal. This is the financial-health veto, alongside the existing hard disqualifiers.
- **Rubric weight unchanged.** Max stays 8 (so `confidence = score/8*10` and the 🟢/🟡 raw thresholds are untouched); the fundamental lens stays 0-1 but is now data-driven, and the distress cap gives health real teeth without a rebalance. (If we later want fundamentals to score higher, that is a separate rubric change.)
- **Output stays simplified:** all of this collapses into the single `Fundamentals` line in the alert.

---

## Files touched

| File | Changes |
|---|---|
| Hermes cron (VPS) | retarget `idx-ca-watch` `deliver` (none, else #hermes) so the agent reply stops double-posting |
| `idx-ca-watch/bin/scan.py` | `post-alert` subcommand (Change 1) + markdown template (Change 2); all-attachment extraction (Change 4); `financial_health()` yfinance block + best-effort `GetFinancialReport` PDF fetch + distress signal (Change 5); optional `suppressed` heartbeat count (Change 3) |
| `idx-ca-watch/SKILL.md` | new alert template + simplified-output rule (Change 2); higher posting bar gating (Change 3); financial-health into the fundamental lens + distress cap (Change 5); agent flow uses `post-alert` then `record-score` (Change 1) |
| `idx-ca-watch/DEPLOY.md` | note the deliver retarget; correct stale dev-home path (`~/Documents/Projects/idx-ca-watch` -> `~/Documents/Projects/Hermes/idx-ca-watch`) |
| `idx-ca-watch/tests/test_scan.py` | format render, gating (suppress 🟡 thesis❌), all-attachment extraction, financial_health verdict + distress cap, post-alert rendering |

## Testing
- Logic tests run locally with mocked fetch (the established idx-ca pattern; IDX fetch itself only works on the VPS). Cover: `post-alert` renders the exact template; gating suppresses 🟡 thesis❌ and posts 🟢; all-attachment extraction concatenates with `[filename]` headers and respects the cap; `financial_health()` returns the right verdict and the distress cap triggers on a weak balance sheet.
- VPS verify (datacenter IP): `GetFinancialReport` fetch + PDF extract for a real ticker; one forced dry-run alert (`IDX_CA_WATCH_NO_POST=1`) shows the new wrapper-free markdown; one real `post-alert` lands clean in `1517510484025151538`; confirm no wrapped duplicate after the deliver retarget.

## Deploy / verify
- Edit dev home -> `./deploy.sh idx-ca-watch` -> on the VPS retarget the cron deliver -> forced dry-run + one real alert to confirm format and no double-post -> `~/.dotfiles/sync.sh` mirrors the skill back to dotfiles.
- Dev home `~/Documents/Projects/Hermes/` is not a git repo (spec saved, not committed), consistent with the other cron docs there.

## Risks / notes
- **VPS-only verification.** IDX (announcements + GetFinancialReport) is Cloudflare-gated off non-datacenter IPs; only the deterministic logic is locally testable.
- **Per-item cost/time.** Opening all CA attachments + a financial-statement PDF + yfinance per item is heavier. idx-ca is hourly with few items, so acceptable; keep the financial-report fetch best-effort and time-bounded, and watch `cron.script_timeout_seconds`.
- **Deliver-none support.** If Hermes cannot deliver-none for an agent job, use the #hermes fallback; either way the skill owns the alert-channel output.
- **yfinance coverage.** Some thin tickers lack fundamentals; the Health block degrades to `n/a` and the agent leans on the disclosure text. Alerts already require a liquid name, so coverage mostly lines up.
