-- bursawatch-release: manual

-- Register Serenity (@aleabitoreddit) as a system-owned X people/org source, with the same
-- capability compatibility and x_post_route dispatch group as every other reviewed X endpoint.
-- Migrations 027 to 029 registered and rolled back an earlier attempt; the X and Telegram
-- source intakes are pinned to a reviewed catalog state, so this registration is only safe as
-- one step of the reviewed revision 8 to 9 cutover (X generation edge, Telegram and RSS
-- compatible transitions) described in cron-x-account-watch/AGENTS.md. It adds registry rows
-- only: no subscription exists until the catalog configuration enables one.
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

insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:aleabitoreddit', 'swing_chart_context', 'x_post_route');
insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:aleabitoreddit', 'company_news', 'x_post_route');
insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:aleabitoreddit', 'macro_news', 'x_post_route');
