create table if not exists bursawatch_watchers (
    watcher_id text primary key,
    display_name text not null,
    validator_key text not null,
    current_revision bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists bursawatch_config_revisions (
    watcher_id text not null references bursawatch_watchers(watcher_id),
    revision bigint not null,
    config_version integer not null check (config_version > 0),
    config jsonb not null,
    config_sha256 text not null check (length(config_sha256) = 64),
    actor_id text not null,
    created_at timestamptz not null default now(),
    primary key (watcher_id, revision)
);

alter table bursawatch_watchers
    drop constraint if exists bursawatch_watchers_current_revision_fkey;

alter table bursawatch_watchers
    add constraint bursawatch_watchers_current_revision_fkey
    foreign key (watcher_id, current_revision)
    references bursawatch_config_revisions(watcher_id, revision)
    deferrable initially deferred;

create table if not exists bursawatch_runs (
    run_id text primary key,
    watcher_id text not null references bursawatch_watchers(watcher_id),
    scheduler_job_id text,
    trigger text not null,
    config_revision bigint not null,
    started_at timestamptz not null,
    finished_at timestamptz,
    status text not null check (status in ('running', 'ok', 'degraded', 'failed', 'blocked')),
    error text,
    foreign key (watcher_id, config_revision)
        references bursawatch_config_revisions(watcher_id, revision)
);

create table if not exists bursawatch_events (
    run_id text not null references bursawatch_runs(run_id),
    event_id text not null,
    occurred_at timestamptz not null,
    level text not null check (level in ('debug', 'info', 'warning', 'error', 'fatal')),
    phase text not null,
    event_type text not null,
    message text not null,
    attributes jsonb not null default '{}'::jsonb,
    primary key (run_id, event_id)
);

create index if not exists bursawatch_runs_watcher_started_idx
    on bursawatch_runs (watcher_id, started_at desc);

create index if not exists bursawatch_events_run_occurred_idx
    on bursawatch_events (run_id, occurred_at);
