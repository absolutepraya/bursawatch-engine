# Shared Chart-IMG client

Reusable Python transport and immutable PNG cache for explicit caller-owned
Chart-IMG profiles. This source implementation is tested with fake HTTP and
local temporary stores. It does not establish provider publication rights,
TradingView profile correctness or an exact last-bar cutoff.

Python 3.11 or newer and Pillow are required; see `requirements.txt`. Consumers
explicitly add `lib-chart-img/bin` to their import path, following the other
shared libraries. Importing and construction perform no I/O.

## Public interfaces

`RenderRequest(profile_revision, layout_revision, symbol, interval, time_range,
cutoff, layout_id=None, width=800, height=600, options=None)` is immutable.
The revisions must identify reviewed content, not just a mutable saved layout.
`cutoff` must be timezone-aware. The identity includes both revisions, endpoint
and layout ID, symbol, interval, requested time range, cutoff, dimensions and
all canonical provider options. Nested options are copied into immutable JSON.
The library produces PNG only.

A caller-provided layout ID selects
`POST https://api.chart-img.com/v2/tradingview/layout-chart/{layout_id}`.
The supported local request contract sends symbol, interval, dimensions and
format. Shared-layout presentation/study overrides are rejected because their
support has not been established. The requested time range remains cache
identity/provenance and is **not sent as a purported window control**.

Without a layout ID, the client uses `/v2/tradingview/advanced-chart` and sends
`range`. Accepted range presets are `1D`, `5D`, `1M`, `3M`, `6M`, `YTD`, `1Y`,
`5Y` and `ALL`. Optional presentation fields are `theme`, `studies`, `style`,
`timezone`, `override` and `backgroundColor`. These are caller-owned profiles;
fake tests cannot validate a real provider study configuration or demonstrate
that a range enforces the last-bar date. Neither endpoint receives a fabricated
cutoff parameter.

`RenderCache(path).initialize()` explicitly creates the local SQLite store.
One provider account must share one store across consumers. Initialization
sets the database mode to `0600`; store it outside Git and backups that capture
source. `ChartImgClient(cache, provider=None, clock=None).render(request,
cache_only=True, max_age_seconds=None)` returns an `ImageArtifact`.

```python
from chart_img_client import ChartImgClient, RenderCache

cache = RenderCache('/tmp/my-isolated-chart-preview.sqlite')
cache.initialize()
client = ChartImgClient(cache)  # No credential or network adapter required.
artifact = client.render(request)  # Exact cached identity or cache_miss.
```

A cache-only miss never reserves an allowance or invokes HTTP. A successful
render is immutable: later requests with the same identity return exactly its
bytes, digest and retrieval time. An expired `max_age_seconds` produces
`stale_cache`, without replacing the accepted image. Publication recovery can
reuse frozen bytes without a freshness check. New work requires a new cutoff
or content revision. Corrupted cache bytes fail closed with `cache_corrupt`.

For separately authorized online callers, explicitly construct
`ProviderTransport(config, callable_http)` and pass it to `ChartImgClient`;
request network mode with `cache_only=False`. The callable accepts `HttpRequest`
(url, headers, JSON bytes, timeout_seconds, max_bytes) and returns `HttpResponse`
(status, headers, bytes, optional final_url). `UrllibTransport()` supplies a
standard adapter with redirects disabled, a total deadline, bounded chunk
reads and guaranteed close handling. It makes one attempt and never retries.
`ProviderTransport` is a low-level uncoordinated boundary; production consumers
must use `ChartImgClient` for coordinated allowance accounting.

## Credentials and transport limits

`ChartImgConfig(api_key, timeout_seconds=30, max_bytes=8_000_000)` takes an
explicit key, hidden from its representation. `load_config(explicit_path)`
reads only `CHART_IMG_API_KEY` from a private owner-owned regular file, at most
64,000 characters. It does not evaluate shell expressions or load unrelated
fields/environments. A symlink to the canonical private file is allowed.
`CHART_IMG_LAYOUT_ID` in `.env.example` is a retained private-validation input,
not a library global default; each request receives its layout ID explicitly.

Timeouts must be positive and at most 90 seconds. Payloads are bounded to
64,000 JSON bytes, responses to at most 8,000,000 bytes, dimensions to 4,096 per
axis and 16,000,000 pixels total. Validation checks MIME, actual PNG format,
exact requested dimensions, single-frame content, full decoding and SHA-256.
HTML, truncated data, other formats and mismatched dimensions are rejected.
Only the fixed HTTPS API origin and the two non-storage endpoints are used.
Redirects, including redirects containing credentials, are rejected. Exceptions
from open, read and close are replaced with controlled error codes; raw headers,
provider response bodies and credential-bearing exception text are not exposed.
Injected adapters must honor the supplied deadline and byte bound.

## Allowance and recovery

The separate Chart-IMG guard permits at most 50 attempt reservations per rolling
24 hours, with at least one second between reservations across consumers. This
conservative window does not assume a provider reset timezone. All reservations
remain charged, including HTTP failures, invalid images and uncertain outcomes.
The library does not share Sectors credits or state.

SQLite uses short atomic transactions; HTTP runs outside the transaction.
Identical concurrent work reports `render_in_progress`, rather than making a
second call. An abandoned lease becomes `outcome_unknown`; it does not allow an
automatic replacement request. A known 429 honors its `Retry-After` globally.
A missing/invalid retry header produces a durable unknown throttle and blocks
new provider requests until explicitly resolved, even after time has passed.
Every unresolved unknown 429 holds that global block; resolving one of several
does not release it. Recovery waits at least 24 hours after the latest unknown
429 observation. An observed 429 and its safe Retry-After value survive a
response-close failure, so cleanup cannot erase the provider-wide gate.
Cached images remain readable while new calls are blocked.

Inspect `cache.allowance(now=...)` and `cache.unresolved()`. To resolve an
unknown attempt, first verify externally that its writer stopped and preserve
that evidence. Then call `cache.resolve_unknown(attempt_id, now=...,
evidence_ref=...)`. For an unknown 429, a full 24-hour cooldown from observation
is additionally required. The method appends `cache.audit_log()` evidence and
never refunds the attempt. It performs no provider validation or network probe.
The caller remains responsible for reviewing whether a subsequent online
request is authorized.

`ChartImgError.code` is safe for logging; `retry_at` is an optional aware UTC
timestamp. Errors include `cache_miss`, `cache_unavailable`, `cache_corrupt`,
`stale_cache`, `render_in_progress`, `outcome_unknown`, `rate_limited`,
`allowance_exhausted`, `throttled`, `throttle_unknown`, `invalid_image`,
`redirect_rejected`, `authentication_failed`, `provider_failed`,
`transport_failed` and `deadline_exceeded`. No error automatically retries.

## Byte validity and external verification

`ImageArtifact` contains request identity/provenance, immutable `data` bytes,
content type, decoded format/dimensions, SHA-256 and response-completion
`retrieved_at`. `verification=None` explicitly means unverified. A valid image
cannot be treated as current IHSG market evidence by this library.

A caller may attach `AsOfVerification(image_sha256, request_identity,
last_bar_date, verified_at, method, evidence_ref, time_range)` through
`artifact.with_verification(proof)`. The attachment verifies bindings to the
exact bytes/request, requested range, a last-bar date no later than the cutoff
in UTC, and verification time no earlier than retrieval. It records an external
caller attestation; it does not inspect prices/studies or independently prove
that the supplied last-bar date, visible window or saved/public profile is
correct. This metadata is not persisted into the shared byte cache. The domain
owner must verify the expected trading session/profile before using it, freeze
accepted bytes and evidence with its run, and choose a fallback or omit an
unverifiable image.

## Local tests

From this package, using the main repository's existing interpreter:

```bash
../.venv/bin/python -m pytest -q
```

Adjust the interpreter path when inside a worktree. Tests use generated PNGs,
invented keys, callable fake HTTP and temporary SQLite only. They never read the
real `.env`, call a provider, model or Discord, or validate a real TradingView
layout. See [the architecture note](../docs/notes/2026-10-05-shared-chart-img-client-architecture.md)
for the separate live profile/as-of and publication-rights gates.
