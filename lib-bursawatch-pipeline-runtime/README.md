# Shared Bursawatch pipeline runtime

`bin/pipeline_runtime.py` claims independent subscription work from the Control Plane
and dispatches by frozen `pipeline_id`. A claim includes only the handler IDs this
runtime supports. One handler failure settles only its own lease with a sanitized
`handler_failed` code; later items continue. It never copies raw provider errors
into run telemetry.

Handlers receive the event envelope, frozen settings and revisions, and stable
`effect_key`. The runtime checks the work fence just before dispatch. Handlers must
send `(event_key, version, effect_key)` to their domain owner, which must atomically
reject a version below the newest one it has accepted while deduplicating the effect.
A correction can arrive while a handler is running, after the runtime fence, so this
runtime cannot itself prevent an old in-flight effect. This package has no domain handlers
until platform pilot tasks add them, and it does not send Discord messages directly.

Run `uv run --with pytest pytest -q tests` for the focused suite.
