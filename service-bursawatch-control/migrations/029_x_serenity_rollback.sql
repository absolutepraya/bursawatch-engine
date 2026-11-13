-- bursawatch-release: manual

-- Roll Serenity's source-catalog onboarding back to the reviewed baseline.
-- X source ingest is pinned to catalog revision 8 and an exact effective projection
-- of every X registry row, and Telegram ingest to its revision-8 state marker, so
-- adding an X endpoint or publishing revision 9 fails both closed. Restore the exact
-- pre-onboarding catalog. Guarded so it refuses anything but that precise state, and
-- idempotent so it is a no-op where the same rollback was already applied.
do $migration$
declare
    latest bigint;
    prior_overrides jsonb;
    latest_overrides jsonb;
begin
    perform pg_advisory_xact_lock(71938142);
    select max(revision) into latest from bursawatch_source_catalog_revisions;
    if latest = 9 then
        select jsonb_agg(to_jsonb(o) - 'revision' order by endpoint_id, capability_id) into prior_overrides
          from bursawatch_source_endpoint_overrides o where revision = 8;
        select jsonb_agg(to_jsonb(o) - 'revision' order by endpoint_id, capability_id) into latest_overrides
          from bursawatch_source_endpoint_overrides o
         where revision = 9 and endpoint_id <> 'x:aleabitoreddit';
        if prior_overrides is distinct from latest_overrides
           or (select count(*) from bursawatch_source_endpoint_overrides
                where revision = 9 and endpoint_id = 'x:aleabitoreddit') <> 2
           or exists (select 1 from bursawatch_source_work where catalog_revision = 9)
           or exists (select 1 from bursawatch_source_selections where revision = 9)
           or exists (select 1 from bursawatch_source_people_org_revisions where revision = 9)
           or exists (select 1 from bursawatch_source_endpoint_revisions where revision = 9)
           or exists (select 1 from bursawatch_source_publisher_defaults where revision = 9)
           or exists (select 1 from bursawatch_source_asset_refs where revision = 9) then
            raise exception 'catalog revision 9 is not the reviewed Serenity-only change';
        end if;
        delete from bursawatch_source_endpoint_overrides where revision = 9;
        delete from bursawatch_source_catalog_audit where revision = 9;
        delete from bursawatch_source_catalog_revisions where revision = 9;
    elsif latest <> 8 then
        raise exception 'unexpected latest source catalog revision %', latest;
    end if;
end
$migration$;

delete from bursawatch_source_compatibility where endpoint_id = 'x:aleabitoreddit';
delete from bursawatch_source_endpoints where endpoint_id = 'x:aleabitoreddit' and publisher_id = 'x-aleabitoreddit';
delete from bursawatch_source_publishers where publisher_id = 'x-aleabitoreddit' and system_owned = true;
