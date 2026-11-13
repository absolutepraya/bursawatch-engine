-- bursawatch-release: manual

-- Register Serenity (@aleabitoreddit) as a system-owned X people/org source with the
-- same capability compatibility as every other reviewed X endpoint. This adds registry
-- rows only: no effective subscription exists until a catalog configuration revision
-- enables one, so intake of this account stays off until that separate step.
do $migration$
begin
    if exists (select 1 from bursawatch_source_publishers where publisher_id = 'x-aleabitoreddit')
       or exists (select 1 from bursawatch_source_endpoints where endpoint_id = 'x:aleabitoreddit')
       or exists (select 1 from bursawatch_source_endpoints where platform = 'x' and address = 'aleabitoreddit') then
        raise exception 'Serenity X source identity already exists';
    end if;
    if (select count(*) from bursawatch_source_capabilities
         where capability_id in ('company_news', 'macro_news', 'swing_chart_context')) <> 3 then
        raise exception 'X route capabilities are unavailable';
    end if;
end
$migration$;

insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier)
values ('x-aleabitoreddit', 'people_org', 'Serenity', null, 3);

insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id)
values ('x:aleabitoreddit', 'x-aleabitoreddit', 'x', 'aleabitoreddit', null);

insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:aleabitoreddit', 'swing_chart_context');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:aleabitoreddit', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:aleabitoreddit', 'macro_news');
