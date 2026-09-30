-- bursawatch-release: automatic

-- Forward-only, owner-submitted projection of confirmed public output. The
-- source owners and Discord Delivery Owner keep their existing state and
-- authority. This migration does not import historical messages or runs.
create table bursawatch_publication_cutover (
    singleton boolean primary key default true check (singleton),
    boundary_at timestamptz not null,
    owner_ids jsonb not null check (jsonb_typeof(owner_ids) = 'array'),
    created_at timestamptz not null default now()
);

create table bursawatch_publications (
    publication_id text not null check (publication_id ~ '^[0-9a-f]{64}$'),
    version integer not null check (version between 1 and 1000000),
    owner_id text not null,
    owner_key text not null,
    publication_type text not null,
    route text not null,
    source_name text not null,
    ticker text,
    delivery_confirmed_at timestamptz not null,
    parent_publication_id text,
    digest text not null check (digest ~ '^[0-9a-f]{64}$'),
    snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
    accepted_at timestamptz not null default now(),
    primary key (publication_id, version),
    unique (owner_id, owner_key, version)
);

create index bursawatch_publications_page_idx
    on bursawatch_publications (delivery_confirmed_at desc, publication_id desc, version desc);
create index bursawatch_publications_owner_idx
    on bursawatch_publications (owner_id, publication_id, version desc);
create index bursawatch_publications_parent_idx
    on bursawatch_publications (parent_publication_id, delivery_confirmed_at)
    where parent_publication_id is not null;

create table bursawatch_publication_checkpoints (
    owner_id text primary key,
    compared_at timestamptz not null,
    confirmed_through_at timestamptz,
    accepted_through_at timestamptz,
    outstanding_count integer not null check (outstanding_count >= 0),
    received_at timestamptz not null default now()
);

-- A publication version and the one cutover boundary are append-only. An
-- owner correction inserts a new version instead of mutating accepted output.
create function bursawatch_reject_publication_mutation() returns trigger
language plpgsql as $$
begin
    raise exception 'published record is immutable';
end;
$$;

create trigger bursawatch_publications_immutable
    before update or delete on bursawatch_publications
    for each row execute function bursawatch_reject_publication_mutation();
create trigger bursawatch_publication_cutover_immutable
    before update or delete on bursawatch_publication_cutover
    for each row execute function bursawatch_reject_publication_mutation();

alter table bursawatch_publication_cutover enable row level security;
alter table bursawatch_publications enable row level security;
alter table bursawatch_publication_checkpoints enable row level security;

revoke all privileges on table public.bursawatch_publication_cutover from public;
revoke all privileges on table public.bursawatch_publications from public;
revoke all privileges on table public.bursawatch_publication_checkpoints from public;
do $revoke_publications$
declare
    table_name text;
begin
    for table_name in
        select unnest(array[
            'bursawatch_publication_cutover',
            'bursawatch_publications',
            'bursawatch_publication_checkpoints'
        ])
    loop
        if exists (select 1 from pg_roles where rolname = 'anon') then
            execute format('revoke all privileges on table public.%I from anon', table_name);
        end if;
        if exists (select 1 from pg_roles where rolname = 'authenticated') then
            execute format('revoke all privileges on table public.%I from authenticated', table_name);
        end if;
    end loop;
end
$revoke_publications$;
