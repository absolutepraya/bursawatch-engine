-- The VPS reconciler reports the outcome of applying the current desired
-- schedule. It cannot make an older revision effective after an admin writes
-- a newer desired revision.

alter table bursawatch_scheduler_jobs
    add column if not exists reconciliation_error text;

alter table bursawatch_scheduler_jobs
    drop constraint if exists bursawatch_scheduler_jobs_reconciliation_error_length_check;

alter table bursawatch_scheduler_jobs
    add constraint bursawatch_scheduler_jobs_reconciliation_error_length_check
    check (reconciliation_error is null or length(reconciliation_error) between 1 and 500);

-- The X source poller retained an old internal logical key in migration 003.
-- Its immutable live Hermes identity is the scheduler job name below. This
-- does not edit Hermes or alter its current schedule.
update bursawatch_scheduler_jobs
   set runtime_job_key = 'bursawatch-x-account-watch',
       updated_at = now()
 where job_id = 'bursawatch-x-account-watch-source'
   and runtime_job_key = 'x-post-source';
