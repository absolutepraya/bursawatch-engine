-- bursawatch-release: automatic

create table bursawatch_supported_securities (
    symbol text primary key check (symbol ~ '^[A-Z]{4}$'),
    name text not null,
    exchange text not null check (exchange = 'IDX')
);
create table bursawatch_source_publishers (
    publisher_id text primary key,
    category text not null check (category in ('institution', 'people_org')),
    name text not null,
    kind text,
    source_tier smallint not null check (source_tier between 1 and 3),
    system_owned boolean not null default true
);
create table bursawatch_source_endpoints (
    endpoint_id text primary key,
    publisher_id text not null references bursawatch_source_publishers(publisher_id),
    platform text not null check (platform in ('telegram', 'x', 'instagram', 'whatsapp', 'rss')),
    address text not null,
    provider_id text,
    system_owned boolean not null default true,
    unique (platform, address)
);
create table bursawatch_source_capabilities (
    capability_id text primary key,
    label text not null,
    pipeline_id text not null,
    capability_version integer not null check (capability_version > 0)
);
create table bursawatch_source_compatibility (
    endpoint_id text not null references bursawatch_source_endpoints(endpoint_id),
    capability_id text not null references bursawatch_source_capabilities(capability_id),
    primary key (endpoint_id, capability_id)
);
create table bursawatch_source_catalog_revisions (
    revision bigint primary key check (revision > 0),
    config jsonb not null,
    config_sha256 text not null check (length(config_sha256) = 64),
    actor_id text not null,
    created_at timestamptz not null default now()
);
create table bursawatch_source_selections (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    symbol text not null references bursawatch_supported_securities(symbol),
    primary key (revision, symbol)
);
create table bursawatch_source_people_org_revisions (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    publisher_id text not null,
    name text not null,
    kind text not null check (kind in ('person', 'group', 'community')),
    asset_ref jsonb,
    primary key (revision, publisher_id)
);
create table bursawatch_source_endpoint_revisions (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    endpoint_id text not null,
    publisher_id text not null,
    platform text not null check (platform in ('telegram', 'x', 'instagram', 'whatsapp')),
    address text not null,
    credential_ref text,
    primary key (revision, endpoint_id),
    foreign key (revision, publisher_id) references bursawatch_source_people_org_revisions(revision, publisher_id)
);
create table bursawatch_source_publisher_defaults (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    publisher_id text not null,
    capability_id text not null references bursawatch_source_capabilities(capability_id),
    enabled boolean not null,
    settings jsonb not null,
    primary key (revision, publisher_id, capability_id)
);
create table bursawatch_source_endpoint_overrides (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    endpoint_id text not null,
    capability_id text not null references bursawatch_source_capabilities(capability_id),
    enabled boolean not null,
    settings jsonb not null,
    primary key (revision, endpoint_id, capability_id)
);
create table bursawatch_source_catalog_audit (
    audit_id bigint generated always as identity primary key,
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    actor_id text not null,
    action text not null,
    details jsonb not null,
    created_at timestamptz not null default now()
);
create table bursawatch_source_asset_refs (
    revision bigint not null references bursawatch_source_catalog_revisions(revision),
    publisher_id text not null,
    asset_kind text not null check (asset_kind in ('banner', 'logo', 'profile_picture')),
    public_url text not null check (public_url ~ '^https://'),
    provenance text not null,
    created_at timestamptz not null default now(),
    primary key (revision, publisher_id, asset_kind)
);

insert into bursawatch_source_publishers (publisher_id, category, name, source_tier) values ('phintraco', 'institution', 'Phintraco Sekuritas', 1);
insert into bursawatch_source_publishers (publisher_id, category, name, source_tier) values ('bri-danareksa', 'institution', 'BRI Danareksa Sekuritas', 3);
insert into bursawatch_source_publishers (publisher_id, category, name, source_tier) values ('tuntun', 'institution', 'Tuntun Sekuritas', 3);
insert into bursawatch_source_publishers (publisher_id, category, name, source_tier) values ('samuel-sekuritas', 'institution', 'Samuel Sekuritas Indonesia', 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('kelas-investasi', 'people_org', 'Kelas Investasi', null, 2);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('stockbit', 'people_org', 'Stockbit', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-kutekians', 'people_org', 'Almer Sad, CFA', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-rickyho1989', 'people_org', 'Ricky Ho', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-writingtorch', 'people_org', 'Torch', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-arvinhonami', 'people_org', 'Arvin Honami', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-insidertracker', 'people_org', 'Insider Tracker', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-doktermarket', 'people_org', 'DokterMarket', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-txthariansaham', 'people_org', 'Ga Cuan Ga tidur', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-wavetiga', 'people_org', 'Andriy', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-aldotjahjadi8', 'people_org', 'IHSG Journal 🍀🌞', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('x-kobeissiletter', 'people_org', 'The Kobeissi Letter', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-beyondthefundamental', 'people_org', 'Beyond thy Fundamental', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-investart_id', 'people_org', 'Investart', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-avenirresearch_id', 'people_org', 'Avenir Research', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-acresresearch', 'people_org', 'Acres Research', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-sectorsapp', 'people_org', 'Sectors', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-cukhurukuque', 'people_org', 'Cukhurukuque', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('instagram-notintofinance', 'people_org', 'NIFI', null, 3);
insert into bursawatch_source_publishers (publisher_id, category, name, kind, source_tier) values ('whatsapp-ins', 'people_org', 'INS', null, 3);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:kutekians', 'x-kutekians', 'x', 'Kutekians', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:rickyho_1989', 'x-rickyho1989', 'x', 'rickyho_1989', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:writingtorch', 'x-writingtorch', 'x', 'writingtorch', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:arvinhonami', 'x-arvinhonami', 'x', 'ArvinHonami', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:insidertrackx', 'x-insidertracker', 'x', 'InsiderTrackX', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:doktermarket', 'x-doktermarket', 'x', 'doktermarket', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:txthariansaham', 'x-txthariansaham', 'x', 'txthariansaham', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:wavetiga', 'x-wavetiga', 'x', 'wavetiga', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:aldotjahjadi8', 'x-aldotjahjadi8', 'x', 'aldotjahjadi8', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('x:kobeissiletter', 'x-kobeissiletter', 'x', 'KobeissiLetter', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:beyondthefundamental', 'instagram-beyondthefundamental', 'instagram', 'beyondthefundamental', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:investart_id', 'instagram-investart_id', 'instagram', 'investart_id', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:avenirresearch.id', 'instagram-avenirresearch_id', 'instagram', 'avenirresearch.id', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:acresresearch', 'instagram-acresresearch', 'instagram', 'acresresearch', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:sectorsapp', 'instagram-sectorsapp', 'instagram', 'sectorsapp', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:cukhurukuque', 'instagram-cukhurukuque', 'instagram', 'cukhurukuque', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('instagram:notintofinance', 'instagram-notintofinance', 'instagram', 'notintofinance', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'whatsapp-ins', 'whatsapp', 'https://whatsapp.com/channel/0029Vb6qi96ISTkJcDn4op2z', '0029Vb6qi96ISTkJcDn4op2z');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('telegram:phintraprofits', 'phintraco', 'telegram', 'phintraprofits', '1444713822');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('telegram:phintasprofits', 'phintraco', 'telegram', 'phintasprofits', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('telegram:kelasinvestasiid', 'kelas-investasi', 'telegram', 'kelasinvestasiid', '2142109618');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('telegram:tuntunsekuritas', 'tuntun', 'telegram', 'tuntunsekuritas', null);
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('whatsapp:0029VbAjdnb60eBhwVdJxj1c', 'bri-danareksa', 'whatsapp', 'https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c', '0029VbAjdnb60eBhwVdJxj1c');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('whatsapp:0029VagNdGpFMqrXKEcdBb2U', 'samuel-sekuritas', 'whatsapp', 'https://whatsapp.com/channel/0029VagNdGpFMqrXKEcdBb2U', '0029VagNdGpFMqrXKEcdBb2U');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('rss:stockbit:stockbit_commentary', 'stockbit', 'rss', 'stockbit_commentary', 'stockbit_commentary');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('rss:stockbit:unboxing', 'stockbit', 'rss', 'unboxing', 'unboxing');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('rss:stockbit:unboxing_ipo', 'stockbit', 'rss', 'unboxing_ipo', 'unboxing_ipo');
insert into bursawatch_source_endpoints (endpoint_id, publisher_id, platform, address, provider_id) values ('rss:stockbit:ai_reports_stockbit', 'stockbit', 'rss', 'ai_reports_stockbit', 'ai_reports_stockbit');
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('trading_plans', 'Trading Plans', 'swing_plan', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('swing_support', 'Swing Supporting Setup', 'swing_support', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('swing_chart_context', 'Swing Chart Context', 'swing_chart_context', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('company_news', 'Company/Stock News', 'company_news', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('macro_news', 'Macro News', 'macro_news', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('stock_status', 'Stock Information/Stock Status', 'stock_status', 1);
insert into bursawatch_source_capabilities (capability_id, label, pipeline_id, capability_version) values ('stockbit_snips', 'Stockbit Snips', 'stockbit_snips', 1);
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:kutekians', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:kutekians', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:rickyho_1989', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:rickyho_1989', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:writingtorch', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:writingtorch', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:arvinhonami', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:arvinhonami', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:insidertrackx', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:insidertrackx', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:doktermarket', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:doktermarket', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:txthariansaham', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:txthariansaham', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:wavetiga', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:wavetiga', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:aldotjahjadi8', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:aldotjahjadi8', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:kobeissiletter', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('x:kobeissiletter', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:beyondthefundamental', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:beyondthefundamental', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:investart_id', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:investart_id', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:avenirresearch.id', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:avenirresearch.id', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:acresresearch', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:acresresearch', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:sectorsapp', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:sectorsapp', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:cukhurukuque', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:cukhurukuque', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:notintofinance', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('instagram:notintofinance', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:phintraprofits', 'trading_plans');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:phintasprofits', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:phintasprofits', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:phintasprofits', 'stock_status');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:kelasinvestasiid', 'swing_support');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:tuntunsekuritas', 'company_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('telegram:tuntunsekuritas', 'macro_news');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('whatsapp:0029VbAjdnb60eBhwVdJxj1c', 'swing_chart_context');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('rss:stockbit:stockbit_commentary', 'stockbit_snips');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('rss:stockbit:unboxing', 'stockbit_snips');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('rss:stockbit:unboxing_ipo', 'stockbit_snips');
insert into bursawatch_source_compatibility (endpoint_id, capability_id) values ('rss:stockbit:ai_reports_stockbit', 'stockbit_snips');
insert into bursawatch_source_catalog_revisions (revision, config, config_sha256, actor_id) values (1, '{"selected_securities":[],"people_org":[],"endpoints":[],"publisher_defaults":[],"endpoint_overrides":[]}'::jsonb, '90914b1d34a991b07c055735047d06a254120eafcc2bfac6067eacbeed3625e1', 'source-baseline');

alter table bursawatch_supported_securities enable row level security;
revoke all privileges on table bursawatch_supported_securities from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_supported_securities from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_supported_securities from authenticated; end if; end $$;
alter table bursawatch_source_publishers enable row level security;
revoke all privileges on table bursawatch_source_publishers from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_publishers from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_publishers from authenticated; end if; end $$;
alter table bursawatch_source_endpoints enable row level security;
revoke all privileges on table bursawatch_source_endpoints from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_endpoints from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_endpoints from authenticated; end if; end $$;
alter table bursawatch_source_capabilities enable row level security;
revoke all privileges on table bursawatch_source_capabilities from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_capabilities from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_capabilities from authenticated; end if; end $$;
alter table bursawatch_source_compatibility enable row level security;
revoke all privileges on table bursawatch_source_compatibility from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_compatibility from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_compatibility from authenticated; end if; end $$;
alter table bursawatch_source_catalog_revisions enable row level security;
revoke all privileges on table bursawatch_source_catalog_revisions from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_catalog_revisions from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_catalog_revisions from authenticated; end if; end $$;
alter table bursawatch_source_catalog_audit enable row level security;
revoke all privileges on table bursawatch_source_catalog_audit from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_catalog_audit from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_catalog_audit from authenticated; end if; end $$;
alter table bursawatch_source_asset_refs enable row level security;
revoke all privileges on table bursawatch_source_asset_refs from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_asset_refs from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_asset_refs from authenticated; end if; end $$;
alter table bursawatch_source_selections enable row level security;
revoke all privileges on table bursawatch_source_selections from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_selections from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_selections from authenticated; end if; end $$;
alter table bursawatch_source_people_org_revisions enable row level security;
revoke all privileges on table bursawatch_source_people_org_revisions from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_people_org_revisions from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_people_org_revisions from authenticated; end if; end $$;
alter table bursawatch_source_endpoint_revisions enable row level security;
revoke all privileges on table bursawatch_source_endpoint_revisions from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_endpoint_revisions from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_endpoint_revisions from authenticated; end if; end $$;
alter table bursawatch_source_publisher_defaults enable row level security;
revoke all privileges on table bursawatch_source_publisher_defaults from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_publisher_defaults from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_publisher_defaults from authenticated; end if; end $$;
alter table bursawatch_source_endpoint_overrides enable row level security;
revoke all privileges on table bursawatch_source_endpoint_overrides from public;
do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then revoke all privileges on table bursawatch_source_endpoint_overrides from anon; end if; if exists (select 1 from pg_roles where rolname = 'authenticated') then revoke all privileges on table bursawatch_source_endpoint_overrides from authenticated; end if; end $$;
