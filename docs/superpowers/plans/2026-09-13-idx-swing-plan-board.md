# IDX Swing Plan Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Discord forum that presents the current Phintraco cash-equity Swing plan and connected per-ticker source history, while preserving the chronological All Swing feed.

**Architecture:** A new deterministic `idx-swing-plan-board` owner exclusively writes its SQLite state and all forum Discord objects. Existing watchers finish their normal All Swing delivery first, then submit a durable source event to that owner. The owner is invoked immediately for source events, runs price reconciliation at 16:30 WIB, and performs one 17:00 WIB retry only after an unavailable initial check.

**Tech Stack:** Python 3.12, standard-library `sqlite3`, `Decimal`, `requests`, existing `yfinance`, Discord REST API v10, existing Hermes wrappers and cron registry, pytest.

**Spec:** [docs/superpowers/specs/2026-09-13-idx-swing-plan-board-design.md](../specs/2026-09-13-idx-swing-plan-board-design.md)

## Global Constraints

- Work in the dedicated `wt` worktree for this branch. Do not modify the main worktree during implementation.
- Keep `#id-stocks-swing` (`1525102458253217803`) as the All Swing source feed. A board failure must not suppress or duplicate an All message.
- Target only `#id-stocks-swing-board` (`1548273399069933720`). Do not create a live test post, reply, reaction, or bootstrap item.
- The board owner is the only writer of `~/.hermes/state/idx-swing-board.sqlite3`, its media directory, forum posts, top cards, titles, tags, history replies, and archival state.
- Primary Plan means only a complete Phintraco Daily cash-equity BUY setup. SSF never sends a board event.
- Preserve source facts. Do not infer a plan, analyst, chart, historical price state, or a member action.
- Market states are only `Below entry`, `Entry zone`, `Above entry`, `TP1 reached` through `TP6 reached`, and `Stop-loss breached`.
- Use `19 Sep 2026 16:30 WIB` formatting. Never expose internal versions.
- The lifecycle tags are exactly `Source plan`, `Primary plan`, and `Resolved`. Resolve all tag IDs by exact name and fail closed on missing or duplicated names.
- The factual market tags are exactly `Below entry`, `Entry zone`, `Above entry`, `TP1 reached`, `TP2 reached`, `TP3 reached`, `TP4 reached`, `TP5 reached`, `TP6 reached`, and `Stop-loss breached`. Resolve these by exact name too.
- A source-only episode has no price checkpoint. A resolved episode receives no retention activity and auto-archives after Discord's seven-day inactivity interval.
- Use `IDX_SWING_PLAN_BOARD_NO_POST=1` with isolated state and media paths for every board smoke test. Never reset, hand-edit, initialize, or replay production state.
- Scheduled owner commands post their own `#hermes` heartbeat and use Hermes `--deliver local` to avoid an additional raw cron response.
- Use the installed `yfinance`, `requests`, and `pandas` packages. Do not alter the shared Yahoo Finance tool environment.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `idx-swing-plan-board/bin/models.py` | Closed source-event, plan-level, checkpoint, and outbox value objects. |
| `idx-swing-plan-board/bin/calendar.py` | IDX session calendar and 20-session arithmetic. |
| `idx-swing-plan-board/bin/idx_trading_holidays.json` | Reviewed 2026 IDX exchange closures. |
| `idx-swing-plan-board/bin/store.py` | SQLite migration, idempotent intake, episode state, and outbox persistence. |
| `idx-swing-plan-board/bin/render.py` | Exact top-card, neutral card, source-reply, and managed-card content. |
| `idx-swing-plan-board/bin/discord_forum.py` | Forum thread, message, attachment, title, and tag REST operations. |
| `idx-swing-plan-board/bin/prices.py` | Yahoo current-session close fetch and threshold classification. |
| `idx-swing-plan-board/bin/engine.py` | Promotion, source-status, resolution, and checkpoint state machine. |
| `idx-swing-plan-board/bin/board.py` | `submit-source-event`, `drain`, and after-close CLI. |
| `idx-swing-plan-board/bin/idx-swing-plan-board.sh` | VPS wrapper for the owner. |
| `idx-swing-plan-board/{AGENTS.md,CRON.md,tests/}` | No-agent contract and isolated test suite. |
| `idx-swing-watch-phintraco-daily/bin/scan.py` | Ticker-first All rendering and durable post-All board handoff. |
| `kelas-investasi-gtw-watch/bin/{state.py,discord.py,scan.py}` | Post-All source-only board handoff for a GTW bundle. |
| `x-post-watch/bin/{state.py,scan.py}` | Conservative post-All source-only board handoff for X technical posts. |
| `AGENTS.md`, `README.md`, `scripts/test-all`, `tests/test_documentation_contract.py` | New cron inventory, ownership policy, complete-suite registration, and docs contract. |

## Task 1: Create closed board models and the IDX session calendar

**Files:**
- Create: `idx-swing-plan-board/AGENTS.md`
- Create: `idx-swing-plan-board/CRON.md`
- Create: `idx-swing-plan-board/bin/models.py`
- Create: `idx-swing-plan-board/bin/calendar.py`
- Create: `idx-swing-plan-board/bin/idx_trading_holidays.json`
- Create: `idx-swing-plan-board/tests/conftest.py`
- Create: `idx-swing-plan-board/tests/test_models.py`
- Create: `idx-swing-plan-board/tests/test_calendar.py`

**Interfaces:**
- Consumes: normalized source-event JSON submitted by the three existing watchers.
- Produces: `SourceEvent`, `PlanLevels`, `SourceOutcome`, `Checkpoint`, `MarketState`, `is_idx_trading_day()`, and `sessions_ago()`.

- [ ] **Step 1: Write the failing model and calendar tests**

```python
from datetime import date

from calendar import is_idx_trading_day, sessions_ago
from models import MarketState, PlanLevels, SourceEvent


def test_source_event_is_strict_and_normalizes_ticker() -> None:
    event = SourceEvent.from_json({
        "event_key": "phintraco:1444713822:33655",
        "source": "phintraco",
        "kind": "buy",
        "ticker": "scma",
        "published_at": "2026-09-19T09:05:00+07:00",
        "source_url": "https://t.me/phintraprofits/33655",
        "all_content": "### <:phintraco:1> SCMA: Buy",
        "source_title": "SCMA: Trading Buy",
        "source_status": "New setup",
        "plan": {"entry": "208 to 212", "stop_loss": "<200", "targets": ["230"]},
        "media_path": None,
        "media_urls": [],
    })
    assert event.ticker == "SCMA"
    assert event.plan == PlanLevels("208 to 212", "<200", ("230",))


def test_calendar_skips_official_closures_and_counts_sessions() -> None:
    assert is_idx_trading_day(date(2026, 3, 19)) is False
    assert is_idx_trading_day(date(2026, 3, 25)) is True
    assert sessions_ago(date(2026, 3, 25), 1) == date(2026, 3, 17)
    assert MarketState.TP3_REACHED.value == "TP3 reached"
```

- [ ] **Step 2: Run the tests and verify that imports fail**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_models.py idx-swing-plan-board/tests/test_calendar.py
```

Expected: FAIL because the project modules do not exist.

- [ ] **Step 3: Implement the closed model and calendar surface**

Create frozen `PlanLevels`, `SourceOutcome`, and `Checkpoint` dataclasses plus a `MarketState(StrEnum)` with `from_target_number(number: int) -> MarketState`. `SourceEvent.from_json()` rejects unknown keys, naive timestamps, unsupported URL schemes, invalid media paths, unsupported kinds, and social events containing a plan. The only kinds are `buy`, `status`, `reminder`, and `social`. A BUY requires a complete `PlanLevels`; a social event must use an exact source title and cannot contain a plan. In `tests/conftest.py`, define `example_buy_event(key: str = "phintraco:1444713822:33655", ticker: str = "SCMA")` and `social_event(key: str, ticker: str, source_title: str)` by calling `SourceEvent.from_json()` with complete valid values; later tests import only these factories.

Create `idx_trading_holidays.json` with the reviewed weekday closures from the [IDX 2026 Trading Holiday announcement](https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf):

```json
{
  "2026": [
    "2026-01-01", "2026-01-16", "2026-02-16", "2026-02-17",
    "2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24",
    "2026-05-01", "2026-05-14", "2026-05-15", "2026-05-27", "2026-05-28", "2026-05-29",
    "2026-06-01", "2026-06-16", "2026-08-17", "2026-08-25",
    "2026-12-24", "2026-12-25", "2026-12-31"
  ]
}
```

Implement exactly:

```python
def is_idx_trading_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    try:
        holidays = HOLIDAYS_BY_YEAR[str(day.year)]
    except KeyError as exc:
        raise CalendarCoverageError(f"IDX holiday calendar is missing {day.year}") from exc
    return day.isoformat() not in holidays


def sessions_ago(anchor: date, count: int) -> date:
    if count < 0:
        raise ValueError("count must be non-negative")
    current = anchor
    remaining = count
    while remaining:
        current -= timedelta(days=1)
        if is_idx_trading_day(current):
            remaining -= 1
    return current
```

Raise `CalendarCoverageError` for an uncovered weekday year. The caller must warn and skip state change rather than assuming an unknown holiday is open.

- [ ] **Step 4: Write the new no-agent contracts**

State in `AGENTS.md` and `CRON.md` that the owner alone mutates SQLite and forum state, accepts only validated internal watcher events, has no LLM, posts direct heartbeats only for scheduled reconciliation, and cannot bootstrap without a separately approved command. Document `IDX_SWING_PLAN_BOARD_NO_POST=1` and that source submissions may drain the owner outbox but may not calculate a close.

- [ ] **Step 5: Run the focused tests and commit the domain slice**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_models.py idx-swing-plan-board/tests/test_calendar.py
```

Expected: PASS.

```bash
git add idx-swing-plan-board/AGENTS.md idx-swing-plan-board/CRON.md idx-swing-plan-board/bin/models.py idx-swing-plan-board/bin/calendar.py idx-swing-plan-board/bin/idx_trading_holidays.json idx-swing-plan-board/tests
git commit -m "feat: add Swing board domain model"
```

## Task 2: Add the single-owner SQLite store and retry-safe outbox

**Files:**
- Create: `idx-swing-plan-board/bin/store.py`
- Create: `idx-swing-plan-board/tests/test_store.py`
- Modify: `idx-swing-plan-board/bin/models.py`

**Interfaces:**
- Consumes: Task 1 `SourceEvent` values.
- Produces: `BoardStore.submit_event()`, `create_episode()`, `claim_due_outbox()`, `complete_outbox()`, `fail_outbox()`, `active_episode()`, and `record_checkpoint()`.

- [ ] **Step 1: Write failing idempotency and restart-safety tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import example_buy_event
from store import BoardStore

WIB = ZoneInfo("Asia/Jakarta")


def test_duplicate_source_event_is_recorded_once(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    event = example_buy_event("phintraco:1444713822:33655")
    first = store.submit_event(event, datetime(2026, 9, 19, 9, 5, tzinfo=WIB))
    second = store.submit_event(event, datetime(2026, 9, 19, 9, 6, tzinfo=WIB))
    assert first.inserted is True
    assert second.inserted is False
    assert store.count_rows("source_events") == 1
    assert store.count_rows("outbox") == 0


def test_failed_operation_retries_without_second_operation(tmp_path) -> None:
    store = BoardStore(tmp_path / "board.sqlite3")
    episode = store.create_episode("SCMA", "source", "SCMA: source context", datetime(2026, 9, 19, 9, 5, tzinfo=WIB))
    operation = store.enqueue_test_operation("create_thread", episode.id, datetime(2026, 9, 19, 9, 5, tzinfo=WIB))
    claim = store.claim_due_outbox(datetime(2026, 9, 19, 9, 5, tzinfo=WIB))
    store.fail_outbox(operation.id, claim.claim_token, "Discord request failed", datetime(2026, 9, 19, 9, 5, tzinfo=WIB))
    retry = store.claim_due_outbox(datetime(2026, 9, 19, 9, 6, tzinfo=WIB))
    assert retry.id == operation.id
    assert retry.attempts == 1
```

- [ ] **Step 2: Run the store tests and verify they fail**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_store.py
```

Expected: FAIL because `store.py` does not exist.

- [ ] **Step 3: Implement SQLite schema, migration, and transaction boundaries**

Use `sqlite3.connect(path, isolation_level=None)`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, a lock file at `<database>.lock`, and `BEGIN IMMEDIATE`. Create `source_events`, `episodes`, `plans`, `checkpoints`, `history_events`, and `outbox` tables. Enforce unique `source_events.event_key`, one open episode per ticker, one plan source event, one durable history chunk identity, and one outbox `dedupe_key`.

Only these outbox operations are legal: `create_thread`, `edit_starter`, `post_source_reply`, `post_history_reply`, and `patch_thread`. `submit_event()` atomically records only a source event. The Task 4 engine opens its own transaction to write the resulting episode transition and every required outbox intent. Neither method makes an HTTP request. `claim_due_outbox()` returns a fresh claim token, and `complete_outbox()` and `fail_outbox()` require that token so a stale worker cannot mutate reclaimed work.

Backoff is 1, 2, 4, 8, 15, 30, then 60 minutes. An unknown schema version raises `StoreBlockedError` before a write. A migration must preserve all rows and never reset a database.

- [ ] **Step 4: Add migration and corruption tests**

Add tests that a version-one database migrates with rows preserved, a duplicate event does not add a second outbox intent, and an unknown version is blocked without a table mutation. Use only temporary paths.

- [ ] **Step 5: Run the store suite and commit**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_models.py idx-swing-plan-board/tests/test_calendar.py idx-swing-plan-board/tests/test_store.py
```

Expected: PASS.

```bash
git add idx-swing-plan-board/bin/models.py idx-swing-plan-board/bin/store.py idx-swing-plan-board/tests
git commit -m "feat: persist Swing board episodes"
```

## Task 3: Render cards and execute forum operations through the owner

**Files:**
- Create: `idx-swing-plan-board/bin/render.py`
- Create: `idx-swing-plan-board/bin/discord_forum.py`
- Create: `idx-swing-plan-board/tests/test_render.py`
- Create: `idx-swing-plan-board/tests/test_discord_forum.py`

**Interfaces:**
- Consumes: Task 1 values and Task 2 outbox payloads.
- Produces: `render_primary_card()`, `render_source_only_card()`, `render_history()`, and `DiscordForumClient.execute()`.

- [ ] **Step 1: Write failing exact-format tests**

```python
from conftest import example_buy_event
from models import Checkpoint, MarketState
from render import render_history, render_primary_card


def test_primary_card_uses_ticker_first_and_live_fields() -> None:
    checkpoint = Checkpoint.market(
        session_date="2026-09-19",
        checked_at="2026-09-19T16:30:00+07:00",
        close_price="230",
        state=MarketState.TP1_REACHED,
    )
    card = render_primary_card(example_buy_event(), checkpoint)
    assert card.startswith("### <:phintraco:1531272488645038091> SCMA: Buy\n-# Alrich Paskalis T, Investment Advisor\n\n")
    assert "**Source status:** New setup" in card
    assert "**Market checkpoint:** TP1 reached" in card
    assert "**Last checked:** 19 Sep 2026 16:30 WIB" in card
    assert card.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_system_history_is_a_two_line_quote() -> None:
    assert render_history("19 Sep 2026 16:30 WIB", "Market checkpoint: TP1 reached at Rp230") == "> 19 Sep 2026 16:30 WIB\n> Market checkpoint: TP1 reached at Rp230"
```

- [ ] **Step 2: Run renderer and Discord-client tests and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_render.py idx-swing-plan-board/tests/test_discord_forum.py
```

Expected: FAIL because the renderer and forum client do not exist.

- [ ] **Step 3: Implement source-faithful rendering**

Use this exact rendering surface:

```python
def format_wib(value: datetime) -> str:
    return value.astimezone(WIB).strftime("%-d %b %Y %H:%M WIB")


def analyst_byline(name: str | None, role: str | None) -> str:
    return f"-# {escape(name)}, {escape(role)}" if name and role else "-# Phintraco Sekuritas"


def render_source_only_card(title: str) -> str:
    return f"### {escape(title)}\n\n**Primary plan:** No Phintraco plan yet"
```

`render_primary_card()` retains every source target, uses no `Source:` footer, has one blank line after byline and before `[View in Telegram]`, and renders `Market check unavailable` without changing the last valid price or check time. Initial Source Status is `New setup`; only later source events replace that value.

- [ ] **Step 4: Implement mocked forum REST operations before real use**

Set `FORUM_CHANNEL_ID = "1548273399069933720"` and implement `create_forum_thread(name, content, tag_names, chart, nonce_value) -> ForumThread`, `edit_starter(thread_id, message_id, content, chart, clear_attachments=False) -> None`, `post_reply(thread_id, content, media, nonce_value) -> str`, and `patch_thread(thread_id, name, tag_names, archived) -> None`. Resolve each canonical `tag_names` value against the forum channel's `available_tags` by exact name before sending the resulting IDs; fail closed if a required name is missing or duplicated. A chartless BUY replacement sets `clear_attachments=True`; a status edit with no new chart retains the existing attachment.

Create uses `POST /channels/<forum-id>/threads` with the starter message payload. Edit uses `PATCH /channels/<thread-id>/messages/<message-id>` and includes retained attachment metadata or a replacement file so source charts cannot disappear. Replies use `POST /channels/<thread-id>/messages`; title, tags, and archive use `PATCH /channels/<thread-id>`. All create operations use a stable SHA-256 nonce. Reapplying an edit or patch writes the complete desired state.

Stable nonce reuse is only a short-window aid. Persist exact operation/message/attachment identity, bot ID, and a read-back boundary before every create POST. Recover ambiguous timeout or interrupted creates by looking up subsequent own messages or active/public-archived forum threads. An inconclusive or exhausted bounded lookup retains pending work without issuing another create. Only a definite rejected POST may clear this snapshot. Serialize HTTP delivery separately from the state lease, honor 429 delays, and expose retained pending/failed health. Split source replies losslessly for all adapters and reserve managed-card space for status/checkpoint edits, retaining complete compacted source in replies.

- [ ] **Step 5: Test requests and no-post behavior, then commit**

Mock `requests.request` and assert forum path, title, two tags, returned thread and starter IDs, safe attachment replacement, 429 retry delay, and that no-post makes no HTTP request. Then run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_render.py idx-swing-plan-board/tests/test_discord_forum.py
```

Expected: PASS.

```bash
git add idx-swing-plan-board/bin/render.py idx-swing-plan-board/bin/discord_forum.py idx-swing-plan-board/tests
git commit -m "feat: render and deliver Swing board cards"
```

## Task 4: Implement episode promotion, source status, and resolution

**Files:**
- Create: `idx-swing-plan-board/bin/engine.py`
- Create: `idx-swing-plan-board/tests/test_engine.py`
- Modify: `idx-swing-plan-board/bin/store.py`
- Modify: `idx-swing-plan-board/bin/render.py`

**Interfaces:**
- Consumes: `SourceEvent`, `BoardStore`, and `DiscordForumClient` from Tasks 1 to 3.
- Produces: `BoardEngine.submit()` and `BoardEngine.drain()` for the owner CLI and watcher bridges.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_social_event_creates_a_source_only_episode(engine) -> None:
    engine.submit(social_event(
        key="x:marketwriter:101",
        ticker="KPIG",
        source_title="KPIG: Wave IV diproyeksikan menuju area 97 sampai 108",
    ), at("2026-09-19T09:05:00+07:00"))
    episode = engine.store.active_episode("KPIG")
    assert episode.lifecycle == "source"
    assert episode.title == "KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"


def test_buy_inside_twenty_sessions_promotes_without_reposting_social_reply(engine) -> None:
    engine.submit(social_event(key="x:marketwriter:101", ticker="KPIG", source_title="KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"), at("2026-09-19T09:05:00+07:00"))
    engine.drain()
    engine.submit(example_buy_event(key="phintraco:1444713822:33700", ticker="KPIG"), at("2026-09-22T09:05:00+07:00"))
    assert [item.operation for item in engine.store.operations_for_ticker("KPIG")] == [
        "create_thread", "post_source_reply", "edit_starter", "patch_thread", "post_history_reply"
    ]


def test_buy_after_resolved_plan_creates_new_episode(engine) -> None:
    prior = engine.seed_resolved_primary("ABCD")
    engine.submit(example_buy_event(key="phintraco:1444713822:33800", ticker="ABCD"), at("2026-09-19T09:05:00+07:00"))
    active = engine.store.active_episode("ABCD")
    assert active.id != prior.id
    assert active.lifecycle == "primary"
```

- [ ] **Step 2: Run the lifecycle tests and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_engine.py
```

Expected: FAIL because `BoardEngine` does not exist.

- [ ] **Step 3: Implement the state-machine decision order**

In `test_engine.py`, define the local `engine` fixture using a temporary `BoardStore` and a fake `DiscordForumClient`, `at(value: str) -> datetime` for deterministic WIB times, and import `example_buy_event` and `social_event` from `conftest.py`. Implement `BoardEngine.submit(event, now)` in this order:

1. Let `BoardStore.submit_event()` deduplicate event identity before any operation.
2. A `social` event creates a `source` episode only when no active episode exists. Enqueue `create_thread` with `Source plan`, followed by a normal `post_source_reply` with source-rendered All content and direct media.
3. A `buy` event promotes an open `source` episode only when its latest material date is not before `sessions_ago(event_date, 20)`. Enqueue a managed starter edit with the original chart, patch title to `<TICKER>: Buy`, replace lifecycle tag with `Primary plan`, and retain every normal source reply. For a GTW-only episode, enqueue exactly one fresh copy of the latest GTW reply below the new starter with a durable promotion dedupe key.
4. A `buy` event within the same 20-session window for an active primary replaces the managed card and chart, retaining old normal replies and without creating quoted history.
5. A `buy` without an eligible active episode creates a fresh primary episode named `<TICKER>: Buy`, tagged `Primary plan`, with no price-state tag until a factual state exists.
6. A `status` or `reminder` requires an active primary. It updates only Source Status, posts the new distinct source item as a normal reply, and edits the starter. With no matching primary it returns `board_ignored` and leaves the All message as the sole delivery.

`BoardEngine.drain()` claims one operation, executes it, persists returned Discord IDs, and applies the Task 2 backoff. A Discord failure is retained in the owner outbox; it never causes a callback that reposts All Swing.

- [ ] **Step 4: Map direct outcomes and resolution without action claims**

Implement `source_outcome_state(event, active_plan)`. Map `Stop-loss hit` to `Stop-loss breached`; map `All targets achieved` to the final available target; map first through sixth, and higher numeric ordinal, target confirmations to `TP1 reached` through `TP6 reached`, clamping higher ladders at TP6. A HOLD or generic status preserves the last factual market-state tag.

Every forum post carries exactly one lifecycle tag. A `source` episode has `Source plan` and no market tag. An active primary has `Primary plan` plus at most one current factual market tag. A terminal primary replaces `Primary plan` with `Resolved` and retains its final factual market tag, if one exists. The calculated patch always writes the complete desired tag list, so a stale prior price tag cannot remain.

An explicit stop or final-target source outcome marks the plan terminal, sets lifecycle to `Resolved`, preserves the final market tag and chart, emits one quoted resolution event, and blocks later status or price changes for that episode. Do not send an archive operation or any synthetic retention message. The configured Discord auto-archive handles retention.

- [ ] **Step 5: Run the lifecycle suite and commit**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_store.py idx-swing-plan-board/tests/test_render.py idx-swing-plan-board/tests/test_discord_forum.py idx-swing-plan-board/tests/test_engine.py
```

Expected: PASS.

```bash
git add idx-swing-plan-board/bin/engine.py idx-swing-plan-board/bin/store.py idx-swing-plan-board/bin/render.py idx-swing-plan-board/tests
git commit -m "feat: manage Swing board episodes"
```

## Task 5: Add Yahoo reconciliation and a runnable deterministic owner

**Files:**
- Create: `idx-swing-plan-board/bin/prices.py`
- Create: `idx-swing-plan-board/bin/board.py`
- Create: `idx-swing-plan-board/bin/idx-swing-plan-board.sh`
- Create: `idx-swing-plan-board/tests/test_prices.py`
- Create: `idx-swing-plan-board/tests/test_board_cli.py`
- Modify: `idx-swing-plan-board/bin/engine.py`
- Modify: `idx-swing-plan-board/{AGENTS.md,CRON.md}`

**Interfaces:**
- Consumes: active primary plans, the Task 1 IDX calendar, and current-session Yahoo bars.
- Produces: `fetch_session_close()`, `classify_close()`, `BoardEngine.after_close()`, and board CLI commands.

- [ ] **Step 1: Write failing close-classification and CLI tests**

```python
from datetime import date
from decimal import Decimal

from prices import classify_close, fetch_session_close, parse_plan_levels


def test_classify_close_prefers_stop_then_highest_target() -> None:
    plan = parse_plan_levels("208 to 212", "<200", ("230", "250", "270"))
    assert classify_close(Decimal("199"), plan).value == "Stop-loss breached"
    assert classify_close(Decimal("250"), plan).value == "TP2 reached"
    assert classify_close(Decimal("210"), plan).value == "Entry zone"
    assert classify_close(Decimal("205"), plan).value == "Below entry"
    assert classify_close(Decimal("220"), plan).value == "Above entry"


def test_fetch_session_close_rejects_a_previous_yahoo_bar(monkeypatch) -> None:
    monkeypatch.setattr("prices._history", lambda symbol: dataframe_for(date(2026, 9, 18), "230"))
    assert fetch_session_close("SCMA", date(2026, 9, 19)) is None
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests/test_prices.py idx-swing-plan-board/tests/test_board_cli.py
```

Expected: FAIL because `prices.py` and `board.py` do not exist.

- [ ] **Step 3: Implement strict plan-level parsing and factual classification**

Use `Decimal`, not float. Implement `parse_plan_levels(entry: str, stop_loss: str, targets: Sequence[str]) -> ParsedPlanLevels`. Import `Sequence` from `collections.abc`. Parse only a bare integer price, `<N`, `<=N`, `>N`, `>=N`, or `N to M` with `N <= M`. Strip Indonesian thousands separators from integer tokens, but reject decimals, negative values, letters, reversed ranges, and unrelated extra numbers. In `test_prices.py`, define `dataframe_for(day, close)` as the one-row pandas test value consumed by `_history(symbol)`.

Implement:

```python
def classify_close(close: Decimal, levels: ParsedPlanLevels) -> MarketState:
    if levels.stop_loss.is_breached_by(close):
        return MarketState.STOP_LOSS_BREACHED
    reached = [number for number, target in enumerate(levels.targets, start=1) if target.is_reached_by(close)]
    if reached:
        return MarketState.from_target_number(min(max(reached), 5))
    if levels.entry.contains(close):
        return MarketState.ENTRY_ZONE
    if close < levels.entry.lower_bound:
        return MarketState.BELOW_ENTRY
    return MarketState.ABOVE_ENTRY
```

For target ranges use the lower boundary as its reached threshold. For a `>=N` entry, every price at or above N and below the first target is `Entry zone`; never invent an upper entry boundary. Preserve every target in card content, but clamp the tag at `TP6 reached` for target seven or later.

`fetch_session_close(ticker, session_date)` calls `yf.Ticker(f"{ticker}.JK").history(period="5d", interval="1d", auto_adjust=False)` and returns a value only when the final nonempty bar is positive, finite, and dated exactly `session_date` in Jakarta time. Empty data, invalid values, exceptions, and an earlier session return `None`.

- [ ] **Step 4: Implement after-close phases and owner commands**

Implement these commands:

```text
submit-source-event --stdin
drain
after-close --phase initial
after-close --phase retry
```

`submit-source-event --stdin` validates `SourceEvent`, copies any supplied local media into the owner directory before acknowledging acceptance, atomically persists event plus outbox, and runs one best-effort drain. A durable intake returns `{"accepted": true}` even when Discord delivery remains retryable.

`drain` returns `{"drained":N,"pending":N,"failed":N}` and a nonzero exit when pending/failed work remains, including backoff. Ordered public X media becomes durable owner acquisition/upload intents, restricted to HTTPS `pbs.twimg.com` and `video.twimg.com`, supported image/MP4 formats, and 8 MiB per attachment. Cache files are private and atomic; no inherited credentials/proxies or unsafe redirects are allowed. No-post does not download remote media.

`after-close --phase initial` runs only at 16:30 WIB on a configured IDX trading day. It saves a valid close and writes history only on market-state transition. An absent close records an initial unavailable attempt without altering prior facts.

Stop-loss or the actual final source target resolves and finishes the plan, with a lifecycle history transition even if a higher target still uses the TP6 tag. Close operation identities include plan, session, and phase. An unclassifiable source plan preserves prior facts, increments `invalid`, and does not block the remaining tickers; that count degrades the heartbeat. Unexpected reconciliation failures produce a sanitized fatal heartbeat.

`after-close --phase retry` runs only at 17:00 WIB for initial failures from the current session. On a second failure it renders `Market check unavailable`, keeps the latest valid price and time, emits no history reply, and does not alter tags. A holiday makes no board mutation.

Scheduled phases call `drain()` and direct-post exactly one heartbeat to `#hermes` (`1505162000420835388`), such as:

```text
🫀 idx-swing-plan-board · 16:30 WIB · active=3 checked=2 unavailable=1 pending=0 ⚠️
```

- [ ] **Step 5: Implement no-post wrapper and test it**

The wrapper loads only `DISCORD_BOT_TOKEN`, uses `$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python`, defaults the database to `$HOME/.hermes/state/idx-swing-board.sqlite3`, and passes arguments unchanged. It never accepts a watcher-supplied database path.

Provide zero-argument sibling scheduler wrappers: `idx-swing-plan-board-close.sh` invokes the generic wrapper with `after-close --phase initial`, and `idx-swing-plan-board-retry.sh` invokes it with `after-close --phase retry`. Test both actual wrapper paths with isolated no-post state. The generic wrapper remains the watcher submission/drain entry point.

Run:

```bash
IDX_SWING_PLAN_BOARD_NO_POST=1 IDX_SWING_PLAN_BOARD_STATE_PATH=/tmp/idx-swing-board-no-post.sqlite3 IDX_SWING_PLAN_BOARD_MEDIA_ROOT=/tmp/idx-swing-board-no-post-media ../.venv/bin/python idx-swing-plan-board/bin/board.py after-close --phase initial
```

Expected: intended operations and heartbeat print with no HTTP request.

- [ ] **Step 6: Run the full owner suite and commit**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-plan-board/tests
```

Expected: PASS.

```bash
git add idx-swing-plan-board
git commit -m "feat: reconcile Swing board closing prices"
```

## Task 6: Update Phintraco All rendering and add the post-All board handoff

**Files:**
- Modify: `idx-swing-watch-phintraco-daily/bin/scan.py`
- Modify: `idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh`
- Modify: `idx-swing-watch-phintraco-daily/{AGENTS.md,CRON.md}`
- Modify: `idx-swing-watch-phintraco-daily/tests/{test_scan.py,test_wrapper.py}`

**Interfaces:**
- Consumes: existing `SwingCall` values and durable All outbox events.
- Produces: ticker-first All text and an acknowledged `SourceEvent` submitted to Task 5 after All text and chart delivery.

- [ ] **Step 1: Write failing format and handoff tests**

In `test_scan.py`, define test-only `enqueue_ready_chart_call(tmp_state, tmp_path)` to build a complete sample-call outbox entry and write the nonempty `phintraco-33655.jpg` fixture below `tmp_path / "media"`. Define `now()` to return `datetime(2026, 7, 31, 10, 7, tzinfo=scan.WIB)`.

```python
def test_buy_alert_is_ticker_first_with_byline_and_telegram_footer() -> None:
    output = scan.format_swing_alert(sample_call())
    assert output.startswith("### <:phintraco:1531272488645038091> SCMA: Buy\n-# Alrich Paskalis T, Investment Advisor\n\n")
    assert "**Signal date:** 10 Jul 2026 07:00 WIB" in output
    assert output.endswith("[View in Telegram](<https://t.me/phintraprofits/33655>)")


def test_board_handoff_waits_for_all_text_and_chart(tmp_state, tmp_path, monkeypatch) -> None:
    state = enqueue_ready_chart_call(tmp_state, tmp_path)
    submitted = []
    monkeypatch.setattr(scan, "post_discord_text", lambda *_: "all-text")
    monkeypatch.setattr(scan, "post_discord_file", lambda *_: "all-chart")
    monkeypatch.setattr(scan, "submit_board_event", lambda payload, chart, dry_run: submitted.append((payload, chart)) or True)
    scan.drain_outbox(state, now())
    assert submitted[0][0]["kind"] == "buy"
    assert submitted[0][1].name == "phintraco-33655.jpg"
    assert state["outbox"] == {}
```

- [ ] **Step 2: Run the focused suite and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q idx-swing-watch-phintraco-daily/tests/test_scan.py idx-swing-watch-phintraco-daily/tests/test_wrapper.py
```

Expected: FAIL because the old renderer and delivery state have no board phase.

- [ ] **Step 3: Replace only the agreed All Swing visual format**

Render `### <emoji> TICKER: Buy`, `Hold`, and `Reminder`, with no heading bold markers. Put `-# <analyst>, Investment Advisor` immediately below, or `-# Phintraco Sekuritas` when absent. Use `%-d %b %Y %H:%M WIB`, retain bold labels and source values, put one blank line before content and footer, and replace the prior Source footer with `[View in Telegram](<source-url>)`. Keep chart acquisition and All text-then-chart order unchanged.

- [ ] **Step 4: Add a durable `pending_board` phase after All completes**

Add phase `pending_board` plus `board_submitted`, `board_attempts`, `board_next_attempt_at`, and `board_last_error` to every daily outbox event. A BUY produces its full plan and `New setup`; STATUS carries source status; REMINDER carries explicit outcomes. Only after All text and the same-message chart succeed does `submit_board_event()` invoke:

```text
$HOME/.hermes/scripts/idx-swing-plan-board.sh submit-source-event --stdin
```

It writes JSON to standard input and accepts only `{"accepted": true}`. Board failure uses the existing bounded retry and retains the cached chart. It cannot repeat All text or chart. Every normal daily run also invokes the owner's `drain` command; a drain failure marks the watcher heartbeat degraded but does not block Telegram cursor progress or All delivery.

Use exact boolean acknowledgement, not numeric equality. Keep source-ordered board retries in a separate logical queue so failed/backed-off handoffs never hold subsequent All text/chart pairs. Invoke drain even when already degraded, and consume its pending/failed counts as unhealthy work.

- [ ] **Step 5: Update wrapper and contracts, test retries, then commit**

Export `IDX_SWING_PLAN_BOARD_WRAPPER` with default `$HOME/.hermes/scripts/idx-swing-plan-board.sh`. Do not load new credentials. Document that this watcher submits source events but never reads the board database, updates tags, posts forum content, or calculates prices.

Test chartless BUY, status without primary, board retry preserving existing All message IDs, and source chart retention until owner acknowledgment. Then run:

```bash
../.venv/bin/python -m pytest -q idx-swing-watch-phintraco-daily/tests
```

Expected: PASS.

```bash
git add idx-swing-watch-phintraco-daily
git commit -m "feat: project Phintraco swings to board"
```

## Task 7: Project Kelas GTW plans as source-only board context

**Files:**
- Modify: `kelas-investasi-gtw-watch/bin/{state.py,discord.py,scan.py,kelas-investasi-gtw-watch.sh}`
- Modify: `kelas-investasi-gtw-watch/{AGENTS.md,SKILL.md}`
- Modify: `kelas-investasi-gtw-watch/tests/{test_state.py,test_discord.py,test_scan.py,test_wrapper.py}`

**Interfaces:**
- Consumes: a completed GTW bundle only after accepted agent work and existing All Swing text plus header-image delivery.
- Produces: a `social` `SourceEvent` with exact GTW header title, source reply content, and first direct source image.

- [ ] **Step 1: Write failing Kelas board-handoff tests**

In `test_discord.py`, define test-only `ready_gtw_event(header)` by using the existing GTW state constructors to create one delivered-to-All, board-pending event with the supplied preserved Telegram header. Define `now()` as a fixed WIB datetime used by the delivery call.

```python
def test_ready_gtw_event_keeps_media_until_board_accepts(tmp_path, monkeypatch) -> None:
    event = ready_gtw_event(header="Good to watch - RAJA #GTW")
    state = {"version": 2, "cursor": None, "pending": [], "outbox": [event], "stats": {"observed": 0}}
    monkeypatch.setattr(discord, "post_text", lambda *_: "all-text")
    monkeypatch.setattr(discord, "post_file", lambda *_: "all-image")
    monkeypatch.setattr(discord, "submit_board_event", lambda payload, media, dry_run: True)
    assert discord.deliver_oldest_ready_event(state, now(), False, media_root=tmp_path) is True
    assert state["outbox"] == []


def test_gtw_payload_uses_exact_header_and_social_kind() -> None:
    payload = discord.board_payload(ready_gtw_event(header="Good to watch - RAJA #GTW"))
    assert payload["kind"] == "social"
    assert payload["source_title"] == "Good to watch - RAJA #GTW"
    assert payload["ticker"] == "RAJA"
```

- [ ] **Step 2: Run the focused Kelas tests and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_state.py kelas-investasi-gtw-watch/tests/test_discord.py kelas-investasi-gtw-watch/tests/test_scan.py kelas-investasi-gtw-watch/tests/test_wrapper.py
```

Expected: FAIL because Kelas state has no board phase or payload adapter.

- [ ] **Step 3: Migrate Kelas state and add post-All submission**

Migrate state version 1 to version 2 without cursor reset. Add `board_phase`, `board_attempts`, `board_next_attempt_at`, and `board_last_error` to outbox events. After every All text chunk and its header image complete, retain the event until the board owner accepts the submission.

Legacy pending bundles without a source publication time retain `board_phase="unavailable"` when closed and reloaded. Board handoffs keep source order but never block later All text/image pairs; the All and board queues are logically independent.

`board_payload()` must submit `kind="social"`, the parsed ticker, exact first header line as `source_title`, source publication time, rendered existing Kelas content as `all_content`, exact Telegram URL, and the captured first-header image path. It must not use the agent-generated title as a forum title. A failed board handoff retries only the board phase and never calls the agent or replays All text and image legs.

- [ ] **Step 4: Keep the Hermes agent boundary unchanged**

Do not add a board field to the agent's `{event_key,title,summary}` schema. Update `AGENTS.md` and `SKILL.md` only to state that the deterministic scanner may project an accepted GTW bundle as source-only context after All delivery, while the board owner is the sole forum decision maker.

- [ ] **Step 5: Run Kelas tests and commit**

Run:

```bash
../.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests telegram-resilience/tests/test_documentation.py
```

Expected: PASS.

```bash
git add kelas-investasi-gtw-watch
git commit -m "feat: add Kelas GTW board context"
```

## Task 8: Project only conservative X technical posts as source-only board context

**Files:**
- Modify: `x-post-watch/bin/{state.py,scan.py,x-post-watch.sh}`
- Modify: `x-post-watch/AGENTS.md`
- Modify: `x-post-watch/tests/{test_state.py,test_scan.py,test_wrapper.py}`

**Interfaces:**
- Consumes: an accepted and All-delivered `id_stocks_swing` X event.
- Produces: a single-ticker `social` `SourceEvent`, or no board event. The existing X agent schema, relevance decision, title, summary, and route remain unchanged.

- [ ] **Step 1: Write failing source-eligibility and retry tests**

In `test_scan.py`, define test-only `swing_event(source_text)`, `profile_fixture()`, `ready_swing_state(tmp_path)`, `profiles()`, `stats()`, and `now()` using the existing X watcher `SourcePost`, profile, and durable-state helpers. Each factory must use a fixed WIB timestamp and create exactly one All-delivered Swing outbox event where the test requires handoff retry.

```python
def test_x_board_event_requires_one_exact_ticker_led_source_title() -> None:
    event = swing_event(source_text="KPIG: Wave IV diproyeksikan menuju area 97 sampai 108")
    assert scan.board_source_event(event, profile_fixture())["source_title"] == "KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"


def test_multiticker_or_non_ticker_led_x_source_stays_all_only() -> None:
    assert scan.board_source_event(swing_event(source_text="KPIG dan RAJA menarik"), profile_fixture()) is None
    assert scan.board_source_event(swing_event(source_text="Update teknikal hari ini"), profile_fixture()) is None


def test_board_failure_does_not_repost_existing_all_messages(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    monkeypatch.setattr(scan.discord, "post_text", lambda *_: "all-message")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)
    assert scan._deliver(value, profiles(), 0, False, tmp_path, stats(), now()) is False
    assert value["outbox"][0]["text_message_ids"] == ["all-message"]
    assert value["outbox"][0]["board_phase"] == "pending"
```

- [ ] **Step 2: Run the focused X tests and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q x-post-watch/tests/test_state.py x-post-watch/tests/test_scan.py x-post-watch/tests/test_wrapper.py
```

Expected: FAIL because X durable events have neither source-only eligibility nor a board phase.

- [ ] **Step 3: Implement source-exact eligibility**

Implement `board_source_event(event, profile) -> dict[str, object] | None`. It returns an event only if all conditions hold:

1. final route is `id_stocks_swing`;
2. the first nonempty original source-text line matches `^([A-Z][A-Z0-9]{1,9}):\s+(.+)$`;
3. that exact source title is at most 100 characters and the entire source bundle, including later lines and thread posts, has no second ticker-led clause; and
4. its ticker equals the ticker prefix in the already accepted route title.

The forum title is the raw exact source line, not the LLM title. `all_content` is the existing rendered X output. Include direct ordered X media URLs only, which the board owner downloads into its own directory. When any condition fails, return `None`; the finished X delivery remains All-only.

- [ ] **Step 4: Add the durable post-All handoff without changing agent work**

Migrate X state with `board_phase`, `board_attempts`, `board_next_attempt_at`, and `board_last_error`. Call `record_delivery()` before the board handoff so every All message ID is durable. Keep the X event until the owner accepts. A failed handoff retries using the existing scheduler but never repeats All messages, routes, agent work, or cleanup.

Export `IDX_SWING_PLAN_BOARD_WRAPPER` from the X wrapper and document the source-only boundary in `AGENTS.md`. Do not modify `SKILL.md`; the agent's validated closed schema remains unchanged.

- [ ] **Step 5: Run X tests and commit**

Run:

```bash
../.venv/bin/python -m pytest -q x-post-watch/tests
```

Expected: PASS.

```bash
git add x-post-watch
git commit -m "feat: add X Swing board context"
```

## Task 9: Register contracts, complete-suite coverage, and approved deployment

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `scripts/test-all`
- Modify: `tests/test_documentation_contract.py`
- Modify: `idx-swing-plan-board/{AGENTS.md,CRON.md}`
- Modify: `docs/adr/0020-idx-swing-plan-board.md` only if an implementation fact differs from the accepted design.

**Interfaces:**
- Consumes: completed Tasks 1 to 8.
- Produces: one classified deterministic owner, complete local validation, and exact production handoff commands.

- [ ] **Step 1: Write the documentation-contract regression**

```python
def test_cron_classification_is_complete_and_disjoint() -> None:
    assert "idx-swing-plan-board" in NO_AGENT_CRONS
    assert len(ALL_CRONS) == 17
    assert readme_cron_inventory() == ALL_CRONS
```

- [ ] **Step 2: Run the contract test and verify failure**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_documentation_contract.py
```

Expected: FAIL until root policy and the README table include the new no-agent cron.

- [ ] **Step 3: Update docs and complete-suite registration**

Add `idx-swing-plan-board` to the root `AGENTS.md` no-agent list and README table as the deterministic owner of board state and close reconciliation. Add this line after the daily Swing suite in `scripts/test-all`:

```bash
run_suite idx-swing-plan-board idx-swing-plan-board tests
```

Add the cron to `NO_AGENT_CRONS` and update its expected count to `17`. Keep every existing classification unchanged. Do not revise ADR product decisions in this task.

- [ ] **Step 4: Run documentation and complete local validation**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_documentation_contract.py
bash scripts/test-all
```

Expected: both commands PASS.

- [ ] **Step 5: Commit all documentation integration changes**

```bash
git add AGENTS.md README.md scripts/test-all tests/test_documentation_contract.py idx-swing-plan-board/AGENTS.md idx-swing-plan-board/CRON.md docs/adr/0020-idx-swing-plan-board.md
git commit -m "docs: register Swing board cron"
```

- [ ] **Step 6: Stop at the production approval gate**

Before the first VPS write, new scheduler registration, live forum post, or bootstrap, present the local commits, exact changed files, local test results, and VPS file diffs. Obtain explicit current approval covering deployment and both new scheduler registrations. Design approval does not authorize historical backfill.

- [ ] **Step 7: Deploy reviewed published files and register the two schedules**

After approval, commit and publish the clean main branch, deploy only reviewed source, then compare each local and VPS SHA-256:

```bash
git push origin main
./deploy.sh idx-swing-plan-board
./deploy.sh idx-swing-watch-phintraco-daily
./deploy.sh kelas-investasi-gtw-watch
./deploy.sh x-post-watch
```

Compare `idx-swing-plan-board.sh`, `idx-swing-plan-board-close.sh`, `idx-swing-plan-board-retry.sh`, and `CRON.md` before copying them. After approval, install all three wrappers together under `~/.hermes/scripts/`. Then use the supported VPS command, never hand-editing `~/.hermes/cron/jobs.json`:

```bash
$HOME/.local/bin/hermes cron create '30 16 * * 1-5' --name idx-swing-plan-board-close --script idx-swing-plan-board-close.sh --no-agent --deliver local --workdir /home/praya
$HOME/.local/bin/hermes cron create '0 17 * * 1-5' --name idx-swing-plan-board-retry --script idx-swing-plan-board-retry.sh --no-agent --deliver local --workdir /home/praya
```

Read returned IDs with `hermes cron list --all`, record them in the final `CRON.md`, commit, publish, synchronize that reviewed contract, and compare its VPS checksum.

- [ ] **Step 8: Prove no-post behavior and wait for natural execution**

Run each real wrapper with fresh isolated state, confirm intended output and no Discord request, then inspect the natural scheduler records rather than manually triggering a production job:

```bash
ssh vps 'IDX_SWING_PLAN_BOARD_NO_POST=1 IDX_SWING_PLAN_BOARD_STATE_PATH=/tmp/idx-swing-board-no-post.sqlite3 IDX_SWING_PLAN_BOARD_MEDIA_ROOT=/tmp/idx-swing-board-no-post-media ~/.hermes/scripts/idx-swing-plan-board.sh after-close --phase initial'
ssh vps 'IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1 IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH=/tmp/idx-swing-daily-no-post.json IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT=1 ~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh'
ssh vps 'KELAS_INVESTASI_GTW_NO_POST=1 KELAS_INVESTASI_GTW_STATE_PATH=/tmp/kelas-gtw-no-post.json KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-gtw-no-post-media ~/.hermes/scripts/kelas-investasi-gtw-watch.sh'
ssh vps 'X_POST_WATCH_NO_POST=1 X_POST_WATCH_STATE_PATH=/tmp/x-post-no-post.json ~/.hermes/scripts/x-post-watch.sh'
```

- [ ] **Step 9: Run bootstrap only after a separate candidate report is approved**

Add `bootstrap --dry-run --lookback-sessions 20` to the board CLI. For this command only, extend the board wrapper to load `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING`, add `$HOME/.agents/skills/telegram-resilience/bin` to `PYTHONPATH`, and require `acquire_probe_after_active_lease()` before constructing the Telethon client. It reads retained Phintraco history, prints each candidate ticker, original BUY source ID, later matching source-status IDs, missing-setup reason, and intended forum operation, without touching board state or Discord.

Present the report. Only after explicit approval for those listed external posts, run `bootstrap --apply --lookback-sessions 20`. Persist progress in the owner database so an interrupted bootstrap resumes safely. It must never invent historical price checkpoints.

- [ ] **Step 10: Capture verified VPS source in dotfiles when approved**

Run `~/.dotfiles/sync-mac.sh --check` after natural verification. If the user requests immediate capture, run `~/.dotfiles/sync-mac.sh`, verify job `804f44f0be6e` completed with `mac=ok vps=ok` and `git=push` or `git=noop`, confirm dotfiles `config` equals `origin/config`, and inspect changed runtime paths under `vps/agents/skills/` and `vps/hermes/scripts/`.

## Self-Review

### Spec coverage

- All Swing is preserved and board retries are independent: Tasks 5 through 8.
- SQLite single ownership, durable outbox, post promotion, source history, card editing, tags, terminal lifecycle, and no artificial retention: Tasks 2 through 5.
- Exact Phintraco format: Task 6.
- After-close Yahoo logic, 16:30 check, 17:00 only-if-needed retry, factual labels, unavailable handling, and higher target ladders: Task 5.
- SSF exclusion: global constraints, and no SSF file is modified.
- Kelas and X source-only treatment: Tasks 7 and 8.
- Cron governance, testing, deployment proof, dotfiles capture, and separately approved bootstrap: Task 9.

No approved requirement is uncovered.

### Placeholder scan

The plan contains no deferred implementation placeholder. Its approval gates are explicit safety requirements.

### Type consistency

Every watcher adapter creates `SourceEvent`; Task 1 validates it; Task 2 persists it; Tasks 3 and 4 render and deliver it; Task 5 accepts it through the owner CLI. `BoardStore` is the only database API and `BoardEngine` is the only episode coordinator. Existing watchers never import or write `BoardStore` directly.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-13-idx-swing-plan-board.md`.

Two execution options:

1. **Subagent-Driven (recommended)**: dispatch a fresh subagent per task, then review each task before continuing.
2. **Inline Execution**: execute tasks in this session with checkpoints.

Which approach?
