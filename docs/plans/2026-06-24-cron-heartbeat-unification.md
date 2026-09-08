# Cron Heartbeat Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give all four Hermes crons that report to #hermes (`1505162000420835388`) one identical heartbeat skeleton so the feed is scannable and a missing/degraded heartbeat is obvious.

**Architecture:** Each cron builds its heartbeat from the same canonical template (one short helper, copied identically per cron — they share no venv/package). No alert/embed/digest payloads change — only the heartbeat line.

**Tech Stack:** Python 3.11 (each cron's `bin/scan.py` / `bin/send-digest`), Discord REST API, pytest (polycop + idx-ca have suites), `rsync` + ssh for deploy.

**Spec:** `~/Documents/Projects/Hermes/docs/specs/2026-06-24-cron-heartbeat-unification-design.md`

> **Execution model (updated 2026-06-24, post-reorg):** all four crons now have Mac dev dirs under `~/Documents/Projects/Hermes/`. **One workflow for all:** edit `<cron>/bin/` → `./deploy.sh <cron>` → verify. Verify on the **VPS** for idx-ca only (IDX Cloudflare). The per-task "Execution location" notes below that say "VPS-local agent" are **superseded** — only idx-ca's *verification* needs the VPS; editing is always Mac-side.

## Global Constraints

- **Canonical line:** `🫀 <name> · <HH:MM> WIB · <metric tokens> · …` — `🫀 <name>` is the first ` · `-joined segment, then `HH:MM WIB`, then each metric token. Divider is ` · ` (space-middledot-space).
- **Names (lowercase, exact):** `polycop`, `idx-ca`, `us-etf-dca`, `scele`.
- **Degraded:** append ` ⚠️` (space + warning sign) to the line **only** when the run was degraded. Clean runs carry no glyph.
- **Fatal:** `❌ <name> · <HH:MM> WIB · failed: <reason>` — replaces ad-hoc `⚠️ <skill> gagal: …` messages (polycop, idx-ca).
- **Time:** `now.strftime('%H:%M')` in WIB, 24h.
- **Heartbeat channel:** `1505162000420835388` (#hermes) for ALL four. Do not touch alert channels (`1518193391769358346` polycop, `1517510484025151538` idx-ca, `1508875806032662728` us-etf-dca) or scele's #digest (`1506195083106451576`).
- **Don't author in** `~/.dotfiles/vps/agents/skills/` — it's an `rsync --delete` mirror FROM the VPS.
- **VPS venv** for idx-ca/us-etf-dca/scele dry-runs: each skill has its own `.venv` or shares `~/.local/share/uv/tools/yahoo-finance-mcp/bin/python`; invoke each script with the interpreter from its shebang.

### Reference: the canonical builder (implement identically in each cron)

```python
def fmt_heartbeat(name: str, now, tokens: list[str], degraded: bool = False) -> str:
    segs = [f"🫀 {name}", f"{now.strftime('%H:%M')} WIB", *tokens]
    return " · ".join(segs) + (" ⚠️" if degraded else "")


def fmt_fatal(name: str, now, reason) -> str:
    return f"❌ {name} · {now.strftime('%H:%M')} WIB · failed: {reason}"
```

Token lists per cron (the only per-cron difference):
- polycop: `[f"{n_signals} signals", f"{n_passed12} passed", f"{n_hits} hits"]`
- idx-ca: `[f"{checked} checked", f"{new_count} new", f"{interesting_count} flagged"]`
- us-etf-dca: `[f"{len(results)} signals", f"{len(alert_labels)} alerts", f"sources {ok}/{ok+failed}"]`
- scele: `[f"{deadlines} deadlines", f"{new} new"]`

---

## Task 1: polymarket-signal-watch heartbeat (Mac-first → rsync)

**Execution location:** Mac dev dir, then rsync to VPS. (polycop is a market-watch cron WITH a Mac dev dir + tests — Mac-first is the prescribed flow.)

**Files:**
- Modify: `~/Documents/Projects/Hermes/polymarket-signal-watch/bin/scan.py` — `format_heartbeat` (323–325), bootstrap post (876–878), run() heartbeat call (927–929), fatal (939–941)
- Test: `~/Documents/Projects/Hermes/polymarket-signal-watch/tests/test_scan.py` — `test_format_heartbeat` (235–239), `test_run_heartbeat_and_hit` (472)
- Deploy target: VPS `~/.agents/skills/polymarket-signal-watch/bin/scan.py`

**Interfaces:**
- Produces: `format_heartbeat(now, n_signals, n_passed12, n_hits, degraded=False) -> str` returning `🫀 polycop · HH:MM WIB · {n_signals} signals · {n_passed12} passed · {n_hits} hits[ ⚠️]`

- [ ] **Step 1: Update the heartbeat tests to the new format**

In `tests/test_scan.py`, replace `test_format_heartbeat` (lines 235–239) with:

```python
def test_format_heartbeat():
    now = scan.dt.datetime(2026, 6, 21, 14, 0, tzinfo=scan.WIB)
    s = scan.format_heartbeat(now, 37, 2, 0)
    assert s == "🫀 polycop · 14:00 WIB · 37 signals · 2 passed · 0 hits"
    assert "1&2" not in s
    d = scan.format_heartbeat(now, 37, 2, 0, degraded=True)
    assert d.endswith(" ⚠️")
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/test_scan.py::test_format_heartbeat -q`
Expected: FAIL (current output is `🫀 PolyCop 14:00 WIB · … 2 passed 1&2 …`).

- [ ] **Step 3: Rewrite `format_heartbeat`**

Replace lines 323–325 with:

```python
def format_heartbeat(now: dt.datetime, n_signals: int, n_passed12: int, n_hits: int,
                     degraded: bool = False) -> str:
    segs = ["🫀 polycop", f"{now.strftime('%H:%M')} WIB",
            f"{n_signals} signals", f"{n_passed12} passed", f"{n_hits} hits"]
    return " · ".join(segs) + (" ⚠️" if degraded else "")
```

- [ ] **Step 4: Run the test, verify it PASSES**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/test_scan.py::test_format_heartbeat -q`
Expected: PASS.

- [ ] **Step 5: Wire degraded + new name into run(), bootstrap, and fatal**

In `run()`, change the heartbeat call (927–929) to pass `degraded` from failed wallet fetches:

```python
        post_discord(HEARTBEAT_CHANNEL,
                     format_heartbeat(now, len(signals), n_passed12, len(hits),
                                      degraded=bool(failed_wallets)),
                     dry_run=dry_run)
```

Change the bootstrap post (876–878) to carry the name token:

```python
            post_discord(HEARTBEAT_CHANNEL,
                         f"🫀 polycop · {now.strftime('%H:%M')} WIB · bootstrapped — "
                         f"watching from now ({now.strftime('%Y-%m-%d %H:%M')} WIB).",
                         dry_run=dry_run)
```

Change the fatal handler (939–941) to the `❌` convention:

```python
    except Exception as e:  # noqa: BLE001
        print(f"[fatal] {e}", file=sys.stderr)
        post_discord(HEARTBEAT_CHANNEL,
                     f"❌ polycop · {dt.datetime.now(WIB).strftime('%H:%M')} WIB · failed: {e}",
                     dry_run=dry)
```

- [ ] **Step 6: Update the run() heartbeat assertion test**

In `test_run_heartbeat_and_hit`, line 472, replace with:

```python
    assert any(ch == scan.HEARTBEAT_CHANNEL and c and c.startswith("🫀 polycop · ") and "1 hits" in c
               for ch, c, p in posts)  # heartbeat → 1505
```

- [ ] **Step 7: Run the full suite, verify GREEN**

Run: `cd ~/Documents/Projects/Hermes/polymarket-signal-watch && PYTHONPATH=bin python3 -m pytest tests/ -q`
Expected: all pass (was 50 tests).

- [ ] **Step 8: Deploy to VPS and verify a live dry-run**

```bash
rsync -a ~/Documents/Projects/Hermes/polymarket-signal-watch/bin/scan.py vps:.agents/skills/polymarket-signal-watch/bin/scan.py
ssh vps 'cd ~/.agents/skills/polymarket-signal-watch && POLYMARKET_SIGNAL_WATCH_NO_POST=1 python3 bin/scan.py 2>&1 | grep -i "would post\|🫀\|polycop" | head'
```
Expected: a `[dry-run] would post to 1505162000420835388: 🫀 polycop · HH:MM WIB · N signals · N passed · N hits` line.

- [ ] **Step 9: Commit (Mac dev dir is not git-tracked; back up to dotfiles mirror is done by sync.sh). Skip git here — see Task 5 for the dotfiles commit.**

---

## Task 2: idx-ca-watch heartbeat (VPS-local)

**Execution location:** VPS (`mosh vps`) — idx-ca is VPS-only, no Mac dev dir.

**Files:**
- Modify: `~/.agents/skills/idx-ca-watch/bin/scan.py` — `format_heartbeat` (221–227), bootstrap post (479–481), run() heartbeat call (507–509), fatal (530–532)

**Interfaces:**
- Produces: `format_heartbeat(now, checked, new_count, interesting_count, degraded=False) -> str` returning `🫀 idx-ca · HH:MM WIB · {checked} checked · {new_count} new · {interesting_count} flagged[ ⚠️]` — **score_counts param removed.**

- [ ] **Step 1: Rewrite `format_heartbeat` (drop the colour split)**

Replace lines 221–227 with:

```python
def format_heartbeat(now: dt.datetime, checked: int, new_count: int,
                     interesting_count: int, degraded: bool = False) -> str:
    segs = ["🫀 idx-ca", f"{now.strftime('%H:%M')} WIB",
            f"{checked} checked", f"{new_count} new", f"{interesting_count} flagged"]
    return " · ".join(segs) + (" ⚠️" if degraded else "")
```

- [ ] **Step 2: Update the call site (drop `score_counts`)**

Replace the heartbeat build at lines 507–509 with:

```python
    hb = format_heartbeat(now, checked=len(disclosures), new_count=len(new),
                          interesting_count=len(items_payload))
```

(`score_counts={"green":0,…}` is removed entirely. Note: idx-ca's deterministic pass has no partial-fetch signal — a blocked IDX fetch raises and is caught by the fatal `❌` path below, so `degraded` stays default `False` here. If `fetch_recent` later exposes a partial flag, pass it as `degraded=`.)

- [ ] **Step 3: Update bootstrap + fatal to the name/`❌` convention**

Bootstrap post (479–481) → carry the name token:

```python
        post_discord(HEARTBEAT_CHANNEL,
                     f"🫀 idx-ca · {now.strftime('%H:%M')} WIB · bootstrapped — watching from now "
                     f"({now.strftime('%Y-%m-%d %H:%M')} WIB), {len(classed)} recent filings marked seen.",
                     dry_run=dry_run)
```

Fatal (530–532) → `❌` convention:

```python
    except Exception as e:  # noqa: BLE001
        print(f"[fatal] {e}", file=sys.stderr)
        post_discord(HEARTBEAT_CHANNEL,
                     f"❌ idx-ca · {dt.datetime.now(WIB).strftime('%H:%M')} WIB · failed: {e}",
                     dry_run=dry)
```

- [ ] **Step 4: Verify a live dry-run on the VPS**

```bash
ssh vps 'cd ~/.agents/skills/idx-ca-watch && IDX_CA_WATCH_NO_POST=1 python3 bin/scan.py 2>&1 | grep -i "would post\|🫀\|idx-ca" | head'
```
Expected: `[dry-run] would post to 1505162000420835388: 🫀 idx-ca · HH:MM WIB · N checked · N new · N flagged` — and **no** `(…🟢 …🟡 …🔴)`.

- [ ] **Step 5: Confirm no other reference to the old 5-arg signature**

```bash
ssh vps 'grep -n "score_counts\|format_heartbeat\|🟢\|interesting (" ~/.agents/skills/idx-ca-watch/bin/scan.py'
```
Expected: only the new `format_heartbeat` def + its single call; no `score_counts`, no `🟢`.

---

## Task 3: us-etf-dca-watch heartbeat (VPS-local)

**Execution location:** VPS — us-etf-dca is VPS-only.

**Files:**
- Modify: `~/.agents/skills/us-etf-dca-watch/bin/scan.py` — `make_log_message` (716–765), `main` (1072–1082)

**Interfaces:**
- Consumes: `make_log_message(results, headlines, health, runtime_ny, runtime_jkt, signal_date, alert_labels)` (unchanged signature)
- Produces: the log message now **begins** with `🫀 us-etf-dca · HH:MM WIB · {len(results)} signals · {len(alert_labels)} alerts · sources {ok}/{ok+failed}[ ⚠️]` followed by a blank line, then the existing detail.

> Note: us-etf-dca is gated to the NY pre-open window (`is_preopen_alert_window`), so it posts roughly **once per day**, not hourly. Its 🫀 rides that single daily log; gated hours stay silent by design (no missing-heartbeat alarm expected off-window).

- [ ] **Step 1: Prepend the 🫀 line inside `make_log_message`**

At the top of `make_log_message`, replace the initial `lines = [...]` block (724–730) so the heartbeat is line 0:

```python
    ok = health.get("ok", 0)
    failed = health.get("failed", 0)
    total = ok + failed
    degraded = total > 0 and ok / total < 0.5
    hb_segs = ["🫀 us-etf-dca", f"{runtime_jkt.strftime('%H:%M')} WIB",
               f"{len(results)} signals", f"{len(alert_labels)} alerts", f"sources {ok}/{total}"]
    hb = " · ".join(hb_segs) + (" ⚠️" if degraded else "")
    lines = [
        hb,
        "",
        f"us-etf-dca-watch run: {runtime_jkt.strftime('%Y-%m-%d %H:%M')} WIB",
        f"Pre-open check: {runtime_ny.strftime('%Y-%m-%d %H:%M')} ET",
        f"Signal date: {signal_date} (previous US daily close)",
        "",
    ]
```

(Everything below — per-ticker `state_line`, `Sources:`, `Alert:` — stays unchanged. The `Sources:`/`Alert:` summary lines remain as the detail tail.)

- [ ] **Step 2: Add a fatal handler to `main()`**

Replace `main()` (1072–1082) so a crash posts the `❌` line to the log channel:

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-post", action="store_true", help="Print Discord posts instead of sending them")
    parser.add_argument("--force-window", action="store_true", help="Bypass the NY pre-open delivery window for manual runs")
    parser.add_argument("--force-buy", choices=sorted(WATCHLIST), help="Force a ticker into a chosen signal state for dry-run verification")
    parser.add_argument("--force-state", choices=["WAIT", "BUY", "STRONG_BUY"], help="Signal state to use with --force-buy or US_ETF_DCA_WATCH_FORCE_BUY")
    parser.add_argument("--force-alert", action="store_true", help="Bypass once-per-day alert suppression during dry-run verification")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as e:  # noqa: BLE001
        print(f"[fatal] {e}", file=sys.stderr)
        dry = args.no_post or os.getenv("US_ETF_DCA_WATCH_NO_POST") == "1"
        post_discord(
            f"❌ us-etf-dca · {now_ny().astimezone(JKT).strftime('%H:%M')} WIB · failed: {e}",
            LOG_CHANNEL_ID, dry_run=dry,
        )
        return 0
```

- [ ] **Step 3: Verify a forced dry-run shows the 🫀 line**

```bash
ssh vps 'cd ~/.agents/skills/us-etf-dca-watch && US_ETF_DCA_WATCH_NO_POST=1 python3 bin/scan.py --no-post --force-window 2>&1 | head -8'
```
Expected: first non-`[dry-run]` content line is `🫀 us-etf-dca · HH:MM WIB · 2 signals · N alerts · sources N/N`, then a blank line, then `us-etf-dca-watch run: …`.

- [ ] **Step 4: Sanity-check the degraded glyph logic**

Confirm in the dry-run output that when `Sources:` shows mostly failures (e.g. `2 ok, 10 failed/timeouts`), the 🫀 line ends with ` ⚠️`; when sources are healthy, it does not.

---

## Task 4: scele-digest liveness ping (VPS-local)

**Execution location:** VPS — scele-digest is VPS-only (LLM agent job).

**Files:**
- Modify: `~/.agents/skills/scele-digest/bin/send-digest` — add `HERMES_CHANNEL_ID`, `post_heartbeat`, `fmt_scele_heartbeat`; wire into `main()` (357–exit) success path, the dry-run preview branch, and the validation-failure (`sys.exit(5)`) branch.

**Interfaces:**
- Produces: a one-line `🫀 scele · HH:MM WIB · {deadlines} deadlines · {new} new[ ⚠️]` posted to #hermes on every real run; the rich #digest embeds are unchanged.

> Design note (no wrapper needed): if the LLM job crashes **before** `send-digest` runs, no 🫀 appears in #hermes — that absence IS the "scele broke" signal. So liveness lives entirely inside `send-digest`. `deadlines` = upcoming-deadline count; `new` = new deadlines + new announcements + todos added. "courses" is dropped (no clean payload field; it's a fixed per-semester config value that adds nothing to a liveness line).

- [ ] **Step 1: Add the channel constant + helpers**

Near the top constants (after `CHANNEL_ID = "1506195083106451576"`, ~line 22), add:

```python
HERMES_CHANNEL_ID = "1505162000420835388"  # #hermes heartbeat firehose
```

Add these functions (anywhere above `main`, e.g. after `post_discord`):

```python
def post_heartbeat(text):
    """Post a one-line liveness heartbeat to #hermes. Best-effort: never raises."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return
    requests.post(
        f"{API_BASE}/channels/{HERMES_CHANNEL_ID}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"content": text},
        timeout=15,
    )


def fmt_scele_heartbeat(payload, *, degraded=False):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=7)))  # WIB
    ni = payload.get("new_items", {}) or {}
    deadlines = len(payload.get("upcoming_deadlines") or [])
    new = (len(ni.get("deadlines", []))
           + len(ni.get("announcements", []))
           + len(payload.get("todos_added", [])))
    health = payload.get("health") or {}
    degraded = degraded or any(health.get(k) is False for k in CORE_HEALTH_KEYS)
    segs = ["🫀 scele", f"{now.strftime('%H:%M')} WIB",
            f"{deadlines} deadlines", f"{new} new"]
    return " · ".join(segs) + (" ⚠️" if degraded else "")
```

- [ ] **Step 2: Print the heartbeat in the dry-run/validate branch (testable without posting)**

In `main()`, inside `if dry_run or validate_only:` (after the existing `print(f"    embeds: …")`), add:

```python
        print(f"    heartbeat: {fmt_scele_heartbeat(payload)}")
```

- [ ] **Step 3: Post degraded heartbeat on validation failure (before exit 5)**

In `main()`, in the `if validation_errors:` block, before `sys.exit(5)`, add:

```python
        try:
            post_heartbeat(fmt_scele_heartbeat(payload, degraded=True))
        except Exception as e:  # noqa: BLE001
            print(f"WARN: heartbeat post failed: {e}", file=sys.stderr)
```

- [ ] **Step 4: Post heartbeat on the success path (after the #digest post)**

In `main()`, after `print(f"OK: posted {msg_id}")`, add:

```python
    try:
        post_heartbeat(fmt_scele_heartbeat(payload))
    except Exception as e:  # noqa: BLE001
        print(f"WARN: heartbeat post failed: {e}", file=sys.stderr)
```

- [ ] **Step 5: Verify with a sample payload (dry-run, no posting)**

Use the last preview if present, else a minimal payload:

```bash
ssh vps 'cd ~/.agents/skills/scele-digest && \
  printf "%s" "{\"run_date_display\":\"24 Jun\",\"health\":{\"scele\":true,\"telegram\":true,\"todoist\":true},\"new_items\":{\"deadlines\":[1],\"announcements\":[1,1]},\"todos_added\":[1,1],\"upcoming_deadlines\":[1,1,1]}" \
  | ./bin/send-digest --dry-run 2>&1 | grep -i "heartbeat\|OK"'
```
Expected: `    heartbeat: 🫀 scele · HH:MM WIB · 3 deadlines · 5 new` (no ⚠️ since health all true).

- [ ] **Step 6: Verify the degraded glyph**

Re-run Step 5 with `"todoist":false` in health. Expected: the printed heartbeat ends with ` ⚠️`.

---

## Task 5: Update AGENTS.md on both machines + commit dotfiles

**Execution location:** Mac edits the canonical `~/.agents/AGENTS.md` (symlinked to `~/.claude/CLAUDE.md`); VPS edits its own `~/.agents/AGENTS.md` over ssh (the prescribed method for VPS instruction files). Then back up + commit the dotfiles repo.

**Files:**
- Modify: `~/.agents/AGENTS.md` (Mac)
- Modify: VPS `~/.agents/AGENTS.md` (via ssh)
- Modify: `~/.dotfiles/mac/agents/AGENTS.md` (backup copy), `~/.dotfiles/vps/agents/AGENTS.md` (backup copy)

- [x] **Step 1: Correct the #digest/#hermes mislabel + document the heartbeat format + add the Dashboard note (Mac) — DONE 2026-06-24**

Done in `~/.agents/AGENTS.md` (Hermes section): (a) heartbeat-rule bullet now labels `1505162000420835388` as **#hermes** and states the canonical line `🫀 <name> · HH:MM WIB · <tokens>[ ⚠️]` + fatal `❌ <name> · HH:MM WIB · failed: …` + the four names + spec path; (b) a new **## Dashboard** subsection for `hermes.abhipraya.dev` (auth model, serving `:443`→`:9119`, config locations, recovery); (c) a Dashboard status row; (d) the "expose ports" Don't bullet now covers the dashboard's public route + UFW-blocked `:9119` + no `--insecure`.

- [ ] **Step 2: Apply the SAME edits to the VPS copy (heartbeat note + #hermes fix + Dashboard subsection)**

```bash
ssh vps 'cp ~/.agents/AGENTS.md ~/.agents/AGENTS.md.bak-heartbeat-$(date +%Y%m%d)'
```
Then edit VPS `~/.agents/AGENTS.md` to match the Mac copy: the #hermes heartbeat note, the **## Dashboard** subsection (copy verbatim from the Mac AGENTS.md — same dashboard facts), the dashboard status row, and the updated "expose ports" Don't bullet. Keep the VPS-specific framing already there. (Reference the Mac copy for exact text: `~/.dotfiles/mac/agents/AGENTS.md` after the next sync.)

- [ ] **Step 3: Back up both into the dotfiles repo**

```bash
cp ~/.agents/AGENTS.md ~/.dotfiles/mac/agents/AGENTS.md
scp vps:.agents/AGENTS.md ~/.dotfiles/vps/agents/AGENTS.md
```

- [ ] **Step 4: Commit the spec, plan, the deployed cron mirrors, and AGENTS.md backups**

```bash
cd ~/.dotfiles && git add docs/superpowers mac/agents/AGENTS.md vps/agents/AGENTS.md && \
  git status --short
```
(Note: idx-ca/us-etf-dca/scele changes reach `vps/agents/skills/` only via the next `sync.sh` mirror FROM the VPS — do not hand-edit them here.) Commit with a clear message; push only when the user asks (per CLAUDE.md git rule).

- [ ] **Step 5: Final cross-feed verification (after a real hour rolls over)**

```bash
~/.agents/skills/discord/bin/dch 1505162000420835388 --limit 12
```
Expected: `🫀 polycop · …`, `🫀 idx-ca · …` (no colour split) within the hour; `🫀 us-etf-dca · …` after its next pre-open run; `🫀 scele · …` after its next daily run. No `🫀 PolyCop` (capital), no `(0🟢 0🟡 0🔴)`.

---

## Notes / out of scope
- No change to alert embeds, the scele rich digest, or cron scheduling/modes.
- idx-ca "degraded" is reserved (always `False`) until `fetch_recent` exposes a partial-fetch flag; hard blocks surface via the `❌` fatal path.
- Each cron carries its own copy of the canonical line construction (no shared import) — if the format changes, update the spec and all four.
