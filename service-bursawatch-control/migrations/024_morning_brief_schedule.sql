-- bursawatch-release: manual

-- Stage one paused minute tick. This never creates or activates a Hermes job.
-- Cutoff/delivery remain revisioned morning settings, not fixed cron times.
insert into bursawatch_scheduler_jobs
    (job_id, watcher_id, display_name, runtime_job_key, schedule_kind, min_interval_seconds, max_interval_seconds)
values
    ('bursawatch-dc-morning-brief', 'bursawatch-dc-morning-brief', 'Morning brief', 'bursawatch-dc-morning-brief', 'interval', 60, 60)
on conflict (job_id) do nothing;

insert into bursawatch_schedule_revisions
    (job_id, revision, enabled, interval_seconds, timezone, schedule_sha256, actor_id)
values
    ('bursawatch-dc-morning-brief', 1, false, 60, 'Asia/Jakarta', 'e11f939258d82717a8c933c02b940db30b3b6e70c8ae46557109272917eb3ed8', 'source-baseline')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 1,
       reconciliation_status = 'not_connected',
       applied_schedule_revision = null,
       updated_at = now()
 where job_id = 'bursawatch-dc-morning-brief'
   and current_schedule_revision is null;
