-- bursawatch-release: manual

-- Migration 011 registered the watcher identity as the Hermes job name.
-- Keep the schedule row and revision intact, but point reconciliation at the
-- exact existing Hermes cron name.
do $migration$
declare
    registered_runtime_job_key text;
begin
    select runtime_job_key
      into registered_runtime_job_key
      from bursawatch_scheduler_jobs
     where job_id = 'bursawatch-stockbit-snips'
     for update;

    if not found then
        raise exception 'Stockbit scheduler job is missing';
    end if;

    if registered_runtime_job_key is null or registered_runtime_job_key not in (
        'bursawatch-stockbit-snips',
        'cron-stockbit-snips'
    ) then
        raise exception 'Stockbit scheduler job key changed unexpectedly';
    end if;

    if registered_runtime_job_key = 'bursawatch-stockbit-snips' then
        update bursawatch_scheduler_jobs
           set runtime_job_key = 'cron-stockbit-snips',
               updated_at = now()
         where job_id = 'bursawatch-stockbit-snips';
    end if;
end;
$migration$;
