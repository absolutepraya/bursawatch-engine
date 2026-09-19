-- Desired schedules are operator intent only. This migration does not change
-- the Hermes registry. A trusted VPS reconciler must report an applied
-- revision before any of these values are effective.

insert into bursawatch_scheduler_jobs
    (job_id, watcher_id, display_name, runtime_job_key, schedule_kind, min_interval_seconds, max_interval_seconds)
values
    ('bursawatch-tg-market-news', 'bursawatch-tg-market-news', 'Telegram Market News', 'bursawatch-tg-market-news', 'interval', 60, 3600),
    ('bursawatch-tg-kelas-investasi-gtw', 'bursawatch-tg-kelas-investasi-gtw', 'Telegram Kelas Investasi GTW', 'bursawatch-tg-kelas-investasi-gtw', 'interval', 300, 21600),
    ('bursawatch-wa-channel-watch', 'bursawatch-wa-channel-watch', 'WhatsApp Channel Watch', 'bursawatch-wa-channel-watch', 'interval', 60, 21600)
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
    ('bursawatch-tg-market-news', 1, true, 60, 'Asia/Jakarta', '93bc1ebe79de7f5d1d1fa598dddaa4e8c88cd9d5e5b629e2a9d0779633165c57', 'source-baseline'),
    ('bursawatch-tg-kelas-investasi-gtw', 1, true, 3600, 'Asia/Jakarta', '4fdc76e460655c9a3b9103567df070bf0d2a5dae5dd3f8fdd5c98b80c106d6e9', 'source-baseline'),
    ('bursawatch-wa-channel-watch', 1, false, 60, 'Asia/Jakarta', 'e11f939258d82717a8c933c02b940db30b3b6e70c8ae46557109272917eb3ed8', 'source-baseline')
on conflict (job_id, revision) do nothing;

update bursawatch_scheduler_jobs
   set current_schedule_revision = 1,
       reconciliation_status = 'not_connected',
       applied_schedule_revision = null,
       updated_at = now()
 where job_id in (
    'bursawatch-tg-market-news',
    'bursawatch-tg-kelas-investasi-gtw',
    'bursawatch-wa-channel-watch'
 )
   and current_schedule_revision is null;
