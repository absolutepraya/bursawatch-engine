# WhatsApp platform source boundary

Runtime identity reserved: `bursawatch-wa-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. This release-metadata pilot
must not read the live queue while the existing source reader runs.

Each verified forwarding Channel has an endpoint-local future-only cursor and
private source handoff. The reader uses only the already durable bridge queue,
bounded to 20 new messages per endpoint; a media event retains its cursor and
stores bounded text and identity metadata locally. It never deletes from the
bridge queue. The existing immutable archive remains authoritative for raw
media and history. INS and Samuel are observe-only and are not subscribed to
pipeline work. BRI `swing_chart_context` work is left pending because no
reviewed pipeline owner can reproduce the current agent and image behavior.
