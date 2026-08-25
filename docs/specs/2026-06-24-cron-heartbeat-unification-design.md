# Hermes cron heartbeat unification — design

**Date:** 2026-06-24
**Status:** approved (design); plan + execution to follow
**Scope owner:** Abhip / Yanto (Hermes Agent, VPS)

## Goal

Give every Hermes cron that reports to the **#hermes** channel a single,
identical heartbeat skeleton, so the feed is scannable at a glance and a
*missing* or *degraded* heartbeat is immediately obvious.

## Channel facts (important — the names are misleading)

| Channel | ID | Real name | Role |
|---|---|---|---|
| heartbeat firehose | `1505162000420835388` | **#hermes** | where the hourly crons drop `🫀` lines |
| scele rich digest | `1506195083106451576` | **#digest** | where scele-digest posts its daily multi-embed digest |

All heartbeats in this design go to **#hermes `1505162000420835388`**.

## Crons in scope

Five scheduled workflows emit a heartbeat to #hermes:

| Cron | Type | Cadence | Mac dev dir | Verify |
|---|---|---|---|---|
| `polymarket-signal-watch` | no-agent deterministic | every 5 minutes, hourly heartbeat | `~/Documents/Projects/Hermes/polymarket-signal-watch/` | Mac tests; live run needs the VPS Telethon session |
| `idx-ca-watch` | deterministic collection plus agent scoring | hourly | `~/Documents/Projects/Hermes/idx-ca-watch/` | VPS network verification because IDX blocks non-datacenter IPs |
| `us-etf-dca-watch` | no-agent deterministic | `0 19-23,0-4 * * 1-5` WIB | `~/Documents/Projects/Hermes/us-etf-dca-watch/` | Mac tests and yfinance dry-run |
| `idx-swing-watch` | no-agent deterministic | every minute | `~/Documents/Projects/Hermes/idx-swing-watch/` | Mac tests; live run needs the VPS Telethon session |
| `scele-digest` | LLM agent job | daily around 07:00 WIB | `~/Documents/Projects/Hermes/scele-digest/` | Mac deterministic renderer |

> Execution note: all five workflows have Mac dev
> dirs under `~/Documents/Projects/Hermes/` — **one workflow for all**: edit
> `<cron>/bin/` → `./deploy.sh <cron>` (rsync to VPS) → verify. This is the
> sanctioned market-watch flow (edit on Mac, rsync to VPS), distinct from the
> AGENTS.md "edit Yanto runtime on the VPS" rule which covers `~/.hermes`. Only
> idx-ca's *verification* (not editing) must run on the VPS.

## The canonical heartbeat line

```
🫀 <name> · <HH:MM> WIB · <metric tokens> · <headline>[ ⚠️]
   [optional detail lines below — only crons that have them]
```

- **`🫀`** — shared liveness prefix.
- **`<name>`** — lowercase short id: `idx-ca`, `polymarket-signal`, `us-etf-dca`, `idx-swing`, `scele`.
- **`<HH:MM> WIB`** — actual run time, 24h.
- **metric tokens** — each `<number> <noun>`, ` · `-separated.
- **headline** — the one number that matters (hits / alerts / flagged / new).
- **` ⚠️`** — appended **only when the run was degraded** (see rules). Clean runs
  stay clean, so `⚠️` always means "look here."
- divider is the middle dot `·` (the existing majority). The `|` divider stays
  only inside the polycop *embed*, not the heartbeat.

### Three states, one convention

| State | Shape | When |
|---|---|---|
| **alive** | `🫀 <name> · HH:MM WIB · … · <headline>` | normal run |
| **degraded** | `🫀 <name> · HH:MM WIB · … · <headline> ⚠️` | ran, but partial / non-fatal error caught / core-health check failed |
| **fatal** | `❌ <name> · HH:MM WIB · failed: <short reason>` | crashed before producing a heartbeat (replaces ad-hoc messages like `⚠️ polymarket-signal gagal: …`) |

## Per-cron mapping

```
🫀 idx-ca            · 13:00 WIB · 1 checked · 1 new · 0 flagged
🫀 polymarket-signal · 14:00 WIB · 86 signals · 3 passed · 3 hits
🫀 us-etf-dca        · 19:20 WIB · 2 signals · 0 alerts · sources 2/12 ⚠️
   QQQ WAIT 2/8 · SPY WAIT 3/8
   (news headlines below, as today)
🫀 idx-swing         · 14:01 WIB · 0 messages · 0 calls · 0 delivered · 0 pending
🫀 scele             · 07:06 WIB · 4 courses · 2 deadlines · 5 new
```

### idx-ca-watch
- Current: `🫀 13:00 WIB · checked 1 · 1 new · 0 interesting (0🟢 0🟡 0🔴)`
- New: `🫀 idx-ca · 13:00 WIB · 1 checked · 1 new · 0 flagged`
- Changes: add `idx-ca` name token; `interesting` → `flagged`;
  **drop the `(0🟢 0🟡 0🔴)` colour split entirely.**
  - Rationale: the colours are the agent's per-CA verdict (🟢 worth it / 🟡
    borderline / 🔴 AVOID), scored 0–8 by the Klinik Penyesalan rubric in a
    **later agent turn**. At heartbeat time the counts are hardcoded to zero
    (`scan.py` ~line 509: `score_counts={"green":0,"yellow":0,"red":0}`), so they
    have **never carried information**. The real verdict colours appear in the
    scored alert posted to #id-stocks (`1517510484025151538`). Dropping them from
    the heartbeat loses nothing.
- `⚠️` when: the IDX fetch was blocked/partial (Cloudflare / network) or `checked`
  is below the expected universe.
- Files: VPS `~/.agents/skills/idx-ca-watch/bin/scan.py` — `format_heartbeat()`
  (~line 222) + its call site (~line 506–509).

### polymarket-signal-watch
- Current canonical form: `🫀 polymarket-signal · 14:00 WIB · 86 signals · 3 passed · 3 hits`
- The runtime name is `polymarket-signal-watch`; the heartbeat drops `-watch`, matching the other watcher labels.
- `⚠️` when: Telegram fetch failed, or AI-metrics / PolyCop bot response was
  unavailable for a candidate (non-fatal — run still completed).
- Files: Mac dev `~/Documents/Projects/Hermes/polymarket-signal-watch/bin/scan.py` —
  `format_heartbeat()` (~line 324), bootstrap (~line 877), post (~line 927);
  plus `tests/test_scan.py`. Then rsync to VPS
  `~/.agents/skills/polymarket-signal-watch/bin/scan.py`.

### us-etf-dca-watch
- Current: multi-line log, **no `🫀`** —
  `us-etf-dca-watch run: 2026-06-22 19:20 WIB` / `Alert: none` /
  `Sources: 2 ok, 10 failed/timeouts`, plus a separate `QQQ: WAIT 2/8 … SPY: WAIT
  3/8` pre-open block and AP Politics headlines.
- New: gains the canonical `🫀` **top line** it currently lacks:
  `🫀 us-etf-dca · 19:20 WIB · <N> signals · <N> alerts · sources <ok>/<total>`
  - The WAIT analysis + news stay as **detail lines below** the 🫀 line (decision:
    keep as today).
- `⚠️` when: sources are mostly failing (today's `2 ok, 10 failed` → degraded). Use
  a threshold (e.g. ok/total < ~0.5, exact cutoff decided in the plan).
- Files: VPS `~/.agents/skills/us-etf-dca-watch/bin/scan.py` (+ `watchdog.py`).

### idx-swing-watch
- Canonical form: `🫀 idx-swing · HH:MM WIB · <messages> messages · <calls> calls · <delivered> delivered · <pending> pending`
- `⚠️` when the run degrades or durable outbox work remains pending.
- Files: Mac dev `~/Documents/Projects/Hermes/idx-swing-watch/bin/scan.py`, deployed to VPS `~/.agents/skills/idx-swing-watch/bin/scan.py`.

### scele-digest (new: liveness only in #hermes)
- Today: posts a rich daily multi-embed digest to **#digest** (`1506195083106451576`)
  via `bin/send-digest`. **Posts nothing to #hermes.**
- New: **additionally** post one liveness `🫀` line to #hermes each run; the rich
  digest in #digest is **unchanged**.
  - Proposed: `🫀 scele · 07:06 WIB · 4 courses · 2 deadlines · 5 new`
    (tokens to be confirmed against the SKILL.md step-8 payload during the plan:
    `courses` count, `deadlines` count, `new` = newly-flagged announcements/messages).
  - `⚠️` when: any core-health key is down — `send-digest` already tracks
    `CORE_HEALTH_KEYS = ("scele", "telegram", "todoist")`.
- Because scele is an **LLM agent job**, a mid-run failure could abort before the
  heartbeat. The liveness ping must therefore fire from a **wrapper** around the
  job (or as the cron's final guaranteed step), so that:
  - success → `🫀 scele · … · <metrics>`
  - the job ran but a core-health key failed → `🫀 scele · … ⚠️`
  - the job crashed → `❌ scele · HH:MM WIB · failed: <reason>`
  - Exact wrapper mechanism (shell wrapper vs. an always-run final step vs. Hermes
    cron post-hook) is a plan decision.
- Files: VPS `~/.agents/skills/scele-digest/` — `SKILL.md` workflow + `bin/send-digest`
  (or a new `bin/heartbeat` helper) + the Hermes cron wrapper.

## Shared format helper

The crons do **not** share a venv or package, and live across two machines
(polycop Mac-first; the rest VPS-only). A single imported module is therefore
fragile. Instead:

- This spec is the **single source of truth** for the format.
- Each cron carries a small **identical** self-contained helper, e.g.
  `fmt_heartbeat(name, run_dt, tokens: list[str], headline: str, degraded: bool) -> str`
  returning the canonical string, plus a matching `fmt_fatal(name, run_dt, reason)`.
- Keeping the helper ~15 lines and identical across crons trades a little
  duplication for zero cross-machine/cross-venv coupling. If the format ever
  changes, update this spec and each copy.

## Out of scope

- scele-digest's rich #digest embeds (format, gradient, content) — unchanged.
- Alert payloads/embeds for any cron (polycop embed, idx-ca scored alert,
  us-etf-dca alerts) — unchanged; only the heartbeat line changes.
- Migrating crons between agent / no_agent modes.
- The AGENTS.md "#digest" mislabel for `1505162000420835388` — worth correcting in
  AGENTS.md as a small follow-up, but not part of this change.

## Acceptance

- All four crons emit the canonical `🫀 <name> · HH:MM WIB · … · <headline>` line to
  #hermes, lowercase name tokens, `·` divider.
- `⚠️` appears only on degraded runs; `❌ … failed: …` replaces ad-hoc fatal msgs.
- idx-ca no longer prints the `(0🟢 0🟡 0🔴)` split.
- us-etf-dca has a `🫀` top line with WAIT/news detail beneath.
- scele drops a liveness `🫀` in #hermes every run; its #digest digest is unchanged.
- polycop tests updated and green; the other crons verified by a real run
  (`rc=0`, correct line in #hermes) on the VPS.
