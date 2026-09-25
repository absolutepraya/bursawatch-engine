-- bursawatch-release: automatic

create table bursawatch_source_events (
    event_key text primary key check (event_key ~ '^[0-9a-f]{64}$'),
    endpoint_id text not null,
    publisher_id text not null,
    platform text not null,
    provider_event_id text not null,
    created_at timestamptz not null default now(),
    unique (platform, endpoint_id, provider_event_id)
);
create table bursawatch_source_event_versions (
    event_key text not null references bursawatch_source_events(event_key),
    version integer not null check (version > 0),
    kind text not null check (kind in ('original','correction','tombstone')),
    envelope jsonb not null,
    content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
    actor_id text,
    reason text,
    created_at timestamptz not null default now(),
    primary key (event_key, version),
    check ((kind = 'original' and version = 1 and actor_id is null and reason is null) or (kind <> 'original' and version > 1 and actor_id is not null and reason is not null))
);
create table bursawatch_source_work (
    work_key text primary key check (work_key ~ '^[0-9a-f]{64}$'),
    event_key text not null,
    version integer not null,
    capability_id text not null,
    pipeline_id text not null,
    capability_version integer not null check (capability_version > 0),
    catalog_revision bigint not null references bursawatch_source_catalog_revisions(revision),
    settings jsonb not null,
    config_source text not null check (config_source in ('publisher_default','endpoint_override')),
    effect_key text not null unique,
    status text not null default 'pending' check (status in ('pending','leased','done','dead_letter','suppressed')),
    attempts integer not null default 0 check (attempts between 0 and 5),
    available_at timestamptz not null default now(),
    lease_token text,
    lease_until timestamptz,
    error_code text check (error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz not null default now(),
    foreign key (event_key, version) references bursawatch_source_event_versions(event_key, version),
    unique (event_key, version, capability_id),
    check ((status = 'leased') = (lease_token is not null and lease_until is not null))
);
create index bursawatch_source_work_claim on bursawatch_source_work (available_at, work_key) where status in ('pending','leased');
create table bursawatch_source_work_audit (
    audit_id bigint generated always as identity primary key,
    work_key text not null references bursawatch_source_work(work_key),
    action text not null check (action in ('replay','suppress')),
    actor_id text not null,
    reason text not null check (length(reason) between 1 and 500),
    created_at timestamptz not null default now()
);

alter table bursawatch_source_events enable row level security;
alter table bursawatch_source_event_versions enable row level security;
alter table bursawatch_source_work enable row level security;
alter table bursawatch_source_work_audit enable row level security;
revoke all privileges on table bursawatch_source_events, bursawatch_source_event_versions, bursawatch_source_work, bursawatch_source_work_audit from public;
do $$ begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all privileges on table bursawatch_source_events, bursawatch_source_event_versions, bursawatch_source_work, bursawatch_source_work_audit from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all privileges on table bursawatch_source_events, bursawatch_source_event_versions, bursawatch_source_work, bursawatch_source_work_audit from authenticated;
    end if;
end $$;
