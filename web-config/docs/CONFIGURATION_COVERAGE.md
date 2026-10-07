# Configuration coverage

## Source Catalog API contract (phase 1)

The Control Plane now exposes a separate source registry and catalog revision
through `/v1/source-catalog`, with `/v1/source-catalog/effective` for resolved
subscriptions and an admin-only optimistic write route at
`/v1/source-catalog/config`. The Sources page reads and edits this catalog;
the eight workflow editors below still write their own watcher revisions.
Catalog writes do not alter those revisions, schedules, cursors, or existing
live source behavior. The source securities allowlist is initially empty
pending a reviewed finite engine universe. New People & Org endpoints can be
recorded as pending, but they are inactive until identity verification exists.
Identity verification and an enabled subscription do not by themselves make a
new endpoint runnable. The platform adapter and its domain owner must also
have a reviewed profile/configuration snapshot contract for that endpoint.
Until then, ingestion rejects the endpoint and creates no source events.
`publisher_defaults[].enabled` and `endpoint_overrides[].enabled` are saved
capability intent, consumed by the Source Inbox snapshot. `settings` remains a
strict empty object because no typed consumer has been approved. Catalog enable
intent does not override endpoint verification, adapter binding, or the owner's
enabled profile gate.

The workspace exposes nine watcher editors. Seven originate from the
`absolutepraya/bursawatch` control-plane commit
`25079b3465a97de132ed977ffec3ce3a488a867a`. The additional optional X
`show_quoted_post` field follows main commit
`103a4856901c51f145851af8768506124f83c174`.
Review at `f426e24f447961d1371638735ccc6e3a060ef43e` on 22 September 2026
corrected an earlier missed WhatsApp v2 schema change. The WhatsApp editor now
accepts version 2 only; the other eight editors accept version 1. The unified
workspace exposes the configuration fields below with input, processing and
output summaries. The follow-up engine review at `a343ec4d` also connects the
separate profile/avatar endpoints through an on-demand Source profiles panel.
The service remains the authority for validation and permissions. No source
defaults, private configuration, destination values, credentials, or runtime
state are bundled in these forms or their tests.

Stockbit Snips is the eighth editor, added under its version 1 control-plane
contract. It appears only when the authenticated API lists that watcher.

Morning Brief is the ninth editor. Its version 1 settings cover the WIB data
cutoff and delivery target, fallback and retry windows, nullable Discord
destination, supported market instruments and instrument emojis. Saving applies
to the next unfrozen session and does not activate or schedule a job.

## Account and channel watchers

Each profile editor includes the following keys:

| Watcher            | Editable keys                                                                                                                                                                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| All three          | `id`, `enabled`, `display_name`, `emoji`, `discord_channels[].key`, `discord_channels[].channel_id`, `discord_channels[].description`, `forward_media`, `enable_llm_title`, `enable_llm_summary`, `enable_llm_routing`, `enable_llm_relevance_filter`, `additional_prompt_instruction`, `max_items_per_poll`        |
| X accounts         | `source`, `profile_url`, `handle`, `twitter_emoji`, `forward_normal_post`, `forward_quote_post`, `show_quoted_post`, `forward_reply`, `forward_repost`, `media_policy`, `relevance_scope`, `thread_handling.mode`, `thread_handling.max_posts`, `thread_handling.max_age_minutes`, `thread_handling.settle_minutes` |
| Instagram accounts | `profile_url`, `handle`, `platform_emoji`, `forward_post`, `forward_reel`, `ocr_languages`, `ocr_min_confidence`, `max_reel_frames`                                                                                                                                                                                 |
| WhatsApp channels  | `channel_jid`, `channel_url`, `status_emojis.up`, `status_emojis.down`, `status_emojis.hold`, `relevance_scope`                                                                                                                                                                                                     |

Profiles and destinations can be added or removed within the backend's schema
constraints; X and Instagram require at least one profile. New sources start paused.
The optional WhatsApp status emojis serialize as `null` when cleared.
WhatsApp additionally exposes `mode` (`observe` or `forward`). Observe mode
requires a null source emoji, no Discord routes and disabled media/LLM flags;
forward mode requires a source emoji and at least one route. Changing mode alone
does not erase settings. Invalid combinations are blocked before a save.
Instagram's required `source` is preserved as `rsshub`, its only supported value.
X's optional `source`, `media_policy`, `relevance_scope`, and `show_quoted_post`
may remain absent in an existing snapshot; displayed defaults match the service.
`forward_quote_post` determines whether authored quote posts are eligible;
`show_quoted_post` separately controls display of the quoted original content.
Instagram settings belong to its domain owner, but Instagram source ingest has
no scheduled job and is not currently collected. Saving or enabling an
Instagram profile does not schedule intake.

## Telegram and Discord watchers

| Watcher               | Editable keys                                                                                                                                                                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Kelas Investasi GTW   | Read-only legacy `source.telegram_channel_id`, `source.telegram_username`; editable `destinations.alert_discord_channel_id`, `destinations.heartbeat_discord_channel_id`, `additional_prompt_instruction`                                                                                                  |
| Phintraco swing calls | Read-only legacy `source.telegram_channel_id`, `source.telegram_username`; editable `destinations.alert_discord_channel_id`, `destinations.heartbeat_discord_channel_id`                                                                                                                                     |
| Telegram market news  | `providers.phintraco.telegram_username`, `providers.tuntun.telegram_username`, `destinations.id_stocks_news_discord_channel_id`, `destinations.macro_news_discord_channel_id`, `destinations.industry_news_discord_channel_id`, `destinations.heartbeat_discord_channel_id`, `additional_prompt_instruction` |
| Discord swing board   | `destinations.heartbeat_discord_channel_id`                                                                                                                                                                                                                                                                  |

BRI Danareksa is represented by a WhatsApp profile. Phintraco swing and
`providers.phintraco` in market news are separate configurations. Market news
accepts exactly the `phintraco` and `tuntun` provider keys; its editor does not
create arbitrary Telegram providers. Their usernames are consumed provider
identity metadata, not a selector for the shared Telegram reader. The Phintraco
and GTW legacy source pairs are pinned by their migrated owners and shown
read-only; shared intake source selection belongs to Source Catalog. The workflow
output summary describes the watcher's capability, not additional editable fields.

## Stockbit Snips

The version 1 editor contains exactly four fixed `feeds[].enabled` switches:
Stockbit Commentary (`stockbit_commentary`), Unboxing (`unboxing`), Unboxing IPO
(`unboxing_ipo`), and AI Reports Stockbit (`ai_reports_stockbit`). It also edits
`destinations.id_stocks_news_channel_id`,
`destinations.macro_news_channel_id`, and the optional
`additional_prompt_instruction`. Both routes require distinct 17 to 20 digit
Discord IDs. The instruction is normalized and limited to 800 Unicode code
points. The editor submits the complete version 1 config; unknown keys, missing
or duplicate lanes, and unsupported versions are rejected.

The feed identities and RSS URLs, route names, heartbeat destination,
credentials, parsers, agent response schema, and fixed safety rules remain
system-owned. Pausing a lane stops new intake. Resuming starts from the newest
item after the next successful fetch; it does not backfill the paused interval.
Already queued articles continue using their frozen configuration. An additive
instruction can guide future analysis within the fixed agent rules. Saving the
config records a revision for future invocations; it does not prove a run used
that revision or that Discord received an article.

## Public source identities

The Sources page uses a dated, reviewed public catalog and links only to
workflows present in the API's watcher list. Its illustrated security cards,
people profiles, preview statuses, photographs and descriptions do not
establish saved source membership, current configuration or health.
Actual `profiles[]` rows come from an admin-only config read. Public avatars
decorate a row only after consistent platform and canonical URL/handle matching;
unmatched identities use the fallback presentation.

The web consumes separate profile metadata, avatar update and refresh endpoints
(see `CONTROL_PLANE.md`). Signed-in users can load saved identities; admins can
select auto/manual photos or request refresh. Refresh is asynchronous, not proof
of a new photo, and catalog photography remains separate. The backend still
has no arbitrary workflow creation, brokerage `goal`, `priceSummary`, `language`
or `tone` configuration, or outbound WhatsApp/Telegram delivery controls.
Sample preferences remain browser-local. All editable delivery fields above
target Discord; credentials and provider connection setup remain backend-owned.

## Jobs page and schedule controls

The Jobs page is the single home for declared jobs, desired schedules,
reconciliation state and fresh Hermes observations. An interval job exposes
`enabled` and `interval_seconds` as whole minutes within the server-provided
bounds. `timezone` remains `Asia/Jakarta`; fixed schedules are read-only.
Workflow details link to their shared jobs and show observed state, without a
duplicate schedule editor. Sources and Workflows remain separate views of the
adapter and owner configuration that those jobs serve.

The Jobs editor labels desired, applied and observed state separately. A
schedule is active only when the fresh observation matches the desired revision
and the reconciler reports that revision applied. Pending checks pause in
hidden tabs, stop after a bounded number of attempts, and can be refreshed.
Another save is disabled while reconciliation is pending. Config and schedule
saves use separate revisions and retain separate drafts. The old
`/workspace/schedules` URL redirects to Jobs. Stockbit uses the same editor and
the bounds returned for its job; its initial desired cadence is 15 minutes.

## Checked operator field map

`src/lib/operator-control-coverage.ts` is the machine-readable inventory used by
the focused coverage tests. It records each JSON field path (with `[]` for
repeated rows), editor, validation boundary, API, migrated consumer, and effect
limit. It includes Source Catalog defaults and overrides, all nine watcher
editors, interval job `enabled` and `interval_seconds`, and the read-only
Phintraco/GTW legacy Telegram fields. Profile coverage includes shared identity,
route, media, processing, prompt and poll-limit fields plus platform-specific X,
Instagram and WhatsApp fields. Stockbit covers its four fixed feed switches,
both routes and additive instruction. Schedule timezone, config versions,
revisions, preserved unknown keys, and empty Source Catalog `settings` are not
editable fields.

Schema/version fields, revisions, hashes, timestamps, fixed job times,
credentials, provider authentication, worker infrastructure, and runtime state
are outside these editors. There is no raw JSON editor. Edits clone the existing
snapshot and change only selected fields; unknown fields are preserved for
service validation rather than silently removed. Unsupported config versions
cannot be edited. Save conflicts and uncertain outcomes retain the draft and
require reloading current settings before another write.
