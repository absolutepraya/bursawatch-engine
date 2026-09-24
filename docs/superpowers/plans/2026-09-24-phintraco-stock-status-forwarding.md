# Phintraco Stock Information Status Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forward each new Phintraco `Stock Information` post as one deterministic, grouped status message in Discord `#id-stocks-news`.

**Architecture:** Add a pure parser and renderer for the five Phintraco status sections. Persist each grouped message as a separate durable status event in the existing watcher state, then send it through the watcher's text delivery API with the message ID as its idempotency identity. Intercept the status post before ordinary issuer candidate creation so it does not wake the AI classifier or request market data.

**Tech Stack:** Python 3, dataclasses, standard-library date and regular-expression parsing, pytest, existing JSON watcher state and Discord text sender.

**Spec:** [`docs/superpowers/specs/2026-09-24-phintraco-stock-status-forwarding-design.md`](../specs/2026-09-24-phintraco-stock-status-forwarding-design.md)

## Global Constraints

- Only a newly observed message from the `phintasprofits` source whose first line is exactly `Stock Information` is handled by this path.
- It forwards each newly published Phintraco `Stock Information` post as one grouped Discord message in `#id-stocks-news`.
- The output order and labels are fixed: UMA, Suspend In, Suspend Out, FCA In, FCA Out.
- Every section is present in every message. A category with no tickers renders as `(None)`.
- The status path is deterministic. It does not call the agent classifier or fetch Yahoo Finance quotes.
- The watcher processes new Telegram messages only. It does not watch edits, backfill old messages, rewind the existing cursor, or add a manual replay path for this feature.
- A missing or duplicate expected heading, an unrecognized status heading, an invalid effective date, or malformed category entry rejects the whole message. No partial alert is sent.
- Posts above Discord's 2,000-character content limit are also rejected and reported as degraded; they are not split or truncated.
- Before implementation, inspect the effective live cadence read-only and use it as found. This design does not authorize changing the schedule, route configuration, or any production state.
- Existing provider cursor remains the boundary between historical and new messages. There is no launch-time history replay.

## Review Focus

- Category order or harmless surrounding whitespace changes in the source: accept recognized sections, then render in the fixed Discord order. Task 1 tests reordered sections and whitespace normalization.
- An empty category versus an absent category: render `>-` or an empty body as `(None)`, but reject a missing section. Task 1 tests both empty forms and a missing heading.
- Repeated tickers: remove repeated occurrences within one category while retaining the first-seen order, and preserve a ticker that also appears in another category. Task 1 tests both cases.
- Unknown headings, duplicate expected headings, or duplicate and malformed effective dates: reject the whole source post. Task 1 tests each rejection without producing a partial status object.
- A formatted message at or above Discord's size boundary: accept exactly 2,000 characters and reject any longer payload. Task 2 tests both boundaries.

---

## File Map

- Create `cron-tg-market-news/bin/stock_status.py` for the immutable status model, strict source parser, and deterministic Discord renderer.
- Create `cron-tg-market-news/tests/fixtures/phintraco-stock-status-35326.txt` and `cron-tg-market-news/tests/fixtures/phintraco-stock-status-35377.txt` from the two approved source examples.
- Create `cron-tg-market-news/tests/test_stock_status.py` for parser and renderer behavior.
- Modify `cron-tg-market-news/bin/state.py` to validate and persist grouped status events, rejected source IDs, delivery state, and retries under `stats.stock_status_events`.
- Modify `cron-tg-market-news/tests/test_state.py` to cover legacy state compatibility, strict status-event validation, idempotent event identity, and retry persistence.
- Modify `cron-tg-market-news/bin/delivery.py` to deliver the frozen status payload through `post_discord_text` and existing retry timing.
- Modify `cron-tg-market-news/tests/test_delivery.py` to cover route, exact payload, idempotent event key, success, generic failure, and rate-limit retry.
- Modify `cron-tg-market-news/bin/scan.py` to intercept Phintraco status posts, advance the cursor only after an event or rejection is durable, drain pending status deliveries, and report degraded runs for rejected status posts.
- Modify `cron-tg-market-news/tests/test_scan.py` to verify intake, routing, no classifier wake, cursor ordering, retry, all-empty delivery, and degraded rejection.
- Modify `cron-tg-market-news/AGENTS.md` and `cron-tg-market-news/SKILL.md` so the active package and runtime prompt describe the deterministic status path.

No new dependency, schedule, wrapper, Discord channel, or production state path is added.

## Execution Prerequisite

- [ ] Read `AGENTS.md` and `cron-tg-market-news/AGENTS.md` in the active worktree.
- [ ] Use the supported read-only Hermes schedule inspection to record the effective enabled state and interval for `bursawatch-tg-market-news`, plus the current `id_stocks_news_channel_id` mapping. Keep those values as found. Do not edit or trigger a Hermes job.
- [ ] Confirm the worktree branch is `absolutepraya/phintraco-stock-status` and the worktree is clean before starting code changes.

## Task 1: Parse Phintraco status source posts

**Files:**
- Create: `cron-tg-market-news/bin/stock_status.py`
- Create: `cron-tg-market-news/tests/fixtures/phintraco-stock-status-35326.txt`
- Create: `cron-tg-market-news/tests/fixtures/phintraco-stock-status-35377.txt`
- Create: `cron-tg-market-news/tests/test_stock_status.py`

**Interfaces:**
- Produces `StockStatus`, an immutable dataclass with `source_message_id: int`, `effective_date: date`, and tuple fields `uma`, `suspend_in`, `suspend_out`, `fca_in`, and `fca_out`.
- Produces `is_stock_information(text: str) -> bool`, true only when the first line is exactly `Stock Information`.
- Produces `parse_stock_information(source_message_id: int, text: str) -> StockStatus`; it raises `StockStatusError` for malformed, incomplete, duplicate, or unknown source structure.
- Task 2 consumes the `StockStatus` type and parser.

- [ ] **Step 1: Add the two exact reference messages as fixtures.**

Copy the text returned by Telegram message 35326 and 35377 into the two named fixtures. Preserve the source's `Effective date`, five headings, `>TICKER` entries, `>-` empty markers, attribution, disclaimer, and blank lines. Do not add Telegram metadata lines to the fixtures.

- [ ] **Step 2: Write parser tests for the examples and rejection cases.**

```python
from datetime import date

import pytest

from stock_status import StockStatusError, is_stock_information, parse_stock_information


def test_message_35377_maps_all_sections_and_empty_values(load_fixture):
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )

    assert status.effective_date == date(2026, 9, 23)
    assert status.uma == ()
    assert status.suspend_in == ()
    assert status.suspend_out == ("WAPO", "NASI")
    assert status.fca_in == ()
    assert status.fca_out == ("UNSP",)


def test_message_35326_preserves_source_lists(load_fixture):
    status = parse_stock_information(
        35326, load_fixture("phintraco-stock-status-35326.txt")
    )

    assert status.effective_date == date(2026, 9, 21)
    assert status.uma == ("WAPO", "NASI")
    assert status.suspend_in == ("SEMA", "TEBE", "IDEA", "NICK", "WIKA", "BIKE")
    assert status.suspend_out == ("LIFE", "GRPH", "TRUE")
    assert status.fca_in == ("LIFE", "GRPH")
    assert status.fca_out == ("CSMI",)


@pytest.mark.parametrize(
    "body",
    [
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA) :\n>-\nSuspend :\n>-\n"
        "Unsuspend :\n>-\nFCA In :\n>-\n",
        "Stock Information\nEffective date : 23 September 2026\n"
        "Unusual Market Activity (UMA) :\n>-\nSuspend :\n>-\n"
        "Unsuspend :\n>-\nFCA In :\n>-\nFCA Out :\n>-\n"
        "New Status :\n>ABCD\n",
    ],
)
def test_incomplete_or_unknown_status_sections_are_rejected(body):
    with pytest.raises(StockStatusError):
        parse_stock_information(35377, body)


def test_only_exact_stock_information_header_selects_status_parser():
    assert is_stock_information("Stock Information\nEffective date : 23 September 2026")
    assert not is_stock_information("Stock Information: more text")
    assert not is_stock_information("Company Flash: ABCD")
```

Add parser cases for source-order variation, whitespace normalization,
`>-` and blank-body empty sections, repeated tickers within a section,
cross-section ticker repeats, duplicate dates, duplicate expected sections,
invalid dates, and malformed ticker entries.

- [ ] **Step 3: Run the focused parser tests and confirm they fail because the module is absent.**

Run from the repository root: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_stock_status.py`.

Expected: collection fails with `ModuleNotFoundError: No module named 'stock_status'`.

- [ ] **Step 4: Implement the model and parser.**

Use `datetime.strptime(value, "%d %B %Y").date()` for exactly one English `Effective date : D Month YYYY` line. Normalize only surrounding whitespace and whitespace around a recognized heading's colon. Require each of the five source headings exactly once, allow source sections in any order, and accept only one `>ABCD` line per ticker or the `>-` empty marker within a section. Deduplicate a repeated ticker within its section while retaining first-seen order. Reject unknown heading-shaped lines and malformed category entries. Ignore only the known research attribution and disclaimer after the status sections. Store no raw post text in an error record or error reason.

Use this immutable model and error type:

```python
@dataclass(frozen=True, slots=True)
class StockStatus:
    source_message_id: int
    effective_date: date
    uma: tuple[str, ...]
    suspend_in: tuple[str, ...]
    suspend_out: tuple[str, ...]
    fca_in: tuple[str, ...]
    fca_out: tuple[str, ...]


class StockStatusError(ValueError):
    pass
```

- [ ] **Step 5: Run parser tests and verify both fixtures parse.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_stock_status.py`.

Expected: parser tests pass, including both reference post fixtures, reordered sections, duplicate ticker handling, empty bodies, missing and duplicate headings, unknown categories, duplicate dates, and malformed ticker lines.

- [ ] **Step 6: Commit the parser and fixtures.**

```bash
git add cron-tg-market-news/bin/stock_status.py cron-tg-market-news/tests/fixtures/phintraco-stock-status-35326.txt cron-tg-market-news/tests/fixtures/phintraco-stock-status-35377.txt cron-tg-market-news/tests/test_stock_status.py
git commit -m "feat: parse Phintraco stock status posts"
```

## Task 2: Render the fixed Discord status format

**Files:**
- Modify: `cron-tg-market-news/bin/stock_status.py`
- Modify: `cron-tg-market-news/tests/test_stock_status.py`

**Interfaces:**
- Consumes `StockStatus` from Task 1.
- Produces `format_stock_status(status: StockStatus, source_url: str) -> str`.
- The renderer emits the fixed five headings, the custom Phintraco emoji, the effective date, `(None)` for empty sections, and the Markdown source link.

- [ ] **Step 1: Write the exact message 35377 rendering test and length-boundary tests.**

```python
import pytest

from stock_status import (
    StockStatusError,
    format_stock_status,
    parse_stock_information,
)


def test_message_35377_renders_the_approved_discord_message(load_fixture):
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )
    base_url = "https://t.me/phintasprofits/35377"
    base_content = format_stock_status(status, base_url)
    exact_length_url = base_url + ("x" * (2000 - len(base_content)))

    assert len(format_stock_status(status, exact_length_url)) == 2000
    with pytest.raises(StockStatusError):
        format_stock_status(status, exact_length_url + "x")

    assert format_stock_status(
        status, base_url
    ) == (
        "### <:phintraco:1531272488645038091> Stock Status: Wed, 23 Sep 2026\n\n"
        "**UMA:**\n(None)\n\n"
        "**Suspend In:**\n(None)\n\n"
        "**Suspend Out:**\n- WAPO\n- NASI\n\n"
        "**FCA In:**\n(None)\n\n"
        "**FCA Out:**\n- UNSP\n\n"
        "[View in Telegram](<https://t.me/phintasprofits/35377>)"
    )
```

- [ ] **Step 2: Run the focused renderer test and confirm it fails because the formatter is absent.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_stock_status.py -k renders`.

Expected: collection fails with `ImportError: cannot import name 'format_stock_status' from 'stock_status'`.

- [ ] **Step 3: Implement the renderer and Discord content guard.**

Use explicit English weekday and month abbreviation tuples so output does not depend on the VPS locale. Render section order as `UMA`, `Suspend In`, `Suspend Out`, `FCA In`, `FCA Out`. Put one blank line between sections and exactly one blank line before the source link. Do not render an attribution line. Raise `StockStatusError` when the rendered message is longer than 2,000 characters. Do not split or truncate content.

- [ ] **Step 4: Run parser and renderer tests, including 2,000 and 2,001 character cases.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_stock_status.py`.

Expected: exact message comparison passes, the footer is one empty line after the final section, exactly 2,000 characters is accepted, and 2,001 characters is rejected.

- [ ] **Step 5: Commit the formatter.**

```bash
git add cron-tg-market-news/bin/stock_status.py cron-tg-market-news/tests/test_stock_status.py
git commit -m "feat: render Phintraco stock status alerts"
```

## Task 3: Persist status events and rejection records

**Files:**
- Modify: `cron-tg-market-news/bin/state.py`
- Modify: `cron-tg-market-news/tests/test_state.py`

**Interfaces:**
- Consumes `StockStatus` from Task 1.
- Produces `enqueue_stock_status(state: dict[str, object], status: StockStatus, source_url: str, channel_id: str, content: str, now: datetime) -> bool`.
- Produces `reject_stock_status(state: dict[str, object], source_message_id: int, source_url: str, reason_code: str, now: datetime) -> bool`.
- Produces `pending_stock_status_events(state: dict[str, object], now: datetime) -> list[tuple[str, dict[str, object]]]`.
- Produces `mark_stock_status_delivered(state: dict[str, object], event_key: str, discord_message_id: str, now: datetime) -> None`.
- Produces `schedule_stock_status_retry(state: dict[str, object], event_key: str, now: datetime, error: str, minimum_delay_seconds: float = 0) -> None`.
- The event key is `phintraco-stock-status:<source_message_id>`. Events are stored in `state["stats"]["stock_status_events"]`; old states without this nested map remain readable and retain every existing candidate, cursor, retry, and delivery record.

- [ ] **Step 1: Write state round-trip, legacy-state, collision, and validation tests.**

```python
from datetime import datetime, timezone

from stock_status import format_stock_status, parse_stock_information
from state import (
    empty_state,
    enqueue_stock_status,
    load_state,
    pending_stock_status_events,
    save_state,
)


def test_stock_status_event_round_trips_without_changing_provider_cursors(
    tmp_path, monkeypatch, load_fixture
):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(state_path))
    state = empty_state()
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")
    source_url = "https://t.me/phintasprofits/35377"
    content = format_stock_status(status, source_url)

    assert enqueue_stock_status(
        state, status, source_url, "123", content, now
    ) is True
    save_state(state, state_path)
    restored = load_state(state_path)

    assert restored["providers"]["phintraco"]["observed_message_id"] == 0
    assert "phintraco-stock-status:35377" in restored["stats"]["stock_status_events"]


def test_old_state_without_stock_status_map_remains_readable():
    state = empty_state()
    state["stats"].pop("stock_status_events", None)

    assert pending_stock_status_events(state, datetime.now(timezone.utc)) == []
```

- [ ] **Step 2: Run focused state tests and confirm they fail because the event API is absent.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_state.py -k stock_status`.

Expected: collection fails with `ImportError: cannot import name 'enqueue_stock_status' from 'state'`.

- [ ] **Step 3: Add the closed event record schema and lifecycle helpers.**

Store source message ID, source URL, effective date, five parsed ticker lists, frozen destination channel ID, frozen content, phase, retry record, delivered Discord ID, and rejection code. A rejected event stores the source identity and a bounded reason code, never the raw source body. Validate allowed keys, phases, ticker arrays, timestamps, retry counters, and phase-specific required fields inside `_validate_state`. Keep the top-level state version and path unchanged. Create the nested event map lazily when a status event is first queued, and treat its absence as an empty map for existing state.

- [ ] **Step 4: Test cursor ordering and retry persistence.**

Add tests proving a rejected event can be persisted before `advance_provider_cursor`, and that a pending event reloads with identical content, channel ID, and retry metadata. Prove duplicate enqueue of an identical event returns `False`, while a different payload under the same event key raises `StateBlockedError`. Prove unknown phase or malformed retry data is rejected by `load_state()`.

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_state.py -k stock_status`.

Expected: all focused status-event state tests pass and existing state tests remain unchanged.

- [ ] **Step 5: Commit durable status state.**

```bash
git add cron-tg-market-news/bin/state.py cron-tg-market-news/tests/test_state.py
git commit -m "feat: persist Phintraco status events"
```

## Task 4: Deliver grouped events through the existing Discord sender

**Files:**
- Modify: `cron-tg-market-news/bin/delivery.py`
- Modify: `cron-tg-market-news/tests/test_delivery.py`

**Interfaces:**
- Consumes the persisted event functions from Task 3.
- Produces `async def deliver_stock_status_event(state: dict[str, object], event_key: str, now: datetime, *, dry_run: bool = False) -> bool`.
- It reads the persisted content and frozen channel ID, calls `post_discord_text(content, channel_id, event_key, dry_run=dry_run)`, then marks success or records the existing bounded retry schedule.

- [ ] **Step 1: Write delivery tests for success, retry, and rate limit.**

```python
import asyncio
from datetime import datetime
from types import SimpleNamespace

import delivery
import pytest
from state import empty_state, enqueue_stock_status
from stock_status import format_stock_status, parse_stock_information


@pytest.fixture
def status_event(load_fixture, tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    state = empty_state()
    status = parse_stock_information(
        35377, load_fixture("phintraco-stock-status-35377.txt")
    )
    now = datetime.fromisoformat("2026-09-23T08:30:00+07:00")
    source_url = "https://t.me/phintasprofits/35377"
    content = format_stock_status(status, source_url)
    event_key = "phintraco-stock-status:35377"
    enqueue_stock_status(state, status, source_url, "123", content, now)
    return SimpleNamespace(
        state=state, event_key=event_key, now=now, content=content
    )


def test_status_delivery_posts_frozen_payload_to_frozen_channel(monkeypatch, status_event):
    calls = []

    def post(content, channel_id, event_key, dry_run=False):
        calls.append((content, channel_id, event_key, dry_run))
        return "discord-message-42"

    monkeypatch.setattr(delivery, "post_discord_text", post)
    delivered = asyncio.run(
        delivery.deliver_stock_status_event(
            status_event.state, status_event.event_key, status_event.now
        )
    )

    assert delivered is True
    assert calls == [
        (status_event.content, "123", status_event.event_key, False)
    ]
```

- [ ] **Step 2: Run focused status delivery tests and confirm they fail because the delivery function is absent.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_delivery.py -k status`.

Expected: FAIL with `AttributeError: module 'delivery' has no attribute 'deliver_stock_status_event'`.

- [ ] **Step 3: Implement status delivery using the existing text sender.**

Before sending, require the event phase to be `pending_delivery` and require its persisted payload and destination. On success, store the Discord message ID and completion time. On `DiscordRateLimited`, honor `retry_after` through `schedule_stock_status_retry`; on other delivery failures, use the existing retry delay sequence of 1, 2, 4, 8, 15, 30, then 60 minutes. Keep the same event key, payload, and frozen channel on every retry.

- [ ] **Step 4: Verify idempotent retry behavior and the 2,000-character guard.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_delivery.py -k status`.

Expected: success marks the event delivered once; a transient error preserves the same rendered content, channel, and event key; a rate limit honors its server delay; oversized content never reaches `post_discord_text`.

- [ ] **Step 5: Commit status delivery.**

```bash
git add cron-tg-market-news/bin/delivery.py cron-tg-market-news/tests/test_delivery.py
git commit -m "feat: deliver Phintraco status alerts"
```

## Task 5: Intercept new status posts in the watcher

**Files:**
- Modify: `cron-tg-market-news/bin/scan.py`
- Modify: `cron-tg-market-news/tests/test_scan.py`

**Interfaces:**
- Consumes `is_stock_information`, `parse_stock_information`, and `format_stock_status` from Task 1 and Task 2.
- Consumes status-event enqueue, rejection, pending, completion, and retry functions from Task 3 and Task 4.
- `_ingest_provider` returns `ProviderIngestResult` with `source_messages: int`, `candidates: int`, `status_events: int`, `status_rejected: int`, and `error: str | None`.
- The run drains pending status events in the same invocation, includes successful status alerts in `news_delivered`, and includes pending status retries in delivery health.

Define the result in `scan.py` as:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderIngestResult:
    source_messages: int
    candidates: int
    status_events: int
    status_rejected: int
    error: str | None
```

- [ ] **Step 1: Write scanner integration tests against `FakeClients`.**

Use the existing `FakeClients`, temporary watcher state, and `IDX_MARKET_NEWS_NO_POST=1`. Set Tuntun input to empty and provide one of the two status fixture bodies as a Phintraco Telegram message. Monkeypatch `delivery.post_discord_text` to capture payloads for route assertions.

```python
from stock_status import format_stock_status, parse_stock_information


def test_status_post_sends_one_grouped_message_without_agent_wake(
    tmp_state, monkeypatch, load_fixture
):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setenv("IDX_MARKET_NEWS_NO_POST", "1")
    _bootstrapped_state(tmp_state)
    monkeypatch.setattr(
        delivery,
        "get_market_snapshot",
        lambda *_args: pytest.fail("status-only run requested a market quote"),
    )
    clients = FakeClients()
    clients.client.messages["tuntun"] = []
    clients.client.messages["phintraco"] = [SimpleNamespace(
        id=35377,
        message=load_fixture("phintraco-stock-status-35377.txt"),
        date=datetime.fromisoformat("2026-09-23T01:27:27+00:00"),
        photo=None,
    )]
    posts = []

    def post(content, channel_id, event_key, dry_run=False):
        posts.append((content, channel_id, event_key, dry_run))
        return "discord-message-42"

    monkeypatch.setattr(delivery, "post_discord_text", post)

    result = asyncio.run(
        scan.run(datetime.fromisoformat("2026-09-23T08:30:00+07:00"), clients)
    )

    assert result["wakeAgent"] is False
    assert result["items"] == []
    assert result["stock_status_delivered"] == 1
    assert load_state()["candidates"] == {}
    assert load_state()["providers"]["phintraco"]["observed_message_id"] == 35377
    assert len(posts) == 1
    assert posts[0][0] == format_stock_status(
        parse_stock_information(
            35377, load_fixture("phintraco-stock-status-35377.txt")
        ),
        "https://t.me/phintasprofits/35377",
    )
    assert posts[0][1] == config.default_watch_config().id_stocks_news_channel_id
    assert posts[0][2] == "phintraco-stock-status:35377"
    assert posts[0][3] is True
```

- [ ] **Step 2: Run the new scanner test and confirm it fails because status intake is not implemented.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_scan.py -k status_post`.

Expected: FAIL because the status message enters ordinary candidate extraction and does not return `stock_status_delivered`.

- [ ] **Step 3: Intercept and persist status messages before ordinary candidate extraction.**

Inside `_ingest_provider`, when `provider is Provider.PHINTRACO` and `is_stock_information(text)` is true, create `SourceMessage(Provider.PHINTRACO, message_id, published_at, text, direct_image)` and pass it to the existing `source_message_url` helper. Parse and render the complete event, freeze `config.active_watch_config().id_stocks_news_channel_id`, and call `enqueue_stock_status`. For `StockStatusError`, call `reject_stock_status` with a closed reason code. In both branches, persist the status event or rejection before advancing the Phintraco cursor, then continue to the next message without calling `PhintracoNewsAdapter.extract_candidates`. All other provider messages keep the existing extraction path.

- [ ] **Step 4: Drain delivery and report status counters without logging source text.**

Add `_drain_stock_status_events` beside `_drain_delivery`, select only due `pending_delivery` events, and call `deliver_stock_status_event` for each. Combine successful status posts into `news_delivered`, add `stock_status_delivered` and `stock_status_rejected` counters to the run result and structured control-plane attributes, include pending status events in `_pending_count` and `_health_and_warning`, and mark the current run degraded when intake records a status rejection. Pass the rejection flag to the existing hourly heartbeat warning marker without adding source text to it.

- [ ] **Step 5: Add the all-empty and duplicate-read scanner tests.**

Build an all-empty source body from fixture 35377 by replacing its WAPO, NASI, and UNSP entries with `>-`. Assert that this valid event still sends all five `(None)` sections. Run the valid 35377 input twice against the same temporary state and assert that the cursor prevents a second Discord delivery.

- [ ] **Step 6: Run the all-empty and duplicate-read scanner tests.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_scan.py -k 'status and (empty or duplicate)'`.

Expected: an all-empty post sends one complete status message, and processing the same source ID again does not create another Discord post.

- [ ] **Step 7: Add a scanner retry test.**

Make the first mocked `post_discord_text` call return `None`, then run the scanner again one minute later with no newly fetched source messages. Assert that the second attempt reuses the original content, route, and event key.

- [ ] **Step 8: Run the scanner retry test.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_scan.py -k 'status and retry'`.

Expected: the failed status delivery remains pending, then retries with the same saved message text, destination channel, and event key on the next scan.

- [ ] **Step 9: Add a malformed-source scanner test.**

Provide a status message with an unknown heading and capture `ControlPlaneRun.finish`; assert that the rejection record is durable, the Phintraco cursor reaches that message ID, no Discord status post occurs, the run finishes as `degraded`, and neither the source body nor its ticker list appears in operational output.

- [ ] **Step 10: Run the malformed-source scanner test.**

Run: `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_scan.py -k 'status and malformed'`.

Expected: the malformed post is withheld, its rejection is saved before the cursor advances, and the current run completes as degraded without exposing source text in operational output.

- [ ] **Step 11: Verify ordinary source paths.**

Add assertions that a Phintraco Company Flash still creates its ordinary candidate and Tuntun ingestion still works. Run `../.venv/bin/python -m pytest -q cron-tg-market-news/tests/test_scan.py`; expect the existing scan tests and the new status tests to pass.

- [ ] **Step 12: Commit watcher integration.**

```bash
git add cron-tg-market-news/bin/scan.py cron-tg-market-news/tests/test_scan.py
git commit -m "feat: route Phintraco status posts directly"
```

## Task 6: Align package guidance and validate the full source change

**Files:**
- Modify: `cron-tg-market-news/AGENTS.md`
- Modify: `cron-tg-market-news/SKILL.md`

- [ ] **Step 1: Update package operating guidance.**

In `cron-tg-market-news/AGENTS.md`, replace the statement that Stock Information creates one candidate per identified issuer. Document the deterministic one-event-per-message behavior, the five source-to-output mappings, `#id-stocks-news` route, effective-date header, required sections, fail-closed rejection, empty category rendering, 2,000-character limit, new-message-only cursor behavior, and no-backfill rule. State explicitly that these events bypass AI classification and Yahoo market data.

- [ ] **Step 2: Update the Hermes runtime prompt.**

In `cron-tg-market-news/SKILL.md`, add a short deterministic-boundary note: the scanner consumes Phintraco `Stock Information` posts before agent wake and never supplies those posts as classifier items. Keep the existing JSON classification schema unchanged.

- [ ] **Step 3: Run focused package tests and repository validation.**

Run these commands from the repository root:

```bash
../.venv/bin/python -m pytest -q \
  cron-tg-market-news/tests/test_stock_status.py \
  cron-tg-market-news/tests/test_sources.py \
  cron-tg-market-news/tests/test_state.py \
  cron-tg-market-news/tests/test_delivery.py \
  cron-tg-market-news/tests/test_scan.py

../.venv/bin/python -m pytest -q \
  cron-tg-market-news/tests \
  lib-telegram-resilience/tests/test_documentation.py

bash scripts/test-all
```

Expected: focused tests, all market-news and resilience documentation tests, and repository validation pass. The tests use temporary state and mocked Discord delivery. They make no Discord post and do not trigger a Hermes job.

- [ ] **Step 4: Review the final diff and commit documentation.**

Run `git diff --check`, inspect `git status --short`, and confirm no files outside the file map changed. Commit the package docs:

```bash
git add cron-tg-market-news/AGENTS.md cron-tg-market-news/SKILL.md
git commit -m "docs: define Phintraco status forwarding"
```

- [ ] **Step 5: Publish the reviewed source branch.**

After all implementation commits pass the checks above, publish this feature branch with:

```bash
git push -u origin absolutepraya/phintraco-stock-status
```

Do not create a pull request automatically.

## Release Boundary

This plan ends with local verification and the reviewed source branch. It does not deploy runtime files, write VPS state or configuration, change or trigger Hermes schedules, post a test message, replay Telegram history, or alter production delivery routes. Any production release remains a separate reviewed operation under the Bursawatch release contract.
