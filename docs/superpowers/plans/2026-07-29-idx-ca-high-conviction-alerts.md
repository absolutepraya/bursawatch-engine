# IDX CA High-Conviction Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `idx-ca-watch` into a Bahasa Indonesia, high-conviction corporate-action feed that posts only fundamental or corporate-action catalysts scoring 7 to 10.

**Architecture:** Keep IDX fetching, deduplication, red-flag filtering, state, heartbeat, chart generation, and Discord delivery deterministic in `scan.py`. Remove all technical data from the candidate payload and alert body. The agent supplies a named four-component fundamental/corporate-action score; `scan.py` validates the mandatory 7+ gates before it can render or post an alert.

**Tech Stack:** Python 3.11, pytest, yfinance, IDX HTTP endpoints, Discord REST, Hermes cron, Bash wrapper.

## Global Constraints

- Develop only in `idx-ca-watch/bin/` and `idx-ca-watch/tests/`, never in the VPS runtime or dotfiles mirror.
- Do not add, remove, reschedule, or retarget a cron.
- Do not reset, edit, replay, or backfill production state or historical Discord messages.
- Do not score or display RSI, moving averages, ATR, volume, price momentum, liquidity, or any other technical indicator.
- Keep the chart as a Discord attachment only. Do not make a technical claim from it.
- Use Indonesian in the rendered alert, with H3 header `### <:idx:1531974045266874499> TICKER (Company name)`.
- Post only scores 7 to 10. A valid published score needs materiality at least 2, fundamental impact at least 2, execution certainty at least 1, and no blocking red flag or financial-distress verdict.
- Use the shared test interpreter: `../.venv/bin/python -m pytest -q` from `idx-ca-watch/`.
- Deploy executable changes only with `./deploy.sh idx-ca-watch <file>` after local and VPS checksums are compared. Sync `SKILL.md` separately after its checksum comparison.
- This workspace has no Git repository. Do not run `git add` or `git commit`; record test and deployment evidence in the handoff instead.

---

## File structure

| File | Responsibility |
| --- | --- |
| `idx-ca-watch/bin/scan.py` | Candidate payload construction, fundamental context, publish-gate validation, Indonesian rendering, chart attachment, deterministic Discord posting |
| `idx-ca-watch/SKILL.md` | Agent scoring contract, suppress-and-record instructions, Indonesian summary rules, and exact `post-alert` JSON shape |
| `idx-ca-watch/tests/test_scan.py` | Regression tests for technical-data removal, high-conviction validation, rendering, and no-post alert dispatch |
| `docs/superpowers/specs/2026-07-29-idx-ca-high-conviction-alerts-design.md` | Approved source-of-truth product contract, already written. Do not alter unless the user changes the design |

## Task 1: Remove technical scoring inputs and enrich fundamental context

**Files:**
- Modify: `idx-ca-watch/bin/scan.py:13-15, 201-242, 307-343, 527-560, 563-715`
- Modify: `idx-ca-watch/tests/test_scan.py:118-130, 185-205, 219-253`

**Interfaces:**
- Consumes: `Disclosure`, `Classification`, `financial_health(ticker)` and `render_chart(ticker)`.
- Produces: `build_item_payload(d, c, health, pdf_text, fin_report_text, chart_path) -> dict` with `company_name`, `fundamental_context`, `health`, and no `metrics` key.
- Produces: `disqualified(red_flags: list[str]) -> tuple[bool, str | None]` with no market-data argument.

- [ ] **Step 1: Write failing scanner-boundary tests**

Replace the current run fixtures that monkeypatch `market_metrics` with a guard that raises if it is called. Assert that a valid new corporate action still wakes the agent, retains `health`, includes a chart path, and omits `metrics`.

```python
def test_run_payload_has_no_technical_metrics(tmp_state, monkeypatch):
    seed = scan.load_state()
    seed["seen"]["old"] = {"ts": "2026-07-29T08:00:00"}
    scan.save_state(seed)
    disclosure = _mk(title="Keterbukaan Informasi Rights Issue HMETD", ticker="BREN")
    disclosure.id2 = "ri-no-tech"
    disclosure.pdf_urls = ["https://example.test/disclosure.pdf"]
    monkeypatch.setattr(scan, "fetch_recent", lambda state: [disclosure])
    monkeypatch.setattr(scan, "market_metrics", lambda ticker: (_ for _ in ()).throw(AssertionError("technical fetch is forbidden")), raising=False)
    monkeypatch.setattr(scan, "financial_health", lambda ticker: {"company_name": "PT Baren Energi Tbk", "market_cap": 2_000_000_000_000, "total_revenue": 1_000_000_000_000, "total_assets": 3_000_000_000_000, "shares_outstanding": 1_000_000_000, "roe": 0.2, "net_cash": True, "ni_ttm": 1_000_000_000})
    monkeypatch.setattr(scan, "fetch_attachments_text", lambda *args, **kwargs: "Nilai transaksi Rp300 miliar")
    monkeypatch.setattr(scan, "fetch_financial_report_text", lambda *args, **kwargs: "Pendapatan tahunan Rp1 triliun")
    monkeypatch.setattr(scan, "render_chart", lambda ticker: "/tmp/chart.png")
    monkeypatch.setattr(scan, "post_discord", lambda *args, **kwargs: True)

    result = scan.run()

    assert result["wakeAgent"] is True
    item = result["items"][0]
    assert item["company_name"] == "PT Baren Energi Tbk"
    assert item["chart_path"] == "/tmp/chart.png"
    assert "metrics" not in item
```

Add a direct red-flag test for the narrowed interface:

```python
def test_disqualified_rejects_uma_without_market_metrics():
    assert scan.disqualified(["uma"]) == (True, "uma")
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_run_payload_has_no_technical_metrics tests/test_scan.py::test_disqualified_rejects_uma_without_market_metrics
```

Expected: FAIL because `run()` invokes `market_metrics`, `disqualified()` still requires a metrics argument, and payloads lack `company_name`.

- [ ] **Step 3: Implement the minimal technical-data removal**

In `scan.py`:

1. Remove `SCORE_MAX`, `LIQUIDITY_MIN_IDR`, `ATR_MIN_PCT`, `market_metrics()`, `tech_stats()`, `passes_gates()`, and all use of their results.
2. Set `DISQUALIFY_FLAGS = {"uma", "suspend", "fca_ppk", "pkpu"}` and implement:

```python
def disqualified(red_flags: list[str]) -> tuple[bool, str | None]:
    for flag in red_flags:
        if flag in DISQUALIFY_FLAGS:
            return True, flag
    return False, None
```

3. Extend `financial_health()` to include the non-technical context below from `yfinance.Ticker(...).info`, preserving `None` when a key is absent:

```python
out = {
    "company_name": None,
    "market_cap": None,
    "total_revenue": None,
    "total_assets": None,
    "shares_outstanding": None,
    "roe": None,
    "net_margin": None,
    "net_cash": None,
    "current_ratio": None,
    "fcf_pos": None,
    "ni_ttm": None,
    "ni_yoy": None,
    "rev_yoy": None,
}
out["company_name"] = info.get("longName") or info.get("shortName")
out["market_cap"] = info.get("marketCap")
out["total_revenue"] = info.get("totalRevenue")
out["total_assets"] = info.get("totalAssets")
out["shares_outstanding"] = info.get("sharesOutstanding")
```

4. Build `fundamental_context` from the five contextual keys and choose `company_name` from `health["company_name"]`, falling back to the ticker only when the provider has no name.
5. Change `build_item_payload()` to accept no metrics argument and return `company_name`, `fundamental_context`, `health`, source text, and `chart_path`, but no `metrics`.
6. In `run()`, call `disqualified(c.red_flags)`, fetch the disclosure and financial context, then call `render_chart(d.ticker)` independently of technical market data.

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_run_payload_has_no_technical_metrics tests/test_scan.py::test_disqualified_rejects_uma_without_market_metrics tests/test_scan.py::test_findings_reescalate_until_recorded
```

Expected: PASS. The re-escalation test must be updated to use the new payload interface and must still prove that an unrecorded candidate reappears.

- [ ] **Step 5: Inspect the diff and record the local-only checkpoint**

Run:

```bash
git diff --no-index /dev/null idx-ca-watch/bin/scan.py >/dev/null 2>&1 || true
cd idx-ca-watch && rg -n 'market_metrics|tech_stats|passes_gates|vol_vs_20d|avg_value_idr' bin/scan.py
```

Expected: the search returns no matches. The chart command may still include its existing visual indicators, but no technical data may feed candidate selection, scoring, or rendered text. Do not commit because this workspace has no Git repository.

## Task 2: Enforce the 7+ fundamental and corporate-action publication gate

**Files:**
- Modify: `idx-ca-watch/bin/scan.py:257-331`
- Modify: `idx-ca-watch/tests/test_scan.py:291-375`

**Interfaces:**
- Consumes: an agent-supplied `score_components` object with integer keys `materiality`, `fundamental_impact`, `structure_alignment`, and `execution_certainty`; `score`, `red_flags`, and `health`.
- Produces: `validate_publication_fields(fields: dict) -> None`, which raises `ValueError` for malformed or ineligible alerts and returns normally only for valid 7 to 10 alerts.
- Produces: `publication_score(components: dict[str, int]) -> int`, used by the validator and renderer to prevent an arbitrary total from differing from its components.

- [ ] **Step 1: Write failing gate tests**

Add this helper and tests beside the existing alert tests:

```python
def _high_conviction_fields():
    return {
        "ticker": "ANTM",
        "company_name": "PT Aneka Tambang Tbk",
        "ca_label": "Pembelian saham oleh pengendali",
        "summary": "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.",
        "score_components": {
            "materiality": 2,
            "fundamental_impact": 2,
            "structure_alignment": 2,
            "execution_certainty": 1,
        },
        "score": 7,
        "red_flags": [],
        "health": {"ni_ttm": 1_000_000_000, "current_ratio": 2.0, "net_cash": True},
        "fundamental_context": {"market_cap": 2_000_000_000_000, "total_revenue": 1_000_000_000_000, "total_assets": 3_000_000_000_000, "shares_outstanding": 1_000_000_000},
        "pdf_url": "https://www.idx.co.id/StaticData/x/y.pdf",
        "chart_path": "/tmp/c.png",
    }


def test_validate_publication_fields_accepts_exact_score_seven():
    scan.validate_publication_fields(_high_conviction_fields())


def test_validate_publication_fields_rejects_score_six_even_when_components_match():
    fields = _high_conviction_fields()
    fields["score_components"] = {"materiality": 1, "fundamental_impact": 2, "structure_alignment": 2, "execution_certainty": 1}
    fields["score"] = 6
    with pytest.raises(ValueError, match="published score"):
        scan.validate_publication_fields(fields)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"score": 6}, "must equal component total"),
        ({"score_components": {"materiality": 1, "fundamental_impact": 3, "structure_alignment": 2, "execution_certainty": 1}, "score": 7}, "materiality"),
        ({"score_components": {"materiality": 2, "fundamental_impact": 1, "structure_alignment": 2, "execution_certainty": 2}, "score": 7}, "fundamental impact"),
        ({"score_components": {"materiality": 2, "fundamental_impact": 3, "structure_alignment": 2, "execution_certainty": 0}, "score": 7}, "execution certainty"),
        ({"red_flags": ["uma"]}, "red flag"),
        ({"health": {"ni_ttm": -1, "current_ratio": 0.8, "net_cash": False}}, "financial distress"),
    ],
)
def test_validate_publication_fields_rejects_failed_gate(changes, message):
    fields = _high_conviction_fields()
    fields.update(changes)
    with pytest.raises(ValueError, match=message):
        scan.validate_publication_fields(fields)
```

Add a missing-evidence case. It must verify that the agent cannot claim materiality 2 when `fundamental_context` lacks every relevant denominator:

```python
def test_validate_publication_fields_rejects_material_score_without_denominator():
    fields = _high_conviction_fields()
    fields["fundamental_context"] = {"market_cap": None, "total_revenue": None, "total_assets": None, "shares_outstanding": None}
    with pytest.raises(ValueError, match="denominator"):
        scan.validate_publication_fields(fields)
```

- [ ] **Step 2: Run gate tests to verify they fail**

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_validate_publication_fields_accepts_exact_score_seven tests/test_scan.py::test_validate_publication_fields_rejects_score_six_even_when_components_match tests/test_scan.py::test_validate_publication_fields_rejects_failed_gate tests/test_scan.py::test_validate_publication_fields_rejects_material_score_without_denominator
```

Expected: FAIL because `validate_publication_fields` and `publication_score` do not exist.

- [ ] **Step 3: Implement validation before Discord posting**

Define the score limits and validator in `scan.py` above `render_alert()`:

```python
SCORE_COMPONENT_LIMITS = {
    "materiality": 3,
    "fundamental_impact": 3,
    "structure_alignment": 2,
    "execution_certainty": 2,
}
PUBLISH_BLOCKING_FLAGS = {"uma", "suspend", "fca_ppk", "pkpu"}


def publication_score(components: dict[str, int]) -> int:
    if set(components) != set(SCORE_COMPONENT_LIMITS):
        raise ValueError("score components are incomplete")
    for name, maximum in SCORE_COMPONENT_LIMITS.items():
        value = components[name]
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"invalid {name} score")
    return sum(components.values())


def validate_publication_fields(fields: dict) -> None:
    components = fields.get("score_components")
    if not isinstance(components, dict):
        raise ValueError("score components are required")
    total = publication_score(components)
    if fields.get("score") != total:
        raise ValueError("score must equal component total")
    if not 7 <= total <= 10:
        raise ValueError("published score must be 7 to 10")
    if components["materiality"] < 2:
        raise ValueError("materiality must be at least 2")
    if components["fundamental_impact"] < 2:
        raise ValueError("fundamental impact must be at least 2")
    if components["execution_certainty"] < 1:
        raise ValueError("execution certainty must be at least 1")
    if set(fields.get("red_flags") or ()) & PUBLISH_BLOCKING_FLAGS:
        raise ValueError("red flag blocks publication")
    if health_verdict(fields.get("health") or {})[1]:
        raise ValueError("financial distress blocks publication")
    context = fields.get("fundamental_context") or {}
    denominator_keys = ("market_cap", "total_revenue", "total_assets", "shares_outstanding")
    if components["materiality"] >= 2 and not any(context.get(key) for key in denominator_keys):
        raise ValueError("materiality denominator is required")
```

Require `ticker`, `company_name`, `ca_label`, `summary`, and `pdf_url` to be non-empty strings in the same function. Call `validate_publication_fields(fields)` at the start of `cli_post_alert()` before `render_alert()` or `post_discord()`.

- [ ] **Step 4: Run gate tests to verify they pass**

Run the command from Step 2 again.

Expected: PASS. Every invalid field set must fail before the Discord function is called.

- [ ] **Step 5: Add a dispatch-order test and run it**

Add this test:

```python
def test_post_alert_rejects_before_discord(monkeypatch):
    fields = _high_conviction_fields()
    fields["score"] = 6
    monkeypatch.setattr(scan, "post_discord", lambda *args, **kwargs: pytest.fail("Discord must not be called"))
    with pytest.raises(ValueError, match="must equal component total"):
        scan.cli_post_alert(["--json", json.dumps(fields)])
```

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_post_alert_rejects_before_discord
```

Expected: PASS.

## Task 3: Render the approved Indonesian `:idx:` alert shape

**Files:**
- Modify: `idx-ca-watch/bin/scan.py:307-331`
- Modify: `idx-ca-watch/tests/test_scan.py:291-375`

**Interfaces:**
- Consumes: validated fields from `validate_publication_fields()`.
- Produces: `render_alert(fields: dict) -> str` with H3 header, one or two supplied Indonesian paragraphs, action label, score, and source link.
- Produces: `cli_post_alert()` behavior that attaches `chart_path` to the same message but never renders technical or fundamental statistic blocks.

- [ ] **Step 1: Write the failing rendering test**

Replace the legacy English report-format assertion with this exact expected message:

```python
def test_render_alert_uses_approved_idx_format():
    fields = _high_conviction_fields()
    fields["summary"] = (
        "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.\n\n"
        "Struktur transaksi mendukung alignment pengendali dengan pemegang saham publik, tetapi realisasi dampaknya tetap bergantung pada eksekusi yang telah diungkapkan."
    )
    expected = (
        "### <:idx:1531974045266874499> ANTM (PT Aneka Tambang Tbk)\n"
        "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.\n\n"
        "Struktur transaksi mendukung alignment pengendali dengan pemegang saham publik, tetapi realisasi dampaknya tetap bergantung pada eksekusi yang telah diungkapkan.\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "*Jenis aksi:* Pembelian saham oleh pengendali\n"
        "*Skor katalis:* 7/10\n"
        "*Sumber:* [Keterbukaan Informasi BEI](<https://www.idx.co.id/StaticData/x/y.pdf>)"
    )

    output = scan.render_alert(fields)

    assert output == expected
    assert "RSI" not in output
    assert "MA200" not in output
    assert "ATR" not in output
    assert "**Fundamentals:**" not in output
    assert "\u2014" not in output
```

- [ ] **Step 2: Run the rendering test to verify it fails**

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_render_alert_uses_approved_idx_format
```

Expected: FAIL because the current renderer produces an H2 English research report with technical and fundamental blocks.

- [ ] **Step 3: Implement the renderer and chart dispatch**

Replace the legacy renderer with:

```python
IDX_EMOJI = "<:idx:1531974045266874499>"
ALERT_SEPARATOR = "┈┈┈┈┈┈┈┈┈┈┈┈┈"


def render_alert(fields: dict) -> str:
    return "\n".join([
        f"### {IDX_EMOJI} {fields['ticker']} ({fields['company_name']})",
        fields["summary"].strip(),
        ALERT_SEPARATOR,
        f"*Jenis aksi:* {fields['ca_label']}",
        f"*Skor katalis:* {fields['score']}/10",
        f"*Sumber:* [Keterbukaan Informasi BEI](<{fields['pdf_url']}>)",
    ])
```

Keep `post_discord(ALERT_CHANNEL, text, media_path=fields.get("chart_path"), ...)` unchanged so the chart remains an attachment to the same alert.

- [ ] **Step 4: Run renderer and no-post dispatch tests**

Update `test_post_alert_dry_run` to call `_high_conviction_fields()` and assert the media path remains `/tmp/c.png`. Then run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py::test_render_alert_uses_approved_idx_format tests/test_scan.py::test_post_alert_dry_run tests/test_scan.py::test_post_alert_rejects_before_discord
```

Expected: PASS. The captured text begins with the approved H3 and captured media remains the chart path.

## Task 4: Replace the agent scoring and posting contract

**Files:**
- Modify: `idx-ca-watch/SKILL.md:1-156`

**Interfaces:**
- Consumes: scanner payload fields `company_name`, `fundamental_context`, `health`, `pdf_text`, `fin_report_text`, `red_flags`, `ca_type`, `pdf_url`, and `chart_path`.
- Produces: the exact JSON accepted by `validate_publication_fields()` plus one `record-score` call for every evaluated item.

- [ ] **Step 1: Write the new score contract into `SKILL.md`**

Replace the current owner-intent and technical rubric with the four exact components below:

```text
materiality 0-3: 0 unquantified or below 5%; 1 from 5% to below 10%; 2 from 10% to below 25%; 3 at least 25% or a material change in control/free float
fundamental_impact 0-3: a verified path to revenue, earnings, cash flow, productive assets, capital structure, control, or free float
structure_alignment 0-2: terms that protect or improve public-shareholder economics, including credible controller commitment when disclosed
execution_certainty 0-2: disclosed price, size, parties, funding, approvals, timetable, and material terms
```

State these non-negotiable rules in the skill:

- The horizon is roughly 1 to 20 trading days.
- Do not use or mention technical indicators. The chart is visual context only.
- Scores 0 to 6 are always suppressed and recorded.
- Score 7 to 10 requires materiality at least 2, fundamental impact at least 2, execution certainty at least 1, a usable denominator, and no red flag or financial distress.
- Routine results, ordinary dividends, vague joint ventures, generic material facts, and unquantified filings cannot score 7.
- If key evidence is missing, suppress rather than infer.
- Summaries are one or two short Indonesian paragraphs, in the X-post watcher style: facts first, named parties and material numbers, then only supportable implications.

- [ ] **Step 2: Replace the post command with the validated JSON shape**

Use this complete example, matching the new validator names exactly:

```json
{
  "ticker": "ANTM",
  "company_name": "PT Aneka Tambang Tbk",
  "ca_label": "Pembelian saham oleh pengendali",
  "summary": "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.",
  "score_components": {
    "materiality": 2,
    "fundamental_impact": 2,
    "structure_alignment": 2,
    "execution_certainty": 1
  },
  "score": 7,
  "red_flags": [],
  "fundamental_context": {"market_cap": 2000000000000, "total_revenue": 1000000000000, "total_assets": 3000000000000, "shares_outstanding": 1000000000},
  "health": {"ni_ttm": 1000000000, "current_ratio": 2.0, "net_cash": true},
  "pdf_url": "https://www.idx.co.id/StaticData/example.pdf",
  "chart_path": "/tmp/chart.png"
}
```

In the prose around the example, direct the agent to copy `fundamental_context`, `health`, `red_flags`, `pdf_url`, and `chart_path` from the scanner payload verbatim. It may write only `ca_label`, `summary`, and the score fields after evidence-based evaluation.

- [ ] **Step 3: Check that the old contract is absent**

Run:

```bash
cd idx-ca-watch && rg -n 'Money flow|RSI|MA200|ATR|liq|🟡|🟢|What happened|Why it may matter|metrics' SKILL.md
```

Expected: no matches for technical terms, old alert sections, or yellow-alert instructions. The search may still match the word `chart` because the attachment remains required.

## Task 5: Complete verification and safe deployment

**Files:**
- Modify only as produced by Tasks 1 to 4.

**Interfaces:**
- Consumes: reviewed local `scan.py`, `SKILL.md`, and `test_scan.py`.
- Produces: matching VPS runtime source, a verified isolated no-post run, and evidence without changing production state or posting a Discord message.

- [ ] **Step 1: Run the full local test suite**

Run:

```bash
cd idx-ca-watch && ../.venv/bin/python -m pytest -q
```

Expected: all tests pass. If a legacy test expects technical metrics or the old English report format, update only that test to the approved behavior before rerunning.

- [ ] **Step 2: Compare local and VPS source before writes**

Run from the Hermes root:

```bash
shasum -a 256 idx-ca-watch/bin/scan.py idx-ca-watch/SKILL.md
ssh vps 'shasum -a 256 ~/.agents/skills/idx-ca-watch/bin/scan.py ~/.agents/skills/idx-ca-watch/SKILL.md'
```

Expected: record both checksum pairs. They may differ before deployment; inspect `diff -u` for each differing file before copying.

Run the exact diff commands:

```bash
remote_scan=$(mktemp)
remote_skill=$(mktemp)
scp vps:~/.agents/skills/idx-ca-watch/bin/scan.py "$remote_scan"
scp vps:~/.agents/skills/idx-ca-watch/SKILL.md "$remote_skill"
diff -u "$remote_scan" idx-ca-watch/bin/scan.py || true
diff -u "$remote_skill" idx-ca-watch/SKILL.md || true
rm -f "$remote_scan" "$remote_skill"
```

- [ ] **Step 3: Obtain the required current-chat approval for the first VPS write**

Show the reviewed `diff -u` output and both checksum pairs from Step 2. Ask the user once for approval to copy only `idx-ca-watch/bin/scan.py` and `idx-ca-watch/SKILL.md` to the VPS. Do not deploy until that approval is explicit.

- [ ] **Step 4: Deploy only the reviewed executable and sync the reviewed skill instructions**

Run:

```bash
./deploy.sh idx-ca-watch scan.py
scp idx-ca-watch/SKILL.md vps:~/.agents/skills/idx-ca-watch/SKILL.md
```

Expected: `deploy.sh` changes only the runtime `bin/scan.py`; `scp` changes only the runtime `SKILL.md`. Do not copy `state/`, wrapper, or dotfiles mirror.

- [ ] **Step 5: Verify deployed checksums**

Run:

```bash
shasum -a 256 idx-ca-watch/bin/scan.py idx-ca-watch/SKILL.md
ssh vps 'shasum -a 256 ~/.agents/skills/idx-ca-watch/bin/scan.py ~/.agents/skills/idx-ca-watch/SKILL.md'
```

Expected: each local checksum matches its VPS counterpart exactly.

- [ ] **Step 6: Run isolated no-post smoke tests without changing production state**

Run:

```bash
ssh vps 'set -eu; smoke_state=$(mktemp); IDX_CA_STATE_PATH="$smoke_state" IDX_CA_WATCH_NO_POST=1 ~/.hermes/scripts/idx-ca-watch.sh; rm -f "$smoke_state"'
```

Expected: exit code 0, no Discord message, no write to `~/.agents/skills/idx-ca-watch/state/state.json`, and either a bootstrap or a JSON result using the new payload contract. If a fresh temporary state would bootstrap without exercising the alert renderer, run `post-alert` with a locally prepared valid JSON and `IDX_CA_WATCH_NO_POST=1`, still using a temporary state and no Discord side effect.

- [ ] **Step 7: Verify live registration without claiming a future alert**

Run:

```bash
ssh vps '/home/praya/.local/bin/hermes cron list | sed -n "/idx-ca-watch/,+8p"'
```

Expected: existing `idx-ca-watch` remains active with its current schedule and heartbeat delivery target. Report the test result, checksum matches, smoke output, and registration evidence. Do not claim that a future scheduled high-conviction alert was observed until one actually occurs.
