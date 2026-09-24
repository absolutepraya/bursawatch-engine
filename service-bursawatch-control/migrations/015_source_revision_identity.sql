-- bursawatch-release: automatic

alter table bursawatch_source_event_versions add column revision_id text;
create unique index bursawatch_source_event_revision_identity
    on bursawatch_source_event_versions (event_key, revision_id)
    where revision_id is not null;
alter table bursawatch_source_work drop constraint bursawatch_source_work_status_check;
alter table bursawatch_source_work add constraint bursawatch_source_work_status_check
    check (status in ('pending','leased','done','dead_letter','suppressed','superseded'));
