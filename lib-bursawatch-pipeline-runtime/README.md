# Shared Bursawatch pipeline runtime

`bin/pipeline_runtime.py` claims independent subscription work from the Control Plane
and dispatches by frozen `pipeline_id`. One handler failure settles only its own lease
with a sanitized `handler_failed` code; later items continue. Missing handlers use
`handler_unavailable`. It never copies raw provider errors into run telemetry.

Handlers receive the event envelope, frozen settings and revisions, and stable
`effect_key`. They must use that effect key with their existing domain owner before
any externally visible effect. A lease can expire after an effect but before settlement,
so domain-owner deduplication remains required. This package has no domain handlers
until platform pilot tasks add them, and it does not send Discord messages directly.

Run `uv run --with pytest pytest -q tests` for the focused suite.
