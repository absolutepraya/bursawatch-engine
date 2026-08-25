# idx-ca-watch explained alerts implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make IDX corporate-action alerts readable to non-specialists with an H2 header, right-aligned score emoji, and clear `What happened:` / `Why it may matter:` explanations.

**Architecture:** `render_alert()` receives a clean new payload contract, `what_happened` and `why_it_matters`, and preserves multiline explanations verbatim. The wake-up agent is the sole producer, so `SKILL.md` migrates the JSON example and writing rules in the same cutover. Scanning, scoring, gates, metrics, chart attachment, and Discord posting remain untouched.

**Tech Stack:** Python 3, pytest, Discord webhook posting through existing `scan.py`, VPS deployment via rsync.

## Global Constraints

- No changes to scan fetch, deduplication, classification, scoring, alert gates, financial-distress cap, technical metrics, chart generation, attachments, channel IDs, or scheduling.
- No changes to the 0 to 10 score rubric, 🟢/🟡 posting rules, hard disqualifiers, or `record-score` workflow.
- Exactly one emoji in an alert: the existing score emoji at the far right of the H2 header.
- New header format: `## **{ticker}** · {ca_label} · `{score:g}/10` {emoji}`.
- Clean cutover only. Retire `deal`, `owner_intent`, and `owner_why`; do not support aliases or fallback parsing.
- New required fields: `what_happened`, `why_it_matters`.
- `what_happened` and `why_it_matters` may contain newlines. The renderer must pass their text through unchanged beneath their labels.
- Alert writing uses 2 to 4 short sentences per explanation, clear Indonesian/English plain language as appropriate to the source facts, and separates filing facts from qualified inference and uncertainty.
- Never assert hidden control, proxies, manipulation, wash sales, markup, price support, future rerating, or owner intent as fact without disclosure or independently verified evidence.
- Project root `~/Documents/Projects/Hermes/` is not a git repo. Do not initialize Git or commit.
- Test command: `cd ~/Documents/Projects/Hermes/idx-ca-watch && python3 -m pytest tests/ -v`.
- Deploy command syncs only `bin/`: `cd ~/Documents/Projects/Hermes && ./deploy.sh idx-ca-watch`. Sync modified `SKILL.md` separately with rsync.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `idx-ca-watch/bin/scan.py` | Modify | Render the H2 header and new explanation payload fields only. |
| `idx-ca-watch/tests/test_scan.py` | Modify | Migrate exact renderer fixture and assertions to the new contract. |
| `idx-ca-watch/SKILL.md` | Modify | Give wake-up agent the new payload contract, output shape, and evidence-first explanation rules. |

---

### Task 1: Migrate the renderer to the explained-alert contract

**Files:**
- Modify: `idx-ca-watch/tests/test_scan.py:291-350`
- Modify: `idx-ca-watch/bin/scan.py:307-318`

**Interfaces:**
- Consumes:
  ```python
  {
      "emoji": str,
      "ticker": str,
      "ca_label": str,
      "score": int | float,
      "what_happened": str,
      "why_it_matters": str,
      "metrics": dict,
      "health": dict,
      "pdf_url": str,
      "chart_path": str | None,
  }
  ```
- Produces: `render_alert(f: dict) -> str` with H2 first line, multiline `What happened:` and `Why it may matter:` blocks, then the unchanged Fundamentals, Tech, and PDF blocks.
- Rejects: A payload containing only `deal`, `owner_intent`, and `owner_why` must raise `KeyError`.

- [ ] **Step 1: Replace the renderer fixture with the new fields**

In `idx-ca-watch/tests/test_scan.py`, replace the body of `_alert_fields()` with:

```python
def _alert_fields():
    return {
        "emoji": "🟢", "ticker": "ANTM", "ca_label": "Rights issue (HMETD)",
        "score": 8,
        "what_happened": (
            "ANTM plans a 1:5 rights issue at Rp1,850 per share. "
            "Existing holders may exercise or sell their HMETD, while non-participants are diluted."
        ),
        "why_it_matters": (
            "The disclosed SOE controller supports funding for expansion. "
            "If the project adds recurring earnings and execution is on plan, it could support future profits, but it does not prove future price support."
        ),
        "metrics": {"above_ma200": True, "rsi": 58.0, "avg_value_idr": 1.8e11, "atr_pct": 3.4},
        "health": {"roe": 0.14, "net_margin": 0.21, "net_cash": True, "current_ratio": 2.5,
                   "fcf_pos": True, "ni_ttm": 1e12, "ni_yoy": 0.05},
        "pdf_url": "https://www.idx.co.id/StaticData/x/y.pdf", "chart_path": "/tmp/c.png",
    }
```

- [ ] **Step 2: Replace the exact-renderer test with failing requirements**

Replace `test_render_alert_exact()` with:

```python
def test_render_alert_explained_header_and_blocks():
    expected = (
        "## **ANTM** · Rights issue (HMETD) · `8/10` 🟢\n"
        "\n"
        "**What happened:**\n"
        "ANTM plans a 1:5 rights issue at Rp1,850 per share. Existing holders may exercise or sell their HMETD, while non-participants are diluted.\n"
        "\n"
        "**Why it may matter:**\n"
        "The disclosed SOE controller supports funding for expansion. If the project adds recurring earnings and execution is on plan, it could support future profits, but it does not prove future price support.\n"
        "\n"
        "**Fundamentals:** healthy\n"
        "- ROE `14%`\n"
        "- net cash\n"
        "- margin `21%`\n"
        "- NI `+5%`\n"
        "\n"
        "**Tech:**\n"
        "- above MA200\n"
        "- RSI `58`\n"
        "- liq `Rp180.0B/d`\n"
        "- ATR `3.4%`\n"
        "\n"
        "PDF: https://www.idx.co.id/StaticData/x/y.pdf"
    )
    out = scan.render_alert(_alert_fields())
    assert out == expected
    assert out.splitlines()[0] == "## **ANTM** · Rights issue (HMETD) · `8/10` 🟢"
    assert "Cronjob Response" not in out and "job_id" not in out
    assert "\u2014" not in out
    assert "raw" not in out and "DYOR" not in out and "[PDF]" not in out
```

Add this clean-cutover test immediately after it:

```python
def test_render_alert_does_not_accept_retired_explanation_fields():
    fields = _alert_fields()
    fields.pop("what_happened")
    fields.pop("why_it_matters")
    fields.update({
        "deal": "legacy deal",
        "owner_intent": "BULLISH",
        "owner_why": "legacy owner reason",
    })
    with pytest.raises(KeyError):
        scan.render_alert(fields)
```

Add `import pytest` next to the existing test imports if it is not already imported.

- [ ] **Step 3: Update the score and CLI tests to fail against the old output**

Replace `test_render_alert_score_float()` with:

```python
def test_render_alert_score_float():
    f = _alert_fields()
    f["score"] = 7.5
    assert scan.render_alert(f).splitlines()[0] == "## **ANTM** · Rights issue (HMETD) · `7.5/10` 🟢"
    f["score"] = 8.0
    assert scan.render_alert(f).splitlines()[0] == "## **ANTM** · Rights issue (HMETD) · `8/10` 🟢"
```

In `test_post_alert_dry_run()`, replace the final assertion:

```python
    assert captured["content"].startswith("## **ANTM** · Rights issue (HMETD) · `8/10` 🟢")
```

- [ ] **Step 4: Run focused tests and verify they fail**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-ca-watch
python3 -m pytest tests/test_scan.py -v -k "render_alert or post_alert_dry_run"
```

Expected: FAIL. The current renderer reads retired keys, prints the emoji first, uses no H2 marker, and labels blocks `Deal:` / `Owner:`.

- [ ] **Step 5: Replace the renderer implementation**

In `idx-ca-watch/bin/scan.py`, replace `render_alert()` at lines 307-318 with:

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

This code intentionally accesses `what_happened` and `why_it_matters` directly. Do not use `.get()` or accept retired aliases.

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-ca-watch
python3 -m pytest tests/test_scan.py -v -k "render_alert or post_alert_dry_run"
```

Expected: PASS, including exact output, right-aligned emoji, float score formatting, `KeyError` for retired-only payloads, and unmodified post-alert channel / chart path behavior.

---

### Task 2: Replace wake-up instructions with reader-first corporate-action explanations

**Files:**
- Modify: `idx-ca-watch/SKILL.md:77-118`

**Interfaces:**
- Produces: wake-up agent instructions that emit the Task 1 payload contract and write bounded, evidence-first explanations.
- Consumes: unchanged item fields: `pdf_text`, `fin_report_text`, `health`, `chart_path`, `metrics`, `ca_type`, `red_flags`, `ticker`, `title`.

- [ ] **Step 1: Replace the post example JSON contract**

In the `How to post` section, replace the old fields:

```json
"deal":"<ONE line: ratio / price vs VWAP / standby buyer / use of funds>",
"owner_intent":"BULLISH","owner_why":"<ONE clause>",
```

with:

```json
"what_happened":"<2-4 short sentences: filing facts, material terms, and shareholder mechanics>",
"why_it_matters":"<2-4 short sentences: verified context, qualified economic implication, and key uncertainty>",
```

Keep the `emoji`, `ticker`, `ca_label`, `score`, `metrics`, `health`, `pdf_url`, and `chart_path` fields intact.

- [ ] **Step 2: Replace concise one-line instructions with the exact writing rules**

Replace the paragraph that currently says to keep `deal` and `owner_why` to one line and to never use paragraphs with the following text:

```md
Copy `metrics` and `health` verbatim from the item (do NOT retype numbers); the skill formats them. Write `what_happened` and `why_it_matters` in 2-4 short sentences each. Keep each explanation plain-English, factual, and compact. The header is the ONLY emoji and must be an H2 with the emoji at the far right. Do NOT add a DYOR/disclaimer footer.

`What happened:` starts with verified disclosure facts. Explain the action and material terms, then the practical shareholder effect. Explain jargon on first use, for example: "rights issue, meaning existing shareholders can buy newly issued shares." For rights issues, cover ratio, exercise price, discount when supplied, stated use of funds, standby buyer, holder choice, and dilution. For PP, cover recipient, price/discount, size, use of funds, dilution, and any disclosed affiliate or control effect. For buybacks, dividends, M&A, asset sales, contracts, restructurings, and tender offers, explain the material terms and the practical shareholder effect.

`Why it may matter:` starts with disclosed or independently verified owner, controller, affiliate, group, buyer, or counterparty context. Then connect the action to a specific economic path, such as recurring net income, margin, capacity, backlog, operating cash flow, debt reduction, liquidity, or capital structure. State the main risk or uncertainty. Treat unproven group/proxy links as inference, never fact. Never claim hidden control, manipulation, wash sales, markup, price support, future rerating, or owner intent as fact. If evidence is insufficient, say: "The filing does not establish a clear owner incentive, so this is not a standalone bullish catalyst."
```

- [ ] **Step 3: Replace the rendered-shape reference**

Replace the old reference output with:

```md
## **ANTM** · Rights issue (HMETD) · `8/10` 🟢

**What happened:**
ANTM plans a rights issue at Rp1,850 per share. Existing holders may exercise or sell their HMETD, while non-participants are diluted.

**Why it may matter:**
The disclosed SOE controller supports the stated expansion funding. If the project adds recurring earnings and execution is on plan, it could support future profits, but it does not prove future price support.

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

Keep the nearby instruction that this is a factual research signal, not Yanto banter, and preserve the `record-score` workflow below it unchanged.

- [ ] **Step 4: Verify retired vocabulary is gone from active instructions**

Run:

```bash
grep -nE '"deal"|owner_intent|owner_why|\*\*Deal:\*\*|\*\*Owner:\*\*|never paragraphs' ~/Documents/Projects/Hermes/idx-ca-watch/SKILL.md
```

Expected: no output.

Then run:

```bash
grep -nE 'what_happened|why_it_matters|What happened|Why it may matter|H2' ~/Documents/Projects/Hermes/idx-ca-watch/SKILL.md
```

Expected: the new JSON fields, both labels, and the H2 header instruction are present.

---

### Task 3: Full verification and VPS deployment

**Files:**
- No source changes. Run tests and deploy the completed work.

- [ ] **Step 1: Run the full local test suite**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-ca-watch
python3 -m pytest tests/ -v
```

Expected: all existing tests and the migrated renderer tests PASS.

- [ ] **Step 2: Deploy the updated runtime script**

Run:

```bash
cd ~/Documents/Projects/Hermes
./deploy.sh idx-ca-watch
```

Expected: `deployed idx-ca-watch/bin/ → VPS`.

- [ ] **Step 3: Sync the updated instruction file**

Run:

```bash
rsync -a ~/Documents/Projects/Hermes/idx-ca-watch/SKILL.md vps:.agents/skills/idx-ca-watch/SKILL.md
```

Expected: rsync exits successfully.

- [ ] **Step 4: Run VPS renderer smoke test without posting**

Run:

```bash
ssh vps 'IDX_CA_WATCH_NO_POST=1 python ~/.agents/skills/idx-ca-watch/bin/scan.py post-alert --json '"'"'{
  "emoji":"🟢",
  "ticker":"ANTM",
  "ca_label":"Rights issue (HMETD)",
  "score":8,
  "what_happened":"ANTM plans a rights issue at Rp820 per share. Existing holders may exercise or sell their HMETD, while non-participants are diluted.",
  "why_it_matters":"The stated use of funds is expansion. If the project adds recurring earnings and execution is on plan, it could support future profits, but the filing does not prove future price support.",
  "metrics":{},
  "health":{},
  "pdf_url":"https://example.com/disclosure.pdf"
}'"'"''
```

Expected dry-run output contains:

```md
## **ANTM** · Rights issue (HMETD) · `8/10` 🟢

**What happened:**
ANTM plans a rights issue at Rp820 per share.

**Why it may matter:**
The stated use of funds is expansion.
```

and still contains `**Fundamentals:**`, `**Tech:**`, and `PDF: https://example.com/disclosure.pdf`.

- [ ] **Step 5: Confirm no operational behavior changed**

The smoke test uses `post-alert` only and `IDX_CA_WATCH_NO_POST=1`, so it cannot post to Discord. Confirm the command returns `posted` in dry-run mode and no message is sent. No cron restart is required because the cron invokes `~/.hermes/scripts/idx-ca-watch.sh`, which loads the deployed script on each run.
