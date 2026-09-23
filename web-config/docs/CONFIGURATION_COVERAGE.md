# Configuration coverage

The workspace exposes the complete editable operator configuration of the seven
watchers in `absolutepraya/bursawatch` control-plane commit
`25079b3465a97de132ed977ffec3ce3a488a867a`. The additional optional X
`show_quoted_post` field follows main commit
`103a4856901c51f145851af8768506124f83c174`.
Review at `f426e24f447961d1371638735ccc6e3a060ef43e` on 22 September 2026
corrected an earlier missed WhatsApp v2 schema change. The WhatsApp editor now
accepts version 2 only; the other six editors accept version 1. The unified
workspace exposes the configuration fields below with input, processing and
output summaries. The follow-up engine review at `a343ec4d` also connects the
separate profile/avatar endpoints through an on-demand Source profiles panel.
The service remains the authority for validation and permissions. No source
defaults, private configuration, destination values, credentials, or runtime
state are bundled in these forms or their tests.

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

## Telegram and Discord watchers

| Watcher               | Editable keys                                                                                                                                                                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Kelas Investasi GTW   | `source.telegram_channel_id`, `source.telegram_username`, `destinations.alert_discord_channel_id`, `destinations.heartbeat_discord_channel_id`, `additional_prompt_instruction`                                                                                                                              |
| Phintraco swing calls | `source.telegram_channel_id`, `source.telegram_username`, `destinations.alert_discord_channel_id`, `destinations.heartbeat_discord_channel_id`                                                                                                                                                               |
| Telegram market news  | `providers.phintraco.telegram_username`, `providers.tuntun.telegram_username`, `destinations.id_stocks_news_discord_channel_id`, `destinations.macro_news_discord_channel_id`, `destinations.industry_news_discord_channel_id`, `destinations.heartbeat_discord_channel_id`, `additional_prompt_instruction` |
| Discord swing board   | `destinations.heartbeat_discord_channel_id`                                                                                                                                                                                                                                                                  |

BRI Danareksa is represented by a WhatsApp profile. Phintraco swing and
`providers.phintraco` in market news are separate configurations. Market news
accepts exactly the `phintraco` and `tuntun` provider keys; its editor does not
create arbitrary Telegram providers. The workflow output summary describes
the watcher's capability, not additional editable destination fields.

## Public source identities

The Workflows Source library tab uses the dated, reviewed public catalog and links
only to workflows present in the API's watcher list. Its source membership,
photographs and descriptions do not establish current configuration or health.
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

## Schedules and boundaries

Interval jobs expose `enabled` and `interval_seconds` as whole minutes within
each job's server bounds. `timezone` remains `Asia/Jakarta`. Fixed job schedules
are read-only. Saved schedules are only labelled applied when the saved and
applied revisions match and the service confirms effectiveness. Pending checks
pause in hidden tabs, stop after a bounded number of attempts, and can be
refreshed. Another save is disabled while reconciliation is pending.

Schema/version fields, revisions, hashes, timestamps, fixed job times,
credentials, provider authentication, worker infrastructure, and runtime state
are outside these editors. There is no raw JSON editor. Edits clone the existing
snapshot and change only selected fields; unknown fields are preserved for
service validation rather than silently removed. Unsupported config versions
cannot be edited. Save conflicts and uncertain outcomes retain the draft and
require reloading current settings before another write.
