-- bursawatch-release: automatic

insert into bursawatch_source_compatibility (endpoint_id, capability_id)
values
    ('whatsapp:0029VbAjdnb60eBhwVdJxj1c', 'company_news'),
    ('whatsapp:0029VbAjdnb60eBhwVdJxj1c', 'macro_news')
on conflict (endpoint_id, capability_id) do nothing;
