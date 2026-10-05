-- bursawatch-release: manual

-- Jobs may belong to a shared engine component or be fixed host work with no
-- legacy watcher owner. The global registry links jobs to code-owned
-- component declarations without rewriting existing schedule history.
alter table bursawatch_scheduler_jobs
    alter column watcher_id drop not null;

create table bursawatch_component_jobs (
    component_id text not null,
    job_id text not null references bursawatch_scheduler_jobs(job_id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (component_id, job_id)
);

create index bursawatch_component_jobs_job_idx
    on bursawatch_component_jobs (job_id, component_id);

alter table bursawatch_component_jobs enable row level security;
revoke all privileges on table public.bursawatch_component_jobs from public;
do $revoke_component_jobs$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all privileges on table public.bursawatch_component_jobs from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all privileges on table public.bursawatch_component_jobs from authenticated;
    end if;
end
$revoke_component_jobs$;

-- Task 3 uses this single latest-value table. The identity key makes an
-- observation replaceable only for the same declared component or job.
create table bursawatch_operator_observations (
    identity_kind text not null check (identity_kind in ('component', 'job')),
    identity_id text not null,
    observer_id text not null check (length(observer_id) between 1 and 100),
    observed_at timestamptz not null,
    received_at timestamptz not null default now(),
    status text not null check (length(status) between 1 and 32),
    evidence jsonb not null default '{}'::jsonb check (jsonb_typeof(evidence) = 'object'),
    primary key (identity_kind, identity_id)
);

alter table bursawatch_operator_observations enable row level security;
revoke all privileges on table public.bursawatch_operator_observations from public;
do $revoke_observations$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all privileges on table public.bursawatch_operator_observations from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all privileges on table public.bursawatch_operator_observations from authenticated;
    end if;
end
$revoke_observations$;

create index bursawatch_source_events_endpoint_created_idx
    on bursawatch_source_events (endpoint_id, created_at desc);
create index bursawatch_source_work_pipeline_created_idx
    on bursawatch_source_work (pipeline_id, created_at desc);

do $job_identity_guard$
declare
    existing_runtime_key text;
    existing_kind text;
    existing_watcher text;
begin
    -- The exact 21:08 WIB Hermes names were inspected before this migration.
    -- Existing rows are accepted only when their identity and kind match.
    for existing_runtime_key, existing_kind, existing_watcher in
        select * from (values
            ('bursawatch-tg-source-ingest', 'interval', null::text),
            ('bursawatch-tg-market-news-watchdog', 'fixed', 'bursawatch-tg-market-news'),
            ('bursawatch-dc-swing-board-lifecycle', 'fixed', 'bursawatch-dc-swing-board')
        ) as expected(runtime_job_key, schedule_kind, watcher_id)
    loop
        if exists (
            select 1 from bursawatch_scheduler_jobs j
             where j.job_id = existing_runtime_key
               and (j.runtime_job_key <> existing_runtime_key
                    or j.schedule_kind <> existing_kind
                    or j.watcher_id is distinct from existing_watcher)
        ) then
            raise exception 'operator job identity conflicts with existing row: %', existing_runtime_key;
        end if;
    end loop;

    select runtime_job_key into existing_runtime_key
      from bursawatch_scheduler_jobs
     where job_id = 'bursawatch-x-account-watch-queue-worker'
     for update;
    if not found then
        raise exception 'X queue worker scheduler row is missing';
    end if;
    if existing_runtime_key not in (
        'x-post-queue-worker',
        'bursawatch-x-account-watch-queue'
    ) then
        raise exception 'X queue worker identity changed unexpectedly';
    end if;
end
$job_identity_guard$;

insert into bursawatch_scheduler_jobs
    (job_id, watcher_id, display_name, runtime_job_key, schedule_kind,
     min_interval_seconds, max_interval_seconds, current_schedule_revision,
     reconciliation_status)
values
    ('bursawatch-tg-source-ingest', null, 'Telegram Source Intake',
     'bursawatch-tg-source-ingest', 'interval', 60, 3600, null, 'pending'),
    ('bursawatch-tg-market-news-watchdog', 'bursawatch-tg-market-news',
     'Telegram Market News watchdog', 'bursawatch-tg-market-news-watchdog',
     'fixed', null, null, null, 'not_connected'),
    ('bursawatch-dc-swing-board-lifecycle', 'bursawatch-dc-swing-board',
     'Discord Swing Board lifecycle', 'bursawatch-dc-swing-board-lifecycle',
     'fixed', null, null, null, 'not_connected')
on conflict (job_id) do nothing;

-- The X worker retained a legacy internal key in migration 003. Update only
-- the known old key to its exact Hermes name; schedule revisions are untouched.
update bursawatch_scheduler_jobs
   set runtime_job_key = 'bursawatch-x-account-watch-queue', updated_at = now()
 where job_id = 'bursawatch-x-account-watch-queue-worker'
   and runtime_job_key = 'x-post-queue-worker';

-- A matching existing baseline is idempotent. Refuse to point the job at a
-- conflicting revision 1 that ON CONFLICT DO NOTHING would otherwise hide.
do $telegram_revision_guard$
begin
    if exists (
        select 1
          from bursawatch_schedule_revisions
         where job_id = 'bursawatch-tg-source-ingest'
           and revision = 1
           and (
               enabled is distinct from true
               or interval_seconds is distinct from 60
               or timezone is distinct from 'Asia/Jakarta'
               or schedule_sha256 is distinct from '93bc1ebe79de7f5d1d1fa598dddaa4e8c88cd9d5e5b629e2a9d0779633165c57'
               or actor_id is distinct from 'source-baseline'
           )
    ) then
        raise exception 'Telegram source-ingest revision 1 conflicts with the expected baseline';
    end if;
end
$telegram_revision_guard$;

insert into bursawatch_schedule_revisions
    (job_id, revision, enabled, interval_seconds, timezone, schedule_sha256, actor_id)
values
    ('bursawatch-tg-source-ingest', 1, true, 60, 'Asia/Jakarta',
     '93bc1ebe79de7f5d1d1fa598dddaa4e8c88cd9d5e5b629e2a9d0779633165c57',
     'source-baseline')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 1,
       applied_schedule_revision = null,
       reconciliation_status = 'pending',
       reconciliation_error = null,
       updated_at = now()
 where job_id = 'bursawatch-tg-source-ingest'
   and current_schedule_revision is null;

-- These are exactly the job relationships declared in operator_inventory.py.
insert into bursawatch_component_jobs (component_id, job_id)
values
    ('bursawatch-tg-source-ingest', 'bursawatch-tg-source-ingest'),
    ('bursawatch-tg-market-news', 'bursawatch-tg-source-ingest'),
    ('bursawatch-tg-phintraco-swing', 'bursawatch-tg-source-ingest'),
    ('bursawatch-tg-kelas-investasi-gtw', 'bursawatch-tg-source-ingest'),
    ('bursawatch-x-source-ingest', 'bursawatch-x-account-watch-source'),
    ('bursawatch-x-account-watch', 'bursawatch-x-account-watch-source'),
    ('bursawatch-x-account-watch', 'bursawatch-x-account-watch-queue-worker'),
    ('bursawatch-ig-account-watch', 'bursawatch-ig-account-watch-source'),
    ('bursawatch-wa-source-ingest', 'bursawatch-wa-channel-watch'),
    ('bursawatch-wa-channel-watch', 'bursawatch-wa-channel-watch'),
    ('bursawatch-rss-source-ingest', 'bursawatch-stockbit-snips'),
    ('bursawatch-stockbit-snips', 'bursawatch-stockbit-snips'),
    ('bursawatch-tg-market-news', 'bursawatch-tg-market-news'),
    ('bursawatch-tg-phintraco-swing', 'bursawatch-tg-phintraco-swing'),
    ('bursawatch-tg-kelas-investasi-gtw', 'bursawatch-tg-kelas-investasi-gtw'),
    ('bursawatch-dc-swing-board', 'bursawatch-dc-swing-board-close'),
    ('bursawatch-dc-swing-board', 'bursawatch-dc-swing-board-retry'),
    ('bursawatch-dc-swing-board', 'bursawatch-dc-swing-board-lifecycle'),
    ('bursawatch-tg-market-news', 'bursawatch-tg-market-news-watchdog')
on conflict (component_id, job_id) do nothing;
