# Separate BursaWatch and Hermes Personal

The former mixed Hermes repository is split into BursaWatch for market
automation and Hermes Personal for personal automation, while preserving the
full pre-split history in both repositories. BursaWatch development cron
packages use `cron-<surface>-<purpose>` and deploy as
`bursawatch-<surface>-<purpose>`. Hermes Personal development cron packages
deploy as `personal-<slug>`.

Shared RSSHub and Telegram resilience remain BursaWatch-owned dependencies.
The first production cutover changes source and runtime identities while
preserving established state locations. A later state migration is a separate,
integrity-checked operation.
