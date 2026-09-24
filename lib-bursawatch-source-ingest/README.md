# Source ingest handoff

`bin/source_ingest.py` provides an endpoint-local future-only cursor and the
Task 3 durable source inbox handoff contract. It is used only by the
unscheduled Task 5 platform adapters. A source event is staged in a private
spool before inbox acceptance; the cursor advances only after the receipt.
An unavailable inbox leaves the request staged. A media event stores bounded
source text and identity metadata without media bytes or signed locators and
holds its cursor. That metadata cannot replace a durable media object.

`select_endpoints` validates enabled verified effective catalog rows against
each adapter's independently reviewed source and publisher binding. One
endpoint's fetch or handoff failure returns a bounded status code and does
not stop another endpoint. The library never claims pipeline work, handles
Discord, or reads production state by itself.
