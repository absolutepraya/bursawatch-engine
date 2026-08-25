# IDX Swing Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Hermes no-agent watcher that polls Phintraco Telegram every minute and forwards each new individual IDX buy call to Discord as source-only text followed by its source chart.

**Architecture:** A single testable Python module owns the verified Phintraco parser, durable JSON outbox, Telethon reads, Discord writes, retry state machine, heartbeat, and no-agent entrypoint. A thin shell wrapper loads allowlisted secrets and logs execution; a stdlib watchdog independently detects a stale poll. The delivery contract is strict FIFO: durable source capture, one text post, one chart post when present, then the next call.

**Tech Stack:** Python 3.11 or newer, Python stdlib, Telethon, Requests, pytest, Hermes cron, Discord REST API v10.

## Global Constraints

- **No LLM:** The runtime is deterministic `no_agent`; it never invokes an LLM, agent, market-data service, news service, indicator calculator, or chart generator.
- **Source:** Telegram `Phintraco Sekuritas Official`, channel ID `1444713822`.
- **Alert destination:** Discord `#id-stocks-swing`, channel ID `1525102458253217803`.
- **Operations destination:** Discord `#hermes`, channel ID `1505162000420835388`.
- **Schedule:** `* * * * *`, one invocation every minute.
- **Telegram authorization:** Reuse `POLYCOP_SESSION_STRING`; IDX Swing Watch has no Telegram write call site.
- **Call scope:** Trading Buy, Buy on Support, and Speculative Buy only; Entry, Stop-loss or Stoploss, at least one Target, and the Phintraco marker are required.
- **Deferred:** Weekly multi-stock text bundles and PDFs are not parsed or forwarded.
- **Alert copy:** Provider-first headline, bold labels, plain values, full source rationale, source-stated timestamp, named advisor when available, no `Read:` line, and no generated metrics.
- **Chart rule:** Use only a photo attached to the same Telegram message. A genuinely chartless call is forwarded with `**Chart:** Unavailable from source`.
- **Delivery rule:** Existing chart upload failures retry the chart only. Strict FIFO prevents newer alerts from passing an older pending chart.
- **Identity:** Telegram source message ID only. Different source IDs are distinct calls. Source edits are ignored.
- **Bootstrap:** First activation records the newest source ID and does not replay history.
- **Liveness:** One hourly `idx-swing` heartbeat to `#hermes`, using a persisted hour key rather than an exact minute check.
- **No em dashes:** Never use the em-dash character in code, strings, docs, logs, comments, or alerts.
- **Python compatibility:** Local tests run on Python 3.11; the VPS shared runtime is Python 3.13. Code must support both.
- **Lazy runtime dependencies:** Import Telethon and Requests inside the functions that need them so pure parser and state tests run without Telethon installed locally.
- **Dev home is not a Git repository:** There are no per-task Git commits. Every task ends with a focused test and full-suite checkpoint. Versioned backup happens after VPS verification through `~/.dotfiles/sync.sh`.
- **Local test runner:** `PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"`.
- **Source of truth:** `idx-swing-watch/SPEC.md` and `idx-swing-watch/CONTEXT.md`.

---

## File map

### Existing files retained unchanged

- `idx-swing-watch/SPEC.md`: approved behavior and acceptance contract.
- `idx-swing-watch/CONTEXT.md`: canonical domain vocabulary.
- `deploy.sh`: existing Mac-to-VPS `bin/` deployment helper.

### Files to create

- `idx-swing-watch/SKILL.md`: non-user-invocable operational contract for the Hermes cron.
- `idx-swing-watch/bin/scan.py`: parser, formatter, state, lock, Telegram ingestion, media capture, Discord delivery, heartbeat, orchestration, and CLI entrypoint.
- `idx-swing-watch/bin/idx-swing-watch.sh`: allowlisted environment loading, runtime selection, logging, and stdout passthrough.
- `idx-swing-watch/bin/watchdog.py`: gateway-independent stale-poll detector.
- `idx-swing-watch/tests/conftest.py`: inserts `bin/` into `sys.path` and supplies isolated state paths.
- `idx-swing-watch/tests/test_scan.py`: parser, formatter, state, Telegram, delivery, heartbeat, and orchestration behavior.
- `idx-swing-watch/tests/test_watchdog.py`: stale-poll and watchdog rate-limit behavior.
- `idx-swing-watch/tests/fixtures/trading_buy.txt`: SCMA Trading Buy source fixture.
- `idx-swing-watch/tests/fixtures/buy_on_support.txt`: BBRI Buy on Support source fixture.
- `idx-swing-watch/tests/fixtures/speculative_buy.txt`: BUKA Speculative Buy source fixture.

The implementation stays in one `scan.py` because the existing Hermes cron convention uses one deployable scanner, and all runtime transitions share one atomic state file. Pure functions remain at the top of the module; network and orchestration functions remain below them.

---

### Task 1: Pure Swing Call parser and exact Discord formatter

**Files:**
- Create: `idx-swing-watch/bin/scan.py`
- Create: `idx-swing-watch/tests/conftest.py`
- Create: `idx-swing-watch/tests/test_scan.py`
- Create: `idx-swing-watch/tests/fixtures/trading_buy.txt`
- Create: `idx-swing-watch/tests/fixtures/buy_on_support.txt`
- Create: `idx-swing-watch/tests/fixtures/speculative_buy.txt`

**Interfaces:**
- Produces: `PriceTarget(number: int | None, value: str)`.
- Produces: `SwingCall(source_message_id: int, provider: str, ticker: str, call_subtype: str, entry: str, stop_loss: str, targets: tuple[PriceTarget, ...], signal_datetime: datetime, rationale: str, advisor_name: str | None, advisor_role: str | None, has_source_chart: bool)`.
- Produces: `parse_swing_call(message_id: int, text: str, has_photo: bool) -> SwingCall | None`.
- Produces: `looks_like_swing_call(text: str) -> bool`, distinguishing malformed buy candidates from irrelevant posts.
- Produces: `format_swing_alert(call: SwingCall) -> str`.
- Produces: `serialize_call(call: SwingCall) -> dict` and `deserialize_call(payload: dict) -> SwingCall` for later state tasks.

- [ ] **Step 1: Create the three verified source fixtures**

Create `tests/fixtures/trading_buy.txt`:

```text
SCMA - Trading Buy : Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. MACD yang  konsisten membentuk histogram positif sejalan dengan peluang tersebut.

Entry : 208-212
Stop-loss : <200
Target : 230

By PHINTRACO SEKURITAS
10/07/2026 7.00 WIB
Alrich Paskalis T| Investment Advisor
- Disclaimer On -
```

Create `tests/fixtures/buy_on_support.txt`:

```text
BBRI - Buy on Support :  Spinning bottom yang terbentuk menjadi indikasi awal rebound seiring golden cross pada MACD. Jika mampu breakout resistance 2860, menjadi konfirmasi rebound.

Entry : 2710-2780
Stop-loss : <2670
Target 2: 3000
Target 1: 2900

By PHINTRACO SEKURITAS
10/07/2026 7.00 WIB
Alrich Paskalis T| Investment Advisor
- Disclaimer On -
```

Create `tests/fixtures/speculative_buy.txt`:

```text
BUKA - Speculative Buy : Hammer yang terbentuk pasca uji support critical 95 menjadi indikasi awal rebound jangka pendek. Spike volume memperkuat indikasi tersebut.

Entry : 96-97
Stoploss : <95
Target 2: 105
Target 1: 101

By PHINTRACO SEKURITAS
10/07/2026 7:00 WIB
Alrich Paskalis T | Investment Advisor
- Disclaimer On -
```

- [ ] **Step 2: Create test import and isolated-state scaffolding**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_SWING_WATCH_STATE_PATH", str(path))
    return path
```

- [ ] **Step 3: Write failing parser, rejection, and formatter tests**

Create `tests/test_scan.py` with:

```python
import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

import scan

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.mark.parametrize(
    ("filename", "message_id", "ticker", "subtype", "entry", "stop_loss"),
    [
        ("trading_buy.txt", 33655, "SCMA", "Trading Buy", "208 to 212", "<200"),
        ("buy_on_support.txt", 33654, "BBRI", "Buy on Support", "2710 to 2780", "<2670"),
        ("speculative_buy.txt", 33656, "BUKA", "Speculative Buy", "96 to 97", "<95"),
    ],
)
def test_parse_verified_subtypes(filename, message_id, ticker, subtype, entry, stop_loss):
    call = scan.parse_swing_call(message_id, fixture(filename), has_photo=True)
    assert call is not None
    assert call.source_message_id == message_id
    assert call.provider == "Phintraco"
    assert call.ticker == ticker
    assert call.call_subtype == subtype
    assert call.entry == entry
    assert call.stop_loss == stop_loss
    assert call.has_source_chart is True
    assert call.signal_datetime == dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB)
    assert call.advisor_name == "Alrich Paskalis T"
    assert call.advisor_role == "Investment Advisor"


def test_targets_are_sorted_by_number():
    call = scan.parse_swing_call(33654, fixture("buy_on_support.txt"), has_photo=True)
    assert [(target.number, target.value) for target in call.targets] == [(1, "2900"), (2, "3000")]


def test_unnumbered_target_is_preserved():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert call.targets == (scan.PriceTarget(None, "230"),)


def test_header_spacing_variants_parse():
    text = fixture("trading_buy.txt").replace("SCMA - Trading Buy", "SCMA- Trading Buy")
    assert scan.parse_swing_call(1, text, has_photo=False).ticker == "SCMA"
    text = fixture("trading_buy.txt").replace("SCMA - Trading Buy", "SCMA -Trading Buy")
    assert scan.parse_swing_call(2, text, has_photo=False).ticker == "SCMA"


@pytest.mark.parametrize(
    "text",
    [
        "Reminder\n\nMARK - Second target 1100 achieved\n\nBy PHINTRACO SEKURITAS",
        "JPFA - Sell on Strength : consider selling\nResistance : 2050\nBy PHINTRACO SEKURITAS",
        "PHINTAS Weekly Swing Trading Ideas_20260706\nASII - Breakout MA20 : Buy\nEntry : >=4710\nTarget : 5100\nStoploss : <4520\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nStop-loss : <200\nTarget : 230\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nEntry : 208-212\nTarget : 230\nBy PHINTRACO SEKURITAS",
        "SCMA - Trading Buy : rationale\nEntry : 208-212\nStop-loss : <200\nBy PHINTRACO SEKURITAS",
    ],
)
def test_non_calls_and_malformed_calls_are_rejected(text):
    assert scan.parse_swing_call(99, text, has_photo=True) is None

def test_malformed_buy_candidate_is_detectable():
    text = (
        "SCMA - Trading Buy : rationale\n"
        "Stop-loss : <200\n"
        "Target : 230\n"
        "By PHINTRACO SEKURITAS\n"
        "10/07/2026 7.00 WIB"
    )
    assert scan.looks_like_swing_call(text) is True
    assert scan.parse_swing_call(99, text, has_photo=True) is None



def test_format_chart_backed_alert_exact():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert scan.format_swing_alert(call) == (
        "[Phintraco] BUY: **SCMA**\n\n"
        "**Type:** Trading Buy\n"
        "**Entry:** 208 to 212\n"
        "**Stop-loss:** <200\n"
        "**Target:** 230\n"
        "**Signal date:** Fri, Jul 10 2026, 07:00 WIB\n\n"
        "**Reasons:** Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. "
        "MACD yang konsisten membentuk histogram positif sejalan dengan peluang tersebut.\n\n"
        "**Source:** Phintraco Sekuritas | Alrich Paskalis T, Investment Advisor"
    )


def test_format_multi_target_alert_exact():
    call = scan.parse_swing_call(33654, fixture("buy_on_support.txt"), has_photo=True)
    output = scan.format_swing_alert(call)
    assert "**Target 1:** 2900\n**Target 2:** 3000\n**Signal date:**" in output
    assert "`" not in output


def test_format_chartless_alert_exact_suffix():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=False)
    assert scan.format_swing_alert(call).endswith(
        "**Source:** Phintraco Sekuritas | Alrich Paskalis T, Investment Advisor\n"
        "**Chart:** Unavailable from source"
    )


def test_missing_advisor_falls_back_to_source_only():
    text = fixture("trading_buy.txt").replace("Alrich Paskalis T| Investment Advisor\n", "")
    call = scan.parse_swing_call(33655, text, has_photo=True)
    assert scan.format_swing_alert(call).endswith("**Source:** Phintraco Sekuritas")


def test_call_serialization_roundtrip():
    call = scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=True)
    assert scan.deserialize_call(scan.serialize_call(call)) == call
```

- [ ] **Step 4: Run the tests and verify the expected red state**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-swing-watch
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py -q
```

Expected: collection fails because `bin/scan.py` does not exist or the parser symbols are absent.

- [ ] **Step 5: Implement the pure model, parser, serializer, and formatter**

Create `bin/scan.py` with this initial content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE_CHANNEL_ID = 1444713822
ALERT_CHANNEL_ID = "1525102458253217803"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
DISCORD_API = "https://discord.com/api/v10"
WIB = ZoneInfo("Asia/Jakarta")
PROVIDER = "Phintraco"
ALLOWED_SUBTYPES = ("Trading Buy", "Buy on Support", "Speculative Buy")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

HEADER_RE = re.compile(
    r"^(?P<ticker>[A-Z][A-Z0-9]{1,9})\s*-\s*"
    r"(?P<subtype>Trading Buy|Buy on Support|Speculative Buy)\s*:\s*"
    r"(?P<rationale>.*)$",
    re.IGNORECASE,
)
ENTRY_RE = re.compile(r"^Entry\s*:\s*(.+)$", re.IGNORECASE)
STOP_RE = re.compile(r"^Stop(?:-?loss)\s*:\s*(.+)$", re.IGNORECASE)
TARGET_RE = re.compile(r"^Target(?:\s+(\d+))?\s*:\s*(.+)$", re.IGNORECASE)
DATE_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2})[.:](\d{2})\s+WIB$",
    re.IGNORECASE,
)
ADVISOR_RE = re.compile(r"^(.+?)\s*\|\s*(Investment Advisor)\s*$", re.IGNORECASE)
SOURCE_RE = re.compile(r"^By\s+PHINTRACO\s+SEKURITAS$", re.IGNORECASE)


@dataclass(frozen=True)
class PriceTarget:
    number: int | None
    value: str


@dataclass(frozen=True)
class SwingCall:
    source_message_id: int
    provider: str
    ticker: str
    call_subtype: str
    entry: str
    stop_loss: str
    targets: tuple[PriceTarget, ...]
    signal_datetime: dt.datetime
    rationale: str
    advisor_name: str | None
    advisor_role: str | None
    has_source_chart: bool


def normalize_text(value: str) -> str:
    lines = []
    for raw in html.unescape(value or "").replace("\u00a0", " ").splitlines():
        lines.append(re.sub(r"[ \t]+", " ", raw).strip())
    return "\n".join(lines).strip()


def normalize_price(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return re.sub(r"(?<=\d)\s*-\s*(?=\d)", " to ", value)


def canonical_subtype(value: str) -> str:
    folded = value.casefold()
    for subtype in ALLOWED_SUBTYPES:
        if subtype.casefold() == folded:
            return subtype
    raise ValueError(f"unsupported call subtype: {value}")


def looks_like_swing_call(text: str) -> bool:
    lines = normalize_text(text).splitlines()
    return bool(
        lines
        and HEADER_RE.match(lines[0])
        and any(SOURCE_RE.match(line) for line in lines)
    )


def parse_swing_call(message_id: int, text: str, has_photo: bool) -> SwingCall | None:
    normalized = normalize_text(text)
    lines = normalized.splitlines()
    if not lines:
        return None
    header = HEADER_RE.match(lines[0])
    if not header or not any(SOURCE_RE.match(line) for line in lines):
        return None

    entry = None
    stop_loss = None
    targets: list[PriceTarget] = []
    signal_datetime = None
    advisor_name = None
    advisor_role = None
    rationale_parts = [header.group("rationale").strip()]
    before_entry = True

    for line in lines[1:]:
        if not line:
            continue
        entry_match = ENTRY_RE.match(line)
        if entry_match:
            entry = normalize_price(entry_match.group(1))
            before_entry = False
            continue
        if before_entry and not SOURCE_RE.match(line):
            rationale_parts.append(line)
            continue
        stop_match = STOP_RE.match(line)
        if stop_match:
            stop_loss = normalize_price(stop_match.group(1))
            continue
        target_match = TARGET_RE.match(line)
        if target_match:
            number = int(target_match.group(1)) if target_match.group(1) else None
            targets.append(PriceTarget(number, normalize_price(target_match.group(2))))
            continue
        date_match = DATE_RE.match(line)
        if date_match:
            day, month, year, hour, minute = map(int, date_match.groups())
            signal_datetime = dt.datetime(year, month, day, hour, minute, tzinfo=WIB)
            continue
        advisor_match = ADVISOR_RE.match(line)
        if advisor_match:
            advisor_name = advisor_match.group(1).strip()
            advisor_role = "Investment Advisor"

    if entry is None or stop_loss is None or not targets or signal_datetime is None:
        return None

    targets.sort(key=lambda target: (target.number is None, target.number or 0))
    rationale = " ".join(part for part in rationale_parts if part).strip()
    return SwingCall(
        source_message_id=message_id,
        provider=PROVIDER,
        ticker=header.group("ticker").upper(),
        call_subtype=canonical_subtype(header.group("subtype")),
        entry=entry,
        stop_loss=stop_loss,
        targets=tuple(targets),
        signal_datetime=signal_datetime,
        rationale=rationale,
        advisor_name=advisor_name,
        advisor_role=advisor_role,
        has_source_chart=has_photo,
    )


def serialize_call(call: SwingCall) -> dict:
    payload = asdict(call)
    payload["signal_datetime"] = call.signal_datetime.isoformat()
    return payload


def deserialize_call(payload: dict) -> SwingCall:
    return SwingCall(
        source_message_id=int(payload["source_message_id"]),
        provider=str(payload["provider"]),
        ticker=str(payload["ticker"]),
        call_subtype=str(payload["call_subtype"]),
        entry=str(payload["entry"]),
        stop_loss=str(payload["stop_loss"]),
        targets=tuple(PriceTarget(item["number"], str(item["value"])) for item in payload["targets"]),
        signal_datetime=dt.datetime.fromisoformat(payload["signal_datetime"]),
        rationale=str(payload["rationale"]),
        advisor_name=payload.get("advisor_name"),
        advisor_role=payload.get("advisor_role"),
        has_source_chart=bool(payload["has_source_chart"]),
    )


def format_signal_datetime(value: dt.datetime) -> str:
    local = value.astimezone(WIB)
    return (
        f"{WEEKDAYS[local.weekday()]}, {MONTHS[local.month - 1]} {local.day} "
        f"{local.year}, {local:%H:%M} WIB"
    )


def format_swing_alert(call: SwingCall) -> str:
    lines = [
        f"[{call.provider}] BUY: **{call.ticker}**",
        "",
        f"**Type:** {call.call_subtype}",
        f"**Entry:** {call.entry}",
        f"**Stop-loss:** {call.stop_loss}",
    ]
    for target in call.targets:
        label = "Target" if target.number is None else f"Target {target.number}"
        lines.append(f"**{label}:** {target.value}")
    lines.extend(
        [
            f"**Signal date:** {format_signal_datetime(call.signal_datetime)}",
            "",
            f"**Reasons:** {call.rationale}",
            "",
        ]
    )
    source = "**Source:** Phintraco Sekuritas"
    if call.advisor_name and call.advisor_role:
        source += f" | {call.advisor_name}, {call.advisor_role}"
    lines.append(source)
    if not call.has_source_chart:
        lines.append("**Chart:** Unavailable from source")
    return "\n".join(lines)
```

- [ ] **Step 6: Run the parser and formatter tests**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 7: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
```

Expected: all collected tests pass.

---

### Task 2: Atomic state, durable outbox model, retry metadata, and process lock

**Files:**
- Modify: `idx-swing-watch/bin/scan.py`
- Modify: `idx-swing-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: `SwingCall`, `serialize_call`, `deserialize_call` from Task 1.
- Produces: `state_path() -> Path`, `media_dir() -> Path`, `lock_path() -> Path`.
- Produces: `empty_state() -> dict`, `load_state() -> dict`, `save_state(state: dict) -> None`.
- Produces: `enqueue_call(state: dict, call: SwingCall, now: datetime) -> dict`.
- Produces: `oldest_outbox_event(state: dict) -> dict | None`.
- Produces: `retry_due(event: dict, now: datetime) -> bool`, `schedule_retry(event: dict, now: datetime, error: str) -> None`, and `clear_retry(event: dict) -> None`.
- Produces: `run_lock() -> ContextManager[bool]`.
- Produces: `StateBlockedError`, carrying the blocked state for rate-limited fatal reporting.

- [ ] **Step 1: Write failing state, outbox, corruption, retry, and lock tests**

Append to `tests/test_scan.py`:

```python
# State and outbox

def sample_call(has_photo=True):
    return scan.parse_swing_call(33655, fixture("trading_buy.txt"), has_photo=has_photo)


def test_missing_state_returns_empty_state(tmp_state):
    state = scan.load_state()
    assert state["version"] == 1
    assert state["observed_message_id"] == 0
    assert state["outbox"] == {}
    assert state["blocked"] is False


def test_state_roundtrip_is_atomic(tmp_state):
    state = scan.empty_state()
    state["observed_message_id"] = 123
    scan.save_state(state)
    assert scan.load_state()["observed_message_id"] == 123
    assert not tmp_state.with_suffix(".tmp").exists()


def test_enqueue_call_uses_source_id_and_media_phase(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    assert event["event_key"] == "33655"
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["chart_status"] == "expected"
    assert event["text_discord_id"] is None
    assert list(state["outbox"]) == ["33655"]


def test_enqueue_chartless_call_starts_pending_text(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=False), dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["chart_status"] == "absent"


def test_same_source_message_is_not_enqueued_twice(tmp_state):
    state = scan.empty_state()
    first = scan.enqueue_call(state, sample_call(), dt.datetime.now(scan.WIB))
    second = scan.enqueue_call(state, sample_call(), dt.datetime.now(scan.WIB))
    assert first is second
    assert len(state["outbox"]) == 1


def test_retry_backoff_is_bounded(tmp_state):
    event = scan.enqueue_call(scan.empty_state(), sample_call(), dt.datetime.now(scan.WIB))
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    for _ in range(20):
        scan.schedule_retry(event, now, "network failed")
    due = dt.datetime.fromisoformat(event["next_attempt_at"])
    assert due - now == dt.timedelta(minutes=15)
    assert event["last_error"] == "network failed"


def test_corrupt_state_creates_backup_and_blocked_sentinel(tmp_state):
    tmp_state.write_text("{bad json")
    with pytest.raises(scan.StateBlockedError) as raised:
        scan.load_state()
    assert raised.value.state["blocked"] is True
    assert scan.state_path().exists()
    assert len(list(tmp_state.parent.glob("state.corrupt-*.json"))) == 1
    with pytest.raises(scan.StateBlockedError):
        scan.load_state()


def test_run_lock_is_nonblocking(tmp_state):
    with scan.run_lock() as acquired:
        assert acquired is True
        with scan.run_lock() as second:
            assert second is False
```

- [ ] **Step 2: Run the selected tests and verify they fail**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "state or enqueue or retry or corrupt or run_lock"
```

Expected: failures report missing state and lock symbols.

- [ ] **Step 3: Implement state paths, atomic persistence, blocked-state handling, outbox, retries, and lock**

Add these imports near the top of `bin/scan.py`:

```python
import contextlib
import fcntl
import hashlib
import shutil
```

Add below the constants:

```python
STATE_VERSION = 1
PHASE_PENDING_MEDIA_CAPTURE = "pending_media_capture"
PHASE_PENDING_TEXT = "pending_text"
PHASE_PENDING_CHART = "pending_chart"
MAX_RETRY_SECONDS = 15 * 60
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"


class StateBlockedError(RuntimeError):
    def __init__(self, message: str, state: dict):
        super().__init__(message)
        self.state = state


def state_path() -> Path:
    return Path(os.environ.get("IDX_SWING_WATCH_STATE_PATH", str(DEFAULT_STATE_FILE)))


def media_dir() -> Path:
    return state_path().parent / "media"


def lock_path() -> Path:
    return state_path().parent / "run.lock"


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "blocked": False,
        "block_reason": None,
        "observed_message_id": 0,
        "outbox": {},
        "last_poll_success": None,
        "last_delivery_success": None,
        "last_heartbeat_hour": None,
        "last_error_notice": None,
        "stats": {"runs": 0, "messages": 0, "calls": 0, "delivered": 0},
    }


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    os.chmod(temp, 0o600)
    temp.replace(path)


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return empty_state()
    try:
        state = json.loads(path.read_text())
        if state.get("version") != STATE_VERSION:
            raise ValueError(f"unsupported state version: {state.get('version')}")
    except Exception as exc:
        stamp = dt.datetime.now(WIB).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"state.corrupt-{stamp}.json")
        shutil.move(path, backup)
        state = empty_state()
        state["blocked"] = True
        state["block_reason"] = f"state corruption: {type(exc).__name__}"
        save_state(state)
        raise StateBlockedError(state["block_reason"], state) from exc
    if state.get("blocked"):
        raise StateBlockedError(str(state.get("block_reason") or "state is blocked"), state)
    return state


def enqueue_call(state: dict, call: SwingCall, now: dt.datetime) -> dict:
    key = str(call.source_message_id)
    existing = state.setdefault("outbox", {}).get(key)
    if existing is not None:
        return existing
    has_chart = call.has_source_chart
    event = {
        "event_key": key,
        "source_message_id": call.source_message_id,
        "call": serialize_call(call),
        "phase": PHASE_PENDING_MEDIA_CAPTURE if has_chart else PHASE_PENDING_TEXT,
        "chart_status": "expected" if has_chart else "absent",
        "media_path": None,
        "text_discord_id": None,
        "attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
        "created_at": now.isoformat(),
    }
    state["outbox"][key] = event
    return event


def oldest_outbox_event(state: dict) -> dict | None:
    outbox = state.get("outbox") or {}
    if not outbox:
        return None
    key = min(outbox, key=lambda value: int(value))
    return outbox[key]


def retry_due(event: dict, now: dt.datetime) -> bool:
    raw = event.get("next_attempt_at")
    return raw is None or now >= dt.datetime.fromisoformat(raw)


def schedule_retry(event: dict, now: dt.datetime, error: str) -> None:
    event["attempts"] = int(event.get("attempts", 0)) + 1
    delay = min(60 * (2 ** (event["attempts"] - 1)), MAX_RETRY_SECONDS)
    event["next_attempt_at"] = (now + dt.timedelta(seconds=delay)).isoformat()
    event["last_error"] = re.sub(r"\s+", " ", error).strip()[:240]


def clear_retry(event: dict) -> None:
    event["attempts"] = 0
    event["next_attempt_at"] = None
    event["last_error"] = None


@contextlib.contextmanager
def run_lock():
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
```

- [ ] **Step 4: Run the state and lock tests**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "state or enqueue or retry or corrupt or run_lock"
```

Expected: all selected tests pass.

- [ ] **Step 5: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
```

Expected: all collected tests pass.

---

### Task 3: Read-only Telethon observation, bootstrap, ingestion, and durable media capture

**Files:**
- Modify: `idx-swing-watch/bin/scan.py`
- Modify: `idx-swing-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: parser and state interfaces from Tasks 1 and 2.
- Produces: `_env(key: str) -> str | None` and `make_client()`.
- Produces: `resolve_source(client)`, `latest_source_message_id(client, entity) -> int`.
- Produces: `fetch_unseen_messages(client, entity, min_id: int) -> list`.
- Produces: `ingest_unseen_messages(client, entity, state: dict, now: datetime) -> tuple[int, int, int]`, returning `(message_count, call_count, malformed_count)`.
- Produces: `capture_oldest_media(client, entity, state: dict, now: datetime) -> bool`.

- [ ] **Step 1: Write fake Telegram objects and failing observation tests**

Append to `tests/test_scan.py`:

```python
# Telegram observation and media capture

class FakeMessage:
    def __init__(self, message_id, text, photo=False):
        self.id = message_id
        self.message = text
        self.photo = object() if photo else None


class FakeDialog:
    def __init__(self, entity_id, name="Phintraco Sekuritas Official"):
        self.entity = type("Entity", (), {"id": entity_id})()
        self.name = name


class FakeTelegramClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.dialog_calls = 0
        self.download_calls = []

    async def get_dialogs(self):
        self.dialog_calls += 1
        return [FakeDialog(scan.SOURCE_CHANNEL_ID)]

    def iter_messages(self, entity, min_id=0, reverse=False):
        assert reverse is True
        async def generate():
            for message in self.messages:
                if message.id > min_id:
                    yield message
        return generate()

    async def get_messages(self, entity, ids=None, limit=None):
        if ids is not None:
            return next((message for message in self.messages if message.id == ids), None)
        if limit == 1:
            return self.messages[-1:] if self.messages else []
        return self.messages

    async def download_media(self, message, target_type):
        assert target_type is bytes
        self.download_calls.append(message.id)
        return b"\xff\xd8\xffsource-chart"


def test_resolve_source_uses_verified_channel_id():
    client = FakeTelegramClient([])
    entity = asyncio.run(scan.resolve_source(client))
    assert entity.id == scan.SOURCE_CHANNEL_ID
    assert client.dialog_calls == 1


def test_fetch_unseen_messages_is_chronological_and_unbounded():
    client = FakeTelegramClient([
        FakeMessage(10, "irrelevant"),
        FakeMessage(11, fixture("trading_buy.txt"), photo=True),
        FakeMessage(12, fixture("buy_on_support.txt"), photo=True),
    ])
    entity = asyncio.run(scan.resolve_source(client))
    messages = asyncio.run(scan.fetch_unseen_messages(client, entity, min_id=10))
    assert [message.id for message in messages] == [11, 12]


def test_first_run_bootstrap_uses_latest_without_outbox(tmp_state):
    state = scan.empty_state()
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    bootstrapped = asyncio.run(scan.bootstrap_source(client, entity, state, dt.datetime.now(scan.WIB)))
    assert bootstrapped is True
    assert state["observed_message_id"] == 33655
    assert state["outbox"] == {}


def test_ingest_captures_calls_before_cursor_advance(tmp_state):
    state = scan.empty_state()
    state["observed_message_id"] = 33653
    client = FakeTelegramClient([
        FakeMessage(33654, fixture("buy_on_support.txt"), photo=True),
        FakeMessage(33655, fixture("trading_buy.txt"), photo=True),
        FakeMessage(33656, "unrelated research", photo=True),
        FakeMessage(
            33657,
            "SCMA - Trading Buy : rationale\nStop-loss : <200\nTarget : 230\n"
            "By PHINTRACO SEKURITAS\n10/07/2026 7.00 WIB",
            photo=True,
        ),
    ])
    entity = asyncio.run(scan.resolve_source(client))
    messages, calls, malformed = asyncio.run(
        scan.ingest_unseen_messages(client, entity, state, dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    )
    assert (messages, calls, malformed) == (4, 2, 1)
    assert state["observed_message_id"] == 33657
    assert list(state["outbox"]) == ["33654", "33655"]
    persisted = json.loads(tmp_state.read_text())
    assert list(persisted["outbox"]) == ["33654", "33655"]


def test_capture_oldest_media_writes_durable_file(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is True
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["chart_status"] == "captured"
    assert Path(event["media_path"]).read_bytes() == b"\xff\xd8\xffsource-chart"
    assert client.download_calls == [33655]


def test_media_recapture_after_text_returns_to_pending_chart(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    event["text_discord_id"] = "text-33655"
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is True
    assert event["phase"] == scan.PHASE_PENDING_CHART


def test_media_download_failure_stays_pending_capture(tmp_state):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=True), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    client = FakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    async def fail_download(message, target_type):
        raise TimeoutError("telegram media timeout")
    client.download_media = fail_download
    entity = asyncio.run(scan.resolve_source(client))
    captured = asyncio.run(scan.capture_oldest_media(client, entity, state, dt.datetime.now(scan.WIB)))
    assert captured is False
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE
    assert event["last_error"] == "telegram media timeout"
```

- [ ] **Step 2: Run the Telegram tests and verify they fail**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "source or unseen or bootstrap or ingest or media"
```

Expected: failures report missing Telegram observation functions.

- [ ] **Step 3: Implement environment loading and the read-only Telethon client**

Append to `bin/scan.py`:

```python
def _env(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value
    for env_file in (Path.home() / ".hermes" / ".env", Path.home() / "telegram-mcp" / ".env"):
        if not env_file.is_file():
            continue
        for raw in env_file.read_text().splitlines():
            if raw.startswith(key + "="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def make_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = _env("TELEGRAM_API_ID")
    api_hash = _env("TELEGRAM_API_HASH")
    session = _env("POLYCOP_SESSION_STRING")
    if not api_id or not api_hash or not session:
        raise RuntimeError("Telegram credentials are incomplete")
    return TelegramClient(StringSession(session), int(api_id), api_hash)


async def resolve_source(client):
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if getattr(dialog.entity, "id", None) == SOURCE_CHANNEL_ID:
            return dialog.entity
    raise RuntimeError("Phintraco source channel is not accessible")


async def latest_source_message_id(client, entity) -> int:
    messages = await client.get_messages(entity, limit=1)
    return int(messages[0].id) if messages else 0


async def fetch_unseen_messages(client, entity, min_id: int) -> list:
    return [
        message
        async for message in client.iter_messages(entity, min_id=min_id, reverse=True)
    ]
```

The Telegram section must contain no send, reply, edit, delete, reaction, join, leave, or mark-read operation.

- [ ] **Step 4: Implement bootstrap, ingestion, and durable media capture**

Append to `bin/scan.py`:

```python
async def bootstrap_source(client, entity, state: dict, now: dt.datetime) -> bool:
    if int(state.get("observed_message_id", 0)) != 0:
        return False
    state["observed_message_id"] = await latest_source_message_id(client, entity)
    state["last_poll_success"] = now.isoformat()
    save_state(state)
    return True


async def ingest_unseen_messages(client, entity, state: dict, now: dt.datetime) -> tuple[int, int, int]:
    messages = await fetch_unseen_messages(client, entity, int(state.get("observed_message_id", 0)))
    call_count = 0
    malformed_count = 0
    for message in messages:
        source_id = int(message.id)
        source_text = message.message or ""
        call = parse_swing_call(source_id, source_text, has_photo=bool(message.photo))
        if call is not None:
            enqueue_call(state, call, now)
            call_count += 1
            state["stats"]["calls"] = int(state["stats"].get("calls", 0)) + 1
        elif looks_like_swing_call(source_text):
            malformed_count += 1
        state["observed_message_id"] = source_id
        state["stats"]["messages"] = int(state["stats"].get("messages", 0)) + 1
        save_state(state)
    state["last_poll_success"] = now.isoformat()
    save_state(state)
    return len(messages), call_count, malformed_count


async def capture_oldest_media(client, entity, state: dict, now: dt.datetime) -> bool:
    event = oldest_outbox_event(state)
    if event is None or event["phase"] != PHASE_PENDING_MEDIA_CAPTURE:
        return True
    if not retry_due(event, now):
        return False
    try:
        message = await client.get_messages(entity, ids=int(event["source_message_id"]))
        if message is None or not message.photo:
            raise RuntimeError("expected source chart is unavailable")
        content = await client.download_media(message, bytes)
        if not content:
            raise RuntimeError("source chart download returned no bytes")
        directory = media_dir()
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"phintraco-{event['source_message_id']}.jpg"
        temp = final.with_suffix(".tmp")
        temp.write_bytes(content)
        os.chmod(temp, 0o600)
        temp.replace(final)
        event["media_path"] = str(final)
        event["chart_status"] = "captured"
        event["phase"] = PHASE_PENDING_CHART if event.get("text_discord_id") else PHASE_PENDING_TEXT
        clear_retry(event)
        save_state(state)
        return True
    except Exception as exc:
        schedule_retry(event, now, str(exc))
        save_state(state)
        return False
```

- [ ] **Step 5: Run the Telegram ingestion and media tests**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "source or unseen or bootstrap or ingest or media"
```

Expected: all selected tests pass.

- [ ] **Step 6: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
```

Expected: all collected tests pass.

---

### Task 4: Discord REST client and strict FIFO two-leg delivery

**Files:**
- Modify: `idx-swing-watch/bin/scan.py`
- Modify: `idx-swing-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: `format_swing_alert`, state paths, retry helpers, and outbox phases.
- Produces: `_discord_request(method: str, url: str, headers: dict, max_retries: int = 3, **kwargs)`.
- Produces: `post_discord_text(content: str, channel_id: str, dry_run: bool, event_key: str) -> str | None`.
- Produces: `post_discord_file(path: str, channel_id: str, dry_run: bool, event_key: str) -> str | None`.
- Produces: `drain_outbox(state: dict, now: datetime, dry_run: bool = False) -> int`, returning the number delivered in this run.

- [ ] **Step 1: Write failing delivery-order and partial-failure tests**

Append to `tests/test_scan.py`:

```python
# Discord delivery and strict FIFO

def enqueue_ready(state, call, tmp_path, chart=True):
    event = scan.enqueue_call(state, call, dt.datetime.now(scan.WIB))
    if chart:
        path = tmp_path / f"{call.source_message_id}.jpg"
        path.write_bytes(b"chart")
        event["phase"] = scan.PHASE_PENDING_TEXT
        event["chart_status"] = "captured"
        event["media_path"] = str(path)
    return event


def test_text_then_chart_order_per_call(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    first = sample_call(has_photo=True)
    second = scan.SwingCall(**{**first.__dict__, "source_message_id": 33656, "ticker": "BUKA"})
    enqueue_ready(state, first, tmp_path)
    enqueue_ready(state, second, tmp_path)
    scan.save_state(state)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append(("text", event_key)) or f"text-{event_key}")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or f"chart-{event_key}")
    delivered = scan.drain_outbox(state, dt.datetime.now(scan.WIB))
    assert delivered == 2
    assert events == [("text", "33655"), ("chart", "33655"), ("text", "33656"), ("chart", "33656")]
    assert state["outbox"] == {}


def test_text_failure_does_not_attempt_chart(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    scan.save_state(state)
    monkeypatch.setattr(scan, "post_discord_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("chart must not be attempted"))
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 0
    assert event["phase"] == scan.PHASE_PENDING_TEXT
    assert event["text_discord_id"] is None


def test_chart_failure_retries_chart_only_and_blocks_newer_call(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    first = sample_call(has_photo=True)
    second = scan.SwingCall(**{**first.__dict__, "source_message_id": 33656, "ticker": "BUKA"})
    first_event = enqueue_ready(state, first, tmp_path)
    enqueue_ready(state, second, tmp_path)
    scan.save_state(state)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append(("text", event_key)) or f"text-{event_key}")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or None)
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    assert scan.drain_outbox(state, now) == 0
    assert events == [("text", "33655"), ("chart", "33655")]
    assert first_event["phase"] == scan.PHASE_PENDING_CHART
    assert first_event["text_discord_id"] == "text-33655"
    scan.clear_retry(first_event)
    events.clear()
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append(("chart", event_key)) or f"chart-{event_key}")
    assert scan.drain_outbox(state, now) == 2
    assert events == [("chart", "33655"), ("text", "33656"), ("chart", "33656")]


def test_chartless_call_delivers_text_only(tmp_state, monkeypatch):
    state = scan.empty_state()
    event = scan.enqueue_call(state, sample_call(has_photo=False), dt.datetime.now(scan.WIB))
    scan.save_state(state)
    captured = {}
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: captured.update(content=content) or "text-33655")
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("chartless call must not upload"))
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 1
    assert "**Chart:** Unavailable from source" in captured["content"]
    assert event["event_key"] not in state["outbox"]


def test_missing_cached_chart_returns_to_media_capture(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    event = enqueue_ready(state, sample_call(), tmp_path)
    Path(event["media_path"]).unlink()
    event["phase"] = scan.PHASE_PENDING_CHART
    event["text_discord_id"] = "text-33655"
    scan.save_state(state)
    monkeypatch.setattr(scan, "post_discord_file", lambda *args, **kwargs: pytest.fail("missing file must not upload"))
    assert scan.drain_outbox(state, dt.datetime.now(scan.WIB)) == 0
    assert event["phase"] == scan.PHASE_PENDING_MEDIA_CAPTURE


def test_oversized_alert_is_rejected_without_splitting(monkeypatch):
    monkeypatch.setattr(scan, "_discord_token", lambda: "token")
    with pytest.raises(ValueError, match="Discord message limit"):
        scan.post_discord_text("x" * 2001, scan.ALERT_CHANNEL_ID, False, "1")
```

- [ ] **Step 2: Run the delivery tests and verify they fail**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "order or failure or chartless or cached_chart or oversized"
```

Expected: failures report missing Discord and delivery functions.

- [ ] **Step 3: Implement bounded Discord requests and message-ID returns**

Add `import time` near the top of `bin/scan.py`, then append:

```python
def _discord_token() -> str | None:
    return _env("DISCORD_BOT_TOKEN")


def _discord_request(method: str, url: str, *, headers: dict, max_retries: int = 3, **kwargs):
    import requests

    response = None
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        except Exception as exc:
            print(f"Discord request failed on attempt {attempt + 1}: {exc}", file=os.sys.stderr)
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 429:
            try:
                delay = float(response.json().get("retry_after", 1.0))
            except Exception:
                delay = float(response.headers.get("Retry-After", 1.0))
            time.sleep(min(delay + 0.25, 10.0))
            continue
        return response
    return response


def post_discord_text(content: str, channel_id: str, dry_run: bool, event_key: str) -> str | None:
    if len(content) > 2000:
        raise ValueError("Swing Alert exceeds Discord message limit")
    if dry_run or os.environ.get("IDX_SWING_WATCH_NO_POST") == "1":
        print(f"[dry-run] Discord text {channel_id} event {event_key}:\n{content}")
        return f"dry-text-{event_key}"
    token = _discord_token()
    if not token:
        return None
    response = _discord_request(
        "POST",
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"content": content},
    )
    if response is None or response.status_code not in (200, 201):
        return None
    return str(response.json()["id"])


def post_discord_file(path: str, channel_id: str, dry_run: bool, event_key: str) -> str | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    if dry_run or os.environ.get("IDX_SWING_WATCH_NO_POST") == "1":
        print(f"[dry-run] Discord chart {channel_id} event {event_key}: {file_path}")
        return f"dry-chart-{event_key}"
    token = _discord_token()
    if not token:
        return None
    for attempt in range(3):
        with file_path.open("rb") as handle:
            response = _discord_request(
                "POST",
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                max_retries=1,
                data={"payload_json": json.dumps({"content": ""})},
                files={"files[0]": (file_path.name, handle, "image/jpeg")},
            )
        if response is not None and response.status_code in (200, 201):
            return str(response.json()["id"])
        if response is None or response.status_code != 429:
            return None
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return None
```

- [ ] **Step 4: Implement strict FIFO outbox delivery**

Append:

```python
def drain_outbox(state: dict, now: dt.datetime, dry_run: bool = False) -> int:
    delivered = 0
    while True:
        event = oldest_outbox_event(state)
        if event is None:
            return delivered
        if not retry_due(event, now):
            return delivered
        phase = event["phase"]
        if phase == PHASE_PENDING_MEDIA_CAPTURE:
            return delivered
        call = deserialize_call(event["call"])

        if phase == PHASE_PENDING_TEXT:
            try:
                text_id = post_discord_text(
                    format_swing_alert(call), ALERT_CHANNEL_ID, dry_run, event["event_key"]
                )
            except Exception as exc:
                schedule_retry(event, now, str(exc))
                save_state(state)
                return delivered
            if text_id is None:
                schedule_retry(event, now, "Discord text delivery failed")
                save_state(state)
                return delivered
            event["text_discord_id"] = text_id
            clear_retry(event)
            if call.has_source_chart:
                event["phase"] = PHASE_PENDING_CHART
                save_state(state)
                phase = PHASE_PENDING_CHART
            else:
                del state["outbox"][event["event_key"]]
                state["last_delivery_success"] = now.isoformat()
                state["stats"]["delivered"] = int(state["stats"].get("delivered", 0)) + 1
                save_state(state)
                delivered += 1
                continue

        if phase == PHASE_PENDING_CHART:
            media_path = Path(event.get("media_path") or "")
            if not media_path.is_file():
                event["phase"] = PHASE_PENDING_MEDIA_CAPTURE
                event["chart_status"] = "expected"
                schedule_retry(event, now, "cached source chart is missing")
                save_state(state)
                return delivered
            chart_id = post_discord_file(
                str(media_path), ALERT_CHANNEL_ID, dry_run, event["event_key"]
            )
            if chart_id is None:
                schedule_retry(event, now, "Discord chart delivery failed")
                save_state(state)
                return delivered
            del state["outbox"][event["event_key"]]
            state["last_delivery_success"] = now.isoformat()
            state["stats"]["delivered"] = int(state["stats"].get("delivered", 0)) + 1
            save_state(state)
            media_path.unlink(missing_ok=True)
            delivered += 1
```

- [ ] **Step 5: Run the delivery tests**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "order or failure or chartless or cached_chart or oversized"
```

Expected: all selected tests pass.

- [ ] **Step 6: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
```

Expected: all collected tests pass.

---

### Task 5: Orchestration, hourly heartbeat, fatal rate limiting, and no-agent output

**Files:**
- Modify: `idx-swing-watch/bin/scan.py`
- Modify: `idx-swing-watch/tests/test_scan.py`

**Interfaces:**
- Consumes: all Tasks 1 through 4 interfaces.
- Produces: `RunStats(messages: int, calls: int, delivered: int, pending: int, degraded: bool)`.
- Produces: `format_heartbeat(now: datetime, stats: RunStats) -> str` and `format_fatal(now: datetime, reason: str) -> str`.
- Produces: `post_heartbeat_if_due(state: dict, now: datetime, stats: RunStats, dry_run: bool) -> bool`.
- Produces: `report_fatal(state: dict, now: datetime, reason: str, dry_run: bool) -> bool`.
- Produces: `async run(now: datetime | None = None, dry_run: bool = False) -> dict`.
- Produces: `main() -> int`, always printing a no-agent JSON object.

- [ ] **Step 1: Write failing heartbeat and orchestration tests**

Append to `tests/test_scan.py`:

```python
# Heartbeat and orchestration

def test_format_heartbeat_healthy_and_degraded():
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    healthy = scan.format_heartbeat(now, scan.RunStats(42, 3, 3, 0, False))
    assert healthy == "🫀 idx-swing · 08:00 WIB · 42 messages · 3 calls · 3 delivered · 0 pending"
    degraded = scan.format_heartbeat(now, scan.RunStats(42, 3, 2, 1, True))
    assert degraded.endswith(" · 1 pending ⚠️")


def test_delayed_new_hour_posts_heartbeat(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["last_heartbeat_hour"] = "2026-07-10T07+07:00"
    scan.save_state(state)
    posts = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: posts.append(content) or "heartbeat-id")
    now = dt.datetime(2026, 7, 10, 8, 7, tzinfo=scan.WIB)
    assert scan.post_heartbeat_if_due(state, now, scan.RunStats(0, 0, 0, 0, False), False) is True
    assert len(posts) == 1
    assert state["last_heartbeat_hour"] == "2026-07-10T08+07:00"


def test_failed_heartbeat_does_not_persist_hour(tmp_state, monkeypatch):
    state = scan.empty_state()
    monkeypatch.setattr(scan, "post_discord_text", lambda *args, **kwargs: None)
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB)
    assert scan.post_heartbeat_if_due(state, now, scan.RunStats(0, 0, 0, 0, False), False) is False
    assert state["last_heartbeat_hour"] is None


def test_fatal_notice_is_rate_limited_per_fingerprint_and_hour(tmp_state, monkeypatch):
    state = scan.empty_state()
    posts = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: posts.append(content) or "fatal-id")
    now = dt.datetime(2026, 7, 10, 8, 1, tzinfo=scan.WIB)
    assert scan.report_fatal(state, now, "Telegram unavailable", False) is True
    assert scan.report_fatal(state, now, "Telegram unavailable", False) is False
    assert len(posts) == 1


class ConnectedFakeTelegramClient(FakeTelegramClient):
    async def connect(self):
        return None

    async def disconnect(self):
        return None


def test_run_bootstraps_without_replay(tmp_state, monkeypatch):
    client = ConnectedFakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    result = asyncio.run(scan.run(now=dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB), dry_run=True))
    assert result == {"wakeAgent": False}
    state = scan.load_state()
    assert state["observed_message_id"] == 33655
    assert state["outbox"] == {}


def test_run_ingests_and_delivers_text_then_chart(tmp_state, tmp_path, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33654
    scan.save_state(state)
    client = ConnectedFakeTelegramClient([FakeMessage(33655, fixture("trading_buy.txt"), photo=True)])
    monkeypatch.setattr(scan, "make_client", lambda: client)
    monkeypatch.setattr(scan, "post_heartbeat_if_due", lambda *args, **kwargs: True)
    events = []
    monkeypatch.setattr(scan, "post_discord_text", lambda content, channel_id, dry_run, event_key: events.append("text") or "text-id")
    monkeypatch.setattr(scan, "post_discord_file", lambda path, channel_id, dry_run, event_key: events.append("chart") or "chart-id")
    result = asyncio.run(scan.run(now=dt.datetime(2026, 7, 10, 8, 0, tzinfo=scan.WIB))
    assert result == {"wakeAgent": False}
    assert events == ["text", "chart"]
    assert scan.load_state()["outbox"] == {}


def test_main_prints_no_agent_json_on_fatal(monkeypatch, capsys):
    async def fail_run(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(scan, "run", fail_run)
    monkeypatch.setattr(scan, "load_state", lambda: scan.empty_state())
    monkeypatch.setattr(scan, "report_fatal", lambda *args, **kwargs: True)
    assert scan.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"wakeAgent": False, "error": "boom"}
```

- [ ] **Step 2: Run the orchestration tests and verify they fail**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "heartbeat or fatal or run_ or main_prints"
```

Expected: failures report missing runtime interfaces.

- [ ] **Step 3: Implement heartbeat and fatal helpers**

Add this dataclass after `SwingCall`:

```python
@dataclass(frozen=True)
class RunStats:
    messages: int
    calls: int
    delivered: int
    pending: int
    degraded: bool
```

Append:

```python
def heartbeat_hour_key(now: dt.datetime) -> str:
    local = now.astimezone(WIB)
    return local.strftime("%Y-%m-%dT%H") + local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:]


def format_heartbeat(now: dt.datetime, stats: RunStats) -> str:
    line = (
        f"🫀 idx-swing · {now.astimezone(WIB):%H:%M} WIB · "
        f"{stats.messages} messages · {stats.calls} calls · "
        f"{stats.delivered} delivered · {stats.pending} pending"
    )
    return line + (" ⚠️" if stats.degraded else "")


def format_fatal(now: dt.datetime, reason: str) -> str:
    clean = re.sub(r"\s+", " ", reason).strip()[:180]
    return f"❌ idx-swing · {now.astimezone(WIB):%H:%M} WIB · failed: {clean}"


def post_heartbeat_if_due(state: dict, now: dt.datetime, stats: RunStats, dry_run: bool) -> bool:
    hour = heartbeat_hour_key(now)
    if not os.environ.get("IDX_SWING_WATCH_FORCE_HEARTBEAT") and state.get("last_heartbeat_hour") == hour:
        return False
    message_id = post_discord_text(
        format_heartbeat(now, stats), HEARTBEAT_CHANNEL_ID, dry_run, f"heartbeat-{hour}"
    )
    if message_id is None:
        return False
    state["last_heartbeat_hour"] = hour
    save_state(state)
    return True


def error_fingerprint(reason: str) -> str:
    clean = re.sub(r"\s+", " ", reason).strip()
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def report_fatal(state: dict, now: dt.datetime, reason: str, dry_run: bool) -> bool:
    notice = {"fingerprint": error_fingerprint(reason), "hour": heartbeat_hour_key(now)}
    if state.get("last_error_notice") == notice:
        return False
    message_id = post_discord_text(
        format_fatal(now, reason), HEARTBEAT_CHANNEL_ID, dry_run,
        f"fatal-{notice['fingerprint']}-{notice['hour']}",
    )
    if message_id is None:
        return False
    state["last_error_notice"] = notice
    save_state(state)
    return True
```

- [ ] **Step 4: Implement the locked runtime orchestration and no-agent entrypoint**

Add `import asyncio` near the top, then append:

```python
async def run(now: dt.datetime | None = None, dry_run: bool = False) -> dict:
    now = now or dt.datetime.now(WIB)
    with run_lock() as acquired:
        if not acquired:
            return {"wakeAgent": False}
        state = load_state()
        state["stats"]["runs"] = int(state["stats"].get("runs", 0)) + 1
        client = make_client()
        await client.connect()
        messages = calls = malformed = delivered = 0
        degraded = False
        try:
            entity = await resolve_source(client)
            if await bootstrap_source(client, entity, state, now):
                stats = RunStats(0, 0, 0, 0, False)
                post_heartbeat_if_due(state, now, stats, dry_run)
                return {"wakeAgent": False}

            messages, calls, malformed = await ingest_unseen_messages(client, entity, state, now)
            degraded = malformed > 0
            while True:
                event = oldest_outbox_event(state)
                if event is None or not retry_due(event, now):
                    break
                if event["phase"] == PHASE_PENDING_MEDIA_CAPTURE:
                    if not await capture_oldest_media(client, entity, state, now):
                        degraded = True
                        break
                before = len(state["outbox"])
                delivered += drain_outbox(state, now, dry_run=dry_run)
                after = len(state["outbox"])
                current = oldest_outbox_event(state)
                if after == before and current is not None:
                    degraded = True
                    break
            state["last_poll_success"] = now.isoformat()
            save_state(state)
        finally:
            await client.disconnect()

        pending = len(state.get("outbox") or {})
        degraded = degraded or pending > 0
        stats = RunStats(messages, calls, delivered, pending, degraded)
        post_heartbeat_if_due(state, now, stats, dry_run)
        return {"wakeAgent": False}


def main() -> int:
    dry_run = os.environ.get("IDX_SWING_WATCH_NO_POST") == "1"
    now = dt.datetime.now(WIB)
    try:
        result = asyncio.run(run(now=now, dry_run=dry_run))
    except StateBlockedError as exc:
        report_fatal(exc.state, now, str(exc), dry_run)
        result = {"wakeAgent": False, "error": str(exc)}
    except Exception as exc:
        try:
            state = load_state()
        except StateBlockedError as blocked:
            state = blocked.state
        except Exception:
            state = empty_state()
        report_fatal(state, now, str(exc), dry_run)
        result = {"wakeAgent": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run heartbeat and orchestration tests**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "heartbeat or fatal or run_ or main_prints"
```

Expected: all selected tests pass.

- [ ] **Step 6: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
$PYT -m py_compile bin/scan.py
```

Expected: all tests pass and compilation exits with code 0.

---

### Task 6: Runtime wrapper, operational skill, and gateway-independent watchdog

**Files:**
- Create: `idx-swing-watch/bin/idx-swing-watch.sh`
- Create: `idx-swing-watch/bin/watchdog.py`
- Create: `idx-swing-watch/SKILL.md`
- Create: `idx-swing-watch/tests/test_watchdog.py`

**Interfaces:**
- Consumes: `scan.load_state`, `scan.empty_state`, `scan.WIB`, and `scan.report_fatal`.
- Produces: `watchdog.is_stale(state: dict, now: datetime, max_gap_minutes: int = 10) -> bool`.
- Produces: executable `idx-swing-watch.sh` and `watchdog.py`.

- [ ] **Step 1: Write failing watchdog tests**

Create `tests/test_watchdog.py`:

```python
import datetime as dt
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "watchdog.py"
SPEC = importlib.util.spec_from_file_location("idx_swing_watchdog", MODULE_PATH)
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def test_is_stale_when_poll_missing():
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=watchdog.WIB)
    assert watchdog.is_stale({}, now, 10) is True


def test_is_stale_after_ten_minutes():
    now = dt.datetime(2026, 7, 10, 8, 11, tzinfo=watchdog.WIB)
    state = {"last_poll_success": "2026-07-10T08:00:00+07:00"}
    assert watchdog.is_stale(state, now, 10) is True


def test_recent_poll_is_healthy():
    now = dt.datetime(2026, 7, 10, 8, 9, tzinfo=watchdog.WIB)
    state = {"last_poll_success": "2026-07-10T08:00:00+07:00"}
    assert watchdog.is_stale(state, now, 10) is False
```

- [ ] **Step 2: Run the watchdog tests and verify they fail**

Run:

```bash
$PYT -m pytest tests/test_watchdog.py -q
```

Expected: import fails because `bin/watchdog.py` does not exist.

- [ ] **Step 3: Implement the stdlib watchdog**

Create `bin/watchdog.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan

WIB = ZoneInfo("Asia/Jakarta")
MAX_GAP_MINUTES = 10


def is_stale(state: dict, now: dt.datetime, max_gap_minutes: int = MAX_GAP_MINUTES) -> bool:
    raw = state.get("last_poll_success")
    if not raw:
        return True
    try:
        last = dt.datetime.fromisoformat(raw).astimezone(WIB)
    except Exception:
        return True
    return now.astimezone(WIB) - last > dt.timedelta(minutes=max_gap_minutes)


def main() -> int:
    now = dt.datetime.now(WIB)
    dry_run = os.environ.get("IDX_SWING_WATCH_NO_POST") == "1"
    try:
        state = scan.load_state()
    except scan.StateBlockedError as exc:
        scan.report_fatal(exc.state, now, f"watchdog state blocked: {exc}", dry_run)
        return 1
    except Exception as exc:
        state = scan.empty_state()
        scan.report_fatal(state, now, f"watchdog cannot read state: {exc}", dry_run)
        return 1
    if not is_stale(state, now):
        return 0
    scan.report_fatal(
        state,
        now,
        f"no successful Telegram poll within {MAX_GAP_MINUTES} minutes",
        dry_run,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Create the deterministic wrapper**

Create `bin/idx-swing-watch.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Jakarta"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

if [[ -r "$HOME/.hermes/.env" ]]; then
  for k in DISCORD_BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH POLYCOP_SESSION_STRING; do
    v="$(grep -E "^${k}=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- || true)"
    [[ -n "${v:-}" ]] && export "${k}=${v}"
  done
fi

PYTHON_BIN="${IDX_SWING_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="$HOME/.agents/skills/idx-swing-watch/bin/scan.py"
LOG_DIR="$HOME/.logs"
LOG="$LOG_DIR/idx-swing-watch.log"
mkdir -p "$LOG_DIR"
ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "$(ts) FATAL: python missing at $PYTHON_BIN" | tee -a "$LOG" >&2
  exit 127
fi

echo "$(ts) START idx-swing-watch $*" >> "$LOG"
set +e
out="$("$PYTHON_BIN" "$SCRIPT" "$@" 2> >(tee -a "$LOG" >&2))"
rc=$?
set -e
printf '%s\n' "$out" | tee -a "$LOG"
echo "$(ts) END rc=$rc" >> "$LOG"
exit "$rc"
```

- [ ] **Step 5: Create the non-user-invocable operational skill**

Create `SKILL.md`:

```markdown
---
name: idx-swing-watch
description: Deterministic Hermes cron that polls Phintraco Telegram every minute and forwards individual IDX buy calls to Discord as source-only text followed by the source chart.
user-invocable: false
---

# idx-swing-watch

Runs as a Hermes `no_agent` cron every minute. It reads Phintraco Sekuritas Official through the existing cron Telethon session, accepts Trading Buy, Buy on Support, and Speculative Buy messages with Entry, Stop-loss, and Target fields, and posts each call to Discord `#id-stocks-swing`.

The runtime calls no LLM and performs no market analysis. Delivery is strict FIFO. A Source Chart attached to the same Telegram message follows the alert text immediately. A chartless source call is delivered text-only with an explicit chart-unavailable field.

## Runtime

```bash
~/.hermes/scripts/idx-swing-watch.sh
```

## Channels

- Telegram source: `1444713822`
- Discord alerts: `1525102458253217803`
- Discord heartbeat and failures: `1505162000420835388`

## Secrets

The wrapper loads `DISCORD_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING` from `~/.hermes/.env`.

## Dry run

- `IDX_SWING_WATCH_NO_POST=1`
- `IDX_SWING_WATCH_STATE_PATH=/tmp/idx-swing-watch-state.json`
- `IDX_SWING_WATCH_FORCE_HEARTBEAT=1`
```

- [ ] **Step 6: Run watchdog, wrapper, and import verification**

Run:

```bash
chmod +x bin/idx-swing-watch.sh bin/watchdog.py bin/scan.py
$PYT -m pytest tests/test_watchdog.py -q
bash -n bin/idx-swing-watch.sh
$PYT -m py_compile bin/scan.py bin/watchdog.py
```

Expected: watchdog tests pass; shell syntax and Python compilation exit with code 0.

- [ ] **Step 7: Full-suite checkpoint**

Run:

```bash
$PYT -m pytest -q
```

Expected: all collected tests pass.

---

### Task 7: Local contract verification against the approved specification

**Files:**
- Verify: `idx-swing-watch/SPEC.md`
- Verify: `idx-swing-watch/CONTEXT.md`
- Verify: all new implementation and test files

**Interfaces:**
- Consumes: completed Tasks 1 through 6.
- Produces: a locally verified deployment candidate with no untested state transition.

- [ ] **Step 1: Run the complete local suite from a clean process**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-swing-watch
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest -q
```

Expected: all tests pass with no warnings caused by IDX Swing Watch.

- [ ] **Step 2: Run focused contract groups separately**

Run:

```bash
$PYT -m pytest tests/test_scan.py -q -k "parse or format or rejected"
$PYT -m pytest tests/test_scan.py -q -k "state or lock or retry"
$PYT -m pytest tests/test_scan.py -q -k "source or ingest or media"
$PYT -m pytest tests/test_scan.py -q -k "delivery or chart or order"
$PYT -m pytest tests/test_scan.py -q -k "heartbeat or fatal or run_"
$PYT -m pytest tests/test_watchdog.py -q
```

Expected: every focused group passes.

- [ ] **Step 3: Verify import-time dependency isolation**

Run with the system Python that does not have Telethon installed:

```bash
cd ~/Documents/Projects/Hermes/idx-swing-watch
python3 -c 'import sys; sys.path.insert(0, "bin"); import scan; print(scan.format_signal_datetime(scan.dt.datetime(2026, 7, 10, 7, 0, tzinfo=scan.WIB)))'
```

Expected:

```text
Fri, Jul 10 2026, 07:00 WIB
```

- [ ] **Step 4: Verify exact alert bytes from the real fixtures**

Run:

```bash
$PYT -c 'import sys; from pathlib import Path; sys.path.insert(0, "bin"); import scan; text=Path("tests/fixtures/trading_buy.txt").read_text(); print(scan.format_swing_alert(scan.parse_swing_call(33655, text, True)))'
```

Expected: the output exactly matches Section 7.1 of `SPEC.md`, contains no inline-code markers, and contains no `Read:` line.

- [ ] **Step 5: Verify no Telegram write surface exists**

Run this exact AST inspection:

```bash
$PYT - <<'PY'
import ast
from pathlib import Path

blocked = {
    "send_message", "send_file", "forward_messages", "edit_message",
    "delete_messages", "send_reaction", "mark_read", "join_channel",
    "leave_channel",
}
tree = ast.parse(Path("bin/scan.py").read_text())
found = sorted(
    node.func.attr
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr in blocked
)
assert found == [], found
print("telegram write surface: none")
PY
```

Expected: `telegram write surface: none`.

- [ ] **Step 6: Verify wrapper dry behavior without network posting**

Run:

```bash
IDX_SWING_WATCH_NO_POST=1 \
IDX_SWING_WATCH_STATE_PATH="$(mktemp -d)/state.json" \
IDX_SWING_WATCH_PY="$PYT" \
HOME="$HOME" \
bash bin/idx-swing-watch.sh
```

Expected: if local Telegram credentials are unavailable, the scanner prints a sanitized handled-fatal no-agent JSON and exits 0. It must not attempt a Discord post because `IDX_SWING_WATCH_NO_POST=1`.

---

### Task 8: Deploy to the VPS and perform a no-post integration run

**Files:**
- Deploy: `idx-swing-watch/bin/scan.py`
- Deploy: `idx-swing-watch/bin/watchdog.py`
- Deploy: `idx-swing-watch/bin/idx-swing-watch.sh`
- Deploy: `idx-swing-watch/SKILL.md`
- Preserve: VPS `~/.agents/skills/idx-swing-watch/state/`

**Interfaces:**
- Consumes: locally verified Task 7 candidate.
- Produces: installed but unscheduled VPS runtime plus evidence that real Telegram reads, parsing, and media capture work without Discord posting.

- [ ] **Step 1: Deploy the scanner and watchdog through the established helper**

Run from `~/Documents/Projects/Hermes`:

```bash
./deploy.sh idx-swing-watch
rsync -a idx-swing-watch/SKILL.md vps:.agents/skills/idx-swing-watch/SKILL.md
```

Expected: `bin/` and `SKILL.md` exist under `vps:~/.agents/skills/idx-swing-watch/`. The deploy helper does not touch `state/`.

- [ ] **Step 2: Install the wrapper and executable modes**

Run:

```bash
ssh vps 'cp ~/.agents/skills/idx-swing-watch/bin/idx-swing-watch.sh ~/.hermes/scripts/idx-swing-watch.sh && chmod +x ~/.hermes/scripts/idx-swing-watch.sh ~/.agents/skills/idx-swing-watch/bin/scan.py ~/.agents/skills/idx-swing-watch/bin/watchdog.py'
```

Expected: command exits 0.

- [ ] **Step 3: Verify VPS dependencies and Python compatibility**

Run:

```bash
ssh vps '~/.local/share/uv/tools/yahoo-finance-mcp/bin/python -c "import telethon,requests; print(\"deps ok\")"'
ssh vps '~/.local/share/uv/tools/yahoo-finance-mcp/bin/python -m py_compile ~/.agents/skills/idx-swing-watch/bin/scan.py ~/.agents/skills/idx-swing-watch/bin/watchdog.py'
ssh vps 'bash -n ~/.hermes/scripts/idx-swing-watch.sh'
```

Expected:

```text
deps ok
```

Compilation and shell syntax exit 0.

- [ ] **Step 4: Run an isolated, exact-message Telegram and delivery integration**

Run:

```bash
ssh vps 'rm -rf /tmp/idx-swing-watch-integration && mkdir -p /tmp/idx-swing-watch-integration'
ssh vps 'IDX_SWING_WATCH_NO_POST=1 IDX_SWING_WATCH_STATE_PATH=/tmp/idx-swing-watch-integration/state.json ~/.local/share/uv/tools/yahoo-finance-mcp/bin/python -' <<'PY'
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents/skills/idx-swing-watch/bin"))
import scan


async def main():
    state = scan.empty_state()
    client = scan.make_client()
    await client.connect()
    try:
        entity = await scan.resolve_source(client)
        message = await client.get_messages(entity, ids=33655)
        call = scan.parse_swing_call(message.id, message.message or "", bool(message.photo))
        assert call is not None
        assert call.ticker == "SCMA"
        scan.enqueue_call(state, call, scan.dt.datetime.now(scan.WIB))
        scan.save_state(state)
        assert await scan.capture_oldest_media(client, entity, state, scan.dt.datetime.now(scan.WIB))
        delivered = scan.drain_outbox(state, scan.dt.datetime.now(scan.WIB), dry_run=True)
        assert delivered == 1
        assert state["outbox"] == {}
        print({"ticker": call.ticker, "delivered": delivered, "pending": 0})
    finally:
        await client.disconnect()


asyncio.run(main())
PY
```

Expected evidence, in order:

1. Dry-run Discord text beginning `[Phintraco] BUY: **SCMA**`.
2. Dry-run Discord chart for event `33655`.
3. `{'ticker': 'SCMA', 'delivered': 1, 'pending': 0}`.
4. No Discord message is created.

- [ ] **Step 5: Remove isolated integration artifacts**

Run:

```bash
ssh vps 'rm -rf /tmp/idx-swing-watch-integration'
```

Expected: command exits 0. Live runtime state remains untouched.

---

### Task 9: Register paused Hermes cron, bootstrap live state, enable, and verify first natural call

**Files:**
- Create at runtime: VPS `~/.agents/skills/idx-swing-watch/state/state.json`
- Create at runtime: Hermes job entry in `~/.hermes/cron/jobs.json`
- Preserve: all existing Hermes jobs

**Interfaces:**
- Consumes: deployed Task 8 runtime.
- Produces: enabled one-minute no-agent job, hourly heartbeat, and first natural text-then-chart evidence in `#id-stocks-swing`.

- [ ] **Step 1: Create the job on a far-future schedule, then pause it before assigning the one-minute schedule**

Run:

```bash
ssh vps '
HERMES="$HOME/.hermes/hermes-agent/venv/bin/hermes"
$HERMES cron create "0 0 1 1 *" "" --name idx-swing-watch --script idx-swing-watch.sh --no-agent --deliver discord:1505162000420835388
JOB_ID="$(python3 -c '"'"'import json,pathlib; jobs=json.loads((pathlib.Path.home()/".hermes/cron/jobs.json").read_text())["jobs"]; print(next(j["id"] for j in jobs if j["name"]=="idx-swing-watch"))'"'"')"
$HERMES cron pause "$JOB_ID"
$HERMES cron edit "$JOB_ID" --schedule "* * * * *" --script idx-swing-watch.sh --no-agent --deliver discord:1505162000420835388
printf "%s\n" "$JOB_ID"
'
```

Expected: the printed job ID identifies a paused `idx-swing-watch` job with schedule `* * * * *` and `no_agent: true`.

- [ ] **Step 2: Verify the paused job configuration exactly**

Run:

```bash
ssh vps 'python3 -c '"'"'import json,pathlib; jobs=json.loads((pathlib.Path.home()/".hermes/cron/jobs.json").read_text())["jobs"]; j=next(x for x in jobs if x["name"]=="idx-swing-watch"); print({k:j[k] for k in ("id","name","script","no_agent","enabled","state","deliver")}, j["schedule"])'"'"''
```

Expected fields:

```text
name=idx-swing-watch
script=idx-swing-watch.sh
no_agent=True
deliver=discord:1505162000420835388
schedule.expr=* * * * *
state=paused
```

- [ ] **Step 3: Bootstrap the live state manually with posting disabled**

Run:

```bash
ssh vps 'IDX_SWING_WATCH_NO_POST=1 IDX_SWING_WATCH_FORCE_HEARTBEAT=1 ~/.hermes/scripts/idx-swing-watch.sh'
```

Expected:

- The newest Telegram message ID becomes `observed_message_id`.
- Live outbox remains empty.
- Historical calls are not forwarded.
- Output ends with `{"wakeAgent": false}`.

- [ ] **Step 4: Verify bootstrap state and health probe**

Run:

```bash
ssh vps 'python3 -c '"'"'import json,pathlib; p=pathlib.Path.home()/".agents/skills/idx-swing-watch/state/state.json"; s=json.loads(p.read_text()); print({"cursor":s["observed_message_id"],"pending":len(s["outbox"]),"last_poll_success":s["last_poll_success"],"blocked":s["blocked"]})'"'"''
```

Expected: cursor is nonzero, pending is `0`, last poll success is populated, and blocked is `False`.

- [ ] **Step 5: Resume the one-minute job**

Run:

```bash
ssh vps '
HERMES="$HOME/.hermes/hermes-agent/venv/bin/hermes"
JOB_ID="$(python3 -c '"'"'import json,pathlib; jobs=json.loads((pathlib.Path.home()/".hermes/cron/jobs.json").read_text())["jobs"]; print(next(j["id"] for j in jobs if j["name"]=="idx-swing-watch"))'"'"')"
$HERMES cron resume "$JOB_ID"
$HERMES cron run "$JOB_ID"
'
```

Expected: the job is scheduled and its requested run completes without an agent wake.

- [ ] **Step 6: Verify one-minute liveness without waiting for a trade call**

Run after two scheduler ticks:

```bash
ssh vps 'python3 -c '"'"'import json,pathlib; jobs=json.loads((pathlib.Path.home()/".hermes/cron/jobs.json").read_text())["jobs"]; j=next(x for x in jobs if x["name"]=="idx-swing-watch"); print({"enabled":j["enabled"],"state":j["state"],"last_status":j["last_status"],"last_error":j["last_error"],"last_run_at":j["last_run_at"]})'"'"''
ssh vps 'python3 -c '"'"'from pathlib import Path; lines=(Path.home()/".logs/idx-swing-watch.log").read_text().splitlines(); print("\n".join(lines[-20:]))'"'"''
```

Expected: enabled is true, state is scheduled, last status is `ok`, last error is null, and the log contains repeated `wakeAgent: false` completions.

- [ ] **Step 7: Register the independent watchdog after the main job is healthy**

Run this idempotent crontab update from the Mac:

```bash
ssh vps 'python3 -' <<'PY'
import subprocess
import tempfile
from pathlib import Path

needle = "/idx-swing-watch/bin/watchdog.py"
entry = (
    "*/5 * * * * HOME=/home/praya "
    "/home/praya/.local/share/uv/tools/yahoo-finance-mcp/bin/python "
    "/home/praya/.agents/skills/idx-swing-watch/bin/watchdog.py "
    ">> /home/praya/.logs/idx-swing-watch-watchdog.log 2>&1"
)
current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
lines = [line for line in current.stdout.splitlines() if needle not in line]
lines.append(entry)
with tempfile.NamedTemporaryFile("w", delete=False) as handle:
    handle.write("\n".join(lines) + "\n")
    temp = handle.name
subprocess.run(["crontab", temp], check=True)
Path(temp).unlink()
PY
ssh vps 'HOME=/home/praya /home/praya/.local/share/uv/tools/yahoo-finance-mcp/bin/python /home/praya/.agents/skills/idx-swing-watch/bin/watchdog.py'
```

Expected: the crontab contains exactly one IDX Swing Watch watchdog entry. The manual watchdog exits 0 because the poll is fresh and posts nothing.

- [ ] **Step 8: Verify the first natural qualifying Phintraco call end to end**

On the next new Trading Buy, Buy on Support, or Speculative Buy message after activation, verify all of these observable facts:

1. Detection occurs on the next successful one-minute polling cycle.
2. Discord text begins `[Phintraco] BUY: **TICKER**`.
3. Labels are bold and values are plain text.
4. Source-stated date appears below targets.
5. Full rationale is preserved.
6. Source and advisor are present when the source contains them.
7. The Source Chart appears as the immediately following Discord message.
8. The live outbox returns to empty.
9. `last_delivery_success` advances.
10. No duplicate text is posted on later cron ticks.

If the natural call has no source photo, verify the text-only Chart field and do not require an image message.

- [ ] **Step 9: Final runtime health check**

Run:

```bash
ssh vps 'python3 -c '"'"'import json,pathlib; p=pathlib.Path.home()/".agents/skills/idx-swing-watch/state/state.json"; s=json.loads(p.read_text()); print({"cursor":s["observed_message_id"],"pending":len(s["outbox"]),"last_poll_success":s["last_poll_success"],"last_delivery_success":s["last_delivery_success"],"last_heartbeat_hour":s["last_heartbeat_hour"],"stats":s["stats"]})'"'"''
```

Expected: pending is `0`, last poll success is current, the heartbeat hour is populated after the next hourly boundary, and delivered count includes the verified natural call.

- [ ] **Step 10: Back up the deployed VPS state of the skill through the established workflow**

Run from the Mac:

```bash
bash ~/.dotfiles/sync.sh "idx-swing-watch: deploy deterministic Telegram watcher"
```

Expected: the VPS skill and operational files are mirrored into the normal backup surfaces without copying live secrets into documentation.

---

## Plan self-review results

### Spec coverage

- Sections 1 to 3: Tasks 1, 6, 8, and 9 cover scope, identifiers, and runtime metadata.
- Sections 4 to 6: Tasks 1, 2, 3, and 5 cover cadence, bootstrap, lock, time zone, read-only Telegram, paging, edits, and parsing.
- Section 7: Task 1 exact-output tests cover every alert-format decision.
- Sections 8 and 9: Tasks 2 and 4 cover durable phases, atomic writes, strict FIFO, retries, identity, blocked corruption, and media storage.
- Sections 10 to 12: Tasks 4, 5, and 6 cover Discord REST, heartbeat, fatal notices, no-agent output, and wrapper behavior.
- Sections 13 and 14: Tasks 6 and 8 cover file layout, deploy paths, dry-run controls, and health checks.
- Sections 15 and 16: Tasks 1 through 9 map parser, rejection, media, bootstrap, delivery, state, lock, heartbeat, VPS dry-run, and live acceptance requirements.
- Section 17: The implementation plan does not add any deferred feature.

### Placeholder scan

The plan contains no undefined implementation markers, no unspecified error-handling steps, and no references to unnamed helper functions. The only time-dependent verification is the first natural qualifying source call, because the approved bootstrap policy forbids replaying history into the live destination.

### Type consistency

- `SwingCall`, `PriceTarget`, serialization, and formatting names are introduced in Task 1 and reused unchanged.
- Outbox phase constants are introduced in Task 2 and reused unchanged in Tasks 3 through 5.
- `post_discord_text` and `post_discord_file` signatures are introduced in Task 4 and used consistently in Tasks 4 through 6.
- `RunStats` and heartbeat signatures are introduced in Task 5 and used consistently by orchestration tests.
- `state_path`, `WIB`, and heartbeat channel names consumed by `watchdog.py` match the Task 2 and Task 1 definitions.
