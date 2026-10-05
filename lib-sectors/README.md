# Sectors client

A standard-library Python library for cache-backed Sectors evidence. Every
consumer explicitly selects the same private host-local SQLite coordination
store, billing-window identity and conservative request cost. Importing the
package performs no IO. Constructing `Config` performs no IO; constructing
`CacheStore` or `SectorsClient` creates or migrates the configured store.

Add `lib-sectors/bin` to the importing application's Python module path.

```python
from datetime import datetime, timezone
from pathlib import Path
from sectors_client import Config, SectorsClient

config = Config(
    store_path=Path("lib-sectors/state/provider.sqlite3"),
    caller="morning-brief",
    billing_window="2026-10",
    caller_limit=830,
    host_limit=1000,
    cache_only=True,
)
client = SectorsClient(config)
result = client.close_session(
    "2026-10-02",
    cutoff=datetime.now(timezone.utc),
    page_limit=30,
    max_cost=1,
)
# result.complete is false and missing_offsets names gaps when pages are absent.
```

`Config.from_env_file(path, **configuration)` reads only `SECTORS_API_KEY` from
an explicit file, without shell expansion or loading process environment values.
Use the canonical main-checkout `lib-sectors/.env` through a non-conflicting
worktree link. Key values are omitted from configuration representations.
Loading a key does not enable network mode: `cache_only=False` must be explicit.
Layout IDs and profile revisions remain caller-owned.

`RequestIdentity(path, query=None, *, generation=None)` canonicalizes a validated
identity at
`https://api.sectors.app`. It supports full-universe close pages, the companies
screener, IHSG index history, per-symbol daily data, per-symbol corporate actions,
and the marketwide stock-split calendar. Split-calendar identities require
`type=stock_split` plus a range of at most 90 inclusive calendar days, avoiding
an implicit request for all action types. Query pagination, ISO dates and symbol
path segments are validated. Provider-origin overrides are rejected.

`generation` is a keyword-only caller-owned immutable revision, such as
`caps:2026-W41`, limited to 100 ASCII letters, digits, underscores, dots, colons
and hyphens, beginning with a letter or digit. None preserves existing request
keys and URLs. A present generation changes only the local request/cache key;
it is never sent in the HTTP path or query. Reusing the same generation shares
cache and fetch leases. A new weekly generation permits a separately budgeted
snapshot through the same client and provider URL. The caller chooses the
revision explicitly; the library has no automatic freshness policy or fetch.
Each generation keeps its own immutable versions, cutoff checks, attempts and
uncertain reservations, while all generations share host/caller window limits.

`SectorsClient.get(identity, cutoff=..., max_cost=..., retry=False)` returns a
`CachedResponse` with payload, available-at timestamp, provenance and imported
flag. Cache versions are append-only; later corrections do not overwrite older
cutoff-visible evidence. A cached response after the caller's cutoff causes a
`CacheMiss`, without another paid fetch. A response obtained after a frozen
cutoff is stored for a later caller but is unavailable to that frozen run.

`close_session(session, cutoff=..., page_limit=30, max_cost=1, retry=False,
max_pages=1000)` starts at offset zero for that date, validates each page and
checks cross-page totals and unique symbols. Pages persist immediately. It
returns `SessionResult(session, rows, pages, total, complete, missing_offsets)`.
Missing cache-only pages produce a partial result; provider failures propagate
as typed safe exceptions, with already completed pages retained for resumption.
No offset from another date is reused. Zero or null close values remain missing
numerical evidence; the morning owner decides eligibility and usable coverage.

`HTTPTransport(config, opener=...)` supplies raw-key authorization, an explicit
User-Agent, HTTPS, bounded socket timeout and response bytes, redirect refusal,
and safe errors. Injectable HTTP adapters exist for offline tests. Authentication,
allowance exhaustion, temporary throttling, invalid responses and uncertain
network outcomes have distinct exception types. Only explicit status/code
evidence classifies exhaustion; an ambiguous 429 is temporary throttling.
Verified `Retry-After` seconds or an HTTP date sets the durable cooldown.

Reservations, request ownership and result persistence use SQLite transactions.
Concurrent identical callers share one fetch or receive bounded
`RequestInFlight`. A crashed or timed-out request retains its conservative
reservation and cannot be stolen or automatically retried. Every failed request
retains its conservative cost unless externally verified reconciliation resolves
it. A retry requires `retry=True`, an elapsed known cooldown, a fresh reservation,
and remaining `Config.max_attempts`. Unknown cooldowns require external
resolution. Retry count is shared per request identity. The client never sleeps
through a provider cooldown or automatically repeats a request.

`CacheStore.usage(window, caller)` reports locally reserved/spent costs, not an
account balance. Limits are durable: another consumer cannot raise an already
established host or caller allowance. Limits can be tightened. Choose one
billing-window identifier across consumers; the store does not infer a billing
period or coordinate unrelated clients on another host. Manual top-up and future
window configuration belong to the fetch authority. The maximum configured host
allowance is 1,000 credits. Endpoint-cost or universe changes require caller
recalculation before spending, including any retry reserve.

`request_status(identity)` returns safe lease metadata. Administrative
`reconcile(identity, token=..., charged_cost=..., evidence_digest=..., now=...)`
requires a matching uncertain, blocked, throttled or expired reservation and a
SHA-256 reference to caller-retained authoritative billing evidence. A verified
throttle cooldown must elapse before reconciliation. An unknown cooldown can be
resolved only through this audited administrative path. It records the
original reservation and verified charge in the reconciliation table. It does
not verify billing itself or claim an account balance. Resumption still requires
an explicit retry and respects the attempt ceiling. Do not resolve uncertainty
merely because a lease expired or a response is absent.

The offline importer accepts an explicit file or directory:

```python
from sectors_client import CacheStore, import_retained

store = CacheStore(config.store_path)
report = import_retained(
    "/explicit/retained/cache/path",
    store,
    imported_at=datetime.now(timezone.utc),
)
```

A directory selects `bursawatch-preview-history-20261005.json`. That retained
wrapper contains completed close pages, including a reused full session. Other
diagnostic, membership and cap artifacts are counted as ignored; the morning
owner supplies typed loaders for those inputs. The importer validates the wrapper
dates, provenance, page identities, totals, offsets, symbols and declared complete
sessions before an atomic import. It reports newly inserted pages, complete and
partial sessions, missing offsets/sessions, source digest and ignored-artifact
count. Repeated identical imports preserve the original availability timestamp.
Import availability is conservatively the caller's import time, not an inferred
historical fetch time. Imported pages incur zero new reservations and do not
establish either a current balance or a complete rotation-history window.

The previously discussed historical setup allowance remains stopped. Neither
cache import nor preview regeneration resumes a historical fetch. Live history
must accumulate within a separately approved recurring budget or a separately
approved bounded import. The library provides no scheduler, deployment,
provider-account authority, layout or publication functionality.

Run the offline package tests with the repository interpreter:

```sh
python -m pytest -q lib-sectors/tests
```
