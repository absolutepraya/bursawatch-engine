-- bursawatch-release: automatic

-- Configuration-only registration. No scheduler job, destination or enabled
-- schedule is created. Existing operator revisions remain authoritative.
insert into bursawatch_watchers (watcher_id, display_name, validator_key)
values ('bursawatch-dc-morning-brief', 'Bursawatch morning brief', 'bursawatch-dc-morning-brief')
on conflict (watcher_id) do nothing;
