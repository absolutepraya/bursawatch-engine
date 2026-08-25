# Hermes cron upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make polymarket-signal-watch run every 5 min (without flooding #hermes), make the US-ETF chart post right after each ticker's text, and turn the US-ETF cron into an intraday live-price monitor with looser thresholds and once-per-state-per-day alerts.

**Architecture:** Two deterministic Python cron scanners (`polymarket-signal-watch/bin/scan.py`, `us-etf-dca-watch/bin/scan.py`). Edit in the Mac dev home `~/Documents/Projects/Hermes/<cron>/`, deploy with `./deploy.sh <cron>` to VPS `~/.agents/skills/<cron>/`, change the two Hermes cron schedules on the VPS, verify with dry-run flags, `sync.sh` mirrors back.

**Tech Stack:** Python 3.11, pandas/numpy/yfinance (us-etf-dca, via the yahoo-finance-mcp shared venv), Telethon (polycop), pytest.

## Global Constraints

- Schedules (verbatim): polycop `*/5 * * * *`; us-etf-dca `0 19-23,0-4 * * 1-5` (WIB, covers pre-open + RTH across DST; script self-gates).
- Heartbeat format unchanged: `🫀 <name> · HH:MM WIB · …`; polycop heartbeat only on the top-of-hour run (`now.minute == 0`).
- US-ETF looser thresholds (verbatim starting values): BUY pullback `2.0%`, STRONG pullback `4.0%`, overheated RSI `65`, overheated EMA20 stretch `3.0%`, BUY RSI ceiling `58`, STRONG RSI ceiling `48`.
- US-ETF suppression: once per ticker **per state** per signal date (BUY once, STRONG BUY once; STRONG BUY may fire after a BUY).
- US-ETF intraday runs use the live price + **no chase guard** + **no #hermes log**; the pre-open run keeps daily-close scoring + chase guard + the daily log (which doubles as the daily heartbeat).
- Dev home `~/Documents/Projects/Hermes/` is not a git repo; the per-cron commits below are optional checkpoints (run `git init` in a cron dir first if you want them, else skip the Commit steps). Deploy is the real "save".
- us-etf-dca has no existing tests; Task 2 creates `us-etf-dca-watch/tests/`.

---

## File Structure

```
~/Documents/Projects/Hermes/
├── polymarket-signal-watch/bin/scan.py        # MODIFY: gate heartbeat on minute==0
├── us-etf-dca-watch/bin/scan.py     # MODIFY: post order, thresholds, intraday, suppression
├── us-etf-dca-watch/tests/
│   ├── conftest.py                  # CREATE: import scan.py as a module
│   └── test_scan.py                 # CREATE: unit tests
├── polymarket-signal-watch/tests/test_scan.py # MODIFY: add heartbeat-gating test
└── docs/specs/2026-06-26-hermes-cron-upgrades-design.md   # (exists)
```

Hermes cron schedules live on the VPS (`hermes cron`), edited in Task 6.

---

## Task 1: polycop heartbeat fires only on the top-of-hour run

**Files:**
- Modify: `~/Documents/Projects/Hermes/polymarket-signal-watch/bin/scan.py:930-933`
- Test: `~/Documents/Projects/Hermes/polymarket-signal-watch/tests/test_scan.py`

**Interfaces:**
- Produces: heartbeat posts only when `now.minute == 0`; hits/errors still post on any run.

- [ ] **Step 1: Write the failing test**

Add to `polymarket-signal-watch/tests/test_scan.py` (use the existing module-import pattern in that file):

```python
def test_heartbeat_only_on_top_of_hour(monkeypatch):
    import scan
    posts = []
    monkeypatch.setattr(scan, "post_discord", lambda channel, *a, **k: posts.append(channel) or True)
    assert scan.should_heartbeat(_dt(13, 0)) is True
    assert scan.should_heartbeat(_dt(13, 5)) is False
    assert scan.should_heartbeat(_dt(13, 55)) is False

def _dt(h, m):
    import datetime as dt
    return dt.datetime(2026, 6, 26, h, m, tzinfo=scan.WIB if hasattr(scan, "WIB") else None)
```

- [ ] **Step 2: Run it, expect fail**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/test_scan.py::test_heartbeat_only_on_top_of_hour -q`
Expected: FAIL (`module 'scan' has no attribute 'should_heartbeat'`).

- [ ] **Step 3: Implement**

Add a tiny helper near `format_heartbeat` in `polymarket-signal-watch/bin/scan.py`:

```python
def should_heartbeat(now) -> bool:
    """Heartbeat once per hour (top-of-hour run) so a 5-min schedule does not
    flood #hermes; missing-heartbeat-means-broken still holds at hourly grain."""
    return now.minute == 0
```

Then gate the heartbeat post in `run()` (currently scan.py:930-933):

```python
        if should_heartbeat(now):
            post_discord(HEARTBEAT_CHANNEL,
                         format_heartbeat(now, len(signals), n_passed12, len(hits),
                                          degraded=bool(failed_wallets)),
                         dry_run=dry_run)
```

(Leave the bootstrap heartbeat near scan.py:879 untouched, and leave hit/error posts untouched so they still fire on every run.)

- [ ] **Step 4: Run it, expect pass**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/test_scan.py::test_heartbeat_only_on_top_of_hour -q`
Expected: PASS.

- [ ] **Step 5: Full polycop suite still green**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/ -q`
Expected: all pass.

---

## Task 2: US-ETF chart posts right after each ticker's text

**Files:**
- Modify: `~/Documents/Projects/Hermes/us-etf-dca-watch/bin/scan.py:896-916` (`post_buy_alerts`)
- Create: `~/Documents/Projects/Hermes/us-etf-dca-watch/tests/conftest.py`, `tests/test_scan.py`

**Interfaces:**
- Produces: `post_buy_alerts` posts per ticker in order: generate chart → text → chart, before the next ticker.

- [ ] **Step 1: Create the test harness**

`us-etf-dca-watch/tests/conftest.py`:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))
```

- [ ] **Step 2: Write the failing test**

`us-etf-dca-watch/tests/test_scan.py`:
```python
import scan

def test_post_order_is_text_then_chart_per_ticker(monkeypatch):
    events = []
    monkeypatch.setattr(scan, "post_discord", lambda content, ch, dry_run: events.append(("text", content.split("**")[1] if "**" in content else content)) or True)
    monkeypatch.setattr(scan, "post_discord_file", lambda path, ch, dry_run: events.append(("chart", path)) or True)
    monkeypatch.setattr(scan, "generate_chart", lambda res, dry_run: setattr(res, "chart_path", f"/tmp/{res.symbol}.png"))
    monkeypatch.setattr(scan, "make_alert_message", lambda res, h, hl: f"BUY setup: **{res.symbol}**")
    results = [scan.TickerResult(symbol="SPY", yf_symbol="SPY"), scan.TickerResult(symbol="QQQ", yf_symbol="QQQ")]
    scan.post_buy_alerts(results, [], {}, ["SPY", "QQQ"], dry_run=True)
    assert events == [("text", "SPY"), ("chart", "/tmp/SPY.png"), ("text", "QQQ"), ("chart", "/tmp/QQQ.png")]
```

- [ ] **Step 3: Run it, expect fail**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py::test_post_order_is_text_then_chart_per_ticker -q`
Expected: FAIL (current order is all-text then all-charts → events interleave wrong).

- [ ] **Step 4: Implement (replace `post_buy_alerts` body, scan.py:896-916)**

```python
def post_buy_alerts(results: list[TickerResult], headlines: list[dict[str, str]], health: dict[str, int], alert_symbols: list[str], dry_run: bool) -> list[str]:
    """Per ticker: generate the chart, post the text, then post the chart
    immediately after, before moving to the next ticker. Suppression is recorded
    only for tickers whose text actually posted (charts that fail don't block it)."""
    by_symbol = {res.symbol: res for res in results}
    posted: list[str] = []
    for symbol in alert_symbols:
        res = by_symbol.get(symbol)
        if res is None:
            continue
        generate_chart(res, dry_run=dry_run)
        if not post_discord(make_alert_message(res, headlines, health), ALERT_CHANNEL_ID, dry_run=dry_run):
            continue
        posted.append(symbol)
        if res.chart_path:
            post_discord_file(res.chart_path, ALERT_CHANNEL_ID, dry_run=dry_run)
        else:
            post_discord(f"Chart failed to generate for **{res.symbol}**", ALERT_CHANNEL_ID, dry_run=dry_run)
    return posted
```

- [ ] **Step 5: Run it, expect pass**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py::test_post_order_is_text_then_chart_per_ticker -q`
Expected: PASS.

---

## Task 3: US-ETF looser thresholds via named constants

**Files:**
- Modify: `~/Documents/Projects/Hermes/us-etf-dca-watch/bin/scan.py` (constants block near the top; `score_ticker` scan.py:490-558)
- Test: `us-etf-dca-watch/tests/test_scan.py`

**Interfaces:**
- Produces: module constants `BUY_PULLBACK_PCT=2.0`, `STRONG_PULLBACK_PCT=4.0`, `OVERHEATED_RSI=65.0`, `OVERHEATED_EMA20_STRETCH=3.0`, `BUY_RSI_MAX=58.0`, `STRONG_RSI_MAX=48.0`, used throughout `score_ticker`.

- [ ] **Step 1: Write the failing test** (synthetic daily data → assert a 2.5% pullback now classifies BUY)

```python
import numpy as np, pandas as pd, datetime as dt

def _synthetic_daily(last_price):
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    base = np.linspace(100, 130, 260)
    base[-1] = last_price
    return pd.DataFrame({"Close": base, "Open": base, "High": base, "Low": base, "Volume": 1e6}, index=idx)

def test_buy_triggers_at_2pct_pullback(monkeypatch):
    daily = _synthetic_daily(last_price=130.0)         # last close = 20D high
    monkeypatch.setattr(scan, "latest_completed_daily", lambda sym, now: daily)
    now = dt.datetime(2026, 6, 26, 9, 0, tzinfo=scan.NY)
    # live price 2.5% below the 20D high → BUY under loosened (2%) but WAIT under old (3%)
    res = scan.score_ticker("SPY", scan.WATCHLIST["SPY"], current_ny=now, live_price=130.0 * 0.975)
    assert res.state == "BUY"
```

- [ ] **Step 2: Run it, expect fail**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py::test_buy_triggers_at_2pct_pullback -q`
Expected: FAIL (`score_ticker() got an unexpected keyword argument 'live_price'` — added in Task 4) **OR**, if Task 4 done first, FAIL because 2.5% < old 3% threshold = WAIT. (Do Task 4 before Task 3's test passes; see ordering note at bottom.)

- [ ] **Step 3: Add the constants** (near the other module constants at the top of scan.py)

```python
# --- DCA signal thresholds (looser = more sensitive; tune here) ---
BUY_PULLBACK_PCT = 2.0          # % below 20D high to count as a BUY pullback (was 3.0)
STRONG_PULLBACK_PCT = 4.0       # deeper pullback for STRONG BUY (was 6.0)
OVERHEATED_RSI = 65.0           # daily RSI above this = overheated/WAIT (was 60)
OVERHEATED_EMA20_STRETCH = 3.0  # % above EMA20 that blocks (was 2)
BUY_RSI_MAX = 58.0              # daily RSI ceiling for the BUY zone (was 55)
STRONG_RSI_MAX = 48.0           # daily RSI ceiling for the STRONG BUY zone (was 45)
```

- [ ] **Step 4: Replace the magic numbers in `score_ticker`**

Apply these exact substitutions (scan.py:490-558):
- L490/492 `(result.daily_rsi or 999) > 60` → `> OVERHEATED_RSI`
- L490/494 `(result.ema20_gap_pct or 0) > 2` → `> OVERHEATED_EMA20_STRETCH`
- L509 `(result.pullback_20d_pct or 0) >= 3` → `>= BUY_PULLBACK_PCT`
- L515 `(result.pullback_20d_pct or 0) >= 6` → `>= STRONG_PULLBACK_PCT`
- L519 `(result.daily_rsi or 999) <= 55` → `<= BUY_RSI_MAX`
- L525 `(result.daily_rsi or 999) <= 45` → `<= STRONG_RSI_MAX`
- L555 (STRONG state): `(result.daily_rsi or 999) <= 45` → `<= STRONG_RSI_MAX`; inner `((result.pullback_20d_pct or 0) >= 3)` → `>= BUY_PULLBACK_PCT`; `((result.pullback_20d_pct or 0) >= 6)` → `>= STRONG_PULLBACK_PCT`
- L557 (BUY state): `(result.daily_rsi or 999) <= 55` → `<= BUY_RSI_MAX`; `((result.pullback_20d_pct or 0) >= 3)` → `>= BUY_PULLBACK_PCT`

Leave the `<= 0` (EMA20) and `<= 1` (EMA50) proximity checks and the `score >= 3 / >= 5` gates as-is.

- [ ] **Step 5: Run it, expect pass** (after Task 4 lands `live_price`)

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py::test_buy_triggers_at_2pct_pullback -q`
Expected: PASS.

---

## Task 4: US-ETF intraday window + live-price scoring

**Files:**
- Modify: `~/Documents/Projects/Hermes/us-etf-dca-watch/bin/scan.py` (`score_ticker` signature scan.py:440-481; new `market_window`; `run()` scan.py:1018-1072)
- Test: `us-etf-dca-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: `latest_preopen_price(yf_symbol, now) -> (price|None, ts|None)` (reused as the live-price source during RTH).
- Produces: `market_window(now, dry_run=False, force_window=False) -> "preopen" | "intraday" | None`; `score_ticker(..., live_price: float | None = None, ...)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_market_window_classifies(monkeypatch):
    import datetime as dt
    wd = dt.datetime(2026, 6, 26, tzinfo=scan.NY)  # Friday
    assert scan.market_window(wd.replace(hour=8, minute=30)) == "preopen"
    assert scan.market_window(wd.replace(hour=11, minute=0)) == "intraday"
    assert scan.market_window(wd.replace(hour=18, minute=0)) is None
    sat = dt.datetime(2026, 6, 27, 11, 0, tzinfo=scan.NY)
    assert scan.market_window(sat) is None

def test_live_price_overrides_daily_close(monkeypatch):
    daily = _synthetic_daily(last_price=130.0)
    monkeypatch.setattr(scan, "latest_completed_daily", lambda sym, now: daily)
    now = dt.datetime(2026, 6, 26, 13, 0, tzinfo=scan.NY)
    res_daily = scan.score_ticker("SPY", scan.WATCHLIST["SPY"], current_ny=now)            # uses 130 close → WAIT
    res_live = scan.score_ticker("SPY", scan.WATCHLIST["SPY"], current_ny=now, live_price=130.0 * 0.94)  # 6% dip
    assert res_daily.state == "WAIT" and res_live.state in ("BUY", "STRONG BUY")
```

- [ ] **Step 2: Run, expect fail**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py -k "market_window or live_price" -q`
Expected: FAIL (`market_window` undefined; `live_price` kwarg unknown).

- [ ] **Step 3: Add `market_window`** (near `is_preopen_alert_window`, scan.py:239). Define RTH constants by `PREOPEN_WINDOW_*`:

```python
RTH_START = dt.time(9, 30)
RTH_END = dt.time(16, 0)

def market_window(now: dt.datetime, dry_run: bool = False, force_window: bool = False) -> str | None:
    """Return 'preopen', 'intraday', or None. Forced/dry runs behave as 'preopen'
    (full daily logic + chase guard) for deterministic test parity."""
    if dry_run or force_window or force_window_enabled():
        return "preopen"
    if now.weekday() >= 5 or now.date().isoformat() in NYSE_HOLIDAYS:
        return None
    t = now.time()
    if PREOPEN_WINDOW_START <= t < PREOPEN_WINDOW_END:
        return "preopen"
    if RTH_START <= t < RTH_END:
        return "intraday"
    return None
```

- [ ] **Step 4: Thread `live_price` into `score_ticker`**

Change the signature (scan.py:440):
```python
def score_ticker(
    symbol: str,
    cfg: dict[str, Any],
    current_ny: dt.datetime,
    live_price: float | None = None,
    force_symbol: str | None = None,
    force_state: str | None = None,
) -> TickerResult:
```

After computing `ema*_last`, `high20_last`, `signal_date` (scan.py:467-473), introduce the reference price `px` and use it for every gap/pullback metric (replace scan.py:476-482):
```python
        px = live_price if live_price is not None else safe_float(d_close.iloc[-1])
        result.signal_date = signal_date
        result.close = px
        result.daily_rsi = rsi_last
        result.ema20_gap_pct = safe_float(((px / ema20_last) - 1) * 100) if px and ema20_last else None
        result.ema50_gap_pct = safe_float(((px / ema50_last) - 1) * 100) if px and ema50_last else None
        result.ema200_gap_pct = safe_float(((px / ema200_last) - 1) * 100) if px and ema200_last else None
        result.pullback_20d_pct = safe_float((1 - (px / high20_last)) * 100) if px and high20_last else None
        result.above_ema200 = bool(px is not None and ema200_last is not None and px >= ema200_last)
        result.ema50_above_ema200 = bool(ema50_last is not None and ema200_last is not None and ema50_last >= ema200_last)
```
Update the `close is None ...` guard (scan.py:485) to check `px` instead of `close`. (The EMAs/RSI/20D-high stay daily-derived.)

- [ ] **Step 5: Wire `run()` for intraday** (scan.py:1018-1072)

Replace the gate (scan.py:1023) and scoring/guard/log sections:
```python
    window = market_window(current_ny, dry_run=dry_run, force_window=force_window)
    if window is None:
        print('{"wakeAgent": false, "gated": true}')
        return 0
    intraday = window == "intraday"
    ...
    live_prices: dict[str, float | None] = {}
    if intraday:
        for symbol, cfg in WATCHLIST.items():
            live_prices[symbol] = latest_preopen_price(cfg["yf"], current_ny)[0]
    results = [
        score_ticker(symbol, cfg, current_ny=current_ny, live_price=live_prices.get(symbol),
                     force_symbol=force_symbol, force_state=force_state)
        for symbol, cfg in WATCHLIST.items()
    ]
    signal_date = next((r.signal_date for r in results if r.signal_date), current_ny.date().isoformat())

    if not intraday:                       # chase guard only pre-open
        for result in results:
            price, ts = latest_preopen_price(result.yf_symbol, current_ny)
            apply_chase_guard(result, price, ts)
```
Then guard the daily log so it only posts on the pre-open run (wrap scan.py:1062-1068 in `if not intraday:`). The alert path (`post_buy_alerts` + `mark_alerts_posted`) stays for both windows.

- [ ] **Step 6: Run, expect pass**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py -q`
Expected: all pass (incl. Task 3's BUY-at-2% test).

---

## Task 5: US-ETF once-per-state-per-day suppression

**Files:**
- Modify: `~/Documents/Projects/Hermes/us-etf-dca-watch/bin/scan.py` (`update_alert_state` scan.py:959-983; `mark_alerts_posted` scan.py:986-992; the `mark_alerts_posted(...)` call at scan.py:1072)
- Test: `us-etf-dca-watch/tests/test_scan.py`

**Interfaces:**
- Produces: per-ticker state holds `last_alert_by_state: {"BUY": date, "STRONG BUY": date}`; `mark_alerts_posted(state, posted_symbols, results, signal_date)`.

- [ ] **Step 1: Write the failing test**

```python
def _res(symbol, state):
    r = scan.TickerResult(symbol=symbol, yf_symbol=symbol)
    r.state = state; r.base_state = state; r.signal_date = "2026-06-26"
    return r

def test_per_state_suppression():
    state = {"tickers": {}}
    d = "2026-06-26"
    syms, _ = scan.update_alert_state(state, [_res("SPY", "BUY")], d)
    assert syms == ["SPY"]
    scan.mark_alerts_posted(state, ["SPY"], [_res("SPY", "BUY")], d)
    # same BUY again same day → suppressed
    syms2, _ = scan.update_alert_state(state, [_res("SPY", "BUY")], d)
    assert syms2 == []
    # upgrade to STRONG BUY same day → still fires
    syms3, _ = scan.update_alert_state(state, [_res("SPY", "STRONG BUY")], d)
    assert syms3 == ["SPY"]
```

- [ ] **Step 2: Run, expect fail**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py::test_per_state_suppression -q`
Expected: FAIL (`mark_alerts_posted` takes 3 args / per-state key absent).

- [ ] **Step 3: Implement per-state eligibility** — replace the eligibility block in `update_alert_state` (scan.py:976-982):

```python
        by_state = item.setdefault("last_alert_by_state", {})
        if res.state in ALERTABLE_STATES:
            if force_alert or by_state.get(res.state) != signal_date:
                alert_symbols.append(res.symbol)
                alert_labels.append(f"{res.state} {res.symbol}")
            else:
                res.alerted_today = True
```

Replace `mark_alerts_posted` (scan.py:986-992):
```python
def mark_alerts_posted(state: dict[str, Any], posted_symbols: list[str], results: list[TickerResult], signal_date: str) -> None:
    """Record once-per-signal-date-per-STATE suppression for tickers that posted."""
    state_by_symbol = {r.symbol: r.state for r in results}
    ticker_state = state.setdefault("tickers", {})
    for symbol in posted_symbols:
        item = ticker_state.setdefault(symbol, {})
        by_state = item.setdefault("last_alert_by_state", {})
        st = state_by_symbol.get(symbol)
        if st:
            by_state[st] = signal_date
```

Update the call site (scan.py:1072): `mark_alerts_posted(state, posted, results, signal_date)`.

- [ ] **Step 4: Run, expect pass**

Run: `cd ~/Documents/Projects/Hermes/us-etf-dca-watch && python3 -m pytest tests/test_scan.py -q`
Expected: all pass.

---

## Task 6: Deploy, schedules, end-to-end verify, docs, mirror

**Files:**
- Modify: `polymarket-signal-watch/SKILL.md` (hourly→5-min + heartbeat note), `us-etf-dca-watch/SKILL.md` (intraday behavior, alert order, thresholds, suppression)
- VPS: Hermes cron schedules

- [ ] **Step 1: Deploy both skills**

```bash
cd ~/Documents/Projects/Hermes && ./deploy.sh polymarket-signal-watch && ./deploy.sh us-etf-dca-watch
```

- [ ] **Step 2: Dry-run verify us-etf-dca on the VPS** (forced BUY then STRONG BUY, no posting)

```bash
ssh vps 'cd ~/.agents/skills/us-etf-dca-watch && US_ETF_DCA_WATCH_NO_POST=1 US_ETF_DCA_WATCH_FORCE_WINDOW=1 US_ETF_DCA_WATCH_FORCE_BUY=SPY US_ETF_DCA_WATCH_FORCE_STATE=BUY US_ETF_DCA_WATCH_FORCE_ALERT=1 ~/.hermes/scripts/us-etf-dca-watch.sh 2>&1 | tail -30'
```
Expected: prints the SPY text alert immediately followed by its chart line (text→chart adjacency), no real Discord post.

- [ ] **Step 3: Dry-run verify polycop heartbeat gating**

```bash
ssh vps 'cd ~/.agents/skills/polymarket-signal-watch && POLYMARKET_SIGNAL_WATCH_NO_POST=1 ~/.hermes/scripts/polymarket-signal-watch.sh 2>&1 | tail -20'
```
Expected: runs clean; heartbeat line printed only if the current minute is `00` (else no heartbeat line, just the scan summary).

- [ ] **Step 4: Update the two Hermes cron schedules** (IDs from `hermes cron list`: polycop `b8d771654461`, us-etf-dca `7d7239aec4d2`)

```bash
ssh vps 'HCLI="$HOME/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main"; $HCLI cron --help 2>&1 | grep -iE "edit|update|set|schedule|remove|add"'
```
Then set polycop → `*/5 * * * *` and us-etf-dca → `0 19-23,0-4 * * 1-5` using the discovered subcommand (likely `cron update <id> --schedule` or remove+add preserving name/deliver/script/no-agent). Re-run `hermes cron list` and confirm both `Next run` values reflect the new cadence.

- [ ] **Step 5: Update SKILL.md docs** for both crons (5-min cadence + heartbeat-on-the-hour for polycop; intraday monitor, RTH+pre-open windows, text→chart order, looser thresholds, per-state suppression for us-etf-dca).

- [ ] **Step 6: Mirror to dotfiles**

```bash
~/.dotfiles/sync.sh
```
Expected: updated `polymarket-signal-watch` + `us-etf-dca-watch` skills land under dotfiles `vps/agents/skills/`, pushed, VPS pulled. (No secrets in these scripts.)

---

## Ordering note
Tasks 3 and 4 both touch `score_ticker` and Task 3's test needs the `live_price` kwarg from Task 4. **Implement Task 4 before Task 3's test passes** (or fold Task 3's constant swaps into Task 4's edit and keep them as separate review gates). Tasks 1, 2, 5 are independent.

## Notes for the implementer
- All us-etf-dca work runs in the yahoo-finance-mcp shared venv on the VPS (`~/.hermes/scripts/us-etf-dca-watch.sh` wrapper); local pytest only needs pandas/numpy (synthetic data, network monkeypatched).
- Never post to the live alert channel during tests — always `US_ETF_DCA_WATCH_NO_POST=1` or monkeypatched posters.
- If `market_window` returns `intraday` but `latest_preopen_price` yields `None` (fetch failed), `score_ticker(live_price=None)` falls back to the daily close — acceptable, no crash.
- `us-etf-dca-health`/`watchdog.py`: re-check that their expected-run cadence assumptions still hold under the new hourly schedule; adjust if they alert on "missed pre-open window".
