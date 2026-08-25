# idx-ca-watch Notification Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace idx-ca-watch's wrapper-wrapped, low-substance alert with a clean markdown alert posted directly by the skill, gated to higher-quality signals, and backed by full attachment extraction plus a yfinance + laporan-keuangan financial-health read.

**Architecture:** All code lives in `~/Documents/Projects/Hermes/idx-ca-watch/bin/scan.py`. The markdown TEMPLATE and all numeric formatting live in pure functions in `scan.py` (deterministic, drift-free, unit-tested); the agent supplies only judgment fields. A new `post-alert` subcommand posts directly via the existing `post_discord()`, so the Hermes cron `deliver` wrapper is bypassed (and retargeted so the agent reply does not double-post). New network functions (`financial_health`, `fetch_attachments_text`, `fetch_financial_report_text`) are thin wrappers around pure helpers; only the pure helpers are unit-tested locally, the network paths are verified on the VPS.

**Tech Stack:** Python 3.13 (stdlib only at import time; `yfinance`, `curl_cffi`, `pypdf`, `requests` imported lazily inside functions), pytest, the IDX `GetAnnouncement` + `GetFinancialReport` JSON endpoints, Discord REST.

## Global Constraints

- **No em dashes** anywhere (code, strings, docs, the alert template). Use `:`, `,`, `(...)`, or `·`. (User rule.)
- **No new top-level imports in `scan.py`.** All of `yfinance`/`curl_cffi`/`pypdf`/`requests`/`cloudscraper` stay imported *inside* functions so `import scan` works with only stdlib (the test runner has no pypdf). Pure functions must be stdlib-only.
- **Dev home is NOT a git repo.** There is no per-task `git commit`. Each task's checkpoint is "full local suite green". Version control happens at the end via `~/.dotfiles/sync.sh` (Task 8).
- **Local test runner:** `PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"`. Run from `~/Documents/Projects/Hermes/idx-ca-watch/`: `$PYT -m pytest -q`. Baseline is 23 passing.
- **Network/IDX verification is VPS-only** (IDX Cloudflare blocks non-datacenter IPs). Functions that hit yfinance or IDX are NOT unit-tested; their pure helpers are. VPS verify is Task 8.
- **Alert channel:** `1517510484025151538`. **Heartbeat channel:** `1505162000420835388`. **Cron id:** `b49432a194d1`.
- **At-least-once contract is preserved:** to-be-scored items are marked seen only via `record_score` (after posting/decision), never speculatively. Do not change this.
- **Confidence math unchanged:** raw is `/8`, `confidence = raw/8*10`, displayed as `/10` leading. Do not rebalance lens weights.

---

### Task 1: Pure display helpers (`format_tech`, `health_verdict`, `format_fund_line`, `_ttm_yoy`)

**Files:**
- Modify: `bin/scan.py` (add four pure functions near the other formatters, after `format_heartbeat`, ~line 226)
- Test: `tests/test_scan.py` (append)

**Interfaces:**
- Produces:
  - `format_tech(metrics: dict) -> str`
  - `health_verdict(h: dict) -> tuple[str, bool]`  (returns `(label, distress)`, label in `{"healthy ✅","mixed ⚠️","weak ❌","n/a"}`)
  - `format_fund_line(h: dict) -> str`
  - `_ttm_yoy(values: list) -> float | None`  (latest-4 sum vs prior-4 sum YoY; `None` if insufficient/zero-base)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan.py`:
```python
# --- Notif upgrade Task 1: pure display helpers ---
def test_format_tech_full():
    s = scan.format_tech({"above_ma200": True, "rsi": 58.0,
                          "avg_value_idr": 1.8e11, "atr_pct": 3.4})
    assert s == "above MA200 ✅ · RSI `58` · liq `Rp180.0B/d` · ATR `3.4%`"


def test_format_tech_handles_none():
    s = scan.format_tech({"above_ma200": None, "rsi": None,
                          "avg_value_idr": None, "atr_pct": None})
    assert s == "MA200 n/a · RSI n/a · liq n/a · ATR n/a"


def test_health_verdict_healthy():
    h = {"roe": 0.14, "net_margin": 0.21, "net_cash": True, "current_ratio": 2.5,
         "fcf_pos": True, "ni_ttm": 1e12, "ni_yoy": 0.05}
    assert scan.health_verdict(h) == ("healthy ✅", False)


def test_health_verdict_distress_on_loss():
    assert scan.health_verdict({"ni_ttm": -5e11}) == ("weak ❌", True)


def test_health_verdict_distress_on_ni_collapse():
    assert scan.health_verdict({"ni_ttm": 1e9, "ni_yoy": -0.7}) == ("weak ❌", True)


def test_health_verdict_na_when_empty():
    assert scan.health_verdict({}) == ("n/a", False)


def test_format_fund_line_healthy():
    h = {"roe": 0.14, "net_margin": 0.21, "net_cash": True, "current_ratio": 2.5,
         "fcf_pos": True, "ni_ttm": 1e12, "ni_yoy": 0.05}
    assert scan.format_fund_line(h) == "healthy ✅ · ROE `14%` · net cash · margin `21%` · NI `+5%`"


def test_format_fund_line_na():
    assert scan.format_fund_line({}) == "n/a"


def test_ttm_yoy():
    # latest 4 sum = 10+11+12+13=46 ; prior 4 = 8+9+9+10=36 ; (46-36)/36
    vals = [13, 12, 11, 10, 10, 9, 9, 8]
    assert round(scan._ttm_yoy(vals), 4) == round((46 - 36) / 36, 4)
    assert scan._ttm_yoy([1, 2, 3]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Documents/Projects/Hermes/idx-ca-watch && $PYT -m pytest -q -k "format_tech or health_verdict or format_fund_line or ttm_yoy"`
Expected: FAIL (AttributeError: module 'scan' has no attribute 'format_tech').

- [ ] **Step 3: Implement the helpers**

In `bin/scan.py`, immediately after `format_heartbeat` (the function ending ~line 225), add:
```python
def format_tech(metrics: dict) -> str:
    m = metrics or {}
    ma = m.get("above_ma200")
    ma_s = "above MA200 ✅" if ma is True else ("below MA200 ❌" if ma is False else "MA200 n/a")
    rsi = m.get("rsi")
    rsi_s = f"RSI `{rsi:.0f}`" if rsi is not None else "RSI n/a"
    av = m.get("avg_value_idr")
    liq_s = f"liq `Rp{av/1e9:.1f}B/d`" if av is not None else "liq n/a"
    atr = m.get("atr_pct")
    atr_s = f"ATR `{atr:.1f}%`" if atr is not None else "ATR n/a"
    return f"{ma_s} · {rsi_s} · {liq_s} · {atr_s}"


def _ttm_yoy(values: list) -> float | None:
    """YoY growth: sum of the latest 4 values vs the prior 4 (values newest-first)."""
    nums = [v for v in (values or []) if v is not None]
    if len(nums) < 8:
        return None
    latest = sum(nums[:4])
    prior = sum(nums[4:8])
    if prior == 0:
        return None
    return (latest - prior) / abs(prior)


def health_verdict(h: dict) -> tuple[str, bool]:
    h = h or {}
    if all(h.get(k) is None for k in ("roe", "net_margin", "net_cash", "current_ratio",
                                      "fcf_pos", "ni_ttm", "ni_yoy")):
        return ("n/a", False)
    ni_ttm = h.get("ni_ttm")
    ni_yoy = h.get("ni_yoy")
    cr = h.get("current_ratio")
    distress = (
        (ni_ttm is not None and ni_ttm < 0)
        or (ni_yoy is not None and ni_yoy < -0.5)
        or (cr is not None and cr < 1 and not h.get("net_cash"))
    )
    if distress:
        return ("weak ❌", True)
    score = 0
    if (h.get("roe") or 0) > 0.10: score += 1
    if (h.get("net_margin") or 0) > 0.08: score += 1
    if h.get("net_cash"): score += 1
    if (cr or 0) > 1.5: score += 1
    if h.get("fcf_pos"): score += 1
    if (ni_yoy if ni_yoy is not None else -1) >= 0: score += 1
    if score >= 4:
        return ("healthy ✅", False)
    if score >= 2:
        return ("mixed ⚠️", False)
    return ("weak ❌", False)


def format_fund_line(h: dict) -> str:
    verdict, _ = health_verdict(h)
    if verdict == "n/a":
        return "n/a"
    parts = [verdict]
    if h.get("roe") is not None:
        parts.append(f"ROE `{h['roe']*100:.0f}%`")
    parts.append("net cash" if h.get("net_cash") else "net debt")
    if h.get("net_margin") is not None:
        parts.append(f"margin `{h['net_margin']*100:.0f}%`")
    if h.get("ni_yoy") is not None:
        parts.append(f"NI `{h['ni_yoy']*100:+.0f}%`")
    return " · ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYT -m pytest -q -k "format_tech or health_verdict or format_fund_line or ttm_yoy"`
Expected: PASS (9 tests).

- [ ] **Step 5: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (32 = 23 baseline + 9).

---

### Task 2: `render_alert()` + `post-alert` subcommand

**Files:**
- Modify: `bin/scan.py` (add `render_alert` after Task 1 helpers; add `post-alert` branch in the `__main__` dispatch ~line 543)
- Test: `tests/test_scan.py` (append)

**Interfaces:**
- Consumes: `format_tech`, `format_fund_line` (Task 1); `post_discord`, `ALERT_CHANNEL` (existing).
- Produces: `render_alert(f: dict) -> str`; CLI `scan.py post-alert [--json '<json>']` (reads stdin if `--json` omitted).
- `f` keys: `emoji, ticker, ca_label, conf(float), raw(int), deal, owner_intent, owner_why, metrics(dict), health(dict), lenses{owner,purpose,fund,flowtech}, gates{thesis:bool,confirm:bool}, pdf_url, chart_path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan.py`:
```python
# --- Notif upgrade Task 2: render_alert + post-alert ---
def _alert_fields():
    return {
        "emoji": "🟢", "ticker": "ANTM", "ca_label": "Rights issue (HMETD)",
        "conf": 8.0, "raw": 6,
        "deal": "1:5 HMETD at Rp1,850, standby buyer MIND ID.",
        "owner_intent": "BULLISH", "owner_why": "SOE controller funding accretive expansion.",
        "metrics": {"above_ma200": True, "rsi": 58.0, "avg_value_idr": 1.8e11, "atr_pct": 3.4},
        "health": {"roe": 0.14, "net_margin": 0.21, "net_cash": True, "current_ratio": 2.5,
                   "fcf_pos": True, "ni_ttm": 1e12, "ni_yoy": 0.05},
        "lenses": {"owner": 2, "purpose": 2, "fund": 1, "flowtech": 1},
        "gates": {"thesis": True, "confirm": True},
        "pdf_url": "https://x/p.pdf", "chart_path": "/tmp/c.png",
    }


def test_render_alert_exact():
    expected = (
        "🟢 **ANTM** · Rights issue (HMETD) · `8.0/10` (raw `6/8`)\n"
        "\n"
        "**Deal:** 1:5 HMETD at Rp1,850, standby buyer MIND ID.\n"
        "**Owner:** `BULLISH`, SOE controller funding accretive expansion.\n"
        "**Fundamentals:** healthy ✅ · ROE `14%` · net cash · margin `21%` · NI `+5%`\n"
        "\n"
        "**Tech:** above MA200 ✅ · RSI `58` · liq `Rp180.0B/d` · ATR `3.4%`\n"
        "**Score:** owner `+2` · purpose `+2` · fund `+1` · flow/tech `+1`  (thesis ✅ · confirm ✅)\n"
        "\n"
        "⚠️ Bukan ajakan beli, DYOR · [PDF](https://x/p.pdf)"
    )
    assert scan.render_alert(_alert_fields()) == expected
    # no cron wrapper cruft
    out = scan.render_alert(_alert_fields())
    assert "Cronjob Response" not in out and "job_id" not in out
    assert "—" not in out  # no em dashes


def test_render_alert_gates_false():
    f = _alert_fields()
    f["gates"] = {"thesis": False, "confirm": True}
    assert "(thesis ❌ · confirm ✅)" in scan.render_alert(f)


def test_post_alert_dry_run(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(scan, "post_discord",
                        lambda ch, content, media_path=None, dry_run=False:
                        captured.update(ch=ch, content=content, media=media_path) or True)
    rc = scan.cli_post_alert(["--json", json.dumps(_alert_fields())])
    assert rc == 0
    assert captured["ch"] == scan.ALERT_CHANNEL
    assert captured["media"] == "/tmp/c.png"
    assert captured["content"].startswith("🟢 **ANTM**")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYT -m pytest -q -k "render_alert or post_alert"`
Expected: FAIL (no attribute `render_alert`).

- [ ] **Step 3: Implement `render_alert` and `cli_post_alert`**

After the Task 1 helpers in `bin/scan.py`, add:
```python
def render_alert(f: dict) -> str:
    g = lambda b: "✅" if b else "❌"
    L = f.get("lenses", {})
    gt = f.get("gates", {})
    head = (f"{f['emoji']} **{f['ticker']}** · {f['ca_label']} · "
            f"`{f['conf']:.1f}/10` (raw `{f['raw']}/8`)")
    deal = f"**Deal:** {f['deal']}"
    owner = f"**Owner:** `{f['owner_intent']}`, {f['owner_why']}"
    fund = f"**Fundamentals:** {format_fund_line(f.get('health', {}))}"
    tech = f"**Tech:** {format_tech(f.get('metrics', {}))}"
    score = (f"**Score:** owner `+{L.get('owner', 0)}` · purpose `+{L.get('purpose', 0)}` · "
             f"fund `+{L.get('fund', 0)}` · flow/tech `+{L.get('flowtech', 0)}`  "
             f"(thesis {g(gt.get('thesis'))} · confirm {g(gt.get('confirm'))})")
    disc = f"⚠️ Bukan ajakan beli, DYOR · [PDF]({f.get('pdf_url', '')})"
    return "\n".join([head, "", deal, owner, fund, "", tech, score, "", disc])


def cli_post_alert(argv: list) -> int:
    raw = None
    if argv and argv[0] == "--json":
        raw = argv[1]
    else:
        raw = sys.stdin.read()
    fields = json.loads(raw)
    text = render_alert(fields)
    ok = post_discord(ALERT_CHANNEL, text, media_path=fields.get("chart_path"),
                      dry_run=os.environ.get("IDX_CA_WATCH_NO_POST") == "1")
    print("posted" if ok else "post-failed")
    return 0 if ok else 1
```

Then wire the subcommand in `__main__` (the block at the bottom, ~line 543). Change:
```python
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "record-score":
        ...
        raise SystemExit(0)
    raise SystemExit(main())
```
to add a `post-alert` branch BEFORE the `record-score` branch:
```python
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "post-alert":
        raise SystemExit(cli_post_alert(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "record-score":
        ...  # unchanged
        raise SystemExit(0)
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYT -m pytest -q -k "render_alert or post_alert"`
Expected: PASS (3 tests).

- [ ] **Step 5: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (35).

---

### Task 3: `financial_health(ticker)` (yfinance wrapper, network)

**Files:**
- Modify: `bin/scan.py` (add after `market_metrics`, ~line 387)
- Test: none (network; the pure logic it feeds is already tested in Task 1). Verified on VPS in Task 8.

**Interfaces:**
- Consumes: `_ttm_yoy` (Task 1).
- Produces: `financial_health(ticker: str) -> dict` with keys `roe, net_margin, net_cash, current_ratio, fcf_pos, ni_ttm, ni_yoy, rev_yoy`. All values `None`/`False` on missing data; returns `{}` only on total failure.

- [ ] **Step 1: Implement (no unit test, mirrors untested `market_metrics`)**

In `bin/scan.py` after `market_metrics`, add:
```python
def financial_health(ticker: str) -> dict:
    """Compact fundamental snapshot from yfinance. Best-effort; {} on failure."""
    out = {"roe": None, "net_margin": None, "net_cash": None, "current_ratio": None,
           "fcf_pos": None, "ni_ttm": None, "ni_yoy": None, "rev_yoy": None}
    try:
        import yfinance as yf
        t = yf.Ticker(f"{ticker}.JK")
        info = {}
        try:
            info = t.info or {}
        except Exception:  # noqa: BLE001
            info = {}
        out["roe"] = info.get("returnOnEquity")
        out["net_margin"] = info.get("profitMargins")
        out["current_ratio"] = info.get("currentRatio")
        out["rev_yoy"] = info.get("revenueGrowth")
        out["ni_yoy"] = info.get("earningsGrowth")
        out["ni_ttm"] = info.get("netIncomeToCommon")
        fcf = info.get("freeCashflow")
        out["fcf_pos"] = (fcf is not None and fcf > 0) or None
        cash, debt = info.get("totalCash"), info.get("totalDebt")
        if cash is not None and debt is not None:
            out["net_cash"] = cash > debt
        # Fallback NI YoY from quarterly statements if info lacked earningsGrowth.
        if out["ni_yoy"] is None:
            try:
                qf = t.quarterly_financials
                if qf is not None and "Net Income" in qf.index:
                    out["ni_yoy"] = _ttm_yoy([float(v) for v in qf.loc["Net Income"].values])
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[health] {ticker} failed: {e}", file=sys.stderr)
        return {}
```

- [ ] **Step 2: Smoke-check locally (yfinance reaches `.JK` from the Mac; IDX does not)**

Run: `$PYT -c "import sys; sys.path.insert(0,'bin'); import scan; print(scan.health_verdict(scan.financial_health('LSIP'))); print(scan.format_fund_line(scan.financial_health('LSIP')))"`
Expected: a `("healthy ✅", False)`-ish tuple and a populated fund line (LSIP is debt-free, high margin). If yfinance is rate-limited, this may return `n/a`; that is acceptable, real verification is the VPS run in Task 8.

- [ ] **Step 3: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (35, unchanged: no new unit tests).

---

### Task 4: All-attachment extraction

**Files:**
- Modify: `bin/scan.py` (`_assemble_pdf_text` new pure helper + `fetch_attachments_text` near `fetch_pdf_text`, ~line 325)
- Test: `tests/test_scan.py` (append, pure helper only)

**Interfaces:**
- Consumes: `fetch_pdf_text` (existing).
- Produces:
  - `_assemble_pdf_text(chunks: list[tuple[str, str]], cap: int) -> str` (pure)
  - `fetch_attachments_text(urls: list, filenames: list, max_pages_each: int = 10, cap: int = 20000) -> str` (network)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scan.py`:
```python
# --- Notif upgrade Task 4: attachment assembly ---
def test_assemble_pdf_text_labels_and_caps():
    chunks = [("cover.pdf", "AAA"), ("letter.pdf", "BBBB"), ("annex.pdf", "CCCCC")]
    out = scan._assemble_pdf_text(chunks, cap=1000)
    assert out == "[cover.pdf]\nAAA\n\n[letter.pdf]\nBBBB\n\n[annex.pdf]\nCCCCC"
    capped = scan._assemble_pdf_text(chunks, cap=12)
    assert len(capped) == 12 and capped.startswith("[cover.pdf]")


def test_assemble_pdf_text_skips_empty():
    out = scan._assemble_pdf_text([("a.pdf", ""), ("b.pdf", "X")], cap=1000)
    assert out == "[b.pdf]\nX"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PYT -m pytest -q -k assemble_pdf_text`
Expected: FAIL (no attribute `_assemble_pdf_text`).

- [ ] **Step 3: Implement**

In `bin/scan.py`, after `fetch_pdf_text` (~line 350), add:
```python
def _assemble_pdf_text(chunks: list, cap: int) -> str:
    """chunks: list of (filename, text). Prepend [filename], drop empties, cap total."""
    blocks = [f"[{name}]\n{text}" for name, text in chunks if (text or "").strip()]
    joined = "\n\n".join(blocks)
    return joined[:cap]


def fetch_attachments_text(urls: list, filenames: list,
                           max_pages_each: int = 10, cap: int = 20000) -> str:
    """Extract text from ALL CA attachments (not just the cover), labelled by filename."""
    urls = urls or []
    filenames = filenames or []
    chunks = []
    for i, u in enumerate(urls):
        if not u:
            continue
        name = filenames[i] if i < len(filenames) and filenames[i] else f"attachment-{i+1}.pdf"
        chunks.append((name, fetch_pdf_text(u, max_pages=max_pages_each)))
    return _assemble_pdf_text(chunks, cap)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$PYT -m pytest -q -k assemble_pdf_text`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (37).

---

### Task 5: Laporan keuangan PDF fetch (best-effort)

**Files:**
- Modify: `bin/scan.py` (constants + `_report_query_order`, `_pick_report` pure helpers + `fetch_financial_report_text` network, after Task 4 functions)
- Test: `tests/test_scan.py` (append, pure helpers only)

**Interfaces:**
- Consumes: `fetch_pdf_text` (existing), `BROWSER_HEADERS`/`IMPERSONATE_PROFILES` (existing).
- Produces:
  - `_report_query_order(now: dt.datetime) -> list[tuple[int, str]]` (pure; `(year, periode)` newest-first)
  - `_pick_report(results: list) -> str | None` (pure; full URL of the FinancialStatements pdf, or None)
  - `fetch_financial_report_text(ticker: str, now=None, max_pages: int = 6, cap: int = 8000) -> str` (network, best-effort, `""` on any failure)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan.py`:
```python
# --- Notif upgrade Task 5: financial-report selection ---
def test_report_query_order_walks_back():
    now = scan.dt.datetime(2026, 6, 27, tzinfo=scan.WIB)
    order = scan._report_query_order(now)
    assert order[0] == (2026, "tw1")
    assert (2025, "audit") in order
    assert order[-1][0] == 2025


def test_pick_report_finds_financial_statements_pdf():
    results = [{
        "KodeEmiten": "LSIP",
        "Attachments": [
            {"File_Name": "inlineXBRL.zip", "File_Type": ".zip",
             "File_Path": "/Portals/0/x/inlineXBRL.zip"},
            {"File_Name": "FinancialStatements-2025-TW3.pdf", "File_Type": ".pdf",
             "File_Path": "/Portals/0/x/FinancialStatements-2025-TW3.pdf"},
        ],
    }]
    url = scan._pick_report(results)
    assert url == "https://www.idx.co.id/Portals/0/x/FinancialStatements-2025-TW3.pdf"


def test_pick_report_none_when_no_pdf():
    assert scan._pick_report([{"Attachments": [
        {"File_Name": "x.zip", "File_Type": ".zip", "File_Path": "/a.zip"}]}]) is None
    assert scan._pick_report([]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYT -m pytest -q -k "report_query_order or pick_report"`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `bin/scan.py`, near the top constants block add (after `API_URL`, ~line 8):
```python
FIN_REPORT_URL = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
IDX_BASE = "https://www.idx.co.id"
```
Then after the Task 4 functions add:
```python
def _report_query_order(now: dt.datetime) -> list:
    """(year, periode) pairs to try: this year's periods, then last year's."""
    y = now.year
    cur = [(y, p) for p in ["tw1", "tw2", "tw3", "audit"]]
    prev = [(y - 1, p) for p in ["audit", "tw3", "tw2", "tw1"]]
    return cur + prev


def _pick_report(results: list) -> str | None:
    for res in results or []:
        for att in res.get("Attachments", []) or []:
            name = (att.get("File_Name") or "")
            ftype = (att.get("File_Type") or "").lower()
            if name.lower().startswith("financialstatements") and ftype == ".pdf":
                path = att.get("File_Path") or ""
                if path:
                    return IDX_BASE + path
    return None


def fetch_financial_report_text(ticker: str, now: dt.datetime | None = None,
                                max_pages: int = 6, cap: int = 8000) -> str:
    """Best-effort: latest IDX financial-statement PDF text for the ticker. '' on any failure."""
    now = now or dt.datetime.now(WIB)
    try:
        from curl_cffi import requests as creq
        for year, periode in _report_query_order(now):
            params = (f"?indexFrom=1&pageSize=3&year={year}&reportType=rdf"
                      f"&periode={periode}&kodeEmiten={ticker}&SortColumn=KodeEmiten&SortOrder=asc")
            url = FIN_REPORT_URL + params
            for imp in IMPERSONATE_PROFILES[:3]:
                try:
                    r = creq.get(url, impersonate=imp, headers=BROWSER_HEADERS, timeout=30)
                    if r.status_code == 200 and r.text.lstrip().startswith("{"):
                        pdf_url = _pick_report(r.json().get("Results", []))
                        if pdf_url:
                            return fetch_pdf_text(pdf_url, max_pages=max_pages)[:cap]
                        break  # endpoint answered, no report for this period -> try next period
                except Exception:  # noqa: BLE001
                    continue
        return ""
    except Exception as e:  # noqa: BLE001
        print(f"[finreport] {ticker} failed: {e}", file=sys.stderr)
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYT -m pytest -q -k "report_query_order or pick_report"`
Expected: PASS (3 tests).

- [ ] **Step 5: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (40).

---

### Task 6: Wire `run()` + `build_item_payload` (health + multi-attachment + fin report into the payload)

**Files:**
- Modify: `bin/scan.py` (`build_item_payload` ~line 228; `run()` interesting loop ~line 492-503)
- Test: `tests/test_scan.py` (update `test_build_item_payload_shape`, `test_run_findings_wake`, `test_findings_reescalate_until_recorded`)

**Interfaces:**
- Consumes: `financial_health` (T3), `fetch_attachments_text` (T4), `fetch_financial_report_text` (T5).
- Produces: `build_item_payload(d, c, metrics, health, pdf_text, fin_report_text, chart_path) -> dict` adds keys `health`, `fin_report_text`.

- [ ] **Step 1: Update the failing tests**

In `tests/test_scan.py`, REPLACE `test_build_item_payload_shape` with:
```python
def test_build_item_payload_shape():
    d = _mk(title="HMETD", ticker="BREN")
    d.id2 = "bren-1"
    d.pdf_urls = ["http://x/b.pdf"]
    c = scan.Classification(True, "rights_issue", [])
    health = {"roe": 0.2, "net_cash": True}
    pl = scan.build_item_payload(d, c, {"rsi": 58, "atr_pct": 4.1, "avg_value_idr": 1.8e11,
                                        "above_ma200": True, "vol_vs_20d": 2.3},
                                 health, pdf_text="ringkasan...",
                                 fin_report_text="laba bersih naik", chart_path="/tmp/c.png")
    assert pl["ticker"] == "BREN" and pl["ca_type"] == "rights_issue"
    assert pl["health"] == health and "laba bersih" in pl["fin_report_text"]
    assert pl["chart_path"] == "/tmp/c.png" and "ringkasan" in pl["pdf_text"]
```
In `test_run_findings_wake` AND `test_findings_reescalate_until_recorded`, REPLACE the `fetch_pdf_text` monkeypatch line with these three (so run() finds the new functions):
```python
    monkeypatch.setattr(scan, "fetch_attachments_text", lambda urls, filenames, **k: "ringkasan rights issue untuk ekspansi")
    monkeypatch.setattr(scan, "financial_health", lambda t: {"roe": 0.2, "net_cash": True, "ni_ttm": 1e9})
    monkeypatch.setattr(scan, "fetch_financial_report_text", lambda t, **k: "laporan keuangan sehat")
```
And add an assertion in `test_run_findings_wake` after the items check:
```python
    assert res["items"][0]["health"]["roe"] == 0.2
    assert "laporan keuangan" in res["items"][0]["fin_report_text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYT -m pytest -q -k "build_item_payload_shape or run_findings_wake or reescalate"`
Expected: FAIL (build_item_payload got unexpected/positional mismatch; run() still calls fetch_pdf_text).

- [ ] **Step 3: Implement**

In `bin/scan.py`, change `build_item_payload` (~line 228) to:
```python
def build_item_payload(d: Disclosure, c: Classification, metrics: dict, health: dict,
                       pdf_text: str, fin_report_text: str, chart_path: str | None) -> dict:
    return {
        "id2": d.id2, "ticker": d.ticker, "title": d.title, "subject": d.subject,
        "ts": d.ts, "ca_type": c.ca_type, "red_flags": c.red_flags,
        "pdf_url": d.pdf_urls[0] if d.pdf_urls else None,
        "pdf_text": pdf_text[:20000] if pdf_text else "",
        "fin_report_text": fin_report_text[:8000] if fin_report_text else "",
        "metrics": metrics, "health": health, "chart_path": chart_path,
    }
```
In `run()`, replace the interesting-loop body (~line 492-503, the `for d, c in interesting:` block) so it computes health + multi-attachment text + fin report:
```python
    for d, c in interesting:
        metrics = market_metrics(d.ticker)
        bad, why = disqualified(c.red_flags, metrics)
        if bad:
            mark_seen(state, d, interesting=True, scored=True, score=0, ca_type=c.ca_type)
            print(f"[skip] {d.ticker} disqualified: {why}", file=sys.stderr)
            continue
        health = financial_health(d.ticker)
        pdf_text = fetch_attachments_text(d.pdf_urls, d.filenames)
        fin_text = fetch_financial_report_text(d.ticker)
        chart = render_chart(d.ticker) if metrics.get("avg_value_idr") else None
        items_payload.append(build_item_payload(d, c, metrics, health, pdf_text, fin_text, chart))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYT -m pytest -q -k "build_item_payload_shape or run_findings_wake or reescalate"`
Expected: PASS.

- [ ] **Step 5: Full suite checkpoint**

Run: `$PYT -m pytest -q`
Expected: PASS (40).

---

### Task 7: Rewrite `SKILL.md` agent instructions + `DEPLOY.md` note

**Files:**
- Modify: `SKILL.md` (the "Your job", "Scoring rubric", "Alert format", record-score sections)
- Modify: `DEPLOY.md` (add deliver-retarget note; fix stale dev-home path)
- Test: none (docs). Checkpoint: full suite still green (no code touched).

- [ ] **Step 1: Replace the "Alert format" + "Your job" sections of `SKILL.md`**

Replace the section from `## Your job when woken with items[]` through the end of the ```` ``` ```` alert-format block with:
````markdown
## Your job when woken with items[]

For EACH item in `items[]`: score it, decide whether it clears the bar, and if so
POST it via the skill (NOT as your chat reply, which would get wrapped). Use the
item's `pdf_text` (now ALL attachments, labelled `[filename]`), `fin_report_text`
(laporan keuangan extract), `health` (yfinance fundamentals), `chart_path` (LOOK
at it), `metrics`, `ca_type`, `red_flags`, `ticker`, `title`.

### Scoring rubric (raw 0-8, max 8)
`confidence = raw/8*10`. Emoji: 🟢 raw 6-8 · 🟡 raw 4-5 · 🔴 raw 0-3.
Allocate across the lenses (Klinik Penyesalan Days 1-7):
1. **Owner intent / cui bono (0-2)** (unchanged from prior doctrine).
2. **CA type & purpose (0-2)** (unchanged; run the PP 6-point check).
3. **Fundamental & NI trigger (0-1)** - now data-backed: read `health` +
   `fin_report_text`. Award the point when fundamentals plausibly support a
   re-rate (healthy balance sheet, positive NI trend, recurring revenue).
4. **Money flow + technical (0-3)** from `metrics` + the CHART (unchanged).
5. **Hard disqualifiers (veto)** - `red_flags` uma/suspend/etc (unchanged).

**Two-gate rule for 🟢 (raw 6-8):** require thesis floor (owner+purpose >= 3 of 4)
AND confirmation floor (flow/tech >= 2 of 3). Miss either -> cap 🟡.

**Financial-distress cap:** if `health` reads `weak ❌` (negative trailing NI,
NI collapse > ~50% YoY, current ratio < 1 without net cash) OR `fin_report_text`
flags going-concern, cap the alert at 🟡 (🔴 if severe) regardless of the deal.

### Posting bar (which alerts actually fire)
- 🟢 (raw 6-8): always post.
- 🟡 (raw 4-5): post ONLY if the thesis floor holds (owner+purpose >= 3 of 4).
  Otherwise SUPPRESS (do not post).
- 🔴 (raw 0-3): SUPPRESS.
- Whether posted or suppressed, you MUST `record-score` every item (below).

### How to post (clears the bar)
Build a JSON object and post it through the skill (no wrapper, chart attached):
```bash
python ~/.agents/skills/idx-ca-watch/bin/scan.py post-alert --json '{
  "emoji":"🟢","ticker":"ANTM","ca_label":"Rights issue (HMETD)",
  "conf":8.0,"raw":6,
  "deal":"<ONE line: ratio / price vs VWAP / standby buyer / use of funds>",
  "owner_intent":"BULLISH","owner_why":"<ONE clause>",
  "metrics":<copy item.metrics verbatim>,
  "health":<copy item.health verbatim>,
  "lenses":{"owner":2,"purpose":2,"fund":1,"flowtech":1},
  "gates":{"thesis":true,"confirm":true},
  "pdf_url":"<item.pdf_url>","chart_path":"<item.chart_path>"
}'
```
The skill renders the markdown and attaches the chart. Copy `metrics` and `health`
verbatim from the item (do not retype numbers); the skill formats them. Keep
`deal`, `owner_why` to ONE line each. SIMPLIFIED OUTPUT: never paragraphs.

Rendered shape (for reference, the skill builds this):
```
🟢 **ANTM** · Rights issue (HMETD) · `8.0/10` (raw `6/8`)

**Deal:** ...
**Owner:** `BULLISH`, ...
**Fundamentals:** healthy ✅ · ROE `14%` · net cash · margin `21%` · NI `+5%`

**Tech:** above MA200 ✅ · RSI `58` · liq `Rp180B/d` · ATR `3.4%`
**Score:** owner `+2` · purpose `+2` · fund `+1` · flow/tech `+1`  (thesis ✅ · confirm ✅)

⚠️ Bukan ajakan beli, DYOR · [PDF](...)
```
````
Keep the existing record-score paragraph that follows (every item must be recorded).

- [ ] **Step 2: Add the deliver-retarget note + fix the stale path in `DEPLOY.md`**

In `DEPLOY.md`, change the stale staging path `~/Documents/Projects/idx-ca-watch/` to `~/Documents/Projects/Hermes/idx-ca-watch/` (it appears in the warning box and the rsync command), and append a section:
```markdown
## 9. Deliver retarget (notification upgrade, 2026-06-27)
The agent now posts alerts itself via `scan.py post-alert`, so the cron's
`deliver` must NOT also dump the wrapped agent reply into the alert channel.
Discover the flag, then retarget:
    ~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main cron edit --help
Prefer disabling delivery if supported (e.g. `--deliver none`/`--no-deliver`);
otherwise retarget to the heartbeat channel:
    ...cron edit b49432a194d1 --deliver discord:1505162000420835388
Verify after restart: a forced run posts ONE clean alert to 1517510484025151538
and NO wrapped duplicate.
```

- [ ] **Step 3: Full suite checkpoint (docs only, code untouched)**

Run: `$PYT -m pytest -q`
Expected: PASS (40).

---

### Task 8: Deploy, retarget cron deliver, VPS verification, mirror

**Files:** none (runbook). Operates on the VPS.

- [ ] **Step 1: Deploy the skill to the VPS**

Run: `cd ~/Documents/Projects/Hermes && ./deploy.sh idx-ca-watch`
Expected: `deployed idx-ca-watch/bin/ → VPS`.

- [ ] **Step 2: VPS verify financial-report fetch + health (datacenter IP)**

Run:
```bash
ssh vps 'V=~/.local/share/uv/tools/yahoo-finance-mcp/bin/python; \
  $V -c "import sys; sys.path.insert(0,\"$HOME/.agents/skills/idx-ca-watch/bin\"); import scan; \
  print(\"finrep:\", repr(scan.fetch_financial_report_text(\"LSIP\"))[:120]); \
  print(\"health:\", scan.format_fund_line(scan.financial_health(\"LSIP\")))"'
```
Expected: `finrep:` shows real extracted text (not `''`); `health:` shows a populated `healthy ✅ ...` line.

- [ ] **Step 3: VPS verify the rendered alert + a real direct post**

Run (dry-run render, then one real post to the alert channel):
```bash
ssh vps 'V=~/.local/share/uv/tools/yahoo-finance-mcp/bin/python; B=$HOME/.agents/skills/idx-ca-watch/bin; \
  J='"'"'{"emoji":"🟢","ticker":"ANTM","ca_label":"Rights issue (HMETD)","conf":8.0,"raw":6,"deal":"deploy test","owner_intent":"BULLISH","owner_why":"deploy test","metrics":{"above_ma200":true,"rsi":58,"avg_value_idr":1.8e11,"atr_pct":3.4},"health":{"roe":0.14,"net_margin":0.21,"net_cash":true,"current_ratio":2.5,"fcf_pos":true,"ni_ttm":1e12,"ni_yoy":0.05},"lenses":{"owner":2,"purpose":2,"fund":1,"flowtech":1},"gates":{"thesis":true,"confirm":true},"pdf_url":"https://www.idx.co.id/","chart_path":""}'"'"'; \
  echo "$J" | IDX_CA_WATCH_NO_POST=1 $V $B/scan.py post-alert; \
  source <(grep ^DISCORD_BOT_TOKEN $HOME/.hermes/.env | sed "s/^/export /"); \
  echo "$J" | $V $B/scan.py post-alert'
```
Expected: dry-run prints the markdown (no `Cronjob Response`/`job_id`); the real run prints `posted` and a clean alert appears in `1517510484025151538`. Delete the test message afterward.

- [ ] **Step 4: Retarget the cron deliver (stop the double-post)**

Run `ssh vps '~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main cron edit --help'` to find the deliver flag, then apply (prefer disabling delivery; else retarget to the heartbeat channel `1505162000420835388`). Confirm with `... cron list | sed -n "/idx-ca/,/^$/p"`.
Expected: `Deliver:` no longer `discord:1517510484025151538`.

- [ ] **Step 5: Verify a real cron run end-to-end**

Trigger one run (or wait for the top of the hour) and watch both channels:
```bash
ssh vps 'IDX_CA_WATCH_NO_POST=1 ~/.hermes/scripts/idx-ca-watch.sh; tail -20 ~/.logs/idx-ca-watch.log'
```
Expected: heartbeat to `1505162000420835388`; if there are flagged items, exactly one clean alert per posted item in `1517510484025151538` and NO wrapped duplicate. Suppressed/borderline items do not appear.

- [ ] **Step 6: Mirror back to dotfiles**

Run: `~/.dotfiles/sync.sh`
Expected: the updated `idx-ca-watch` skill is mirrored into the dotfiles repo and pushed (secrets scrubbed). This is the version-control checkpoint for the whole change.

---

## Self-Review

**Spec coverage:**
- Change 1 (kill wrapper): Task 2 (`post-alert`) + Task 8 Step 4 (deliver retarget). ✓
- Change 2 (markdown format): Task 1 (`format_tech`/fund line) + Task 2 (`render_alert`) + Task 7 (SKILL.md template). ✓
- Change 3 (higher bar): Task 7 (posting-bar gating in SKILL.md; gating is the agent's job, no scan.py code needed). ✓
- Change 4 (all attachments): Task 4 + Task 6 wiring. ✓
- Change 5 (financial health + laporan keuangan + distress cap): Task 1 (verdict/line), Task 3 (yfinance), Task 5 (report PDF), Task 6 (payload), Task 7 (distress cap rule). ✓

**Placeholder scan:** No "TBD"/"handle errors"; every code step shows full code. The one discovery step (Task 8 Step 4, `cron edit --help`) is an intentional CLI-probe in a runbook task, with both concrete fallbacks given.

**Type consistency:** `build_item_payload(d, c, metrics, health, pdf_text, fin_report_text, chart_path)` is defined in Task 6 and matched in its test and the `run()` call. `render_alert` field names match the SKILL.md JSON (Task 7) and the test (Task 2). `health_verdict`/`format_fund_line` keys (`roe, net_margin, net_cash, current_ratio, fcf_pos, ni_ttm, ni_yoy`) match `financial_health`'s output (Task 3). `metrics` keys (`above_ma200, rsi, avg_value_idr, atr_pct`) match `market_metrics` and `format_tech`.
