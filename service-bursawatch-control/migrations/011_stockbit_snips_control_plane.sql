-- bursawatch-release: manual

-- Mirror the existing 15-minute Hermes job as desired schedule state only.
-- The reconciler must report an applied revision before it is effective.
insert into bursawatch_watchers (watcher_id, display_name, validator_key)
values
    ('bursawatch-stockbit-snips', 'Stockbit Snips', 'bursawatch-stockbit-snips')
on conflict (watcher_id) do update
    set display_name = excluded.display_name,
        validator_key = excluded.validator_key,
        updated_at = now();

insert into bursawatch_scheduler_jobs
    (job_id, watcher_id, display_name, runtime_job_key, schedule_kind, min_interval_seconds, max_interval_seconds)
values
    ('bursawatch-stockbit-snips', 'bursawatch-stockbit-snips', 'Stockbit Snips', 'bursawatch-stockbit-snips', 'interval', 300, 3600)
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
    ('bursawatch-stockbit-snips', 1, true, 900, 'Asia/Jakarta', '7287c1843e09696920a9a9fe00f911173640134e6fabf39c7e5e08d3f94c57f9', 'source-baseline')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 1,
       reconciliation_status = 'not_connected',
       applied_schedule_revision = null,
       updated_at = now()
 where job_id = 'bursawatch-stockbit-snips'
   and current_schedule_revision is null;
