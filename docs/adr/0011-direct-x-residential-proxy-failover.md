---
status: accepted
---

# Use ordered residential proxy failover for direct-X sources

Direct-X profiles will use the authenticated rotating residential proxy on port `3010` as the primary route and port `443` as the fallback route. The behavior applies to every direct-X profile, while RSSHub remains unchanged. The wrapper reads the authenticated URLs from `X_POST_WATCH_PROXY_PRIMARY` and `X_POST_WATCH_PROXY_FALLBACK`. Proxy credentials live only in the VPS Hermes environment and never in source control, logs, or Discord.

Each direct-X poll starts with the primary route. A recoverable transport, proxy, timeout, X `403` or `429`, or upstream `5xx` failure retries the affected request once through the fallback and keeps the fallback for the rest of that poll. Missing status links, malformed payloads, parsing failures, `404`, and other non-recoverable source errors do not trigger failover. If the fallback succeeds, no rate-limit cooldown is recorded; the existing three-hour cooldown applies only when both routes fail with rate limiting. The watcher fails closed when proxy configuration is absent and never falls back to an unproxied direct connection.
