# PolyCop Telegram Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent concurrent Telegram connection retry storms across four PolyCop-session market watchers, while preserving every watcher cursor and outbox and emitting one durable outage and recovery notice per incident.

**Architecture:** A shared `telegram_resilience` module owns lock-protected health state and a 30-day JSONL log. Each scanner continues to own its Telethon client, parsing, cursor, outbox, and existing Discord sender; it asks the module for permission to connect, records the connection outcome, then claims and acknowledges any operations notification.

**Tech Stack:** Python 3, Telethon, JSON, `fcntl` advisory locks, atomic file replacement, JSONL, pytest, Bash, Hermes cron.

## Global Constraints

- Cover only `idx-market-news-watch`, `idx-swing-watch-phintraco-daily`, `idx-ssf-watch-phintraco-weekly`, and `polymarket-signal-watch`, which share `POLYCOP_SESSION_STRING`.
- Do not change gateway `telegram-mcp` or SCELE `tg-window`, which use `TELEGRAM_SESSION_STRING`.
- Do not add a daemon, Hermes cron, database, persistent connection, automatic session re-login, or an external messaging path.
- Do not persist credentials, session strings, tokens, raw headers, source text, or raw exceptions.
- An unavailable session must not advance a watcher cursor, mutate a watcher delivery outbox, or message a PolyCop analysis bot.
- Existing schedules, market policy, Discord destinations, and normal heartbeat cadence remain unchanged.
- Handled outcomes print `{"wakeAgent": false}` and exit zero. Market News must not wake its Hermes agent after a handled collection failure.
- State: `$HOME/.hermes/state/telegram-resilience-polyclop.json`. Log: `$HOME/.logs/telegram-resilience-polyclop.jsonl`, retaining 30 calendar days.
- Run watcher suites separately with the shared `.venv`. Deploy only after exact local and VPS checksum parity. Never manually trigger a Hermes schedule.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `telegram-resilience/bin/telegram_resilience.py` | Versioned state schema, lock, atomic I/O, redaction, probe lease, circuit transitions, notification claims. |
| `telegram-resilience/bin/telegram-resilience-probe.py` | Safe CLI: connect, authorization test, `get_me`, disconnect, JSON result. |
| `telegram-resilience/tests/test_telegram_resilience.py` | Deterministic state, lease, backoff, redaction, notification, and probe tests. |
| `telegram-resilience/README.md` | Runtime path, safe probe, deployment sequence, re-login procedure. |
| `deploy.sh` | Creates a component runtime `bin` directory before copying its source. |
| Four watcher wrappers | Export one shared runtime path through `PYTHONPATH`. |
| Four `scan.py` files | Use the guard around their existing `await client.connect()` boundary. |
| Four watcher `conftest.py` and tests | Add local shared module path and test adapter regressions. |

## Shared Interfaces

Create this exact public API in `telegram_resilience.py`. No scanner reads or writes the shared JSON directly.

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

OutcomeKind = Literal["probe", "cooldown", "leased", "auth_required", "state_blocked"]
NotificationKind = Literal["transport_outage", "auth_required", "recovery", "state_blocked"]

@dataclass(frozen=True)
class ProbeDecision:
    kind: OutcomeKind
    lease_id: str | None
    incident_id: str | None
    retry_at: datetime | None

@dataclass(frozen=True)
class PendingNotification:
    claim_id: str
    incident_id: str
    kind: NotificationKind
    event_key: str
    content: str

class PolyCopResilience:
    @classmethod
    def for_paths(cls, state_path: Path, log_path: Path) -> "PolyCopResilience": ...
    def acquire_probe(self, watcher: str, now: datetime) -> ProbeDecision: ...
    def record_transport_failure(self, lease_id: str, watcher: str, error: BaseException, now: datetime) -> None: ...
    def record_auth_required(self, lease_id: str, watcher: str, now: datetime) -> None: ...
    def record_authenticated_success(self, lease_id: str, watcher: str, now: datetime, dc_id: int | None, endpoint: str | None) -> None: ...
    def claim_notification(self, watcher: str, now: datetime) -> PendingNotification | None: ...
    def acknowledge_notification(self, claim_id: str, now: datetime) -> None: ...
```

A watcher skipped by cooldown, another live lease, or authorization-required state appends its name to the active incident. Only an authenticated success closes an incident. A notification is acknowledged only after Discord returns a successful message ID.

Every scanner-adapter test defines this local test double before its first test:

```python
class FakeResilience:
    @classmethod
    def cooldown(cls): ...
    @classmethod
    def auth_required(cls): ...
    @classmethod
    def probe(cls): ...
    @classmethod
    def with_notification(cls, event_key: str): ...

    acknowledged_claim_ids: list[str]
```

The double implements the six public methods above and records every method call. Its `claim_notification` method returns the supplied `PendingNotification` once, and its `acknowledge_notification` method appends the claim ID. Do not use the real shared-state file in adapter tests.

## Task 1: Build validated shared state and deterministic circuit behavior

**Files:**
- Create: `telegram-resilience/bin/telegram_resilience.py`
- Create: `telegram-resilience/tests/test_telegram_resilience.py`
- Create: `telegram-resilience/README.md`

**Interfaces:**
- Consumes: watcher name, timezone-aware clock, explicit state/log paths in tests.
- Produces: `PolyCopResilience`, `ProbeDecision`, and `PendingNotification`.

- [ ] **Step 1: Write failing state, concurrency, and authorization tests**

```python
def test_new_state_is_private_and_versioned(tmp_path: Path) -> None:
    resilience = PolyCopResilience.for_paths(tmp_path / "state.json", tmp_path / "events.jsonl")
    decision = resilience.acquire_probe("idx-swing-watch-phintraco-daily", WIB_NOW)

    state = json.loads((tmp_path / "state.json").read_text())
    assert decision.kind == "probe"
    assert state["version"] == 1
    assert state["circuit"]["status"] == "probing"
    assert oct((tmp_path / "state.json").stat().st_mode & 0o777) == "0o600"
    assert "SESSION" not in json.dumps(state).upper()

def test_only_one_of_four_watchers_gets_a_probe(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)
    later = [
        resilience.acquire_probe(name, WIB_NOW).kind
        for name in ("idx-swing-watch-phintraco-daily", "idx-ssf-watch-phintraco-weekly", "polymarket-signal-watch")
    ]
    assert owner.kind == "probe"
    assert later == ["leased", "leased", "leased"]

def test_unauthorized_session_never_auto_retries(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("polymarket-signal-watch", WIB_NOW)
    resilience.record_auth_required(owner.lease_id, "polymarket-signal-watch", WIB_NOW)
    assert resilience.acquire_probe("idx-ssf-watch-phintraco-weekly", WIB_NOW + timedelta(days=1)).kind == "auth_required"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest -q telegram-resilience/tests/test_telegram_resilience.py`

Expected: FAIL during collection because `telegram_resilience` does not exist.

- [ ] **Step 3: Implement state, lease, and circuit rules**

Use this exact initial state:

```python
{
    "version": 1,
    "circuit": {
        "status": "closed",
        "lease_id": None,
        "lease_expires_at": None,
        "consecutive_transport_failures": 0,
        "next_probe_at": None,
    },
    "incident": None,
    "notifications": [],
    "last_authenticated_success_at": None,
    "last_connection": {"dc_id": None, "endpoint": None},
}
```

Use `fcntl.flock` on a companion lock file; exact-key schema validation; same-directory temporary write; file and directory `fsync`; `os.replace`; and mode `0600`. On invalid state, preserve the original file and return `state_blocked`.

Set `PROBE_LEASE_SECONDS = 75`, `BACKOFF_BASE_SECONDS = 60`, `BACKOFF_CAP_SECONDS = 900`, and `JITTER_MAX_SECONDS = 15`. Classify only `TimeoutError`, `OSError`, `socket.gaierror`, `ssl.SSLError`, and Telethon connection transport exceptions as transport failures. Derive jitter from incident ID plus failure count, not random process state. Reclaim expired leases before a decision. A transport failure creates one incident and a next-probe deadline. An authenticated success clears the circuit and queues recovery only if an incident existed.

- [ ] **Step 4: Add boundary and secrecy coverage, then run the complete common suite**

Add tests for first retry delay in 60 to 75 seconds, doubled retries, 900-second cap, stale lease recovery after 75 seconds, invalid-state preservation, and redaction of session-shaped and token-shaped strings from JSON and JSONL.

Run: `./.venv/bin/python -m pytest -q telegram-resilience/tests`

Expected: PASS.

- [ ] **Step 5: Commit the shared state machine**

```bash
git add telegram-resilience/bin/telegram_resilience.py telegram-resilience/tests/test_telegram_resilience.py telegram-resilience/README.md
git commit -m "feat: add PolyCop Telegram resilience state"
```

## Task 2: Add durable notices and a safe live-auth probe

**Files:**
- Modify: `telegram-resilience/bin/telegram_resilience.py`
- Create: `telegram-resilience/bin/telegram-resilience-probe.py`
- Modify: `telegram-resilience/tests/test_telegram_resilience.py`
- Modify: `telegram-resilience/README.md`

**Interfaces:**
- Consumes: completed circuit transitions and an existing scanner Discord sender result.
- Produces: retryable `PendingNotification` claims keyed as `<incident-id>:<kind>`, and a no-message probe CLI.

- [ ] **Step 1: Write failing notification and probe tests**

```python
def test_failed_notification_claim_retries_with_same_event_key(tmp_path: Path) -> None:
    resilience = _open_transport_incident(tmp_path)
    first = resilience.claim_notification("idx-swing-watch-phintraco-daily", WIB_NOW)
    assert first.event_key == f"{first.incident_id}:transport_outage"
    assert resilience.claim_notification("idx-market-news-watch", WIB_NOW) is None

    retry = resilience.claim_notification("idx-market-news-watch", WIB_NOW + timedelta(seconds=76))
    assert retry.event_key == first.event_key

def test_acknowledged_notification_is_never_claimed_again(tmp_path: Path) -> None:
    resilience = _open_transport_incident(tmp_path)
    notice = resilience.claim_notification("polymarket-signal-watch", WIB_NOW)
    resilience.acknowledge_notification(notice.claim_id, WIB_NOW)
    assert resilience.claim_notification("idx-ssf-watch-phintraco-weekly", WIB_NOW) is None
```

Add a fake-client subprocess test proving the CLI calls `connect`, `is_user_authorized`, `get_me`, and `disconnect`, but cannot call `get_entity`, `iter_messages`, `send_message`, or a Discord sender.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m pytest -q telegram-resilience/tests/test_telegram_resilience.py -k 'notification or probe'`

Expected: FAIL because the notification protocol and CLI do not exist.

- [ ] **Step 3: Implement notifications and probe**

Render only:

```text
❌ telegram-polycop · HH:MM WIB · transport unavailable; affected=<watchers>
❌ telegram-polycop · HH:MM WIB · authorization required; manual PolyCop session login needed
🫀 telegram-polycop · HH:MM WIB · recovered after <duration>; affected=<watchers>
```

Claiming sets a 75-second notification lease. Acknowledgement alone marks delivery. The CLI accepts `--state-path`, `--log-path`, and `--no-notify`; uses only existing PolyCop credentials from its wrapper environment; prints `connected`, `authorized`, and safe DC data as JSON; and never touches watcher state.

- [ ] **Step 4: Run all shared tests**

Run: `./.venv/bin/python -m pytest -q telegram-resilience/tests`

Expected: PASS.

- [ ] **Step 5: Commit notices and probe**

```bash
git add telegram-resilience
git commit -m "feat: add durable Telegram incident notifications"
```

## Task 3: Deploy the common module once and expose it to four scanners

**Files:**
- Modify: `deploy.sh`
- Modify: `idx-market-news-watch/bin/idx-market-news-watch.sh`
- Modify: `idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh`
- Modify: `idx-ssf-watch-phintraco-weekly/bin/idx-ssf-watch-phintraco-weekly.sh`
- Modify: `polymarket-signal-watch/bin/polymarket-signal-watch.sh`
- Modify: `idx-market-news-watch/tests/test_packaging.py`
- Create: `idx-swing-watch-phintraco-daily/tests/test_wrapper.py`
- Modify: `idx-ssf-watch-phintraco-weekly/tests/test_wrapper.py`
- Create: `polymarket-signal-watch/tests/test_wrapper.py`

**Interfaces:**
- Consumes: `./deploy.sh <component> [file]`.
- Produces: `$HOME/.agents/skills/telegram-resilience/bin/telegram_resilience.py` and an identical wrapper import contract.

- [ ] **Step 1: Write failing wrapper and deploy tests**

```python
def test_wrapper_exports_shared_runtime_path() -> None:
    wrapper = (ROOT / "bin/idx-swing-watch-phintraco-daily.sh").read_text()
    assert 'RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"' in wrapper
    assert "telegram_resilience.py" in wrapper
    assert "TELEGRAM_SESSION_STRING" not in wrapper

def test_deploy_creates_component_runtime_directory_before_rsync() -> None:
    script = Path("deploy.sh").read_text()
    assert 'install -d -m 700 "$HOME/.agents/skills/$cron/bin"' in script
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest -q idx-market-news-watch/tests/test_packaging.py idx-ssf-watch-phintraco-weekly/tests/test_wrapper.py idx-swing-watch-phintraco-daily/tests/test_wrapper.py polymarket-signal-watch/tests/test_wrapper.py`

Expected: FAIL because the common runtime path is absent.

- [ ] **Step 3: Implement the single import boundary**

Each wrapper adds this setup after its existing `PATH` export:

```bash
RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"
if [[ ! -r "$RESILIENCE_BIN/telegram_resilience.py" ]]; then
  printf '%s FATAL: telegram resilience module missing at %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$RESILIENCE_BIN" >&2
  exit 127
fi
export PYTHONPATH="$RESILIENCE_BIN:${PYTHONPATH-}"
```

Keep current credential loading unchanged. Update `deploy.sh` to validate its local `bin/` source and run `install -d -m 700 "$HOME/.agents/skills/$cron/bin"` on the VPS before the existing copy. Preserve single-file deployment.

- [ ] **Step 4: Run syntax and package checks**

```bash
bash -n deploy.sh
bash -n idx-market-news-watch/bin/idx-market-news-watch.sh
bash -n idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh
bash -n idx-ssf-watch-phintraco-weekly/bin/idx-ssf-watch-phintraco-weekly.sh
bash -n polymarket-signal-watch/bin/polymarket-signal-watch.sh
./.venv/bin/python -m pytest -q idx-market-news-watch/tests/test_packaging.py idx-ssf-watch-phintraco-weekly/tests/test_wrapper.py idx-swing-watch-phintraco-daily/tests/test_wrapper.py polymarket-signal-watch/tests/test_wrapper.py
```

Expected: PASS.

- [ ] **Step 5: Commit the import boundary**

```bash
git add deploy.sh idx-market-news-watch/bin/idx-market-news-watch.sh idx-swing-watch-phintraco-daily/bin/idx-swing-watch-phintraco-daily.sh idx-ssf-watch-phintraco-weekly/bin/idx-ssf-watch-phintraco-weekly.sh polymarket-signal-watch/bin/polymarket-signal-watch.sh idx-market-news-watch/tests/test_packaging.py idx-swing-watch-phintraco-daily/tests/test_wrapper.py idx-ssf-watch-phintraco-weekly/tests/test_wrapper.py polymarket-signal-watch/tests/test_wrapper.py
git commit -m "chore: expose shared Telegram resilience runtime"
```

## Task 4: Integrate Daily Swing and Weekly SSF at the connection boundary

**Files:**
- Modify: `idx-swing-watch-phintraco-daily/bin/scan.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/conftest.py`
- Modify: `idx-swing-watch-phintraco-daily/tests/test_scan.py`
- Modify: `idx-ssf-watch-phintraco-weekly/bin/scan.py`
- Modify: `idx-ssf-watch-phintraco-weekly/tests/conftest.py`
- Modify: `idx-ssf-watch-phintraco-weekly/tests/test_scan.py`

**Interfaces:**
- Consumes: the common guard before each current `await client.connect()`.
- Produces: clean skips and notification acknowledgement through Daily Swing `post_discord_text` and SSF `post_operational_text`.

- [ ] **Step 1: Write failing adapter regressions**

```python
def test_daily_swing_cooldown_does_not_create_client_or_change_outbox(tmp_state, monkeypatch):
    before = scan.empty_state()
    before["outbox"] = {"34093": {"phase": "pending_text"}}
    scan.save_state(before)
    monkeypatch.setattr(scan, "_resilience", lambda now: FakeResilience.cooldown())
    monkeypatch.setattr(scan, "make_client", lambda: pytest.fail("cooldown must not connect"))

    assert asyncio.run(scan.run(now=WIB_NOW)) == {"wakeAgent": False}
    assert scan.load_state()["outbox"] == before["outbox"]

def test_ssf_auth_required_does_not_resolve_source_or_advance_cursor(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["observed_message_id"] = 33681
    scan.save_state(state)
    monkeypatch.setattr(scan, "_resilience", lambda now: FakeResilience.auth_required())
    monkeypatch.setattr(scan, "resolve_source", lambda *_: pytest.fail("must not read Telegram"))

    assert asyncio.run(scan.run(now=WIB_NOW, dry_run=True)) == {"wakeAgent": False}
    assert scan.load_state()["observed_message_id"] == 33681
```

Add sender tests asserting a notification uses `notification.event_key` and is acknowledged only when the existing sender returns a Discord message ID.

- [ ] **Step 2: Run the regressions to verify they fail**

```bash
(cd idx-swing-watch-phintraco-daily && ../.venv/bin/python -m pytest -q tests/test_scan.py -k 'cooldown or resilience')
(cd idx-ssf-watch-phintraco-weekly && ../.venv/bin/python -m pytest -q tests/test_scan.py -k 'auth_required or resilience')
```

Expected: FAIL because neither scanner has the guard.

- [ ] **Step 3: Apply the guard only around connection and authorization**

Add the local common `bin` directory to both `conftest.py` files. Before `make_client()`, call `acquire_probe`. For a non-`probe` decision, claim and post a notification then return `{"wakeAgent": False}` before client creation, source resolution, or watcher-state write.

Immediately after `await client.connect()`, add:

```python
if not await client.is_user_authorized():
    resilience.record_auth_required(decision.lease_id, WATCHER_NAME, now)
    await client.disconnect()
    _publish_resilience_notification(resilience, now, dry_run)
    return {"wakeAgent": False}

me = await client.get_me()
resilience.record_authenticated_success(
    decision.lease_id, WATCHER_NAME, now,
    getattr(client.session, "dc_id", None), _safe_endpoint(client),
)
```

Catch only classified transport exceptions around the connection and authorization segment. Do not route source-parser or Discord-delivery errors into the common Telegram circuit.

- [ ] **Step 4: Run both full watcher suites**

```bash
(cd idx-swing-watch-phintraco-daily && ../.venv/bin/python -m pytest -q)
(cd idx-ssf-watch-phintraco-weekly && ../.venv/bin/python -m pytest -q)
```

Expected: PASS.

- [ ] **Step 5: Commit the read-only watcher integration**

```bash
git add idx-swing-watch-phintraco-daily idx-ssf-watch-phintraco-weekly
git commit -m "feat: guard Phintraco watchers from Telegram outages"
```

## Task 5: Integrate Polymarket without bot traffic during an outage

**Files:**
- Modify: `polymarket-signal-watch/bin/scan.py`
- Modify: `polymarket-signal-watch/tests/conftest.py`
- Modify: `polymarket-signal-watch/tests/test_scan.py`
- Modify: `polymarket-signal-watch/SKILL.md`
- Modify: `polymarket-signal-watch/DEPLOY.md`

**Interfaces:**
- Consumes: the common guard before `make_client()`.
- Produces: no `read_new_signals`, `fetch_ai_metrics`, `fetch_whale_profile`, or analysis-bot message call while the common circuit is unavailable.

- [ ] **Step 1: Write failing no-message and notification acknowledgement tests**

```python
def test_polymarket_cooldown_preserves_state_and_never_messages_bot(tmp_state, monkeypatch):
    state = scan.empty_state()
    state["last_seen_id"] = 100
    scan.save_state(state)
    monkeypatch.setattr(scan, "_resilience", lambda now: FakeResilience.cooldown())
    monkeypatch.setattr(scan, "make_client", lambda: pytest.fail("cooldown must not connect"))
    monkeypatch.setattr(scan, "fetch_ai_metrics", lambda *_: pytest.fail("must not message bot"))

    assert asyncio.run(scan.run(now=WIB_NOW)) == {"wakeAgent": False}
    assert scan.load_state()["last_seen_id"] == 100

def test_polymarket_acknowledges_only_after_discord_success(tmp_state, monkeypatch):
    resilience = FakeResilience.with_notification("incident-1:transport_outage")
    monkeypatch.setattr(scan, "_resilience", lambda now: resilience)
    monkeypatch.setattr(scan, "post_discord", lambda *args, **kwargs: False)

    asyncio.run(scan.run(now=WIB_NOW))
    assert resilience.acknowledged_claim_ids == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `(cd polymarket-signal-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py -k 'cooldown or acknowledges')`

Expected: FAIL because Polymarket connects before a shared decision.

- [ ] **Step 3: Integrate guard and stable nonce**

Add the common module path in `conftest.py`. Apply Task 4's guard flow before `make_client()`. Extend `post_discord` with `event_key: str | None = None`. For a resilience text notification use `{"content": content, "nonce": event_key}`; leave normal alerts and heartbeats unchanged when `event_key is None`. Preserve the existing PolyCop bot-analysis circuit breaker after a healthy authenticated connection.

- [ ] **Step 4: Run the complete Polymarket suite**

Run: `(cd polymarket-signal-watch && ../.venv/bin/python -m pytest -q)`

Expected: PASS.

- [ ] **Step 5: Commit the Polymarket integration**

```bash
git add polymarket-signal-watch
git commit -m "feat: share Telegram outage handling with Polymarket"
```

## Task 6: Integrate Market News and remove the noisy agent handoff

**Files:**
- Modify: `idx-market-news-watch/bin/scan.py`
- Modify: `idx-market-news-watch/tests/conftest.py`
- Modify: `idx-market-news-watch/tests/test_scan.py`
- Modify: `idx-market-news-watch/tests/test_packaging.py`
- Modify: `idx-market-news-watch/SKILL.md`
- Modify: `idx-market-news-watch/DEPLOY.md`

**Interfaces:**
- Consumes: the common guard before `_make_client()` and existing `post_hermes_text`.
- Produces: zero-exit no-agent outcomes for unavailable, cooldown, leased, and auth-required states; only a healthy classification claim can return `wakeAgent:true`.

- [ ] **Step 1: Write failing regression tests**

```python
def test_transport_failure_preserves_provider_cursor_and_returns_no_agent(tmp_state, monkeypatch):
    state = empty_state()
    state["providers"]["phintraco"]["highest_observed_message_id"] = 44
    save_state(state, tmp_state)
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    monkeypatch.setattr(scan, "_resilience", lambda now: FakeResilience.probe())
    monkeypatch.setattr(scan, "_make_client", lambda: FailingConnectClient(TimeoutError()))

    assert asyncio.run(scan.run(now=WIB_NOW))["wakeAgent"] is False
    assert load_state(tmp_state)["providers"]["phintraco"]["highest_observed_message_id"] == 44

def test_handled_resilience_result_makes_main_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(scan, "run", lambda: {"wakeAgent": False, "error": "telegram unavailable"})

    assert scan.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"wakeAgent": False, "error": "telegram unavailable"}
```

Also assert an unavailable decision does not invoke `_resolve_runtime_clients`, `claim_oldest_pending_analysis`, or `build_wake_payload`, and acknowledges a notification only after `post_hermes_text` returns a message ID.

- [ ] **Step 2: Run the regressions to verify they fail**

Run: `(cd idx-market-news-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py -k 'resilience or handled_resilience')`

Expected: FAIL because `main()` currently exits one for collector exceptions.

- [ ] **Step 3: Apply the narrow guard and exit-code change**

Add the common module path in `conftest.py`. For non-probe, transport, and auth-required outcomes, publish any claimable notification through `post_hermes_text(content, event_key, dry_run)`, return a handled no-agent object, and make `main()` return zero for that object. Preserve a nonzero exit only for unexpected programming or unrelated state errors. Do not alter the healthy one-item agent classification protocol.

- [ ] **Step 4: Run the full Market News suite**

Run: `(cd idx-market-news-watch && ../.venv/bin/python -m pytest -q)`

Expected: PASS.

- [ ] **Step 5: Commit the no-agent repair**

```bash
git add idx-market-news-watch
git commit -m "fix: keep Telegram collector failures out of Market News agent runs"
```

## Task 7: Document, deploy with approval, and verify safely

**Files:**
- Modify: `telegram-resilience/README.md`
- Modify: `idx-market-news-watch/SKILL.md`
- Modify: `idx-swing-watch-phintraco-daily/SKILL.md`
- Modify: `idx-ssf-watch-phintraco-weekly/SKILL.md`
- Modify: `polymarket-signal-watch/SKILL.md`
- Modify: `idx-market-news-watch/DEPLOY.md`
- Modify: `polymarket-signal-watch/DEPLOY.md`
- Modify: `idx-swing-watch-phintraco-daily/SPEC.md`
- Modify: `idx-ssf-watch-phintraco-weekly/SPEC.md`

**Interfaces:**
- Consumes: completed common module and four integrations.
- Produces: exact deployment, checksum, safe-probe, and natural-schedule verification instructions.

- [ ] **Step 1: Write failing documentation contract tests**

Require every affected watcher document to name `telegram-resilience`, `POLYCOP_SESSION_STRING`, the common state path, and no-agent/no-cursor-advance outage behavior. Reject `TELEGRAM_SESSION_STRING` in those four watcher documents.

- [ ] **Step 2: Run the documentation tests to verify they fail**

```bash
(cd idx-market-news-watch && ../.venv/bin/python -m pytest -q tests/test_packaging.py)
(cd idx-swing-watch-phintraco-daily && ../.venv/bin/python -m pytest -q tests/test_scan.py -k runtime)
(cd idx-ssf-watch-phintraco-weekly && ../.venv/bin/python -m pytest -q tests/test_scan.py -k runtime)
(cd polymarket-signal-watch && ../.venv/bin/python -m pytest -q tests/test_scan.py -k runtime)
```

Expected: FAIL until the runtime contract is documented.

- [ ] **Step 3: Document deployment order and prohibitions**

Document:

```bash
./deploy.sh telegram-resilience
./deploy.sh idx-swing-watch-phintraco-daily scan.py
./deploy.sh idx-ssf-watch-phintraco-weekly scan.py
./deploy.sh polymarket-signal-watch scan.py
./deploy.sh idx-market-news-watch scan.py
```

Require checksum comparison for two common files, four scanners, and changed wrappers. Document the safe probe with isolated `/tmp/telegram-resilience-probe-state.json` and `--no-notify`. Prohibit manual Hermes triggers, live state edits, Discord test messages, and a Polymarket scanner smoke run.

- [ ] **Step 4: Run the complete local verification matrix**

```bash
./.venv/bin/python -m pytest -q telegram-resilience/tests
(cd idx-swing-watch-phintraco-daily && ../.venv/bin/python -m pytest -q)
(cd idx-ssf-watch-phintraco-weekly && ../.venv/bin/python -m pytest -q)
(cd polymarket-signal-watch && ../.venv/bin/python -m pytest -q)
(cd idx-market-news-watch && ../.venv/bin/python -m pytest -q)
bash -n deploy.sh
```

Expected: every command exits zero.

- [ ] **Step 5: Obtain approval, deploy, and observe natural runs**

Before the first VPS write, show the exact source-to-VPS diff and checksums, then obtain current-session approval. Deploy the common module before every watcher change, compare local and VPS SHA-256 values, and run only the isolated safe probe. Do not manually trigger any job. Observe natural scheduled executions, confirm all four jobs stay active, inspect shared state and JSONL, and confirm Discord history has no resilience notice unless a real incident happens.

- [ ] **Step 6: Commit documents and rollout guidance**

```bash
git add telegram-resilience idx-market-news-watch idx-swing-watch-phintraco-daily idx-ssf-watch-phintraco-weekly polymarket-signal-watch
git commit -m "docs: document PolyCop Telegram resilience operations"
```

## Plan Self-Review

### Spec coverage

- Shared in-process module, no daemon, no new cron, no database: Tasks 1 to 3.
- Exactly four PolyCop watchers and gateway/SCELE exclusion: Global Constraints and Tasks 4 to 7.
- One probe lease, bounded transport backoff, stale lease recovery, and authorization-required state: Task 1.
- Durable outage and recovery notifications with idempotent acknowledgement: Task 2 and adapter Tasks 4 to 6.
- Cursor/outbox preservation, no Polymarket bot traffic, and Market News no-agent behavior: Tasks 4 to 6.
- 30-day diagnostics, checksum parity, safe probe, and natural-run verification: Tasks 1, 2, and 7.

### Placeholder scan

Every task names exact paths, public interfaces, test examples, failing and passing commands, deployment order, and commit commands.

### Type consistency

All integrations use `PolyCopResilience`, `ProbeDecision`, `PendingNotification`, `acquire_probe`, `record_transport_failure`, `record_auth_required`, `record_authenticated_success`, `claim_notification`, and `acknowledge_notification`. Event keys are always `<incident-id>:<kind>`.
