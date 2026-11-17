-- bursawatch-release: manual

-- Register Wall St Engine (@wallstengine) as a system-owned X people/org source, with the same
-- capability compatibility and x_post_route dispatch group as every other reviewed X endpoint.
-- The X, Telegram and RSS source intakes are pinned to a reviewed catalog state, so this registration is only safe as
-- one step of the reviewed revision 10 to 11 cutover (X generation edge, Telegram and RSS
-- compatible transitions) described in cron-x-account-watch/AGENTS.md. It adds registry rows
-- only: no subscription exists until the catalog configuration enables one.
do $migration$
begin
    if exists (select 1 from bursawatch_source_publishers where publisher_id = 'x-wallstengine')
       or exists (select 1 from bursawatch_source_endpoints where endpoint_id = 'x:wallstengine')
       or exists (select 1 from bursawatch_source_endpoints where platform = 'x' and address = 'wallstengine') then
        raise exception 'Wall St Engine X source identity already exists';
    end if;
    if (select count(*) from bursawatch_source_capabilities
         where capability_id in ('company_news', 'macro_news', 'swing_chart_context')) <> 3 then
        raise exception 'X route capabilities are unavailable';
    end if;
end
$migration$;

insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier)
values ('x-wallstengine', 'people_org', 'Wall St Engine', null, 3);

insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id)
values ('x:wallstengine', 'x-wallstengine', 'x', 'wallstengine', null);

insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:wallstengine', 'swing_chart_context', 'x_post_route');
insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:wallstengine', 'company_news', 'x_post_route');
insert into bursawatch_source_compatibility (endpoint_id, capability_id, dispatch_group) values ('x:wallstengine', 'macro_news', 'x_post_route');
