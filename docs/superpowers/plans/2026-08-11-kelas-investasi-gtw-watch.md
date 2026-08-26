# Kelas Investasi GTW Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build an hourly future-only Telegram #GTW watcher that summarizes complete Kelas Investasi bundles and posts their source images to Discord #stock-news.

**Architecture:** A dedicated deterministic Python cron uses the shared PolyCop Telegram session and telegram-resilience. It persists a cursor, pending bundles, source image files, agent leases, and a FIFO outbox. Hermes supplies only a validated title and summary. The scanner owns text-first Discord delivery and attachment retries.

**Tech Stack:** Python 3, Telethon, requests, JSON state, fcntl locks, pytest, Hermes cron wake payloads, Discord API v10.

## Global Constraints

- Identity: kelas-investasi-gtw-watch. Source: @kelasinvestasiid, Telegram ID 2142109618.
- Schedule only after explicit approval: 0 * * * *, WIB.
- Destination: Discord #stock-news, channel ID 1525102508714889257, posted by Yanto.
- First observation saves the newest cursor and never backfills.
- Eligible header is case-insensitive Good to watch - <IDX ticker> #GTW only.
- A bundle contains contiguous text and images. It closes on the next eligible header or an inter-message gap greater than 20 minutes. A header-closed bundle is ready immediately. A final bundle needs 20 quiet minutes.
- Exclude late replies, disclaimer, article links, promotions, and unrelated posts.
- Use only POLYCOP_SESSION_STRING through acquire_probe_after_active_lease. A cooldown or auth hold must not mutate cursor, pending bundle, or outbox.
- Text precedes source image attachments in original order. Retrying an image never duplicates delivered text.
- Use exactly <:telegram:1531657996432576618> and <:kelasinvestasi:1536570114772574218> in rendered text. Do not use generic alert emoji, Good to Watch label, or middle-dot separator.
- Plan source always renders Buy area, Target, and Stoploss rows. Missing values are -.
- Successful heartbeat: 🫀 kelas-investasi-gtw, HH:MM WIB, scanned=N pending=N delivered=N. Fatal: ❌ kelas-investasi-gtw, HH:MM WIB, failed: <sanitized reason>.
- Run the final suite with ../.venv/bin/python -m pytest -q. Do not create a watcher-specific virtual environment.
- This workspace has no Git repository. Never initialize one. At each commit checkpoint, record that git rev-parse --is-inside-work-tree fails and make no commit.

---

## File structure

| File | Responsibility |
|---|---|
| kelas-investasi-gtw-watch/bin/models.py | Source message, image, plan, bundle, and outbox dataclasses |
| kelas-investasi-gtw-watch/bin/parsing.py | Header detection and deterministic source-plan extraction |
| kelas-investasi-gtw-watch/bin/state.py | Atomic cursor, pending-bundle, outbox, lease, retry, and lock state |
| kelas-investasi-gtw-watch/bin/telegram_source.py | Telethon fetch, source resolution, and durable source-image capture |
| kelas-investasi-gtw-watch/bin/render.py | Exact Discord text layout and message splitting |
| kelas-investasi-gtw-watch/bin/discord.py | Nonce-based text and local-file attachment delivery |
| kelas-investasi-gtw-watch/bin/agent_protocol.py | Bounded Hermes item and strict submission validation |
| kelas-investasi-gtw-watch/bin/scan.py | Resilience, orchestration, heartbeat, no-post, and submit CLI |
| kelas-investasi-gtw-watch/bin/kelas-investasi-gtw-watch.sh | VPS environment and logging wrapper |
| kelas-investasi-gtw-watch/tests/ | Focused behavioral test modules and fixtures |
| kelas-investasi-gtw-watch/{SKILL.md,README.md,SPEC.md,CONTEXT.md,DEPLOY.md} | Runtime and deployment contract |
| AGENTS.md, README.md, telegram-resilience/tests/test_documentation.py | Root inventory and shared-session documentation |

## Task 1: Models and GTW parsing

**Files:**
- Create: kelas-investasi-gtw-watch/bin/models.py
- Create: kelas-investasi-gtw-watch/bin/parsing.py
- Create: kelas-investasi-gtw-watch/tests/conftest.py
- Create: kelas-investasi-gtw-watch/tests/test_parsing.py

**Interfaces:**
- Produces SourceMedia(message_id: int, ordinal: int), SourceMessage(message_id: int, posted_at: datetime, text: str, reply_to_message_id: int | None, media: tuple[SourceMedia, ...]), PlanSource(buy_area: str, targets: str, stoploss: str), parse_gtw_header(text: str) -> GtwHeader | None, and extract_plan(text: str) -> PlanSource.

- [ ] **Step 1: Write failing eligibility and plan tests**

~~~python
def test_header_is_case_insensitive_and_normalizes_ticker() -> None:
    header = parse_gtw_header("good to watch - ctra #gtw")
    assert header is not None
    assert header.ticker == "CTRA"

def test_untagged_and_non_idx_headers_are_rejected() -> None:
    assert parse_gtw_header("Good to watch - CTRA") is None
    assert parse_gtw_header("Good to watch - AAPL #GTW") is None

def test_plan_uses_dash_for_absent_fields() -> None:
    plan = extract_plan("Buy area: 605–630\nTP 1: 655\nTP 2: 675")
    assert (plan.buy_area, plan.targets, plan.stoploss) == ("605 sampai 630", "655, 675", "-")
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_parsing.py

Expected: import failure because parsing.py does not exist.

- [ ] **Step 3: Implement the smallest parser**

Use one anchored, case-insensitive regex for Good to watch, a two-to-five-letter IDX ticker, and standalone #GTW. Do not accept the older untagged Good to watch posts. Extract Buy area, TP or Target labels, and Stoploss or Stop-loss labels. Normalize only a buy-area range to “sampai”, preserve source numeric values and < stoploss values, and return - for each absent field.

- [ ] **Step 4: Add regression tests**

Test mixed-case tag, rejected promotional text, several TP labels in original order, a singular Target label, and a source with no plan labels.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_parsing.py && git rev-parse --is-inside-work-tree

Expected: tests pass, Git command reports not a git repository, no commit.

## Task 2: Atomic state and bundle boundaries

**Files:**
- Create: kelas-investasi-gtw-watch/bin/state.py
- Create: kelas-investasi-gtw-watch/tests/test_state.py
- Create: kelas-investasi-gtw-watch/tests/fixtures/messages.py

**Interfaces:**
- Produces new_state(), load_state(path), save_state(path, value), observe_messages(value, messages, now), ready_events(value, now), claim_oldest_agent(value, now), and run_lock(path).
- State fields: version, cursor, pending, outbox, stats.
- Pending bundle fields: header_message_id, ticker, source_message_ids, source_text, media, last_message_at, closed_by_header.
- Outbox fields: event_key, ticker, header_message_id, source_text, plan, media, title, summary, agent_phase, agent_lease_until, text_index, next_media_index, attempts, next_attempt_at, last_error.

- [ ] **Step 1: Write failing cold-start and 20-minute tests**

~~~python
def test_first_observation_only_initializes_cursor() -> None:
    value = new_state()
    observe_messages(value, [header(100, "CTRA")], at("2026-08-11T09:00:00+07:00"))
    assert value["cursor"] == 100
    assert value["pending"] == []
    assert value["outbox"] == []

def test_final_bundle_is_ready_only_after_twenty_quiet_minutes() -> None:
    value = initialized_state(cursor=100)
    observe_messages(value, [header(101, "CTRA"), analysis(102)], at("2026-08-11T09:00:00+07:00"))
    assert ready_events(value, at("2026-08-11T09:20:00+07:00")) == []
    assert [event["ticker"] for event in ready_events(value, at("2026-08-11T09:20:01+07:00"))] == ["CTRA"]
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_state.py

Expected: import failure because state.py does not exist.

- [ ] **Step 3: Implement durable transitions**

Use JSON temporary files with 0600 mode, fsync, and os.replace. Hold a nonblocking fcntl run lock. On corrupt state, move the original to state.corrupt-<timestamp>.json and block execution without creating a new cursor. Observe message IDs ascending and persist cursor together with each transition.

- [ ] **Step 4: Add boundary and exclusion regressions**

~~~python
def test_next_gtw_header_makes_prior_bundle_ready_immediately() -> None:
    value = initialized_state(cursor=100)
    observe_messages(value, [header(101, "CTRA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:17+07:00"))
    assert [event["ticker"] for event in ready_events(value, at("2026-08-11T09:00:17+07:00"))] == ["CTRA"]

def test_late_disclaimer_and_article_link_do_not_change_closed_bundle() -> None:
    value = closed_bundle("RAJA", ids=[101, 102])
    observe_messages(value, [reply(201, "Disclaimer", parent=101), reply(202, "Baca selengkapnya", parent=101)], at("2026-08-11T10:00:00+07:00"))
    assert value["outbox"][0]["source_message_ids"] == [101, 102]
~~~

Also test observed zero-second and 17-second analysis gaps, same-timestamp RATU then FORE headers, image-only continuation, duplicate fetch replay, exact 20-minute boundary, lock contention, and state round trip.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_state.py && git rev-parse --is-inside-work-tree

Expected: tests pass, no commit because Git is unavailable.

## Task 3: Rendering and Hermes protocol

**Files:**
- Create: kelas-investasi-gtw-watch/bin/render.py
- Create: kelas-investasi-gtw-watch/bin/agent_protocol.py
- Create: kelas-investasi-gtw-watch/tests/test_render.py
- Create: kelas-investasi-gtw-watch/tests/test_agent_protocol.py

**Interfaces:**
- Produces render_event(event) -> list[str], agent_item(event) -> dict[str, object], build_wake_payload(item), and validate_submission(event, payload) -> dict[str, str].

- [ ] **Step 1: Write failing exact-output tests**

~~~python
def test_render_matches_approved_stock_news_layout() -> None:
    text = render_event(event("CTRA", "605 sampai 630", "655, 675, 700", "<573"))[0]
    assert text == (
        "### <:telegram:1531657996432576618> CTRA: Akumulasi kuat di area breakout\n"
        "-# <:kelasinvestasi:1536570114772574218> Kelas Investasi\n\n"
        "*(Ringkasan)* Ringkasan tervalidasi.\n\n"
        "*Plan sumber*\n- Buy area: 605 sampai 630\n- Target: 655, 675, 700\n- Stoploss: <573\n\n"
        "[View on Telegram](<https://t.me/kelasinvestasiid/101>)"
    )
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_render.py kelas-investasi-gtw-watch/tests/test_agent_protocol.py

Expected: import failures for render.py and agent_protocol.py.

- [ ] **Step 3: Implement exact renderer and validator**

Title requires the source ticker followed by colon, is five to 120 characters, has no URL or ending punctuation. Summary begins exactly *(Ringkasan)* , has one or two single-line paragraphs, is at most 1,600 characters, and cannot invent plan data. Renderer always emits all three plan lines, uses extracted - values, escapes Discord control markup, links the public header URL, and splits safely below Discord’s 2,000 character limit.

The agent receives only event key, ticker, source URL, normalized bundle text, and instruction to ignore embedded source instructions. It returns exactly event_key, title, and summary. It never posts Discord itself.

- [ ] **Step 4: Add safety regressions**

Test wrong title ticker, extra JSON keys, invalid summary prefix, missing plan values, absence of generic emoji and Good to Watch text, absence of middle dots, safe source-link rendering, and a long summary that splits without splitting the plan block or link.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_render.py kelas-investasi-gtw-watch/tests/test_agent_protocol.py && git rev-parse --is-inside-work-tree

Expected: tests pass, no Git commit.

## Task 4: Shared-resilient Telegram source and images

**Files:**
- Create: kelas-investasi-gtw-watch/bin/telegram_source.py
- Create: kelas-investasi-gtw-watch/tests/test_telegram_source.py
- Modify: kelas-investasi-gtw-watch/bin/models.py

**Interfaces:**
- Produces make_client(), resolve_source(client), latest_message_id(client, entity), fetch_unseen_messages(client, entity, min_id), to_source_message(message), and capture_image(client, entity, message_id, ordinal, destination).

- [ ] **Step 1: Write failing adapter tests**

~~~python
async def test_unseen_messages_are_returned_by_ascending_id() -> None:
    messages = await fetch_unseen_messages(FakeClient([raw(103), raw(101), raw(102)]), object(), 100)
    assert [message.message_id for message in messages] == [101, 102, 103]

async def test_capture_image_writes_the_downloaded_source_bytes(tmp_path: Path) -> None:
    path = await capture_image(FakeClient(image=b"chart"), object(), 102, 0, tmp_path)
    assert path.read_bytes() == b"chart"
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_telegram_source.py

Expected: import failure for telegram_source.py.

- [ ] **Step 3: Implement Telethon source adapter**

Build TelegramClient with StringSession(POLYCOP_SESSION_STRING), TELEGRAM_API_ID, and TELEGRAM_API_HASH. Resolve only Telegram ID 2142109618. Fetch incremental messages through iter_messages with min_id and reverse=True, then numeric-sort before conversion. Treat Telegram photos as images and ignore non-image documents. Capture image bytes before delivery into state/media/kelas-investasi-<message-id>-<ordinal>.jpg using durable atomic writes. Do not mutate watcher state in adapter functions.

- [ ] **Step 4: Add source and credential safety tests**

Test text document exclusion, two images in different message order, empty download failure, inaccessible source message, and an incomplete-credentials error that does not expose session content.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_telegram_source.py telegram-resilience/tests/test_telegram_resilience.py && git rev-parse --is-inside-work-tree

Expected: tests pass, no Git commit.

## Task 5: Discord text-first delivery and retry legs

**Files:**
- Create: kelas-investasi-gtw-watch/bin/discord.py
- Create: kelas-investasi-gtw-watch/tests/test_discord.py
- Modify: kelas-investasi-gtw-watch/bin/state.py

**Interfaces:**
- Produces nonce(event_key, leg), post_text(content, channel_id, dry_run, nonce_value), post_file(path, channel_id, dry_run, nonce_value), and deliver_oldest_ready_event(state, now, dry_run).

- [ ] **Step 1: Write failing order test**

~~~python
def test_delivery_sends_text_then_images_in_source_order(tmp_path: Path, mocker) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg"), image(tmp_path, "two.jpg")])
    sent = []
    mocker.patch("discord.post_text", side_effect=lambda *args: sent.append("text"))
    mocker.patch("discord.post_file", side_effect=lambda path, *args: sent.append(Path(path).name))
    deliver_until_idle(state_with(event), now())
    assert sent == ["text", "one.jpg", "two.jpg"]
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_discord.py

Expected: import failure for discord.py.

- [ ] **Step 3: Implement one-leg-at-a-time durable delivery**

Use Discord API v10, DISCORD_BOT_TOKEN, 30-second timeout, deterministic 24-character SHA-256 nonce from kelas-investasi-gtw-watch:<event-key>:<leg>, and 429 retry-after propagation. Persist after each successful text chunk or image. Use already-captured local images only. On failure, store a sanitized error no longer than 180 characters and exponential retry from 60 seconds to a 15-minute cap. Remove event only after all legs finish. In KELAS_INVESTASI_GTW_NO_POST=1, print intended operations and do not advance any delivery leg.

- [ ] **Step 4: Add partial-delivery regressions**

~~~python
def test_second_image_failure_retries_only_second_image(tmp_path: Path, mocker) -> None:
    event = text_and_first_image_delivered_event(tmp_path)
    mocker.patch("discord.post_file", side_effect=[RuntimeError("temporary"), "discord-id"])
    assert deliver_oldest_ready_event(state_with(event), now()) is False
    assert event["text_index"] == 1
    assert event["next_media_index"] == 1
    assert deliver_oldest_ready_event(state_with(event), retry_due_time(event)) is True
    assert event["next_media_index"] == 2
~~~

Also test dry run makes no HTTP call, text message limit rejection, 429 retry, missing local image, and no duplicate nonce leg.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_discord.py kelas-investasi-gtw-watch/tests/test_state.py && git rev-parse --is-inside-work-tree

Expected: tests pass, no Git commit.

## Task 6: Scanner, wrapper, heartbeat, and wake submission

**Files:**
- Create: kelas-investasi-gtw-watch/bin/scan.py
- Create: kelas-investasi-gtw-watch/bin/kelas-investasi-gtw-watch.sh
- Create: kelas-investasi-gtw-watch/tests/test_scan.py
- Create: kelas-investasi-gtw-watch/tests/test_wrapper.py

**Interfaces:**
- Produces run(now=None, dry_run=None) -> dict[str, object] and submit_analysis_payload(payload, dry_run=None) -> dict[str, object].

- [ ] **Step 1: Write failing orchestration tests**

~~~python
def test_complete_final_bundle_wakes_agent_only_after_quiet_window(mocker) -> None:
    mocker.patch("scan.fetch_unseen_messages", return_value=[header(101, "CTRA"), analysis(102)])
    assert run(now=at("2026-08-11T09:19:59+07:00"), dry_run=True)["wakeAgent"] is False
    assert run(now=at("2026-08-11T09:20:01+07:00"), dry_run=True)["wakeAgent"] is True

def test_shared_cooldown_does_not_change_state(mocker, tmp_path: Path) -> None:
    mocker.patch("scan.acquire_probe_after_active_lease", return_value=blocked_probe())
    before = read_state(tmp_path / "state.json")
    assert run(now=now(), dry_run=True)["wakeAgent"] is False
    assert read_state(tmp_path / "state.json") == before
~~~

- [ ] **Step 2: Verify the test fails**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests/test_scan.py kelas-investasi-gtw-watch/tests/test_wrapper.py

Expected: import and wrapper-path failures.

- [ ] **Step 3: Implement orchestration**

Acquire run lock, then acquire_probe_after_active_lease before creating a Telegram client. On clean skip, print wakeAgent false without writing state. On success, verify authorization, initialize or ingest source, close and capture bundle images, persist, claim one 15-minute Hermes lease, and emit raw wake payload. submit-analysis validates the exact event, persists title and summary, then runs text-first delivery. Always disconnect the client and release resilience success, transport failure, or auth-required outcome in finally.

Wrapper exports PYTHONPATH=$HOME/.agents/skills/telegram-resilience/bin, loads only DISCORD_BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, and POLYCOP_SESSION_STRING from ~/.hermes/.env, uses the shared VPS Python runtime, logs sanitized output to ~/.logs/kelas-investasi-gtw-watch.log, and preserves scanner exit code.

- [ ] **Step 4: Add failure and no-post tests**

Test invalid summary leaves event pending, unavailable source, unauthenticated client, transport classification, lock contention, no eligible source, media capture failure, no-post no Discord calls, exact heartbeat, and exact sanitized fatal format.

- [ ] **Step 5: Run and record checkpoint**

Run: ./.venv/bin/python -m pytest -q kelas-investasi-gtw-watch/tests && git rev-parse --is-inside-work-tree

Expected: tests pass, no Git commit.

## Task 7: Documentation, deploy, and no-post proof

**Files:**
- Create: kelas-investasi-gtw-watch/SKILL.md
- Create: kelas-investasi-gtw-watch/README.md
- Create: kelas-investasi-gtw-watch/SPEC.md
- Create: kelas-investasi-gtw-watch/CONTEXT.md
- Create: kelas-investasi-gtw-watch/DEPLOY.md
- Modify: AGENTS.md
- Modify: README.md
- Modify: telegram-resilience/tests/test_documentation.py

**Interfaces:**
- Documents source boundary, exact JSON submission, no-post environment, shared-session rule, deployment checksums, and no-backfill policy.

- [ ] **Step 1: Extend documentation test first**

~~~python
def test_kelas_investasi_gtw_documents_shared_session() -> None:
    text = (ROOT / "kelas-investasi-gtw-watch" / "SKILL.md").read_text()
    assert "POLYCOP_SESSION_STRING" in text
    assert "acquire_probe_after_active_lease" in text
    assert "KELAS_INVESTASI_GTW_NO_POST=1" in text
~~~

Add the watcher to telegram-resilience/tests/test_documentation.py expected watcher inventory.

- [ ] **Step 2: Verify documentation test fails**

Run: ./.venv/bin/python -m pytest -q telegram-resilience/tests/test_documentation.py

Expected: the new SKILL.md and shared inventory are absent.

- [ ] **Step 3: Write runtime docs and update inventories**

Document all Global Constraints, exact text format, source-instruction safety, no direct Telegram posting, deployment through ./deploy.sh kelas-investasi-gtw-watch, runtime docs sync, wrapper checksum, and this no-post command:

~~~bash
ssh vps 'KELAS_INVESTASI_GTW_NO_POST=1 KELAS_INVESTASI_GTW_STATE_PATH=/tmp/kelas-investasi-gtw-state.json KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-investasi-gtw-media ~/.hermes/scripts/kelas-investasi-gtw-watch.sh'
~~~

Update AGENTS.md shared PolyCop watcher list and root README cron inventory. Do not modify the dotfiles mirror.

- [ ] **Step 4: Deploy source only after tests**

Run focused tests then full suite. Diff local and VPS target before copying. Deploy bin with ./deploy.sh kelas-investasi-gtw-watch, synchronize runtime docs separately, copy only the wrapper to ~/.hermes/scripts/, set executable mode, and compare local and VPS SHA-256 for each changed file. Do not create the Hermes job or alter live state.

- [ ] **Step 5: Run isolated no-post verification**

Run:

~~~bash
./.venv/bin/python -m pytest -q
ssh vps 'KELAS_INVESTASI_GTW_NO_POST=1 KELAS_INVESTASI_GTW_STATE_PATH=/tmp/kelas-investasi-gtw-state.json KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-investasi-gtw-media ~/.hermes/scripts/kelas-investasi-gtw-watch.sh'
git rev-parse --is-inside-work-tree
~~~

Expected: all tests pass; isolated no-post prints intended heartbeat and creates no Discord message, source media delivery, or production state mutation; no Git commit.

## Task 8: Register and observe only after explicit approval

**Files:**
- Modify: Hermes registry through supported Hermes CLI only.

**Interfaces:**
- Consumes deployed wrapper, checksum proof, successful no-post output, and explicit current-session approval.
- Produces enabled hourly job and later natural delivery evidence.

- [ ] **Step 1: Present the exact command and request approval**

Do not run this before approval:

~~~bash
ssh vps '$HOME/.local/bin/hermes cron create "0 * * * *" --name kelas-investasi-gtw-watch --deliver discord:1505162000420835388 --skill kelas-investasi-gtw-watch --script kelas-investasi-gtw-watch.sh --workdir /home/praya'
~~~

Explain that the first natural execution is cursor initialization only and sends no historical #GTW alerts.

- [ ] **Step 2: After approval, create and inspect job**

Run the approved command. Verify name, schedule, enabled state, no-agent script, #hermes delivery, and WIB next-run through hermes cron list. Never hand-edit ~/.hermes/cron/jobs.json.

- [ ] **Step 3: Verify natural cold start**

Wait for the natural first run. Inspect durable scheduler result, #hermes heartbeat, and state. Verify state stores latest source cursor and no historical outbox event. Do not reset, replay, or backfill.

- [ ] **Step 4: Verify future source delivery naturally**

When a new #GTW bundle appears, verify one #stock-news text message with the exact rendering, public source link, three-row plan, and all source images in original order. Verify all delivery legs complete. Do not manufacture a Telegram message or test-post externally.

- [ ] **Step 5: Handoff evidence**

Report job ID, execution ID, source header ID, Discord text ID, attachment count, state status, and expected absent Git commit.

## Plan self-review

- Spec coverage: Tasks 1 and 2 cover exact #GTW detection, 20-minute grouping, no backfill, and exclusions. Tasks 3 and 5 cover the exact approved rendering, plan rows, source link, text-first media, and retries. Tasks 4 and 6 cover Telethon plus shared resilience. Tasks 7 and 8 cover documentation, checksums, no-post proof, registration approval, heartbeat, and natural evidence.
- Placeholder scan: no incomplete marker, deferred implementation, or unspecified error-handling step appears.
- Type consistency: models and parser precede state; state precedes renderer and agent protocol; Telegram source and Discord delivery precede scanner; scanner precedes docs, deployment, and registration.

## Task 7 documentation review evidence, 2026-08-11

- Corrected the shared PolyCop inventory to five watchers, including `kelas-investasi-gtw-watch`, and updated the shared checksum inventory to five scanners.
- Removed the unsupported `KELAS_INVESTASI_GTW_FORCE_HEARTBEAT` instruction from the Kelas deployment runbook.
- Documented the supported isolated watcher state and media paths, while explicitly recording that the shared resilience state, lock, and production JSONL log remain live paths that a no-post run may touch. The runbook no longer claims production-state-free verification or guaranteed heartbeat output.
- Local verification passed: `telegram-resilience/tests/test_documentation.py`, 4 passed; `telegram-resilience/tests`, 21 passed; `kelas-investasi-gtw-watch/tests`, 110 passed.
- No SSH, deployment, scheduler, runtime state, external delivery, or Git operation was performed.
