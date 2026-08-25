# Phintraco SSF Watch and Daily Watcher Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the existing Phintraco daily cash-equity watcher cleanly and add a deterministic Phintraco Weekly SSF Review watcher that delivers five source-faithful text-and-chart pairs to Discord.

**Architecture:** The daily watcher remains a self-contained Telegram text and source-image watcher, but its directory, runtime script, cron name, state path, logs, tests, dry-run variables, nonce namespace, and heartbeat identity become explicitly Phintraco daily. The new SSF watcher is a separate no-agent cron with its own cursor, report-capture queue, Poppler-backed deterministic PDF validator, extracted native-chart cache, strict FIFO delivery outbox, heartbeat, and watchdog. The two watchers share only external credentials and Discord destinations, not state, locks, parsers, or retry queues.

**Tech Stack:** Python 3.13 shared watcher runtime, Telethon, Requests, Poppler (`pdfinfo`, `pdftotext`, `pdfimages`), Discord API v10, pytest, Bash runtime wrappers, Hermes no-agent cron.

## Global Constraints

- **No LLM:** Both runtimes are deterministic `no_agent` jobs. They never invoke an LLM, agent, OCR/vision model, market-data service, news service, indicator calculator, chart generator, or Telegram write API.
- **Telegram source:** Phintraco Sekuritas Official, channel ID `1444713822`, read through `POLYCOP_SESSION_STRING`.
- **Discord alerts:** `#id-stocks-swing`, channel ID `1525102458253217803`.
- **Discord operations:** `#hermes`, channel ID `1505162000420835388`.
- **Daily clean cutover:** Rename every runtime and source reference from `idx-swing-watch` to `idx-swing-watch-phintraco-daily`. Do not leave aliases, old wrappers, fallback paths, old environment variables, or deprecated cron entries.
- **Daily cadence:** `* * * * *`.
- **Weekly SSF cadence:** `*/30 * * * *`, every day, in `Asia/Jakarta`.
- **Daily alert heading:** `## [Phintraco] BUY: **TICKER**`.
- **SSF alert heading:** `## [Phintraco-SSF] LONG|SHORT|MIXED: **TICKER**`.
- **SSF report acceptance:** exactly four PDF pages, five underlying blocks, three source contract horizons per underlying, five native technical charts in a `2 / 2 / 1` page layout, and every required source field. A malformed report forwards nothing.
- **SSF first run:** forward the newest valid SSF Review once, then observe only later source messages. Never replay older reports.
- **SSF chart delivery:** extract native analyst charts with Poppler and preserve text-then-chart FIFO adjacency. Do not generate, OCR, substitute, infer, or duplicate charts.
- **State safety:** atomic replace plus directory fsync. Never reset corrupt state, replay delivered alerts, or overwrite runtime state during deployment.
- **Heartbeats:** every successful SSF run posts `🫀 idx-ssf · HH:MM WIB · source=ok|missing|invalid · reports=N · alerts=N[ ⚠️]` to `#hermes`. Fatal failures use `❌ idx-ssf · HH:MM WIB · failed: …`.
- **Workspace:** `~/Documents/Projects/Hermes` is not a Git worktree. Do not add artificial commit steps. Deploy through `./deploy.sh <cron>` and preserve VPS runtime state.

---

## File map

### Daily watcher rename

- Move: `idx-swing-watch/` → `idx-swing-watch-phintraco-daily/`
- Modify: `idx-swing-watch-phintraco-daily/bin/scan.py`
- Move and rename: `idx-swing-watch-phintraco-daily/bin/idx-swing-watch.sh` → `idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh`
- Modify: `idx-swing-watch-phintraco-daily/bin/watchdog.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/conftest.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/test_scan.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/test_watchdog.py`
- Modify: `idx-swing-watch-phintraco-daily/SPEC.md`
- Modify and rename: `idx-swing-watch-phintraco-daily/SKILL.md`
- Modify: `README.md`

### New Weekly SSF watcher

- Existing approved glossary: `idx-ssf-watch-phintraco-weekly/CONTEXT.md`
- Existing approved behavior contract: `idx-ssf-watch-phintraco-weekly/SPEC.md`
- Create: `idx-ssf-watch-phintraco-weekly/SKILL.md`
- Create: `idx-ssf-watch-phintraco-weekly/bin/scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/bin/idx-ssf-watch-phintraco-weekly.sh`
- Create: `idx-ssf-watch-phintraco-weekly/bin/watchdog.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/conftest.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/test_scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/test_watchdog.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33681.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33568.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33327.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/malformed-five-pages.pdf`
- Modify: `README.md`

### Operational runtime changes

- Create on VPS: `~/.agents/skills/idx-ssf-watch-phintraco-weekly/` and its private `state/` directory.
- Move on VPS: `~/.agents/skills/idx-swing-watch/state/` → `~/.agents/skills/idx-swing-watch-phintraco-daily/state/`.
- Rename on VPS: `~/.hermes/scripts/idx-swing-watch.sh` → `~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh`.
- Replace in Hermes cron: `idx-swing-watch` → `idx-swing-watch-phintraco-daily`.
- Create in Hermes cron: `idx-ssf-watch-phintraco-weekly`.
- Replace in VPS crontab: daily watchdog command path and log name. Add the SSF watchdog command.

## Shared interfaces

Daily rename preserves these public module interfaces, changing only configuration identifiers and alert heading text:

```python
parse_swing_call(message_id: int, text: str, has_photo: bool) -> SwingCall | None
format_swing_alert(call: SwingCall) -> str
run(now: datetime | None = None, dry_run: bool = False) -> dict
```

The new SSF scanner exports:

```python
@dataclass(frozen=True)
class ContractRecommendation:
    horizon_months: int
    strategy: str
    purchase_price: str
    target_price: str
    support_resistance: str

@dataclass(frozen=True)
class UnderlyingSsfReview:
    ticker: str
    issuer_name: str
    share_price: str
    contracts: tuple[ContractRecommendation, ContractRecommendation, ContractRecommendation]
    chart_path: str | None

@dataclass(frozen=True)
class WeeklySsfReview:
    source_message_id: int
    report_date: date
    provider: str
    underlyings: tuple[UnderlyingSsfReview, UnderlyingSsfReview, UnderlyingSsfReview, UnderlyingSsfReview, UnderlyingSsfReview]

@dataclass(frozen=True)
class SsfCandidate:
    message_id: int
    pdf_path: Path

@dataclass(frozen=True)
class RunStats:
    source_status: str
    reports: int
    alerts: int
    degraded: bool

parse_weekly_ssf_pdf(source_message_id: int, pdf_path: Path) -> WeeklySsfReview
format_ssf_alert(underlying: UnderlyingSsfReview, report_date: date) -> str
ssf_alert_direction(contracts: tuple[ContractRecommendation, ContractRecommendation, ContractRecommendation]) -> str
run(now: datetime | None = None, dry_run: bool = False) -> dict
```

---

### Task 1: Cleanly rename the daily Phintraco watcher and upgrade its heading

**Files:**
- Move: `idx-swing-watch/` → `idx-swing-watch-phintraco-daily/`
- Modify: `idx-swing-watch-phintraco-daily/bin/scan.py`
- Move and rename: `idx-swing-watch-phintraco-daily/bin/idx-swing-watch.sh` → `idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh`
- Modify: `idx-swing-watch-phintraco-daily/bin/watchdog.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/conftest.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/test_scan.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/test_watchdog.py`
- Modify: `idx-swing-watch-phintraco-daily/SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: existing `SwingCall`, outbox, state, Telethon, Discord, and watchdog interfaces unchanged.
- Produces: the same daily alerts and state semantics under provider-specific runtime names, with a level-two Discord heading.

- [ ] **Step 1: Write failing heading and identifier tests**

In `tests/test_scan.py`, change each exact daily heading expectation from:

```python
"[Phintraco] BUY: **SCMA**\n\n"
```

to:

```python
"## [Phintraco] BUY: **SCMA**\n\n"
```

Add a configuration-identity test:

```python
def test_daily_runtime_identifiers_are_provider_specific():
    assert scan.WATCHER_NAME == "idx-swing-watch-phintraco-daily"
    assert scan.WATCHER_HEARTBEAT_NAME == "idx-swing-phintraco-daily"
    assert "idx-swing-watch-phintraco-daily" in str(scan.DEFAULT_STATE_FILE)
```

In `tests/conftest.py`, replace every old `IDX_SWING_WATCH_*` variable with the exact `IDX_SWING_WATCH_PHINTRACO_DAILY_*` name that the scanner will consume.

- [ ] **Step 2: Run focused tests to prove the old output fails**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-swing-watch
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py::test_format_chart_backed_alert_exact tests/test_scan.py::test_daily_runtime_identifiers_are_provider_specific -q
```

Expected: FAIL because the current formatter lacks `## ` and the old module does not expose provider-specific identity constants.

- [ ] **Step 3: Move the local source directory and rename the wrapper**

Run:

```bash
cd ~/Documents/Projects/Hermes
mv idx-swing-watch idx-swing-watch-phintraco-daily
mv idx-swing-watch-phintraco-daily/bin/idx-swing-watch.sh idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh
```

Update all local test imports and test commands to the moved directory. Do not leave a symlink or a duplicate `idx-swing-watch/` directory.

- [ ] **Step 4: Implement provider-specific configuration identifiers and heading**

At the top of `bin/scan.py`, define:

```python
WATCHER_NAME = "idx-swing-watch-phintraco-daily"
WATCHER_HEARTBEAT_NAME = "idx-swing-phintraco-daily"
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"
```

Read only these environment variables:

```python
IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH
IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST
IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT
IDX_SWING_WATCH_PHINTRACO_DAILY_PY
```

Implement `state_path()` as:

```python
def state_path() -> Path:
    return Path(
        os.environ.get(
            "IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH",
            str(DEFAULT_STATE_FILE),
        )
    )
```

Use `WATCHER_NAME` in Discord nonce input and `WATCHER_HEARTBEAT_NAME` in heartbeat and fatal strings. Change the first formatter line to:

```python
f"## [{call.provider}] BUY: **{call.ticker}**"
```

- [ ] **Step 5: Rename wrapper, logs, skill metadata, and README entry**

The new wrapper must use:

```bash
PYTHON_BIN="${IDX_SWING_WATCH_PHINTRACO_DAILY_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="$HOME/.agents/skills/idx-swing-watch-phintraco-daily/bin/scan.py"
LOG="$HOME/.logs/idx-swing-watch-phintraco-daily.log"
```

Update its start line to `START idx-swing-watch-phintraco-daily`. Update `SKILL.md` front matter and runtime path to `idx-swing-watch-phintraco-daily`. Replace the `README.md` watcher table row with:

```markdown
| `idx-swing-watch-phintraco-daily` | Phintraco individual IDX swing-call forwarder (Telegram text then source chart) | tests yes; a live run needs the VPS Telethon session |
```

- [ ] **Step 6: Run renamed daily unit tests and static checks**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-swing-watch-phintraco-daily
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest -q
bash -n bin/idx-swing-watch-phintraco-daily.sh
$PYT -m py_compile bin/scan.py bin/watchdog.py
```

Expected: all moved daily tests pass; Bash syntax and Python compilation succeed.

---

### Task 2: Add real SSF fixtures and deterministic PDF parsing

**Files:**
- Create: `idx-ssf-watch-phintraco-weekly/bin/scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/conftest.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/test_scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33681.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33568.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/33327.pdf`
- Create: `idx-ssf-watch-phintraco-weekly/tests/fixtures/ssf/malformed-five-pages.pdf`

**Interfaces:**
- Consumes: Poppler binaries, immutable Telegram source PDFs, `Asia/Jakarta` date rendering.
- Produces: `ContractRecommendation`, `UnderlyingSsfReview`, `WeeklySsfReview`, `parse_weekly_ssf_pdf`, `ssf_alert_direction`, and `format_ssf_alert`.

- [ ] **Step 1: Capture verified source fixtures once**

Download immutable source documents from Telegram messages `33681`, `33568`, and `33327` with the existing VPS Telethon authorization. Store them under `tests/fixtures/ssf/` with the message-ID filenames above.

Create `malformed-five-pages.pdf` by appending a blank fifth page to `33681.pdf` using a deterministic test-only fixture generator. Keep the source fixtures byte-for-byte unchanged. The malformed fixture must have the same selectable content and charts as `33681.pdf` plus one blank fifth page.

- [ ] **Step 2: Write failing parser and native-chart tests**

Create tests that use the real fixture PDFs:

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))


@pytest.fixture
def tmp_state(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    monkeypatch.setenv("IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH", str(path))
    return path
```

Start `tests/test_scan.py` with:

```python
import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

import scan

FIXTURES = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 7, 13, 6, 0, tzinfo=scan.WIB)


@pytest.fixture
def report_fixture():
    return scan.parse_weekly_ssf_pdf(33681, FIXTURES / "ssf" / "33681.pdf")
```

```python
@pytest.mark.parametrize("message_id", [33681, 33568, 33327])
def test_verified_ssf_reports_parse_five_underlyings_and_five_charts(message_id):
    report = scan.parse_weekly_ssf_pdf(
        message_id,
        FIXTURES / "ssf" / f"{message_id}.pdf",
    )
    assert report.source_message_id == message_id
    assert report.provider == "Phintraco"
    assert len(report.underlyings) == 5
    assert [len(item.contracts) for item in report.underlyings] == [3] * 5
    assert all(item.chart_path is None for item in report.underlyings)


def test_current_report_preserves_source_strategies_and_prices():
    report = scan.parse_weekly_ssf_pdf(33681, FIXTURES / "ssf" / "33681.pdf")
    indf = report.underlyings[0]
    assert indf.ticker == "INDF"
    assert [contract.strategy for contract in indf.contracts] == ["Short", "Short", "Short"]
    assert [contract.purchase_price for contract in indf.contracts] == ["6825", "6825", "6825"]


def test_mixed_contract_strategies_produce_mixed_heading():
    report = scan.parse_weekly_ssf_pdf(33568, FIXTURES / "ssf" / "33568.pdf")
    indf = report.underlyings[0]
    assert [contract.strategy for contract in indf.contracts] == ["Short", "Long", "Long"]
    assert scan.ssf_alert_direction(indf.contracts) == "MIXED"
    assert scan.format_ssf_alert(indf, report.report_date).startswith(
        "## [Phintraco-SSF] MIXED: **INDF**\n"
    )


def test_five_page_source_is_rejected_without_partial_report():
    with pytest.raises(scan.InvalidSsfReport, match="exactly four pages"):
        scan.parse_weekly_ssf_pdf(9, FIXTURES / "ssf" / "malformed-five-pages.pdf")
```

Add tests that monkeypatch the Poppler command runner to return five chart entries not arranged `2 / 2 / 1`, then assert `InvalidSsfReport` with a `chart distribution` message.

- [ ] **Step 3: Run tests to prove the parser does not exist**

Run:

```bash
cd ~/Documents/Projects/Hermes/idx-ssf-watch-phintraco-weekly
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py -q
```

Expected: FAIL during `import scan` because `bin/scan.py` is absent.

- [ ] **Step 4: Implement safe Poppler command execution and PDF metadata parsing**

Implement an allowlisted command helper that never invokes a shell:

```python
def run_poppler(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout
```

Implement `parse_weekly_ssf_pdf` to call only:

```python
info = run_poppler("pdfinfo", str(pdf_path))
layout_text = run_poppler("pdftotext", "-layout", str(pdf_path), "-")
image_table = run_poppler("pdfimages", "-list", str(pdf_path))
```

Parse `Pages:` exactly as an integer and raise:

```python
raise InvalidSsfReport("expected exactly four pages")
```

for every non-four-page document. Reject empty layout text before attempting block parsing.

- [ ] **Step 5: Implement source block and contract-column parsing**

Split the layout text into five blocks using this verified heading shape:

```python
UNDERLYING_HEADER_RE = re.compile(
    r"(?m)^\s*([A-Z]{4})\s+(.+?)\s+Shares Statistics as of\s+(.+?)\s*$"
)
```

For each block, require the ordered labels `1 Month Contract`, `2 Month Contract`, and `3 Month Contract`, then parse the three aligned values for each required label:

```text
Strategy
Contract Purchase Price (IDR)
Potential Target Price (IDR)
Support / Resistance
```

Normalize whitespace, preserve numeric values as source strings, and require exactly three `Long` or `Short` values. Reject an extra, missing, or unsupported strategy rather than choosing a value by proximity.

- [ ] **Step 6: Implement deterministic chart inventory parsing**

Parse `pdfimages -list` rows into:

```python
@dataclass(frozen=True)
class PdfImage:
    page: int
    width: int
    height: int
    ordinal: int
```

Keep only images where `width >= 1000` and `height >= 500`. Require exactly five and verify page distribution:

```python
assert [image.page for image in charts] == [1, 1, 2, 2, 3]
```

Convert an assertion failure to `InvalidSsfReport("unexpected technical-chart distribution")`.

- [ ] **Step 7: Implement exact concise text formatting**

Implement:

```python
def ssf_alert_direction(contracts):
    strategies = {contract.strategy for contract in contracts}
    if strategies == {"Long"}:
        return "LONG"
    if strategies == {"Short"}:
        return "SHORT"
    return "MIXED"
```

Render each contract with this exact source-faithful shape:

```python
lines.extend([
    f"**{contract.horizon_months}-month contract**",
    f"**Strategy:** {contract.strategy}",
    f"**Purchase price:** {contract.purchase_price}",
    f"**Target price:** {contract.target_price}",
    f"**Support / resistance:** {contract.support_resistance}",
])
```

The formatter must produce one Discord message under 2,000 characters, beginning with:

```python
f"## [Phintraco-SSF] {direction}: **{underlying.ticker}**"
```

- [ ] **Step 8: Run parser and formatter tests**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py -q
$PYT -m py_compile bin/scan.py
```

Expected: all real-fixture parsing, malformed-PDF, mixed-heading, and formatter tests pass.

---

### Task 3: Implement SSF report capture, durable state, extracted-chart cache, and FIFO delivery

**Files:**
- Modify: `idx-ssf-watch-phintraco-weekly/bin/scan.py`
- Modify: `idx-ssf-watch-phintraco-weekly/tests/test_scan.py`

**Interfaces:**
- Consumes: `WeeklySsfReview`, chart inventory order, and `format_ssf_alert` from Task 2.
- Produces: atomic state functions, report job phases, five ordered outbox events, `extract_charts`, `post_discord_text`, `post_discord_file`, and `drain_outbox`.

- [ ] **Step 1: Write failing state and delivery tests**

Add isolated state-path tests:

```python
def prepare_events(tmp_state, tmp_path, report_fixture):
    charts = []
    for ordinal, underlying in enumerate(report_fixture.underlyings, start=1):
        path = tmp_path / f"{ordinal}-{underlying.ticker}.png"
        path.write_bytes(b"chart")
        charts.append(replace(underlying, chart_path=str(path)))
    prepared_review = replace(report_fixture, underlyings=tuple(charts))
    state = scan.empty_state()
    scan.enqueue_review(state, prepared_review, NOW)
    scan.save_state(state)
    return list(state["outbox"])


def test_valid_report_creates_five_ordered_outbox_events(tmp_state, tmp_path, report_fixture):
    keys = prepare_events(tmp_state, tmp_path, report_fixture)
    assert keys == [
        "33681:INDF", "33681:BBCA", "33681:BMRI", "33681:ASII", "33681:MDKA",
    ]
    state = scan.load_state()
    assert [event["phase"] for event in state["outbox"].values()] == ["pending_text"] * 5


def test_text_success_then_chart_failure_retries_only_chart(tmp_state, tmp_path, report_fixture, monkeypatch):
    first_key = prepare_events(tmp_state, tmp_path, report_fixture)[0]
    monkeypatch.setattr(scan, "post_discord_text", lambda *args: "text-1")
    monkeypatch.setattr(
        scan,
        "post_discord_file",
        lambda *args: (_ for _ in ()).throw(RuntimeError("upload failed")),
    )
    state = scan.load_state()
    scan.drain_outbox(state, NOW)
    event = state["outbox"][first_key]
    assert event["text_discord_id"] == "text-1"
    assert event["phase"] == "pending_chart"


def test_later_underlying_waits_for_prior_chart(tmp_state, tmp_path, report_fixture, monkeypatch):
    first_key, second_key, *_ = prepare_events(tmp_state, tmp_path, report_fixture)
    text_calls = []
    chart_calls = []

    def post_text(_content, _channel_id, _dry_run, event_key):
        text_calls.append(event_key)
        return f"text-{len(text_calls)}"

    def fail_first_chart(_path, _channel_id, _dry_run, event_key):
        chart_calls.append(event_key)
        raise RuntimeError("upload failed")

    monkeypatch.setattr(scan, "post_discord_text", post_text)
    monkeypatch.setattr(scan, "post_discord_file", fail_first_chart)
    state = scan.load_state()
    scan.drain_outbox(state, NOW)

    assert text_calls == [first_key]
    assert chart_calls == [first_key]
    assert state["outbox"][first_key]["phase"] == "pending_chart"
    assert state["outbox"][second_key]["phase"] == "pending_text"

- [ ] **Step 2: Run tests to prove durable outbox functions are absent**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py::test_valid_report_creates_five_ordered_outbox_events tests/test_scan.py::test_text_success_then_chart_failure_retries_only_chart -q
```

Expected: FAIL because `empty_state`, `enqueue_review`, and `drain_outbox` are not implemented.

- [ ] **Step 3: Implement versioned atomic state**

Use this minimum state shape:

```python
{
    "version": 1,
    "bootstrap_complete": False,
    "observed_message_id": 0,
    "report_jobs": {},
    "invalid_reports": {},
    "outbox": {},
    "last_poll_success": None,
    "last_delivery_success": None,
    "last_heartbeat_run": None,
    "last_error_notice": None,
    "stats": {"runs": 0, "reports": 0, "alerts": 0, "delivered": 0},
}
```

Persist through a sibling temporary file opened with mode `0o600`, `fsync` the file, `os.replace`, and `fsync` the parent directory. Reject corrupt or unsupported existing state by raising `StateBlockedError`; never replace it with an empty state.

- [ ] **Step 4: Implement PDF and native-chart capture before enqueueing**

For a candidate report job:

1. Download the Telegram document to `state/reports/<message_id>.pdf.tmp`.
2. `fsync`, atomically rename it to `<message_id>.pdf`, and parse it with `parse_weekly_ssf_pdf`.
3. Run `pdfimages -png <pdf> <media-prefix>`.
4. Use Task 2’s validated image ordinals to select exactly five extracted files.
5. Atomically move the five selected files to `state/media/<message_id>-<ordinal>-<ticker>.png`.
6. Attach each durable chart path to its matching underlying.
7. Atomically create all five `pending_text` outbox events in source order.

If download or extraction fails, keep the report job pending with retry metadata. If parsing or validation fails, record terminal invalidity and do not create any outbox event.

- [ ] **Step 5: Implement Discord delivery with deterministic nonces**

Use Discord API v10 and a nonce namespace that includes the new watcher name:

```python
def discord_nonce(event_key: str, leg: str) -> str:
    identity = f"idx-ssf-watch-phintraco-weekly:{event_key}:{leg}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]
```

For an event in `pending_text`, post exactly one `format_ssf_alert` text message. On HTTP success, persist the Discord message ID and transition to `pending_chart`. For `pending_chart`, upload only its cached chart, persist `delivered`, then remove that chart file. Delete the source PDF only after every outbox event for its source message is delivered.

- [ ] **Step 6: Run durable delivery tests**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py -q
```

Expected: state atomicity, terminal invalid-report behavior, chart capture, text-before-chart ordering, chart-only retry, and strict FIFO tests pass.

---

### Task 4: Implement Telethon discovery, bootstrap, heartbeat, fatal reporting, and watchdog

**Files:**
- Modify: `idx-ssf-watch-phintraco-weekly/bin/scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/bin/watchdog.py`
- Modify: `idx-ssf-watch-phintraco-weekly/tests/test_scan.py`
- Create: `idx-ssf-watch-phintraco-weekly/tests/test_watchdog.py`

**Interfaces:**
- Consumes: state/outbox APIs from Task 3.
- Produces: `SsfCandidate`, `select_newest_valid_candidate`, `record_invalid_report`, candidate discovery, latest-valid bootstrap, `format_heartbeat`, `format_fatal`, `run`, and `watchdog.is_stale`.

- [ ] **Step 1: Write failing observation, bootstrap, heartbeat, and watchdog tests**

Add pure bootstrap and invalid-source tests:

```python
def test_bootstrap_selects_newest_valid_report_only():
    candidates = [
        scan.SsfCandidate(33327, FIXTURES / "ssf" / "33327.pdf"),
        scan.SsfCandidate(33681, FIXTURES / "ssf" / "33681.pdf"),
    ]
    selected = scan.select_newest_valid_candidate(
        candidates,
        lambda candidate: scan.parse_weekly_ssf_pdf(
            candidate.message_id, candidate.pdf_path
        ),
    )
    assert selected.message_id == 33681


def test_invalid_candidate_forwards_nothing_and_marks_degraded(tmp_state):
    state = scan.empty_state()
    scan.record_invalid_report(state, 999, "expected exactly four pages")
    stats = scan.RunStats(source_status="invalid", reports=0, alerts=0, degraded=True)

    assert state["outbox"] == {}
    assert state["invalid_reports"]["999"]["reason"] == "expected exactly four pages"
    assert scan.format_heartbeat(NOW, stats).startswith(
        "🫀 idx-ssf · 06:00 WIB · source=invalid"
    )


def test_heartbeat_posts_every_run_not_once_per_hour(tmp_state):
    state = scan.empty_state()
    stats = scan.RunStats(source_status="ok", reports=0, alerts=0, degraded=False)
    first = scan.post_heartbeat(state, NOW, stats, dry_run=True)
    second = scan.post_heartbeat(
        state,
        NOW + dt.timedelta(minutes=30),
        stats,
        dry_run=True,
    )
    assert first is True
    assert second is True
```

For the watchdog, assert stale after 65 minutes and exact fatal text starting `❌ idx-ssf`.

- [ ] **Step 2: Run the failing orchestration tests**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py tests/test_watchdog.py -q
```

Expected: FAIL because Telethon orchestration, heartbeat, and watchdog functions are not implemented.

- [ ] **Step 3: Implement candidate discovery and newest-valid bootstrap**

Resolve the configured Phintraco entity, fetch unseen messages in ascending ID order, and accept only candidate PDFs matching Section 5.1 of `SPEC.md`.

When `bootstrap_complete` is false:

1. Inspect candidate PDFs from newest to oldest until one validates.
2. Prepare and enqueue only that newest valid report.
3. Set `observed_message_id` to the newest source message ID, not the accepted report ID.
4. Set `bootstrap_complete` only after the state containing the queued report is durable.

When bootstrap finds no valid report, persist the newest source ID and mark `source=missing`.

- [ ] **Step 4: Implement current-run heartbeat and bounded fatal reporting**

Implement exact heartbeat rendering:

```python
return (
    f"🫀 idx-ssf · {now.astimezone(WIB):%H:%M} WIB · "
    f"source={stats.source_status} · reports={stats.reports} · alerts={stats.alerts}"
    + (" ⚠️" if stats.degraded else "")
)
```

Call it once at the end of every successful non-locked run, even if it found no candidate. Persist `last_heartbeat_run` only after Discord success. Fatal reporting keeps a bounded error-fingerprint set and never exposes secrets, PDF paths, or bytes.

- [ ] **Step 5: Implement the five-minute read-only watchdog**

Base `watchdog.py` on the daily watcher’s design but set:

```python
MAX_GAP_MINUTES = 65
WATCHER_HEARTBEAT_NAME = "idx-ssf"
```

The watchdog may read state and write only `watchdog-notices.json`. It must not change observation cursor, report jobs, outbox events, or delivery data.

- [ ] **Step 6: Run all SSF tests**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest -q
$PYT -m py_compile bin/scan.py bin/watchdog.py
```

Expected: parser, PDF validation, bootstrap, state, delivery, heartbeat, and watchdog tests all pass.

---

### Task 5: Add SSF runtime wrapper, operational skill, and deployment documentation

**Files:**
- Create: `idx-ssf-watch-phintraco-weekly/bin/idx-ssf-watch-phintraco-weekly.sh`
- Create: `idx-ssf-watch-phintraco-weekly/SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `scan.py` and `watchdog.py` from Tasks 2 through 4.
- Produces: executable wrapper, no-agent runtime contract, dry-run controls, and documented deployment path.

- [ ] **Step 1: Write a failing wrapper contract check**

Create a test that reads the wrapper as text and verifies all required identifiers:

```python
def test_wrapper_uses_only_ssf_provider_specific_identifiers():
    wrapper = (ROOT / "bin" / "idx-ssf-watch-phintraco-weekly.sh").read_text()
    assert "IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST" in wrapper
    assert "idx-ssf-watch-phintraco-weekly" in wrapper
    assert "IDX_SWING_WATCH" not in wrapper
```

- [ ] **Step 2: Run it and prove the wrapper is absent**

Run:

```bash
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest tests/test_scan.py::test_wrapper_uses_only_ssf_provider_specific_identifiers -q
```

Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Create the runtime wrapper**

Create `bin/idx-ssf-watch-phintraco-weekly.sh` with:

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

PYTHON_BIN="${IDX_SSF_WATCH_PHINTRACO_WEEKLY_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"
SCRIPT="$HOME/.agents/skills/idx-ssf-watch-phintraco-weekly/bin/scan.py"
LOG="$HOME/.logs/idx-ssf-watch-phintraco-weekly.log"
mkdir -p "$HOME/.logs"
exec "$PYTHON_BIN" "$SCRIPT" "$@"
```

Keep the same sanitized-start/end logging convention as the daily wrapper. Do not log environment values.

- [ ] **Step 4: Create SKILL.md and update README**

The SKILL front matter is:

```yaml
---
name: idx-ssf-watch-phintraco-weekly
description: Deterministic Hermes cron that polls Phintraco Telegram every 30 minutes and forwards each valid Weekly SSF Review underlying as source-only text followed by its native analyst chart.
user-invocable: false
---
```

Document these dry-run variables:

```text
IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST=1
IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH=/tmp/idx-ssf-watch-state.json
IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT=1
```

Add the SSF watcher to the Hermes README table and change the daily row to the provider-specific name.

- [ ] **Step 5: Run wrapper and documentation checks**

Run:

```bash
bash -n bin/idx-ssf-watch-phintraco-weekly.sh
PYT="$HOME/Documents/Projects/Hermes/.venv/bin/python"
$PYT -m pytest -q
```

Expected: Bash syntax succeeds and the complete SSF suite passes.

---

### Task 6: Deploy with a state-preserving daily cutover and a controlled SSF live verification

**Files:**
- Deploy: `idx-swing-watch-phintraco-daily/bin/`
- Deploy: `idx-ssf-watch-phintraco-weekly/bin/`
- Deploy: both `SKILL.md` files
- Preserve and move: VPS daily runtime state
- Create: VPS SSF state through a dry run and Hermes cron bootstrap

**Interfaces:**
- Consumes: locally verified source directories from Tasks 1 through 5.
- Produces: renamed daily Hermes cron and runtime, independent SSF cron, two watchdog entries, and verified nonduplicating delivery state.

- [ ] **Step 1: Deploy both source trees without runtime state**

Run:

```bash
cd ~/Documents/Projects/Hermes
./deploy.sh idx-swing-watch-phintraco-daily
./deploy.sh idx-ssf-watch-phintraco-weekly
rsync -a idx-swing-watch-phintraco-daily/SKILL.md vps:.agents/skills/idx-swing-watch-phintraco-daily/SKILL.md
rsync -a idx-ssf-watch-phintraco-weekly/SKILL.md vps:.agents/skills/idx-ssf-watch-phintraco-weekly/SKILL.md
```

Expected: only `bin/` and `SKILL.md` are copied. Existing state is untouched.

- [ ] **Step 2: Pause the daily job and migrate its state before renaming runtime paths**

On the VPS, locate the existing daily Hermes job named `idx-swing-watch`, pause it, and confirm no daily wrapper process is running. Then run exactly one move:

```bash
mv ~/.agents/skills/idx-swing-watch/state ~/.agents/skills/idx-swing-watch-phintraco-daily/state
```

Move the wrapper:

```bash
mv ~/.hermes/scripts/idx-swing-watch.sh ~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh
chmod +x ~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh
```

Edit the paused Hermes job in place to:

```text
name=idx-swing-watch-phintraco-daily
script=idx-swing-watch-phintraco-daily.sh
schedule=* * * * *
no_agent=True
deliver=discord:1505162000420835388
```

Replace the daily watchdog crontab entry with the provider-specific state path, script path, and log filename. Delete the old source runtime directory only after the renamed dry run succeeds.

- [ ] **Step 3: Verify daily migration with no post**

Run:

```bash
ssh vps 'IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1 ~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh'
```

Expected: exit code `0`, `{"wakeAgent": false}` output, same nonzero migrated cursor, same outbox contents, and no Discord post. Resume the renamed daily job only after this check passes.

- [ ] **Step 4: Register the SSF Hermes cron and watchdog**

Create the SSF job paused first, then configure:

```text
name=idx-ssf-watch-phintraco-weekly
script=idx-ssf-watch-phintraco-weekly.sh
schedule=*/30 * * * *
no_agent=True
deliver=discord:1505162000420835388
```

Add exactly one VPS crontab watchdog entry:

```cron
*/5 * * * * HOME=/home/praya /home/praya/.local/share/uv/tools/yahoo-finance-mcp/bin/python /home/praya/.agents/skills/idx-ssf-watch-phintraco-weekly/bin/watchdog.py >> /home/praya/.logs/idx-ssf-watch-phintraco-weekly-watchdog.log 2>&1
```

- [ ] **Step 5: Run SSF dry-run against the real latest source PDF**

Run with an isolated state path:

```bash
ssh vps 'IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST=1 IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH=/tmp/idx-ssf-watch-dry-run/state.json ~/.hermes/scripts/idx-ssf-watch-phintraco-weekly.sh'
```

Expected: the newest valid source report is parsed into exactly five ordered text-and-chart events, no Discord request occurs, and the dry-run state has five pending events with chart cache paths.

- [ ] **Step 6: Enable SSF and verify one controlled live bootstrap**

Resume the SSF job and invoke it once. Verify in `#id-stocks-swing`:

1. exactly five SSF alert texts;
2. each begins with `## [Phintraco-SSF]`;
3. each text is followed immediately by its matching source chart;
4. no text or chart is duplicated;
5. headings are `LONG`, `SHORT`, or `MIXED` according to the three parsed source strategies.

Verify in `#hermes` one `idx-ssf` heartbeat with `reports=1 · alerts=5`.

- [ ] **Step 7: Verify steady state without duplicate delivery**

Wait for the next two 30-minute cycles, then verify:

```text
- `#id-stocks-swing` received no duplicate SSF events.
- `#hermes` received an `idx-ssf` heartbeat for each run.
- daily watcher continued to poll every minute under its new name.
- no old `idx-swing-watch` cron, wrapper, state directory, watchdog, or log path remains.
```

---

## Plan self-review results

### Spec coverage

- Deterministic-only behavior: Tasks 2 through 6 use Poppler, Telethon, Requests, and no model calls.
- Three-month PDF evidence: Task 2 tests current, July 6, and June 22 real documents; acceptance requires parser tolerance for observed producer and chart-encoding changes.
- Native chart extraction and deterministic `2 / 2 / 1` mapping: Tasks 2 and 3.
- Five FIFO text-and-chart pairs: Tasks 3 and 6.
- `LONG`, `SHORT`, and `MIXED` headings: Task 2 tests and formatter implementation.
- Every-30-minute daily SSF polling and every-run `idx-ssf` heartbeat: Tasks 4 and 6.
- First-run latest-only delivery and no historical replay: Task 4.
- Fail-closed validation and no partial forwarding: Tasks 2 through 4.
- Daily provider-specific clean rename, state migration, and `##` heading: Tasks 1 and 6.

### Placeholder scan

No implementation step delegates unspecified behavior. Every parser guard, state field, external ID, runtime name, output format, test command, and deployment verification is specified above. The two source-fixture download steps name immutable Telegram message IDs.

### Type consistency

`WeeklySsfReview` contains exactly five `UnderlyingSsfReview` values. Every `UnderlyingSsfReview` contains exactly three `ContractRecommendation` values. `ssf_alert_direction` consumes the same three-contract tuple that `format_ssf_alert` renders. Outbox event keys use the report `source_message_id` and the parsed `ticker`, and Discord nonces derive from that same event key.
