-- bursawatch-release: manual
-- Additive, forward-only owner additions to the one publication cutover. The original
-- cutover row and its fixed owner set stay immutable. An owner introduced later gets its
-- own append-only boundary, so only its confirmed post-boundary output is accepted.
create table bursawatch_publication_cutover_owners (
    owner_id text primary key,
    boundary_at timestamptz not null,
    created_at timestamptz not null default now()
);

create trigger bursawatch_publication_cutover_owners_immutable
    before update or delete on bursawatch_publication_cutover_owners
    for each row execute function bursawatch_reject_publication_mutation();

alter table bursawatch_publication_cutover_owners enable row level security;

revoke all privileges on table public.bursawatch_publication_cutover_owners from public;
do $revoke_publication_owners$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all privileges on table public.bursawatch_publication_cutover_owners from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all privileges on table public.bursawatch_publication_cutover_owners from authenticated;
    end if;
end
$revoke_publication_owners$;
