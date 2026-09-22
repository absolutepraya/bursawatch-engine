-- bursawatch-release: manual

-- Advance only the untouched source-owned WhatsApp revision. A dashboard or
-- other operator revision must remain authoritative and block this correction.
insert into bursawatch_config_revisions
    (watcher_id, revision, config_version, config, config_sha256, actor_id)
select w.watcher_id,
       3,
       2,
       jsonb_set(r.config, '{profiles,0,emoji}', to_jsonb('<:bridanareksa:1551797903927025797>'::text), false),
       '56363ca42605494908b52014174dfccb660ee881882c7602ab6b2aca46d1397b',
       'source-baseline-correction'
  from bursawatch_watchers w
  join bursawatch_config_revisions r
    on r.watcher_id = w.watcher_id
   and r.revision = 2
 where w.watcher_id = 'bursawatch-wa-channel-watch'
   and w.current_revision = 2
   and r.config_version = 2
   and r.config_sha256 = '12c37e0c385f6b2431f2d318559d49406b9cb847fc5da8007459d06486602de9'
   and r.actor_id = 'source-baseline-correction'
on conflict (watcher_id, revision) do nothing;

update bursawatch_watchers w
   set current_revision = 3,
       updated_at = now()
 where w.watcher_id = 'bursawatch-wa-channel-watch'
   and w.current_revision = 2
   and exists (
       select 1
         from bursawatch_config_revisions r
        where r.watcher_id = w.watcher_id
          and r.revision = 2
          and r.config_version = 2
          and r.config_sha256 = '12c37e0c385f6b2431f2d318559d49406b9cb847fc5da8007459d06486602de9'
          and r.actor_id = 'source-baseline-correction'
   )
   and exists (
       select 1
         from bursawatch_config_revisions r
        where r.watcher_id = w.watcher_id
          and r.revision = 3
          and r.config_version = 2
          and r.config_sha256 = '56363ca42605494908b52014174dfccb660ee881882c7602ab6b2aca46d1397b'
          and r.actor_id = 'source-baseline-correction'
   );
