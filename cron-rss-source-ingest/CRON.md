# Fixed RSS platform source boundary

Runtime identity reserved: `bursawatch-rss-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. This metadata-only adapter must
not run beside the live Stockbit source job.

The adapter reads page one through the existing Stockbit RSS parser and
handles only its four fixed system-owned lane IDs and URLs. It uses optional
XML item order without changing the live watcher's publication-time sort.
A full 20-article page without its previous anchor blocks the lane and
retains its cursor. Publication time remains event data. Each enabled lane
has a future-only private cursor and staged inbox handoff. More than 20 new
articles on one page blocks that lane without advancing its cursor. Stable
provider identity is SHA-256 of the lane-local RSS GUID; the original GUID
remains in the article payload. Accepted source work retains the current live
watcher config revision but has no handler yet. The old article queue, frozen
destination and instruction settings, routing, and future-only policy remain
with the current watcher until a separate parity and state migration. A
watcher config revision change blocks this pilot until a reviewed future-only
transition; it cannot replay articles accumulated while a lane was disabled.
