-- bursawatch-release: automatic

-- Link the existing morning job to its workflow. Schedule and configuration
-- revisions stay authoritative; this metadata link never enables a job.
insert into bursawatch_component_jobs (component_id, job_id)
values ('bursawatch-dc-morning-brief', 'bursawatch-dc-morning-brief')
on conflict (component_id, job_id) do nothing;
