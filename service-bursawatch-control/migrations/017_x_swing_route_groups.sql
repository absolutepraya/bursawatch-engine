-- bursawatch-release: automatic

alter table bursawatch_source_compatibility
    add column dispatch_group text,
    add constraint source_compatibility_dispatch_group_check
        check (dispatch_group is null or dispatch_group ~ '^[a-z][a-z0-9_]{0,63}$');

insert into bursawatch_source_compatibility (endpoint_id, capability_id)
select endpoint_id, 'swing_chart_context'
from bursawatch_source_endpoints
where platform = 'x';

update bursawatch_source_compatibility as compatibility
set dispatch_group = 'x_post_route'
from bursawatch_source_endpoints as endpoint
where endpoint.endpoint_id = compatibility.endpoint_id
  and endpoint.platform = 'x'
  and compatibility.capability_id in ('company_news', 'macro_news', 'swing_chart_context');

alter table bursawatch_source_work
    add column dispatch_context jsonb not null default '{}'::jsonb,
    add constraint source_work_dispatch_context_object_check
        check (jsonb_typeof(dispatch_context) = 'object');
