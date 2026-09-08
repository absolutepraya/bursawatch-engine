# Instagram Post Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `instagram-post-watch`, an authenticated RSSHub-backed Hermes watcher that monitors public Instagram posts and reels, OCRs every image asset, selectively supplies uncertain assets to the LLM, and delivers relevant source-grounded analysis and original media to Discord.

**Architecture:** The watcher is an independent agent-backed cron with the same durable cursor, outbox, bounded agent lease, strict submission, Discord delivery, and heartbeat pattern as `x-post-watch`. Its deterministic scanner fetches one RSSHub Instagram feed per profile, downloads and caches publication media, samples reel frames, runs an interchangeable OCR backend, chooses `text_only`, `vision_partial`, or `vision_full`, then wakes Hermes with one bounded event containing OCR text and local vision paths when required.

**Tech Stack:** Python 3 standard library, `requests`, pytest, RSSHub JSON, Tesseract or PaddleOCR Mobile selected by VPS benchmark, host `ffmpeg` and `ffprobe` for reel sampling, Discord API v10, Bash, Hermes cron.

**Spec:** `docs/superpowers/specs/2026-08-24-instagram-post-watch-design.md`

## Global Constraints

- Watch public Instagram posts and reels only. Exclude stories, comments, tagged posts, mentions, live broadcasts, and private-account monitoring.
- Use the isolated Instagram RSSHub web API route `http://127.0.0.1:1201/instagram/2/user/<handle>?format=json`; direct Instagram scraping and alternate production fetchers are out of scope.
- Keep Instagram credentials in VPS RSSHub service configuration only. Never place credentials, cookies, signed URLs, or raw provider bodies in source, logs, tests, payloads, or commits.
- Run OCR for every downloaded image and every sampled reel frame, including assets later supplied to the LLM.
- Use `text_only` when OCR is complete and sufficient, `vision_partial` for failed or uncertain assets, and `vision_full` when the publication needs complete visual context.
- Keep local media and sampled frames under runtime state until delivery completes. Never edit or capture live state as source.
- Use an isolated VPS OCR environment. Never add OCR dependencies to the shared Yahoo Finance Python environment.
- Reuse the X watcher's relevance, promotion exclusion, Indonesian title and summary, central-thesis routing, lease, delivery, heartbeat, and no-backfill boundaries.
- Use `macro` and `id_stock` as the first profile's only destination keys. Do not invent custom Discord emoji.
- Use the `instagram-post` heartbeat name and `#hermes` channel `1505162000420835388`.
- The intended Hermes cadence is `*/15 * * * *` in `Asia/Jakarta`, but local source work does not register or change a live cron.
- Do not edit `~/.dotfiles/vps/agents/skills/`. It is a backup mirror from the VPS, not an authoring target.
- Do not modify `~/.hermes/cron/jobs.json` by hand. Use the supported Hermes CLI only after explicit operational approval.
- The implementation starts in an isolated worktree created through the `wt` workflow at execution time. Do not edit the current worktree during implementation.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `instagram-post-watch/AGENTS.md` | Development, source, credential, deployment, and domain contract for the new agent-backed cron. |
| `instagram-post-watch/SKILL.md` | Concise Hermes runtime prompt, including OCR context, local vision paths, exact submission, and no-direct-post boundaries. |
| `instagram-post-watch/config/watches.json` | Strictly reviewed watched-profile and OCR policy for `beyondthefundamental`. |
| `instagram-post-watch/bin/models.py` | Immutable profile, publication, media, downloaded-asset, OCR, vision-decision, and channel models. |
| `instagram-post-watch/bin/config.py` | Exact JSON schema validation and RSSHub feed URL construction. |
| `instagram-post-watch/bin/rsshub.py` | Authenticated RSSHub fetch, Instagram publication parsing, stable IDs, media extraction, and post/reel filtering. |
| `instagram-post-watch/bin/media.py` | Bounded media downloads, SHA-256 hashing, reel frame sampling, local asset cleanup, and media metadata serialization. |
| `instagram-post-watch/bin/ocr.py` | OCR backend protocol, Tesseract and PaddleOCR adapters, bounded output, and cache handling. |
| `instagram-post-watch/bin/vision_gate.py` | Deterministic `text_only`, `vision_partial`, and `vision_full` decision logic and selected asset paths. |
| `instagram-post-watch/bin/agent_protocol.py` | Bounded wake payload, caption plus OCR context, local vision paths, relevance rules, and exact analysis submission validation. |
| `instagram-post-watch/bin/state.py` | Versioned cursor, publication outbox, OCR and media references, delivery legs, filtered count, and agent leases. |
| `instagram-post-watch/bin/render.py` | Caption and analysis rendering, Instagram source links, safe Markdown, and Discord length splitting. |
| `instagram-post-watch/bin/discord.py` | Secret-safe Discord API v10 text and local-media upload operations. |
| `instagram-post-watch/bin/scan.py` | Locking, source observation, asset preparation, OCR, queueing, delivery, heartbeat, agent claim, and submission drain. |
| `instagram-post-watch/bin/instagram-post-watch.sh` | VPS environment loader, selected OCR Python path, scanner launcher, log path, and `submit-analysis` entry point. |
| `instagram-post-watch/tools/benchmark_ocr.py` | VPS-only comparison runner for Tesseract and PaddleOCR using isolated sample images. |
| `instagram-post-watch/tests/conftest.py` | Script-local import path and isolated profile, publication, OCR, and state fixtures. |
| `instagram-post-watch/tests/fixtures/*.json` | RSSHub publication, carousel, reel, private-account, and malformed-source fixtures. |
| `instagram-post-watch/tests/test_config.py` | Strict profile and OCR configuration behavior. |
| `instagram-post-watch/tests/test_rsshub.py` | RSSHub parsing, stable IDs, media order, public-only filtering, and safe source errors. |
| `instagram-post-watch/tests/test_media.py` | Image/video download, hashing, reel frame sampling, size limits, and cleanup. |
| `instagram-post-watch/tests/test_ocr.py` | Backend adapter, bounded text, cache keys, language mapping, and failures. |
| `instagram-post-watch/tests/test_vision_gate.py` | Every vision mode and asset-selection branch. |
| `instagram-post-watch/tests/test_agent_protocol.py` | Exact wake payload, local path handling, relevance guards, and submission validation. |
| `instagram-post-watch/tests/test_state.py` | Cursor, outbox, media/OCR persistence, delivery legs, lease expiry, and no-backfill behavior. |
| `instagram-post-watch/tests/test_render.py` | Exact heading, title, summary, caption, source link, and splitting behavior. |
| `instagram-post-watch/tests/test_scan.py` | End-to-end deterministic orchestration, heartbeats, no-post state isolation, and agent submission. |
| `README.md` | Root cron inventory row for `instagram-post-watch`. |
| `AGENTS.md` | Root child-project list and agent-backed cron classification. |
| `tests/test_documentation_contract.py` | Reviewed cron classification and governance anchors for the new cron. |
| `scripts/test-all` | Complete-suite invocation for the new watcher tests. |

## Task 1: Scaffold the strict profile and normalized publication models

**Files:**
- Create: `instagram-post-watch/config/watches.json`
- Create: `instagram-post-watch/bin/models.py`
- Create: `instagram-post-watch/bin/config.py`
- Create: `instagram-post-watch/tests/conftest.py`
- Create: `instagram-post-watch/tests/test_config.py`

**Interfaces:**
- Produces `Profile`, `DiscordChannel`, `SourcePost`, `SourceMedia`, `PublicationKind`, and `MediaKind` models for later tasks.
- Produces `load_watch_config(path: Path) -> WatchConfig`.
- Produces `Profile.feed_url`, exactly `http://127.0.0.1:1201/instagram/2/user/<handle>?format=json`.

- [ ] **Step 1: Create the source directories and approved first profile fixture**

Run:

```bash
mkdir -p instagram-post-watch/bin instagram-post-watch/config instagram-post-watch/tests/fixtures instagram-post-watch/tools
```

Write `config/watches.json` with the exact profile from the approved design: `beyondthefundamental`, source `rsshub`, public profile URL, platform emoji `📸`, empty account emoji, `macro` and `id_stock` channels, all post/reel/media forwarding enabled, all four LLM switches enabled, OCR languages `ind` and `eng`, confidence `0.70`, maximum five reel frames, and a per-poll cap of `20`.

- [ ] **Step 2: Write failing configuration tests**

Add tests for valid parsing, exact RSSHub URL, duplicate IDs, case-insensitive duplicate handles, wrong Instagram host, query or fragment in `profile_url`, invalid username characters, missing required fields, unknown fields, duplicate channel keys, invalid Discord snowflakes, one channel with routing enabled, invalid OCR language, confidence outside `0` to `1`, reel frames outside `1` to `8`, and per-poll limits outside `1` to `100`.

```python
def test_load_config_builds_instagram_feed_url(config_path):
    profile = config_module.load_watch_config(config_path).profiles[0]
    assert profile.handle == "beyondthefundamental"
    assert profile.feed_url == (
        "http://127.0.0.1:1201/instagram/2/user/"
        "beyondthefundamental?format=json"
    )
```

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run:

```bash
cd instagram-post-watch
../.venv/bin/python -m pytest -q tests/test_config.py
```

Expected: import or attribute failures because the new models and loader are not implemented.

- [ ] **Step 4: Implement the immutable models and exact validator**

Define these public fields:

```python
@dataclass(frozen=True)
class Profile:
    id: str
    enabled: bool
    source: str
    profile_url: str
    handle: str
    display_name: str
    platform_emoji: str
    emoji: str
    discord_channels: tuple[DiscordChannel, ...]
    forward_post: bool
    forward_reel: bool
    forward_media: bool
    enable_llm_title: bool
    enable_llm_summary: bool
    enable_llm_routing: bool
    enable_llm_relevance_filter: bool
    additional_prompt_instruction: str
    max_items_per_poll: int
    ocr_languages: tuple[str, ...]
    ocr_min_confidence: float
    max_reel_frames: int

    @property
    def feed_url(self) -> str: ...

    @property
    def uses_llm(self) -> bool: ...

    def channel_for(self, key: str) -> DiscordChannel: ...
```

Accept `https://instagram.com/<handle>` and `https://www.instagram.com/<handle>` without a query, fragment, parameters, extra path, or trailing slash. Accept handles matching `[A-Za-z0-9._]{1,30}`. Require `source == "rsshub"`, non-empty `platform_emoji`, and allow `emoji == ""`. Require `macro` and `id_stock` channels when routing is enabled. Reject unknown keys at every object boundary.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_config.py
```

Expected: all configuration tests pass.

## Task 2: Parse RSSHub publications and prepare ordered media

**Files:**
- Modify: `instagram-post-watch/bin/models.py`
- Create: `instagram-post-watch/bin/rsshub.py`
- Create: `instagram-post-watch/bin/media.py`
- Create: `instagram-post-watch/tests/fixtures/image-post.json`
- Create: `instagram-post-watch/tests/fixtures/carousel-post.json`
- Create: `instagram-post-watch/tests/fixtures/reel-post.json`
- Create: `instagram-post-watch/tests/fixtures/private-profile.json`
- Create: `instagram-post-watch/tests/fixtures/malformed-feed.json`
- Create: `instagram-post-watch/tests/test_rsshub.py`
- Create: `instagram-post-watch/tests/test_media.py`

**Interfaces:**
- Consumes `Profile` from Task 1.
- Produces `fetch_profile_items(profile: Profile, session: requests.Session | None = None, after_id: str | None = None) -> list[SourcePost]`.
- Produces `parse_feed(payload: object, profile: Profile) -> list[SourcePost]`.
- Produces `is_forwardable(profile: Profile, post: SourcePost) -> bool`.
- Produces `download_publication(post: SourcePost, root: Path, session: requests.Session, limits: DownloadLimits) -> DownloadedPublication`.
- Produces `sample_reel_frames(video_path: Path, cover_path: Path, root: Path, max_frames: int) -> tuple[DownloadedAsset, ...]`.

- [ ] **Step 1: Write RSSHub fixture tests for publication identity and media order**

Create fixtures using RSSHub JSON `items` with `url`, `date_published`, `title` or `content_html`, and the route's media markup. Cover one image, a four-image sidecar, a reel video with poster, an item with explicit private metadata, and malformed relation or URL data.

```python
def test_carousel_preserves_source_order(configured_profile, carousel_payload):
    post = rsshub.parse_feed(carousel_payload, configured_profile)[0]
    assert post.kind is PublicationKind.POST
    assert [asset.index for asset in post.media] == [0, 1, 2, 3]
    assert [asset.kind for asset in post.media] == [MediaKind.IMAGE] * 4

def test_reel_is_forwardable_when_reels_are_enabled(configured_profile, reel_payload):
    post = rsshub.parse_feed(reel_payload, configured_profile)[0]
    assert post.kind is PublicationKind.REEL
    assert rsshub.is_forwardable(configured_profile, post) is True
```

- [ ] **Step 2: Run source tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_rsshub.py tests/test_media.py
```

Expected: failures because the Instagram source and media modules do not exist.

- [ ] **Step 3: Implement strict RSSHub parsing**

Define `PublicationKind` values `POST` and `REEL`, and `MediaKind` values `IMAGE` and `VIDEO`. Extract a stable publication ID from RSSHub metadata, then `/p/<shortcode>/` or `/reel/<shortcode>/` URL paths. Reject any item without a stable identity or an exact Instagram publication URL. Strip media tags from `caption_html` while preserving caption text and links. Extract `img` and `video` sources in document order, deduplicate exact URLs, and assign source indexes.

Reject explicitly private targets, malformed items, story or live URLs, and unsupported publication types with a sanitized `SourceFetchError` or a filtered result. Do not use CDN URLs as IDs. `fetch_profile_items` makes one request with a 30-second timeout, requires a JSON object with an `items` list, and never includes response bodies or authentication data in exceptions.

- [ ] **Step 4: Implement bounded media downloads and reel sampling**

Define:

```python
@dataclass(frozen=True)
class DownloadLimits:
    max_asset_bytes: int = 25 * 1024 * 1024
    max_publication_bytes: int = 128 * 1024 * 1024
    timeout_seconds: int = 30

@dataclass(frozen=True)
class DownloadedPublication:
    assets: tuple[DownloadedAsset, ...]
    media_root: Path
```

Stream each image or video into a temporary file, enforce per-asset and per-publication byte limits, validate the content type, atomically rename into the event media directory, calculate SHA-256, and preserve source order. Use `ffprobe` to obtain reel duration and `ffmpeg` to create the cover plus evenly spaced frames up to the profile cap. A frame-generation failure marks the reel vision path degraded but preserves the original video for delivery.

- [ ] **Step 5: Add download, size, sampling, and cleanup tests**

Use fake HTTP responses and a fake `ffmpeg` runner. Prove that hashes are stable, oversized assets are rejected without a partial final file, source order is preserved, a reel produces at most five analysis frames including the cover, and cleanup removes only the event's managed directory.

- [ ] **Step 6: Run source and media tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_rsshub.py tests/test_media.py
```

Expected: all source and media tests pass.

## Task 3: Implement OCR backends, caching, and the deterministic vision gate

**Files:**
- Create: `instagram-post-watch/bin/ocr.py`
- Create: `instagram-post-watch/bin/vision_gate.py`
- Create: `instagram-post-watch/tests/test_ocr.py`
- Create: `instagram-post-watch/tests/test_vision_gate.py`

**Interfaces:**
- Consumes `DownloadedAsset`, `Profile`, and media limits from Tasks 1 and 2.
- Produces `OCRBackend`, `OCRResult`, `build_backend(engine: str | None = None) -> OCRBackend`, `extract_cached(...) -> OCRResult`, and `cache_key(...) -> str`.
- Produces `decide_vision_mode(caption_text: str, assets: tuple[DownloadedAsset, ...], results: tuple[OCRResult, ...], profile: Profile) -> VisionDecision`.

- [ ] **Step 1: Write failing OCR result and cache tests**

Cover successful text extraction, blank no-text results, backend errors, bounded per-asset and total text, cache-key changes for image hash, engine ID, model version, languages, and preprocessing version, and rejection of an unrecognized engine.

```python
def test_cache_key_changes_when_engine_changes():
    tesseract = ocr.cache_key("abc", "tesseract:5.3", ("ind", "eng"), "preprocess-1")
    paddle = ocr.cache_key("abc", "paddleocr:pp-ocrv5-mobile", ("ind", "eng"), "preprocess-1")
    assert tesseract != paddle
```

- [ ] **Step 2: Write failing vision-gate tests for every mode**

Use fake assets and results to prove:

1. complete high-confidence OCR with sufficient caption plus OCR returns `text_only` and no vision paths;
2. one OCR timeout returns `vision_partial` with only that asset path;
3. one low-confidence text asset returns `vision_partial`;
4. two uncertain assets return `vision_full` with all publication image paths;
5. sparse caption plus blank OCR returns `vision_full`;
6. a caption mentioning a chart, table, diagram, or “see slide” returns `vision_full`;
7. blank OCR with a sufficiently descriptive caption remains `text_only`;
8. reel decisions select sampled frame paths, never the original video path, for vision analysis.

- [ ] **Step 3: Run OCR and gate tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_ocr.py tests/test_vision_gate.py
```

Expected: failures because no OCR backend or gate exists.

- [ ] **Step 4: Implement the backend protocol and Tesseract adapter**

Define:

```python
class OCRBackend(Protocol):
    @property
    def engine_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def extract(self, path: Path, languages: tuple[str, ...]) -> OCRResult: ...
```

The Tesseract adapter invokes the binary with TSV output, maps `ind` and `eng` language names to installed trained-data names, parses line confidence, joins recognized words in reading order, and returns a safe status without leaking command output. The PaddleOCR adapter imports lazily from the isolated selected runtime, maps `ind` to its Indonesian model and `eng` to English or Latin support, and normalizes its line results into the same `OCRResult` shape. Missing binaries or packages raise `OCRBackendUnavailable` with a sanitized message.

Normalize whitespace, cap each asset at 4,000 characters and the publication aggregate at 16,000 characters, and preserve the highest-confidence line information needed by the gate. A blank result has status `no_text`; an exception or timeout has status `error`.

- [ ] **Step 5: Implement cache lookup and the three-mode gate**

Cache successful and blank OCR results by `sha256 + engine_id + model_version + languages + preprocessing_version`. Never cache a backend error as a successful result. Implement the v1 gate constants in one module: minimum aggregate context `80` characters, the approved caption visual-reference patterns, and the configured confidence threshold. Treat “no text detected” as valid unless combined caption and OCR context is too sparse.

Return a `VisionDecision` with `mode`, `reason`, and ordered `asset_ids`. For `vision_partial`, select only failed or uncertain assets. For `vision_full`, select every image or sampled reel frame. Never select a reel's original video for the vision payload.

- [ ] **Step 6: Run OCR and gate tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_ocr.py tests/test_vision_gate.py
```

Expected: all OCR and gate tests pass without requiring Tesseract or PaddleOCR in the local development environment because tests use injected fake backends.

## Task 4: Benchmark and select the VPS OCR backend

**Files:**
- Create: `instagram-post-watch/tools/benchmark_ocr.py`

**Interfaces:**
- Consumes a scratch directory of real downloaded carousel images and the Task 3 `OCRBackend` interface.
- Produces a JSON report containing engine ID, model version, language set, per-image latency, total latency, peak RSS, status, character count, confidence, and manually supplied accuracy notes.

- [ ] **Step 1: Add the benchmark command interface**

Implement:

```bash
benchmark_dir="/tmp/instagram-post-watch-ocr-benchmark"
python tools/benchmark_ocr.py --input-dir "$benchmark_dir/images" --output "$benchmark_dir/tesseract.json" --engine tesseract
python tools/benchmark_ocr.py --input-dir "$benchmark_dir/images" --output "$benchmark_dir/paddleocr.json" --engine paddleocr
```

The command processes every image in lexical order, never writes to watcher state, never posts Discord, and exits nonzero on an unavailable requested engine. It records only paths relative to the supplied scratch directory.

- [ ] **Step 2: Perform the VPS preflight without mutating runtime state**

From a VPS-local agent, record that `/usr/bin/ffmpeg` and `/usr/bin/ffprobe` are available, confirm the current CPU, memory, disk, and absence of a GPU, and create a dedicated scratch directory outside the deployed watcher state. Do not use the shared Yahoo Finance Python environment.

- [ ] **Step 3: Obtain approval before the first VPS dependency write**

Before installing anything, show the exact proposed package and environment diff. The approved installation boundary is:

```text
system Tesseract binary plus English and Indonesian trained data
isolated watcher-owned PaddleOCR CPU environment under ~/.local/share/
```

Do not modify `~/rsshub`, Hermes, or the live watcher state during this benchmark task.

- [ ] **Step 4: Capture representative public-account samples**

Using the authenticated RSSHub route and a new scratch state path, capture several current `beyondthefundamental` carousels and one reel if available. Keep the source images outside Git and delete the scratch directory after the report is reviewed.

- [ ] **Step 5: Run both engines and apply the selection rule**

Run both benchmark commands. Manually compare extracted text against every text-bearing slide. Select the engine with the highest complete text-block recovery; when recovery is equivalent, select the lower median per-image latency and lower peak RSS. Record the selected engine ID and model version in the deployment handoff and set `INSTAGRAM_POST_WATCH_OCR_ENGINE` to that value for the first runtime.

- [ ] **Step 6: Preserve the benchmark report outside source control**

Keep the report as operational evidence only. Do not add model caches, downloaded media, benchmark images, or raw account content to the repository.

## Task 5: Add durable publication state and bounded agent leases

**Files:**
- Create: `instagram-post-watch/bin/state.py`
- Create: `instagram-post-watch/tests/test_state.py`

**Interfaces:**
- Consumes the models, prepared assets, OCR results, and vision decision from Tasks 1 to 3.
- Produces `new_state() -> dict`, `load_state(path: Path) -> dict`, `save_state(path: Path, value: dict) -> None`, `serialize_post`, `deserialize_post`, `observe_publications(value, profile, publications, now, prepare_event)`, `claim_oldest_agent`, `awaiting_analysis_event`, `submit_analysis`, `discard_analysis`, and `is_ready`.

- [ ] **Step 1: Write failing state tests**

Test state version `1`, first observation cursor initialization without queueing, later unseen publication queueing in chronological order, duplicate suppression by `profile_id:publication_id`, disabled-profile behavior, serialized OCR and media paths, independent text and media indexes, delivery ledger retention, filtered count, and 15-minute lease expiry.

```python
def test_first_observation_initializes_cursor_without_backfill(tmp_path, configured_profile, publication):
    value = state.new_state()
    created = state.observe_publications(value, configured_profile, [publication], now=NOW, prepare_event=lambda item: {"post": item})
    assert created == 0
    assert value["profiles"][configured_profile.id]["cursor"] == publication.publication_id
    assert value["outbox"] == []
```

- [ ] **Step 2: Run state tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_state.py
```

Expected: import or missing-function failures.

- [ ] **Step 3: Implement versioned state and atomic persistence**

Use the X watcher's state discipline: create parent directories, load a missing state as `new_state`, reject incompatible state versions, write through a temporary sibling file, flush and replace atomically, and never migrate or reset an existing live state implicitly. Store the event's serialized publication, downloaded assets, OCR results, vision mode, selected local paths, `agent_phase`, `agent_lease_until`, `text_index`, `media_index`, returned Discord IDs, last error, and delivery timestamp.

- [ ] **Step 4: Implement observation, lease, and submission transitions**

`observe_publications` must initialize a missing profile cursor to the newest returned publication without queueing historical content. For an initialized profile, queue only IDs newer than its cursor and update the cursor only after source observation succeeds. `claim_oldest_agent` expires leases before claiming one ready event for a profile with LLM enabled. `submit_analysis` accepts only the matching active lease and changes the event to `ready`; `discard_analysis` removes only that event and increments the filtered counter.

- [ ] **Step 5: Run state tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_state.py
```

Expected: all state and lease tests pass.

## Task 6: Build the strict agent protocol and runtime skill

**Files:**
- Create: `instagram-post-watch/bin/agent_protocol.py`
- Create: `instagram-post-watch/SKILL.md`
- Create: `instagram-post-watch/tests/test_agent_protocol.py`

**Interfaces:**
- Consumes `Profile`, `SourcePost`, serialized OCR results, vision decisions, and active local asset paths.
- Produces `agent_item(profile: Profile, event: dict) -> dict`, `build_wake_payload(item)`, `validate_submission(profile, payload)`, `instruction_for(profile, relevance_guard_required)`, `is_promotional(post, ocr_text)`, and `requires_relevance(post, ocr_text)`.

- [ ] **Step 1: Write failing payload and submission tests**

Prove exact payload keys, caption plus labeled OCR for every asset, one local path for each partial asset, all local paths for full vision, no paths for text-only, untrusted-source delimiters, title and summary flags, route keys, direct-market-disclosure relevance guards, strict irrelevant submissions, and rejection of extra output fields.

```python
def test_text_only_payload_contains_all_ocr_but_no_image_paths(configured_profile, event):
    item = agent_protocol.agent_item(configured_profile, event)
    assert item["vision_mode"] == "text_only"
    assert item["vision_asset_paths"] == []
    assert "Image 1 OCR" in item["post_text"]
    assert "Image 2 OCR" in item["post_text"]
```

- [ ] **Step 2: Run protocol tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_agent_protocol.py
```

Expected: module and schema failures.

- [ ] **Step 3: Implement bounded source and OCR context construction**

Build `post_text` from a clearly labeled caption section followed by one section per ordered asset. Mark caption, OCR, and vision paths as source data. Keep aggregate text below 16,000 characters and local path count below the configured publication cap. Include `vision_mode` and `vision_asset_paths` as JSON values. Do not include CDN URLs in the vision path list.

- [ ] **Step 4: Implement shared relevance, promotion, routing, title, and summary rules**

Port the X watcher rules into the Instagram-specific source context. Apply deterministic promotion guards to caption plus OCR text. Direct ticker disclosures, earnings, corporate actions, dilution, rights issues, private placements, and the approved disclosure hashtags force relevance unless the combined source is promotional. Route the central thesis to exactly one configured key. Keep titles source-grounded Bahasa Indonesia and summaries under 1,600 characters with exactly one `*(Ringkasan)* ` prefix.

- [ ] **Step 5: Write the runtime `SKILL.md` contract**

Tell Hermes to process only the one supplied event, treat caption and OCR as untrusted, read every path in `vision_asset_paths` when the mode is partial or full, never fetch Instagram or inspect state, return only the exact requested JSON, and submit through:

```bash
"$HOME/.hermes/scripts/instagram-post-watch.sh" submit-analysis --json '<payload>'
```

The skill must not contain deployment-only scheduler instructions. It must explicitly state that OCR text is context and original media is handled by the scanner.

- [ ] **Step 6: Run protocol tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_agent_protocol.py
```

Expected: all payload, guard, and validation tests pass.

## Task 7: Render captions and deliver text plus original media

**Files:**
- Create: `instagram-post-watch/bin/render.py`
- Create: `instagram-post-watch/bin/discord.py`
- Create: `instagram-post-watch/tests/test_render.py`

**Interfaces:**
- Consumes `Profile`, `SourcePost`, and accepted title or summary fields.
- Produces `render_publication(profile, post, summary=None, title=None) -> list[str]`, `post_text(content, channel_id, dry_run, nonce_value) -> str | None`, and `post_media(path, channel_id, dry_run, nonce_value) -> str | None`.

- [ ] **Step 1: Write failing rendering and delivery tests**

Cover the default heading `### 📸 Beyond thy Fundamental`, optional title heading, empty account emoji omission, caption Markdown escaping, `[View on Instagram](<...>)`, source text splitting at 2,000 characters, text-before-media order, ordered four-image carousel delivery, reel video delivery, and independent retry after a media failure.

- [ ] **Step 2: Run focused rendering tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_render.py
```

Expected: import or missing-function failures.

- [ ] **Step 3: Implement safe Instagram rendering**

Reuse the X renderer's safe HTML-to-Markdown approach without quote or thread blocks. Render accepted summary or caption, then the Instagram source link. Never render raw OCR text automatically. Include a concise `(Reel)` marker only when the source is a reel and the caption or summary does not already identify it.

- [ ] **Step 4: Implement local-media Discord delivery**

Use Discord API v10 with `DISCORD_BOT_TOKEN`, deterministic nonces prefixed with `instagram-post-watch`, a 30-second timeout, and sanitized status errors. Upload the already downloaded local file, not the expiring Instagram CDN URL. Delete the temporary upload path after the request. Treat Discord 429 as a retryable error and preserve independent text and media message IDs.

- [ ] **Step 5: Run rendering tests**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_render.py
```

Expected: all rendering and local-media delivery tests pass.

## Task 8: Orchestrate polling, OCR, vision preparation, delivery, and heartbeats

**Files:**
- Create: `instagram-post-watch/bin/scan.py`
- Create: `instagram-post-watch/bin/instagram-post-watch.sh`
- Create: `instagram-post-watch/tests/test_scan.py`

**Interfaces:**
- Consumes all previous task interfaces.
- Produces `run(now: datetime | None = None, dry_run: bool | None = None) -> dict[str, object]` and `submit_analysis_payload(payload: object, dry_run: bool | None = None) -> dict[str, object]`.
- The wrapper supports no subcommand for scanning and `submit-analysis --json '<payload>'` for agent submission.

- [ ] **Step 1: Write failing orchestration tests**

Test the complete deterministic sequence with fakes:

```text
lock -> load config/state -> fetch RSSHub -> initialize or queue cursor
-> download every asset -> sample reel frames -> OCR every asset
-> cache results -> choose vision mode -> persist event
-> drain ready events -> send heartbeat -> claim one agent lease
```

Include tests for source failure without cursor advancement, one event per carousel, OCR failure producing partial vision, sparse content producing full vision, no-post mode producing no Discord calls, filtered agent submission, valid submission draining text then media, and expired lease recovery.

- [ ] **Step 2: Run scanner tests and confirm they fail**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_scan.py
```

Expected: module or orchestration failures.

- [ ] **Step 3: Implement scanner paths and environment controls**

Use these environment variables:

```text
INSTAGRAM_POST_WATCH_STATE_PATH
INSTAGRAM_POST_WATCH_CONFIG_PATH
INSTAGRAM_POST_WATCH_MEDIA_ROOT
INSTAGRAM_POST_WATCH_NO_POST=1
INSTAGRAM_POST_WATCH_OCR_ENGINE
INSTAGRAM_POST_WATCH_PY
```

Acquire a process lock before source observation and submission. Use an isolated media root when the state path is overridden. Persist every cursor, OCR, queue, lease, and delivery transition before proceeding to the next external operation.

- [ ] **Step 4: Implement run statistics and canonical heartbeat output**

Track fetched, filtered, queued, OCR processed, vision partial, vision full, delivered, and error counts. Emit:

```text
🫀 instagram-post · HH:MM WIB · <tokens>[ · <first sanitized reason> <@443342168434933760> ⚠️]
```

Emit the fatal form on unhandled execution failure. Never include credentials, local secret paths, signed URLs, or raw provider response text.

- [ ] **Step 5: Implement agent submission and delivery drain**

Validate the profile and active lease, reject mismatched or expired `event_key`, apply the deterministic promotion and relevance guards, persist accepted analysis, and deliver the oldest ready event. Send all text legs first, then every original image or reel video in source order. Remove the event and its managed media directory only after all legs and ledger state are persisted.

- [ ] **Step 6: Implement the Bash wrapper**

The wrapper must:

1. export `TZ=Asia/Jakarta`;
2. source only `DISCORD_BOT_TOKEN` from `~/.hermes/.env`;
3. default `INSTAGRAM_POST_WATCH_PY` to the isolated selected OCR runtime;
4. invoke `~/.agents/skills/instagram-post-watch/bin/scan.py`;
5. append output to `~/.logs/instagram-post-watch.log`;
6. preserve the scanner exit status; and
7. pass `submit-analysis --json` unchanged to the scanner.

- [ ] **Step 7: Run the scanner tests and shell syntax check**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_scan.py
bash -n bin/instagram-post-watch.sh
```

Expected: all scanner tests pass and Bash syntax exits zero.

## Task 9: Add repository governance and documentation identity

**Files:**
- Create: `instagram-post-watch/AGENTS.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `tests/test_documentation_contract.py`
- Modify: `scripts/test-all`

**Interfaces:**
- Produces a recognized agent-backed cron with exactly `AGENTS.md` and `SKILL.md` at its source root.
- Adds the new watcher to the root inventory, child instruction list, agent-backed classification, governance anchors, and full test runner.

- [ ] **Step 1: Write `instagram-post-watch/AGENTS.md`**

Document the exact source route, public-only boundary, credential ownership, JSON fields, OCR and vision modes, state ownership, media cleanup, heartbeat name, no-post controls, development test command, deployment checksum rules, and the requirement to obtain approval before the first VPS write. Do not create `README.md`, `SPEC.md`, `DEPLOY.md`, `DESIGN.md`, `PLAN.md`, or `CONTEXT.md` inside the cron directory.

- [ ] **Step 2: Add the root child-project and classification entries**

Add `instagram-post-watch/AGENTS.md` to the root child instruction list and add `instagram-post-watch` to the agent-backed cron list in `AGENTS.md`. Add the root README row describing its authenticated RSSHub source, OCR, selective vision, Discord delivery, and VPS-only live verification.

- [ ] **Step 3: Extend documentation-contract tests**

Add `instagram-post-watch` to `AGENT_BACKED_CRONS`, increase the reviewed total from `15` to `16`, and add governance anchors that must remain in its `AGENTS.md`, including `IG_COOKIE`, `IG_USERNAME`, `IG_PASSWORD`, the cookie-based `/instagram/2/user/<handle>?format=json` route, `vision_partial`, `vision_full`, `public posts and reels`, and `15-minute agent leases`. Keep the existing `x-post-watch` anchors unchanged.

- [ ] **Step 4: Add the watcher suite to `scripts/test-all`**

Add:

```bash
run_suite instagram-post-watch instagram-post-watch tests
```

Do not add OCR runtime packages to `requirements-dev.txt`; local tests inject fake backends and the production OCR environment is VPS-owned.

- [ ] **Step 5: Run repository documentation checks**

Run:

```bash
../.venv/bin/python -m pytest -q tests/test_documentation_contract.py
```

Expected: the new cron is classified as agent-backed, has exactly one contract file, has no redundant nested Markdown, and preserves all governance anchors.

## Task 10: Run the complete local verification and publish the reviewed source

**Files:**
- All files from Tasks 1 through 9.

- [ ] **Step 1: Run the focused new-watcher suite**

Run from the repository root:

```bash
./.venv/bin/python -m pytest -q instagram-post-watch/tests
```

Expected: all new-watcher tests pass without Instagram credentials, OCR packages, or Discord calls.

- [ ] **Step 2: Run the complete repository suite and policy checks**

Run:

```bash
bash scripts/test-all
python scripts/repository_policy.py
git diff --check
```

Expected: every existing suite and the new suite pass, tracked-file policy reports `ok`, and `git diff --check` is silent.

- [ ] **Step 3: Inspect the final source boundary**

Run:

```bash
git status --short
git diff --stat
rg -n "IG_USERNAME|IG_PASSWORD|DISCORD_BOT_TOKEN|signed|cookie|secret" instagram-post-watch AGENTS.md README.md
```

The search may show variable names and documentation references, but it must not show credential values, raw cookies, signed CDN URLs, or local secret contents. Runtime state, OCR caches, downloaded media, and benchmark reports must remain untracked.

- [ ] **Step 4: Commit and publish the source**

Create one reviewed commit after all local tests pass:

```bash
git add AGENTS.md README.md scripts/test-all tests/test_documentation_contract.py docs/superpowers/specs/2026-08-24-instagram-post-watch-design.md docs/superpowers/plans/2026-08-24-instagram-post-watch.md instagram-post-watch
git commit -m "feat: add instagram post watcher"
git push -u origin "$(git branch --show-current)"
```

Use the actual isolated branch name created by the `wt` workflow. Do not deploy a dirty or unpublished commit.

## Task 11: Configure the VPS, deploy, smoke-test, and obtain live approval

**Files and live targets:**
- Deploy: `vps:~/.agents/skills/instagram-post-watch/bin/`
- Sync separately after comparison: `vps:~/.agents/skills/instagram-post-watch/config/watches.json`
- Sync separately after comparison: `vps:~/.agents/skills/instagram-post-watch/SKILL.md`
- Operational review: `vps:~/rsshub/docker-compose.yml` and `vps:~/rsshub/.env`
- Operational review: isolated OCR environment under `vps:~/.local/share/`
- Operational review: Hermes cron registry through the supported CLI only

- [ ] **Step 1: Inspect live VPS targets before writing**

From a VPS-local agent, inspect the current RSSHub compose environment, deployed skill directories, available `ffmpeg` and `ffprobe`, disk and memory headroom, and existing Hermes cron state. Produce exact diffs for the RSSHub environment and any new runtime directories without printing credential values.

- [ ] **Step 2: Obtain approval for the first VPS write**

Show the user the sanitized diff covering the RSSHub `IG_COOKIE` variable reference, isolated OCR environment path, deployed watcher files, and intended cron registration. Do not write any VPS file until this approval is recorded in the current conversation.

- [ ] **Step 3: Configure RSSHub authentication and the isolated OCR runtime**

Add only variable references to the RSSHub compose file and place credential values in the VPS-local RSSHub `.env`. Install the selected OCR backend in its watcher-owned environment and restart only the RSSHub service required for the new environment after validating the compose configuration. Do not touch Hermes gateway state or the shared Yahoo Finance environment.

- [ ] **Step 4: Deploy executable source and compare checksums**

From the clean published checkout, run:

```bash
./deploy.sh instagram-post-watch
```

Compare SHA-256 values for every deployed `bin/` file. Compare the local config and `SKILL.md` with their VPS destinations before synchronizing those two files separately. Never deploy the dotfiles mirror.

- [ ] **Step 5: Run the isolated no-post smoke test**

Use a dedicated state and media directory:

```bash
smoke_dir="$(mktemp -d /tmp/instagram-post-watch-smoke.XXXXXX)"
INSTAGRAM_POST_WATCH_NO_POST=1 \
INSTAGRAM_POST_WATCH_STATE_PATH="$smoke_dir/state.json" \
INSTAGRAM_POST_WATCH_MEDIA_ROOT="$smoke_dir/media" \
"$HOME/.hermes/scripts/instagram-post-watch.sh"
```

Verify that the source, media download, OCR, vision gate, wake payload, rendering, and heartbeat paths execute without a Discord write. Inspect the isolated state and remove the exact scratch directory after verification. Do not point no-post mode at live state.

- [ ] **Step 6: Register the approved schedule through Hermes**

After the user explicitly approves the live schedule, use the supported Hermes cron command to register or enable `instagram-post-watch` at `*/15 * * * *` in `Asia/Jakarta` with the `instagram-post-watch` skill and wrapper. Never edit `~/.hermes/cron/jobs.json` directly.

- [ ] **Step 7: Verify natural scheduled delivery and hand off evidence**

After the first natural run, verify the Hermes execution record, saved stdout, `instagram-post` heartbeat, OCR and vision counters, target Discord delivery, media ordering, and the next scheduled run. Separately verify local and VPS checksums. State clearly whether dotfiles capture is pending; do not claim live success from tests or a no-post smoke alone.

## Self-review checklist

- [ ] Every requirement in `docs/superpowers/specs/2026-08-24-instagram-post-watch-design.md` maps to at least one task above.
- [ ] The OCR gate has explicit `text_only`, `vision_partial`, and `vision_full` tests.
- [ ] All image and sampled-frame OCR occurs before the LLM decision.
- [ ] The agent receives local paths only when the gate requires vision and is instructed to read every supplied path.
- [ ] Original media delivery is independent from OCR and agent submission.
- [ ] No task introduces a second source of truth for runtime state or configuration.
- [ ] No task edits the dotfiles mirror, live state, or Hermes registry by hand.
- [ ] No credentials or signed media URLs enter source control.
- [ ] No unspecified implementation step remains in this plan.
