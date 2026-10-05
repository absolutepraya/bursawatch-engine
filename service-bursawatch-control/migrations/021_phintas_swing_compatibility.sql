-- bursawatch-release: automatic

do $$
begin
    if not exists (
        select 1 from bursawatch_source_endpoints
        where endpoint_id = 'telegram:phintasprofits'
          and publisher_id = 'phintraco'
          and platform = 'telegram'
          and address = 'phintasprofits'
          and provider_id is null
    ) then
        raise exception 'canonical Phintas Telegram endpoint is unavailable';
    end if;
    if not exists (
        select 1 from bursawatch_source_capabilities
        where capability_id = 'trading_plans'
          and pipeline_id = 'swing_plan'
    ) then
        raise exception 'trading_plans capability is unavailable';
    end if;
end $$;

insert into bursawatch_source_compatibility (endpoint_id, capability_id)
values ('telegram:phintasprofits', 'trading_plans');
