-- The live Instagram watcher is intentionally paused. Preserve that established
-- state before the reconciler first reports the catalogued desired schedules.
-- This only corrects source-owned baseline intent; it does not edit Hermes.

insert into bursawatch_schedule_revisions
    (job_id, revision, enabled, interval_seconds, timezone, schedule_sha256, actor_id)
values
    ('bursawatch-ig-account-watch-source', 2, false, 3600, 'Asia/Jakarta', '9a9502a843756bc7dbea26fe1265a811ec314454a7901d0b72c4e60e1ecd2855', 'source-baseline-correction')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 2,
       applied_schedule_revision = null,
       reconciliation_status = 'not_connected',
       reconciliation_error = null,
       updated_at = now()
 where job_id = 'bursawatch-ig-account-watch-source'
   and current_schedule_revision = 1;
