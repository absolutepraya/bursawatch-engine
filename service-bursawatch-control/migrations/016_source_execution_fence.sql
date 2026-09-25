-- bursawatch-release: automatic

alter table bursawatch_source_work drop constraint bursawatch_source_work_status_check;
alter table bursawatch_source_work add constraint bursawatch_source_work_status_check
    check (status in ('pending','leased','executing','done','dead_letter','suppressed','superseded'));
do $$
declare lease_constraint text;
begin
    select conname into lease_constraint
      from pg_constraint
     where conrelid = 'bursawatch_source_work'::regclass
       and contype = 'c'
       and pg_get_constraintdef(oid) ilike '%lease_token%'
       and pg_get_constraintdef(oid) ilike '%lease_until%';
    if lease_constraint is null then
        raise exception 'source work lease constraint is missing';
    end if;
    execute format('alter table bursawatch_source_work drop constraint %I', lease_constraint);
end $$;
alter table bursawatch_source_work add constraint bursawatch_source_work_check
    check ((status in ('leased','executing')) = (lease_token is not null and lease_until is not null));
alter table bursawatch_source_work_audit drop constraint bursawatch_source_work_audit_action_check;
alter table bursawatch_source_work_audit add constraint bursawatch_source_work_audit_action_check
    check (action in ('replay','suppress','recover'));
