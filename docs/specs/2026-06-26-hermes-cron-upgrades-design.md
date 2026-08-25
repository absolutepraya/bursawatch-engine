# Hermes cron upgrades — Design

**Date:** 2026-06-26
**Status:** Approved design, ready for implementation plan
**Scope:** 3 changes across 2 Hermes crons (`polymarket-signal-watch`, `us-etf-dca-watch`). Dev homes at `~/Documents/Projects/Hermes/<cron>/`; deploy to VPS `~/.agents/skills/<cron>/` via `./deploy.sh <cron>`; verify on VPS.

---

## Change 1 — polymarket-signal-watch runs every 5 minutes

**Goal:** pick up PolyCop signals 12× faster (it's deterministic + no-LLM, so ~free), without flooding #hermes with heartbeats.

- **Schedule:** Hermes cron `b8d771654461` `0 * * * *` → `*/5 * * * *`.
- **Heartbeat decoupled from run rate.** `bin/scan.py` posts the `🫀 polycop` heartbeat in `run()` (~line 928–931 via `format_heartbeat`). Gate that post so it only fires on the **top-of-hour run** (`now.minute == 0`). The other 11 runs/hour stay silent **unless** they have a scored hit (→ alert channel `1518193391769358346`) or an error (→ #hermes `1505162000420835388`). Net: still ~24 heartbeats/day, same as today; "missing heartbeat = broken" still holds at hourly granularity. The bootstrap heartbeat (~line 876–880) is unaffected.
- **No rate-limit risk:** the Telethon session reads the channel every 5 min (cheap) and only DMs the Tokyo/NY bots for **new, deduped** signals (state cache `mark_processed`), which are infrequent. No double-alerts (dedup already records processed signals).

---

## Change 2 — US ETF: chart image posts right after each ticker's text

**Goal:** the chart for a ticker arrives immediately after that ticker's text alert, not minutes later.

**Root cause:** `post_buy_alerts` (`us-etf-dca-watch/bin/scan.py:896–916`) posts **all** text alerts in a first loop, then in a **second** loop generates each chart (`generate_chart`, a subprocess up to 45s each) and posts it. So all text lands first and charts trickle in afterward.

**Fix:** restructure `post_buy_alerts` into a single per-ticker loop: for each triggered symbol → `generate_chart(res)` **first** (so the image is ready), then `post_discord(text)`; only if the text posts OK, immediately `post_discord_file(chart)` (or the "Chart failed" fallback), then move to the next ticker. Preserve the existing rule that suppression is recorded only for symbols whose **text** posted (charts that fail don't block suppression). Result per ticker: `[few-sec gen] → text → chart (immediate)`.

---

## Change 3 — US ETF becomes an intraday live-price monitor

**Goal:** instead of a once-a-day pre-open prep signal, ping the moment a ticker dips into a buy zone during the day, with looser thresholds.

### Mode + schedule
- **Cron hourly**, windowed to cover pre-open + RTH across DST: `20,35,50 19,20 * * 1-5` → `0 19-23,0-4 * * 1-5` (WIB). The script **self-gates** (ET-based, DST-safe) and exits early when out of window, so off-window firings are cheap.
- **Two in-script windows** (generalize `is_preopen_alert_window`, scan.py:239):
  - **Pre-open prep** (08:15–09:00 ET) — keep today's behavior: prior-daily-candle signal + pre-open **chase guard**, posts the daily compact log to #hermes (this log doubles as the daily heartbeat).
  - **Intraday** (RTH 09:30–16:00 ET) — new: live-price classification, **no** chase guard, silent on #hermes (alerts only).

### Live-price scoring
- Add a "latest intraday price" fetch (generalize `latest_preopen_price`, scan.py:345, to return the most recent price during RTH).
- In `score_ticker` (scan.py:440), the gap/pullback metrics currently use the prior daily **close** `d_close.iloc[-1]` (scan.py:478–481). For **intraday** runs, substitute the **live price** as the "current price" against the daily-derived levels (EMA20/50/200, 20-day high, RSI all still computed from the daily series). Pre-open runs keep using the daily close (unchanged).

### Looser thresholds (tune later)
Current → new (in `score_ticker`, scan.py:~490–517):
- BUY pullback gate `pullback_20d_pct >= 3` → **`>= 2`** (scan.py:509).
- STRONG BUY deeper-pullback gate (~`>= 6`) → **`>= 4`** (the "deeper pullback window" branch ~scan.py:517).
- Relax the overheated/RSI guard a touch (scan.py:490, `RSI > 60 or ema20_gap > 2`) so small intraday dips aren't blocked, e.g. RSI guard `> 65`, ema20 stretch `> 3`. (EMA20/EMA50 proximity gates at scan.py:497/503 stay.)
- These are starting values; easy to tune in the plan.

### Suppression — once per ticker per **state** per day
- Extend the per-ticker state (`update_alert_state`, scan.py:959; `mark_alerts_posted`) from per-ticker-per-day to **per-ticker-per-state-per-day**: track `buy_date` and `strong_buy_date` separately so BUY fires once/day and STRONG BUY fires once/day, and a STRONG BUY can still fire after a BUY already did (an upgrade). Resets daily. Suppression still recorded only after a successful text post.

### Channels / heartbeat (unchanged cadence)
- Alerts → `1508875806032662728` (BUY channel). Daily pre-open log → `1505162000420835388` (#hermes), serves as the daily heartbeat. Intraday runs post nothing to #hermes unless a BUY/STRONG BUY fires or an error occurs.

---

## Files touched

| File | Changes |
|---|---|
| Hermes cron (VPS, `hermes cron`) | polycop schedule → `*/5 * * * *`; us-etf-dca schedule → `0 19-23,0-4 * * 1-5` |
| `polymarket-signal-watch/bin/scan.py` | gate heartbeat post on `now.minute == 0` |
| `us-etf-dca-watch/bin/scan.py` | `post_buy_alerts` per-ticker interleave (Change 2); intraday window + live-price scoring + looser thresholds + per-state suppression + chase-guard only pre-open (Change 3) |
| `us-etf-dca-watch/bin/watchdog.py` / `us-etf-dca-health` | re-align the health/watchdog window if it assumes the old schedule |
| `us-etf-dca-watch/SKILL.md`, `polymarket-signal-watch/SKILL.md` | doc the new behavior |
| tests (`us-etf-dca-watch/tests/`, `polymarket-signal-watch/tests/`) | per-state suppression, intraday scoring, window gating, heartbeat gating, per-ticker text→chart order |

## Testing
- polycop: unit-test heartbeat fires only at `minute==0`; hits/errors still post off-hour. `POLYMARKET_SIGNAL_WATCH_NO_POST=1` dry run.
- us-etf-dca: dry-run with `US_ETF_DCA_WATCH_NO_POST=1` + `FORCE_WINDOW`/`FORCE_BUY`/`FORCE_STATE`/`FORCE_ALERT`; assert per-ticker order is text→chart→text→chart; assert per-state suppression (BUY then STRONG BUY same day both fire; second BUY suppressed); assert intraday scoring uses live price vs daily levels; assert pre-open run still uses chase guard. Tests run on the VPS shared venv (idx-ca pattern) where needed.

## Deploy / verify
- Edit dev homes → `./deploy.sh <cron>` → update the two Hermes cron schedules on the VPS → verify a forced dry run posts correctly → `sync.sh` mirrors skills back to dotfiles.
- Dev home `~/Documents/Projects/Hermes/` is not a git repo (spec saved, not committed), consistent with the other cron docs there.

## Risks / notes
- Intraday yfinance pricing is delayed/best-effort; fine for a DCA prep nudge (already caveated in SKILL.md).
- Off-window hourly firings must gate **before** any yfinance work so they're cheap.
- Looser thresholds = more alerts; per-state-per-day suppression keeps it bounded to ≤2 alerts/ticker/day.
