-- bursawatch-release: automatic

create table if not exists bursawatch_profile_avatars (
    watcher_id text not null references bursawatch_watchers(watcher_id),
    profile_id text not null,
    handle text not null,
    display_name text not null,
    profile_url text not null,
    enabled boolean not null,
    avatar_mode text not null default 'auto'
        check (avatar_mode in ('auto', 'manual')),
    avatar_url text
        check (avatar_url is null or char_length(avatar_url) between 1 and 2048),
    avatar_source text
        check (avatar_source is null or char_length(avatar_source) between 1 and 64),
    fetched_at timestamptz,
    last_success_at timestamptz,
    last_error text
        check (last_error is null or char_length(last_error) between 1 and 500),
    updated_at timestamptz not null default now(),
    primary key (watcher_id, profile_id)
);

create index if not exists bursawatch_profile_avatars_refresh_idx
    on bursawatch_profile_avatars (watcher_id, last_success_at)
    where avatar_mode = 'auto';

alter table bursawatch_profile_avatars enable row level security;

do $$
begin
    execute 'revoke all privileges on table public.bursawatch_profile_avatars from public';
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all privileges on table public.bursawatch_profile_avatars from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all privileges on table public.bursawatch_profile_avatars from authenticated';
    end if;
end;
$$;
