-- bursawatch-release: manual

-- Rename the curated labels without changing publisher or endpoint identity.
update bursawatch_source_publishers
   set name = 'Dokter Market'
 where publisher_id = 'x-doktermarket'
   and system_owned = true
   and name = 'DokterMarket';

update bursawatch_source_publishers
   set name = 'Aldo Tjahjadi'
 where publisher_id = 'x-aldotjahjadi8'
   and system_owned = true
   and name in ('IHSG Journal', 'IHSG Journal 🍀🌞');

-- Promote only the exact untouched X source baseline. Dashboard-authored
-- configurations must keep their current revision; rename those display_name
-- fields separately through the authenticated watcher configuration API.
-- Never rewrite historical revisions, accepted events, or publications.
do $migration$
declare
    previous_config jsonb;
    renamed_config jsonb;
begin
    select r.config into previous_config
      from bursawatch_watchers w
      join bursawatch_config_revisions r
        on r.watcher_id = w.watcher_id
       and r.revision = w.current_revision
     where w.watcher_id = 'bursawatch-x-account-watch'
       and w.current_revision = 1
       and r.config_version = 1
       and r.config_sha256 = '7f0698fe5bd298335280355fa846e14fc4578806e108afadb77defe153a3e437'
       and r.actor_id = 'source-baseline'
       for update of w;

    if not found then
        return;
    end if;

    select jsonb_set(previous_config, '{profiles}', jsonb_agg(
        case profile ->> 'id'
            when 'doktermarket' then
                jsonb_set(jsonb_set(profile, '{display_name}', '"Dokter Market"'::jsonb, false),
                    '{additional_prompt_instruction}',
                    to_jsonb(replace(profile ->> 'additional_prompt_instruction', 'DokterMarket', 'Dokter Market')), false)
            when 'aldotjahjadi8' then
                jsonb_set(profile, '{display_name}', '"Aldo Tjahjadi"'::jsonb, false)
            else profile
        end order by position
    ), false) into renamed_config
      from jsonb_array_elements(previous_config -> 'profiles') with ordinality as p(profile, position);

    insert into bursawatch_config_revisions
        (watcher_id, revision, config_version, config, config_sha256, actor_id)
    values ('bursawatch-x-account-watch', 2, 1, renamed_config,
        'b6220865ba93f81e96332b7b32b9744b73e6e42bf418a413879c03c62c942d81',
        'source-baseline-correction');

    update bursawatch_watchers
       set current_revision = 2,
           updated_at = now()
     where watcher_id = 'bursawatch-x-account-watch';
end
$migration$;
