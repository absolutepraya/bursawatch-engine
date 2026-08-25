# X Post Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a configuration-driven, no-LLM Hermes watcher that forwards eligible X posts from RSSHub to Discord with durable delivery and actionable hourly heartbeats.

**Architecture:** `x-post-watch` is a standalone Python cron skill. `config/watches.json` defines profiles and delivery policy; the scanner fetches RSSHub JSON, classifies and renders source posts, stores a per-profile cursor and FIFO delivery outbox, then posts text and media directly through Discord API v10. A thin Bash wrapper supplies the VPS environment and Hermes runs that wrapper as an hourly `--no-agent` cron.

**Tech Stack:** Python 3 standard library, `requests` already used by the Swing Watch, pytest, RSSHub JSON feed, Discord API v10, Bash, Hermes cron CLI.

## Global Constraints

- No LLM invocation, agent wake-up, direct X GraphQL polling, account discovery, replay, or state reset.
- Use RSSHub route `http://127.0.0.1:1200/twitter/user/<handle>?format=json` only once per enabled profile per hourly run.
- Use `Asia/Jakarta`; the approved live cron schedule is `0 * * * *`.
- Initial profile observation stores the current cursor and sends no historical posts.
- Default profile policy is normal and quote posts enabled, replies and reposts disabled, and media enabled.
- The exact heading is `### :twitter:<profile emoji><display name>`; the first profile renders `### :twitter::kutekians: Almer Sad, CFA`.
- Normal footer is `[View on X](<post URL>)`; quote footer is `[(Quoted)](<quoted-post URL>), [View on X](<post URL>)`.
- Post every media item as an independent Discord message after all text legs, in source order.
- Never disclose token values, cookies, authorization headers, or raw provider response bodies in source, logs, Discord, tests, or documentation.
- Source failures make the profile heartbeat degraded and do not advance its cursor; do not add a tight source retry loop.
- Every scheduled run, including no-hit, sends `🫀 x-post · HH:MM WIB · <tokens>[ ⚠️]` to `1505162000420835388`.
- Do not edit `~/.dotfiles/vps/agents/skills/`; it is a mirror. Do not hand-edit live state or `~/.hermes/cron/jobs.json`.
- This directory is not a Git worktree. Verify with `git rev-parse --show-toplevel`, expected failure. Do not fabricate a commit; the implementation handoff must state that the repository boundary prevents one.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `x-post-watch/config/watches.json` | Checked-in profile policy and first `Kutekians` profile. |
| `x-post-watch/bin/models.py` | Immutable profile, source post, media, and outbox event data models. |
| `x-post-watch/bin/config.py` | JSON loading and exact configuration validation. |
| `x-post-watch/bin/rsshub.py` | RSSHub JSON fetch, schema validation, HTML extraction, and item classification. |
| `x-post-watch/bin/render.py` | Safe HTML-to-Discord Markdown conversion, exact headings, footers, and 2,000-character splitting. |
| `x-post-watch/bin/state.py` | Versioned state validation, cursor update, FIFO outbox persistence, file lock, and retry scheduling. |
| `x-post-watch/bin/discord.py` | Secret-safe Discord API v10 text and multipart-media delivery. |
| `x-post-watch/bin/scan.py` | Deterministic orchestration, no-post control, profile isolation, and heartbeat/fatal reporting. |
| `x-post-watch/bin/x-post-watch.sh` | VPS environment loader, fixed runtime Python path, logs, and scanner launcher. |
| `x-post-watch/tests/conftest.py` | Adds `bin/` to imports and provides isolated configuration and state fixtures. |
| `x-post-watch/tests/fixtures/*.json` | RSSHub response fixtures for each item relation and failure boundary. |
| `x-post-watch/tests/test_config.py` | Configuration validation behavior. |
| `x-post-watch/tests/test_rsshub.py` | JSON parsing, classification, HTML/media extraction, and error sanitization. |
| `x-post-watch/tests/test_render.py` | Exact message layout and text splitting behavior. |
| `x-post-watch/tests/test_state.py` | Cursor, FIFO outbox, persistence, lock, and retry behavior. |
| `x-post-watch/tests/test_scan.py` | End-to-end deterministic orchestration, no-post, profile isolation, and heartbeat behavior. |
| `x-post-watch/SKILL.md` | Runtime contract and dry-run environment variables. |
| `x-post-watch/README.md` | Local development, tests, deployment, checksum, and VPS smoke instructions. |
| `x-post-watch/SPEC.md` | Complete operational contract for the runtime. |
| `x-post-watch/CONTEXT.md` | Future-maintainer context, source limitations, and configuration guidance. |
| `README.md` | Root inventory row for `x-post-watch`. |

## Task 1: Scaffold and validate the declarative watch configuration

**Files:**
- Create: `x-post-watch/config/watches.json`
- Create: `x-post-watch/bin/models.py`
- Create: `x-post-watch/bin/config.py`
- Create: `x-post-watch/tests/conftest.py`
- Create: `x-post-watch/tests/test_config.py`

**Interfaces:**
- Produces: `Profile`, `WatchConfig`, and `load_watch_config(path: Path) -> WatchConfig` for all later tasks.
- Produces: `Profile.feed_url` as `http://127.0.0.1:1200/twitter/user/<handle>?format=json`.

- [ ] **Step 1: Create the source directories and first profile configuration**

Run:

```bash
mkdir -p x-post-watch/{bin,config,tests/fixtures}
```

Create `config/watches.json` with version `1` and the approved `kutekians` object:

```json
{
  "version": 1,
  "profiles": [{
    "id": "kutekians",
    "enabled": true,
    "profile_url": "https://x.com/Kutekians",
    "handle": "Kutekians",
    "display_name": "Almer Sad, CFA",
    "emoji": ":kutekians:",
    "discord_channel_id": "1531655369884045382",
    "forward_normal_post": true,
    "forward_quote_post": true,
    "forward_reply": false,
    "forward_repost": false,
    "forward_media": true,
    "max_items_per_poll": 50
  }]
}
```

- [ ] **Step 2: Write failing configuration tests**

Define tests for the valid fixture, duplicate IDs, duplicate case-insensitive handles, malformed `https://x.com/<handle>` URL, empty display name, emoji without colons, non-numeric Discord ID, non-boolean forwarding fields, and `max_items_per_poll` outside `1` to `100`.

```python
def test_load_config_builds_profile_and_feed_url(config_path: Path):
    config = config_module.load_watch_config(config_path)
    profile = config.profiles[0]
    assert profile.id == "kutekians"
    assert profile.feed_url == "http://127.0.0.1:1200/twitter/user/Kutekians?format=json"
```

- [ ] **Step 3: Run the focused configuration test and confirm it fails**

Run from `x-post-watch/`:

```bash
../.venv/bin/python -m pytest -q tests/test_config.py
```

Expected: import or attribute failure because `config.py` and its interfaces do not exist.

- [ ] **Step 4: Implement the immutable configuration models and validator**

Implement the exact public model and loader:

```python
@dataclass(frozen=True)
class Profile:
    id: str
    enabled: bool
    profile_url: str
    handle: str
    display_name: str
    emoji: str
    discord_channel_id: str
    forward_normal_post: bool
    forward_quote_post: bool
    forward_reply: bool
    forward_repost: bool
    forward_media: bool
    max_items_per_poll: int

    @property
    def feed_url(self) -> str: ...

@dataclass(frozen=True)
class WatchConfig:
    version: int
    profiles: tuple[Profile, ...]

def load_watch_config(path: Path) -> WatchConfig: ...
```

Use `json.load`, reject unknown top-level version, require every field above with its exact type, and validate `profile_url == f"https://x.com/{handle}"` case-insensitively for hostname only. Never accept a secret field.

- [ ] **Step 5: Run focused configuration tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_config.py
```

Expected: all configuration tests pass.

## Task 2: Parse and classify RSSHub JSON without additional X requests

**Files:**
- Create: `x-post-watch/bin/rsshub.py`
- Create: `x-post-watch/tests/fixtures/normal.json`
- Create: `x-post-watch/tests/fixtures/quote.json`
- Create: `x-post-watch/tests/fixtures/reply.json`
- Create: `x-post-watch/tests/fixtures/repost.json`
- Create: `x-post-watch/tests/fixtures/ambiguous.json`
- Create: `x-post-watch/tests/test_rsshub.py`
- Modify: `x-post-watch/bin/models.py`

**Interfaces:**
- Consumes: `Profile` from Task 1.
- Produces: `PostKind`, `SourceMedia`, `SourcePost`, `fetch_profile_items(profile: Profile, session: requests.Session) -> list[SourcePost]`, and `is_forwardable(profile: Profile, post: SourcePost) -> bool`.

- [ ] **Step 1: Write fixture-backed failing classification tests**

Each fixture is a minimal RSSHub `?format=json` response with `items`. Model quote and repost relationships using `_extra.links` entries with `type` values `quote` and `repost`; model a direct reply with a `reply` relation. Include one post with unrecognized relation type and one post whose quote relation lacks a URL.

```python
def test_quote_item_keeps_quoted_url_and_is_forwardable(kutekians, quote_payload):
    post = rsshub.parse_feed(quote_payload, kutekians)[0]
    assert post.kind is PostKind.QUOTE
    assert post.quoted_url == "https://x.com/original/status/101"
    assert rsshub.is_forwardable(kutekians, post) is True

def test_reply_item_is_skipped_by_default(kutekians, reply_payload):
    post = rsshub.parse_feed(reply_payload, kutekians)[0]
    assert post.kind is PostKind.REPLY
    assert rsshub.is_forwardable(kutekians, post) is False
```

- [ ] **Step 2: Run RSSHub tests and confirm failure**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_rsshub.py
```

Expected: failure because `rsshub.py` has not been implemented.

- [ ] **Step 3: Implement strict JSON parsing and classification**

Define these types and classify repost before quote, quote before reply, and reply before normal:

```python
class PostKind(StrEnum):
    NORMAL = "normal"
    QUOTE = "quote"
    REPLY = "reply"
    REPOST = "repost"
    AMBIGUOUS = "ambiguous"

@dataclass(frozen=True)
class SourceMedia:
    url: str
    index: int

@dataclass(frozen=True)
class SourcePost:
    profile_id: str
    post_id: str
    url: str
    published_at: datetime
    content_html: str
    kind: PostKind
    quoted_url: str | None
    media: tuple[SourceMedia, ...]
```

Fetch only `profile.feed_url` with a 30-second timeout. Require a JSON object with an `items` list. Derive the stable post ID from `/status/<digits>` in the item URL or ID. Accept only `https://x.com/<handle>/status/<id>` URLs. Use RSSHub `_extra.links` relation types rather than text heuristics whenever present. A relation conflict, missing quote URL, invalid post URL, or unknown relation makes the item `AMBIGUOUS`; it is not forwardable. Extract media URLs only from source-owned `img` and video-poster elements, deduplicate exact URLs, and preserve their first appearance order.

- [ ] **Step 4: Add source failure tests and implement secret-safe errors**

Add tests for `requests.Timeout`, HTTP 401, HTTP 403, non-JSON payload, malformed JSON, and missing `items`. Implement a `SourceFetchError` carrying only a short safe message such as `RSSHub X feed HTTP 403: authentication rejected`. Do not include headers, response body, or request URL query values in exceptions.

- [ ] **Step 5: Run RSSHub tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_rsshub.py
```

Expected: all parsing, classification, media, and error-sanitization tests pass.

## Task 3: Render exact Discord text and durable state transitions

**Files:**
- Create: `x-post-watch/bin/render.py`
- Create: `x-post-watch/bin/state.py`
- Create: `x-post-watch/tests/test_render.py`
- Create: `x-post-watch/tests/test_state.py`

**Interfaces:**
- Consumes: `Profile`, `SourcePost`, and `SourceMedia` from Tasks 1 and 2.
- Produces: `render_post(profile: Profile, post: SourcePost) -> list[str]`, `new_state() -> dict`, `load_state(path: Path) -> dict`, `observe_posts(state: dict, profile: Profile, posts: list[SourcePost]) -> int`, and `next_pending_event(state: dict) -> dict | None`.

- [ ] **Step 1: Write exact rendering tests before implementation**

Add exact assertions for the approved heading and both footer forms, safe conversion of paragraph, strong, emphasis, ordered list, unordered list, and link HTML, escaped Discord control characters, empty source text, and a post whose rendered body needs two text legs.

```python
def test_render_quote_post_exact(kutekians, quote_post):
    assert render.render_post(kutekians, quote_post) == [
        "### :twitter::kutekians: Almer Sad, CFA\n\nMarket note\n\n[(Quoted)](<https://x.com/original/status/101>), [View on X](<https://x.com/Kutekians/status/102>)"
    ]
```

- [ ] **Step 2: Run renderer tests and confirm failure**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_render.py
```

Expected: failure because the renderer does not exist.

- [ ] **Step 3: Implement safe conversion and splitting**

Use `html.parser.HTMLParser`, not a browser or an LLM. Preserve semantic paragraphs, `<br>`, list items, `<strong>`, `<em>`, and safe absolute links. Ignore scripts, styles, images, embedded quote HTML, and unknown tags. Escape Discord control characters in plain text. Build the first leg with:

```python
heading = f"### :twitter:{profile.emoji} {profile.display_name}"
```

Split only at paragraph, sentence, or whitespace boundaries so every message is at most 2,000 characters. Place the heading only in leg one and the exact footer only in the final leg.

- [ ] **Step 4: Write state-transition tests**

Test first observation records current IDs without creating events, later unseen forwardable items enqueue oldest first, skipped kinds advance the cursor but never enqueue, ambiguous items preserve the cursor and return a degraded reason, duplicate IDs do not duplicate events, and a partially delivered event remains first in FIFO order.

```python
def test_first_profile_observation_sets_cursor_without_backfill(empty_state, kutekians, posts):
    queued = state.observe_posts(empty_state, kutekians, posts)
    assert queued == 0
    assert empty_state["profiles"]["kutekians"]["cursor"] == posts[0].post_id
```

- [ ] **Step 5: Implement versioned state, atomic persistence, lock, and retry helpers**

Use state version `1`, a state path set by `X_POST_WATCH_STATE_PATH` or defaulting to `state/state.json`, and an adjacent `run.lock`. Persist with write-to-temporary-file then `os.replace`. Keep a `profiles[profile_id]` cursor record and one globally ordered `outbox` list. Each event contains `event_key`, serialized post, `text_index`, `media_index`, `attempts`, `next_attempt_at`, and `last_error`. Cap exponential retry at 15 minutes; source fetches do not call this retry path.

- [ ] **Step 6: Run renderer and state tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_render.py tests/test_state.py
```

Expected: all exact formatting, cursor, locking, persistence, FIFO, and retry tests pass.

## Task 4: Deliver Discord text and media with stable retry boundaries

**Files:**
- Create: `x-post-watch/bin/discord.py`
- Create: `x-post-watch/tests/test_discord.py`
- Modify: `x-post-watch/bin/state.py`

**Interfaces:**
- Consumes: pending events from Task 3.
- Produces: `DiscordRetryAfter`, `post_text(content: str, channel_id: str, dry_run: bool, nonce: str) -> str | None`, and `post_media(url: str, channel_id: str, dry_run: bool, nonce: str) -> str | None`.

- [ ] **Step 1: Write failing Discord transport tests**

Mock `requests.request` and assert a JSON text request to `/api/v10/channels/<id>/messages`, deterministic 24-character nonce derived from `x-post-watch:<event_key>:text:<index>`, multipart media upload after a successful text leg, 429 propagation, and no network calls in dry run.

```python
def test_media_nonce_is_unique_per_event_leg(monkeypatch):
    assert discord.nonce("kutekians:102", "media:0") != discord.nonce("kutekians:102", "media:1")
```

- [ ] **Step 2: Run Discord tests and confirm failure**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_discord.py
```

Expected: failure because the transport module does not exist.

- [ ] **Step 3: Implement text and media delivery**

Load `DISCORD_BOT_TOKEN` only from the environment. Reject text over 2,000 characters before making a request. Download one media URL with a 30-second timeout into the state media directory, upload it as one Discord attachment, and delete the cached file only after Discord returns a message ID. A text or media 429 raises `DiscordRetryAfter(retry_after)`. Other errors return `None` or raise a sanitized `RuntimeError`; neither path logs tokens or raw response bodies.

- [ ] **Step 4: Add partial-delivery and error tests**

Test that a text success persists its returned ID before any media request, failed media retries only that media leg, a 429 schedules the exact retry delay, a failed download is sanitized, and an unavailable token does not call Discord.

- [ ] **Step 5: Run Discord tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_discord.py tests/test_state.py
```

Expected: all transport and partial-delivery tests pass.

## Task 5: Orchestrate profiles, heartbeat, dry run, and the runtime wrapper

**Files:**
- Create: `x-post-watch/bin/scan.py`
- Create: `x-post-watch/bin/x-post-watch.sh`
- Create: `x-post-watch/tests/test_scan.py`
- Modify: `x-post-watch/tests/conftest.py`

**Interfaces:**
- Consumes: all modules from Tasks 1 through 4.
- Produces: `run(now: datetime, dry_run: bool) -> int`, `format_heartbeat(now: datetime, stats: RunStats) -> str`, and `format_fatal(now: datetime, reason: str) -> str`.

- [ ] **Step 1: Write failing orchestration tests**

Mock RSSHub and Discord modules. Cover two enabled profiles where one gets HTTP 403 and the other posts successfully, no-hit run heartbeat, source failure leaving its cursor unchanged, ambiguous item degrading the heartbeat, text then two media legs, dry run producing no Discord calls, and one failed lock acquisition exiting quietly without a heartbeat.

```python
def test_one_failed_profile_does_not_block_another(tmp_state, monkeypatch, now):
    posts = []
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", fake_profile_fetch)
    monkeypatch.setattr(scan.discord, "post_text", capture_text)
    assert scan.run(now, dry_run=False) == 0
    assert any("RSSHub X feed HTTP 403: authentication rejected" in line for line in posts)
```

- [ ] **Step 2: Run orchestration tests and confirm failure**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_scan.py
```

Expected: failure because `scan.py` does not exist.

- [ ] **Step 3: Implement deterministic run order and heartbeat**

Run under a non-blocking `fcntl.flock`. Load configuration and state, process enabled profiles in configuration order, observe each profile after a successful fetch, deliver the globally oldest due outbox event until none remains, then send exactly one direct Discord heartbeat to `1505162000420835388`.

Use these names and forms:

```python
WATCHER_HEARTBEAT_NAME = "x-post"

def format_heartbeat(now: datetime, stats: RunStats) -> str:
    return f"🫀 x-post · {now.astimezone(WIB):%H:%M} WIB · {stats.tokens()}" + (" ⚠️" if stats.degraded else "")

def format_fatal(now: datetime, reason: str) -> str:
    return f"❌ x-post · {now.astimezone(WIB):%H:%M} WIB · failed: {sanitize(reason)}"
```

`X_POST_WATCH_NO_POST=1` must route all Discord calls through dry-run output and `X_POST_WATCH_FORCE_HEARTBEAT=1` must retain a heartbeat in that output. The normal run should emit no stdout so Hermes has no duplicate alert payload to deliver.

- [ ] **Step 4: Implement the Bash wrapper**

Mirror the Swing Watch wrapper: set `TZ=Asia/Jakarta`, load only `DISCORD_BOT_TOKEN` from `~/.hermes/.env`, use `${X_POST_WATCH_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}`, run `$HOME/.agents/skills/x-post-watch/bin/scan.py`, and append timestamped stderr and exit status to `$HOME/.logs/x-post-watch.log`. The wrapper must not print secrets.

- [ ] **Step 5: Run the full local suite**

Run from `x-post-watch/`:

```bash
../.venv/bin/python -m pytest -q
```

Expected: all suites pass, with no network calls because transport and source boundaries are mocked.

## Task 6: Write the in-folder handoff documentation and update inventory

**Files:**
- Create: `x-post-watch/SKILL.md`
- Create: `x-post-watch/README.md`
- Create: `x-post-watch/SPEC.md`
- Create: `x-post-watch/CONTEXT.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: final runtime and environment names from Tasks 1 through 5.
- Produces: enough operational context for a future agent to safely test, deploy, diagnose, and extend a profile without reverse-engineering the scanner.

- [ ] **Step 1: Write `SKILL.md` as the concise runtime contract**

Include front matter `name: x-post-watch`, `user-invocable: false`, the 24-hour no-agent schedule, source route, alert and heartbeat channel IDs, no-LLM guarantee, and these dry-run variables:

```text
X_POST_WATCH_NO_POST=1
X_POST_WATCH_STATE_PATH=/tmp/x-post-watch-state.json
X_POST_WATCH_CONFIG_PATH=/tmp/x-post-watch-watches.json
X_POST_WATCH_FORCE_HEARTBEAT=1
```

- [ ] **Step 2: Write `README.md` and `CONTEXT.md` for a future maintainer**

Document the exact local test command, `./deploy.sh x-post-watch`, separate SKILL/config synchronization, checksum comparison, VPS no-post command, source versus state ownership, and the rule that profile additions are reviewed JSON edits with no state backfill. Explain that `TWITTER_AUTH_TOKEN` stays only in VPS RSSHub configuration and that HTTP 401/403 indicates auth trouble without exposing credentials.

- [ ] **Step 3: Write `SPEC.md` as the full behavioral contract**

Include every configuration field, relation classification order, exact Discord formats, 2,000-character continuation rules, media order, cursor/outbox state schema, retry rules, error sanitization, heartbeat and fatal formats, test matrix, and deployment verification requirements. Do not copy a token, cookie, or live state value.

- [ ] **Step 4: Add the root inventory row**

Add `x-post-watch` to the root README table with description `Configuration-driven RSSHub X post forwarder` and `tests yes; live source and Discord no-post smoke run on the VPS` in the Mac-runnable column.

- [ ] **Step 5: Review documentation consistency**

Run:

```bash
rg -n 'idx-swing-watch-phintraco-daily|TODO|TBD|TWITTER_AUTH_TOKEN=' x-post-watch README.md
```

Expected: no copied Swing-specific identity, no placeholder language, and no secret assignment.

## Task 7: Deploy safely, register the approved hourly cron, and prove the live no-post path

**Files:**
- Create on VPS after first-write confirmation: `~/.agents/skills/x-post-watch/{bin,config}/`
- Create on VPS after first-write confirmation: `~/.hermes/scripts/x-post-watch.sh`
- Create on VPS after first-write confirmation: Hermes cron job named `x-post-watch`

**Interfaces:**
- Consumes: passing local source and documentation from Tasks 1 through 6.
- Produces: a live VPS runtime matching reviewed local source, plus an active hourly no-agent Hermes cron.

- [ ] **Step 1: Confirm the pre-deployment state and prepare the exact remote diff**

Run read-only checks:

```bash
ssh vps 'test ! -e ~/.agents/skills/x-post-watch && echo runtime-absent'
ssh vps 'test ! -e ~/.hermes/scripts/x-post-watch.sh && echo wrapper-absent'
ssh vps '$HOME/.local/bin/hermes cron list'
```

Compare every local source file with its prospective remote path. Because this is the first VPS write in the chat, present the exact file list and request confirmation immediately before writing.

- [ ] **Step 2: Create runtime directories and copy reviewed source after confirmation**

Use the project deployer for executable files:

```bash
./deploy.sh x-post-watch
```

Then separately synchronize reviewed non-`bin/` runtime artifacts:

```bash
ssh vps 'mkdir -p ~/.agents/skills/x-post-watch/config ~/.hermes/scripts'
rsync -a x-post-watch/SKILL.md x-post-watch/README.md x-post-watch/SPEC.md x-post-watch/CONTEXT.md vps:.agents/skills/x-post-watch/
rsync -a x-post-watch/config/watches.json vps:.agents/skills/x-post-watch/config/watches.json
rsync -a x-post-watch/bin/x-post-watch.sh vps:.hermes/scripts/x-post-watch.sh
ssh vps 'chmod 755 ~/.hermes/scripts/x-post-watch.sh'
```

Do not copy any local state directory. Do not touch the dotfiles mirror.

- [ ] **Step 3: Verify deployed checksums before creating the scheduler entry**

Run for every Python module and wrapper:

```bash
for file in x-post-watch/bin/*; do
  base="$(basename "$file")"
  local_sum="$(shasum -a 256 "$file" | awk '{print $1}')"
  remote_sum="$(ssh vps "shasum -a 256 ~/.agents/skills/x-post-watch/bin/$base | awk '{print \\$1}'")"
  test "$local_sum" = "$remote_sum"
done
```

Also compare `SKILL.md`, `README.md`, `SPEC.md`, `CONTEXT.md`, and `config/watches.json` with `shasum -a 256` before proceeding.

- [ ] **Step 4: Run the VPS no-post smoke with isolated state**

Run:

```bash
ssh vps 'X_POST_WATCH_NO_POST=1 X_POST_WATCH_STATE_PATH=/tmp/x-post-watch-state.json X_POST_WATCH_FORCE_HEARTBEAT=1 ~/.hermes/scripts/x-post-watch.sh'
```

Expected: it reaches the RSSHub user route, reports sanitized intended Discord text and media operations plus an intended heartbeat, posts nothing to Discord, and does not read or modify live state. Remove only the explicit `/tmp/x-post-watch-state.json` after inspecting it.

- [ ] **Step 5: Register the approved no-agent hourly Hermes cron**

Run exactly:

```bash
ssh vps '$HOME/.local/bin/hermes cron create "0 * * * *" --name x-post-watch --deliver discord:1505162000420835388 --script ~/.hermes/scripts/x-post-watch.sh --no-agent --workdir /home/praya'
```

Then verify the created entry shows `Schedule: 0 * * * *`, `Mode: no-agent`, `Deliver: discord:1505162000420835388`, `Script: x-post-watch.sh`, and an `Asia/Jakarta` next-run timestamp:

```bash
ssh vps '$HOME/.local/bin/hermes cron list'
```

- [ ] **Step 6: Report verified completion without claiming an unobserved scheduled run**

Report the focused and full pytest results, deployed checksums, the no-post output summary, cron ID and next run, and that no live state was edited or external alert posted. Do not claim the future scheduled execution has occurred.
