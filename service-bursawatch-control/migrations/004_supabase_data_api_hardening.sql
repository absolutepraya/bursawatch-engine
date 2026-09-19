-- The web application talks only to service-bursawatch-control. It must not
-- receive a policy path to the control-plane tables through Supabase Data API.
-- The backend uses a private Postgres connection, not a browser API key.

alter table bursawatch_watchers enable row level security;
alter table bursawatch_config_revisions enable row level security;
alter table bursawatch_runs enable row level security;
alter table bursawatch_events enable row level security;
alter table bursawatch_scheduler_jobs enable row level security;
alter table bursawatch_schedule_revisions enable row level security;
alter table bursawatch_schema_migrations enable row level security;

do $$
declare
    table_name text;
begin
    foreach table_name in array array[
        'bursawatch_watchers',
        'bursawatch_config_revisions',
        'bursawatch_runs',
        'bursawatch_events',
        'bursawatch_scheduler_jobs',
        'bursawatch_schedule_revisions',
        'bursawatch_schema_migrations'
    ]
    loop
        execute format('revoke all privileges on table public.%I from public', table_name);
        if exists (select 1 from pg_roles where rolname = 'anon') then
            execute format('revoke all privileges on table public.%I from anon', table_name);
        end if;
        if exists (select 1 from pg_roles where rolname = 'authenticated') then
            execute format('revoke all privileges on table public.%I from authenticated', table_name);
        end if;
    end loop;
end;
$$;
