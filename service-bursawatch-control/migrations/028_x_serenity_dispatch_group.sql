-- bursawatch-release: manual

-- Migration 027 registered Serenity's compatibility rows without their stored
-- dispatch group, because the column only existed for the endpoints present when
-- migration 017 ran. Put his X route capabilities in the same exclusive group as
-- every other X endpoint. No subscription is enabled by this change.
update bursawatch_source_compatibility
set dispatch_group = 'x_post_route'
where endpoint_id = 'x:aleabitoreddit'
  and capability_id in ('company_news', 'macro_news', 'swing_chart_context')
  and dispatch_group is null;
