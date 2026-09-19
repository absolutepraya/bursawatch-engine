# Hermes schedule reconciler instructions

This host-bound platform package is the only planned bridge from Bursawatch
desired interval schedules to the live Hermes scheduler. It reads the private
control-plane API, resolves immutable runtime job names from the live Hermes
registry, invokes only the supported Hermes CLI, reloads the registry to
verify the result, then reports the revision outcome.

It never edits `~/.hermes/cron/jobs.json`, writes a cron expression supplied by
the web application, exposes its credential to the web application, or changes
fixed calendar jobs. It accepts only interval schedules already bounded by the
control-plane API and converts them to exact Hermes `every <minutes>m` syntax.

Development tests use a temporary registry and fake API. Do not run this
against the VPS registry, install its systemd timer, add its environment
values, or use it to alter a live job without a separately approved deployment
step. `BURSAWATCH_SCHEDULE_RECONCILER_DRY_RUN=1` is the required first runtime
verification mode after deployment.
