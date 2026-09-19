-- Desired schedules are operator intent. They do not mutate Hermes directly.
-- A separately deployed VPS reconciler must report an applied revision before
-- the API or web application treats a change as effective.

create table if not exists bursawatch_scheduler_jobs (
    job_id text primary key,
    watcher_id text not null references bursawatch_watchers(watcher_id),
    display_name text not null,
    runtime_job_key text not null,
    schedule_kind text not null check (schedule_kind in ('interval', 'fixed')),
    min_interval_seconds integer,
    max_interval_seconds integer,
    current_schedule_revision bigint,
    applied_schedule_revision bigint,
    reconciliation_status text not null default 'not_connected'
        check (reconciliation_status in ('not_connected', 'pending', 'applied', 'error')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (schedule_kind = 'interval'
            and min_interval_seconds is not null
            and max_interval_seconds is not null
            and min_interval_seconds <= max_interval_seconds)
        or (schedule_kind = 'fixed'
            and min_interval_seconds is null
            and max_interval_seconds is null)
    )
);

create table if not exists bursawatch_schedule_revisions (
    job_id text not null references bursawatch_scheduler_jobs(job_id),
    revision bigint not null,
    enabled boolean not null,
    interval_seconds integer not null check (interval_seconds between 60 and 86400 and interval_seconds % 60 = 0),
    timezone text not null,
    schedule_sha256 text not null check (length(schedule_sha256) = 64),
    actor_id text not null,
    created_at timestamptz not null default now(),
    primary key (job_id, revision)
);

alter table bursawatch_scheduler_jobs
    drop constraint if exists bursawatch_scheduler_jobs_current_schedule_revision_fkey;

alter table bursawatch_scheduler_jobs
    add constraint bursawatch_scheduler_jobs_current_schedule_revision_fkey
    foreign key (job_id, current_schedule_revision)
    references bursawatch_schedule_revisions(job_id, revision)
    deferrable initially deferred;

create index if not exists bursawatch_scheduler_jobs_watcher_idx
    on bursawatch_scheduler_jobs (watcher_id, job_id);

insert into bursawatch_scheduler_jobs
    (job_id, watcher_id, display_name, runtime_job_key, schedule_kind, min_interval_seconds, max_interval_seconds)
values
    ('bursawatch-x-account-watch-source', 'bursawatch-x-account-watch', 'X Account Watch source poller', 'x-post-source', 'interval', 600, 86400),
    ('bursawatch-x-account-watch-queue-worker', 'bursawatch-x-account-watch', 'X Account Watch queue worker', 'x-post-queue-worker', 'fixed', null, null),
    ('bursawatch-ig-account-watch-source', 'bursawatch-ig-account-watch', 'Instagram Account Watch source poller', 'bursawatch-ig-account-watch', 'interval', 3600, 86400),
    ('bursawatch-tg-phintraco-swing', 'bursawatch-tg-phintraco-swing', 'Telegram Phintraco Swing', 'bursawatch-tg-phintraco-swing', 'interval', 60, 3600),
    ('bursawatch-dc-swing-board-close', 'bursawatch-dc-swing-board', 'Discord Swing Board close', 'bursawatch-dc-swing-board-close', 'fixed', null, null),
    ('bursawatch-dc-swing-board-retry', 'bursawatch-dc-swing-board', 'Discord Swing Board retry', 'bursawatch-dc-swing-board-retry', 'fixed', null, null)
on conflict (job_id) do update
    set watcher_id = excluded.watcher_id,
        display_name = excluded.display_name,
        runtime_job_key = excluded.runtime_job_key,
        schedule_kind = excluded.schedule_kind,
        min_interval_seconds = excluded.min_interval_seconds,
        max_interval_seconds = excluded.max_interval_seconds,
        updated_at = now();

insert into bursawatch_schedule_revisions
    (job_id, revision, enabled, interval_seconds, timezone, schedule_sha256, actor_id)
values
    ('bursawatch-x-account-watch-source', 1, true, 600, 'Asia/Jakarta', 'b0e45457dea1397b7d13bf54538dd8d2d4af2fa07b25a4a92e3a495723850235', 'source-baseline'),
    ('bursawatch-ig-account-watch-source', 1, true, 3600, 'Asia/Jakarta', '4fdc76e460655c9a3b9103567df070bf0d2a5dae5dd3f8fdd5c98b80c106d6e9', 'source-baseline'),
    ('bursawatch-tg-phintraco-swing', 1, true, 60, 'Asia/Jakarta', '93bc1ebe79de7f5d1d1fa598dddaa4e8c88cd9d5e5b629e2a9d0779633165c57', 'source-baseline')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 1,
       reconciliation_status = 'not_connected',
       applied_schedule_revision = null,
       updated_at = now()
 where job_id in (
    'bursawatch-x-account-watch-source',
    'bursawatch-ig-account-watch-source',
    'bursawatch-tg-phintraco-swing'
 )
   and current_schedule_revision is null;
