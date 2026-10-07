import pytest
from sectors_client import Config, RequestIdentity, ValidationError


def test_config_is_explicit_cache_only_and_secret_repr_safe(tmp_path):
    config = Config(store_path=tmp_path / 'cache.sqlite3', caller='morning', billing_window='2026-10', caller_limit=40, api_key='private-key')
    assert config.cache_only
    assert 'private-key' not in repr(config)
    assert not config.store_path.exists()


def test_only_documented_dotenv_key_is_loaded_without_shell_execution(tmp_path):
    env = tmp_path / '.env'
    env.write_text('SECTORS_API_KEY="test-key"\nUNRELATED=$(touch forbidden)\n')
    c = Config.from_env_file(env, store_path=tmp_path / 'cache.sqlite3', caller='morning', billing_window='2026-10', caller_limit=40)
    assert c.api_key == 'test-key'
    assert not (tmp_path / 'forbidden').exists()
    env.write_text('SECTORS_API_KEY=test\nSECTORS_API_KEY=second\n')
    with pytest.raises(ValidationError):
        Config.from_env_file(env, store_path=tmp_path / 'cache.sqlite3', caller='morning', billing_window='2026-10', caller_limit=40)


def test_rejects_origin_override_and_invalid_limits(tmp_path):
    values = dict(store_path=tmp_path / 'cache.sqlite3', caller='morning', billing_window='2026-10', caller_limit=40)
    for changes in [{'origin': 'https://evil.test'}, {'host_limit': 1001}, {'caller_limit': 0}, {'timeout_seconds': 0}, {'max_bytes': 0}]:
        with pytest.raises(ValidationError):
            Config(**(values | changes))


def test_identity_canonicalizes_and_validates_dates_symbols_and_offsets():
    a = RequestIdentity('/v2/close/', {'date':'2026-10-02', 'offset':0, 'limit':30})
    b = RequestIdentity('/v2/close/', {'limit':30, 'offset':0, 'date':'2026-10-02'})
    assert a.key == b.key
    assert a.url == 'https://api.sectors.app/v2/close/?date=2026-10-02&limit=30&offset=0'
    for path, query in [('//evil.test/', {}), ('https://evil.test/', {}), ('/v2/../close/', {}), ('/v2/daily/bbca/', {}), ('/v2/close/', {'date':'2026-02-30'}), ('/v2/close/', {'date':'2026-10-02','offset':-1}), ('/v2/close/', {'date':'2026-10-02','api_key':'secret'}), ('/v2/daily/BBCA/', {'start':'2026-10-03','end':'2026-10-02'})]:
        with pytest.raises(ValidationError):
            RequestIdentity(path, query)


def test_verified_companies_query_and_typed_split_calendar_identities():
    caps=RequestIdentity('/v2/companies/', {'where':'sector IS NOT NULL','order_by':'market_cap','include_query_values':True,'offset':0,'limit':200})
    assert 'include_query_values=true' in caps.url
    split=RequestIdentity('/v2/corporate-actions/', {'type':'stock_split','start':'2026-09-01','end':'2026-10-02'})
    assert 'type=stock_split' in split.url
    for query in ({'start':'2026-09-01','end':'2026-10-02'}, {'type':'all'}, {'type':'stock_split','start':'2026-01-01','end':'2026-10-02'}):
        with pytest.raises(ValidationError):
            RequestIdentity('/v2/corporate-actions/',query)


def test_network_mode_requires_key_before_creating_coordination_state(tmp_path):
    with pytest.raises(ValidationError):
        Config(store_path=tmp_path/'cache.sqlite3',caller='morning',billing_window='oct',caller_limit=40,cache_only=False)
    assert not (tmp_path/'cache.sqlite3').exists()


def test_generation_changes_only_local_identity_and_preserves_default_keys():
    default=RequestIdentity('/v2/companies/',{'offset':0,'limit':200})
    omitted=RequestIdentity('/v2/companies/',{'limit':200,'offset':0},generation=None)
    first=RequestIdentity('/v2/companies/',{'limit':200,'offset':0},generation='caps:2026-W41')
    repeated=RequestIdentity('/v2/companies/',{'offset':0,'limit':200},generation='caps:2026-W41')
    later=RequestIdentity('/v2/companies/',{'offset':0,'limit':200},generation='caps:2026-W42')
    assert default.key==omitted.key=='c5bbf7637e13db8c32b3091af4d247d10943fe9092c2a6f2d0f2f7246dbf1fbd'
    assert default.url==omitted.url==first.url==later.url=='https://api.sectors.app/v2/companies/?limit=200&offset=0'
    assert first.key==repeated.key
    assert len({default.key,first.key,later.key})==3
    for value in ('','a'*101,'generation with spaces','../../other','secret\nvalue',3,False):
        with pytest.raises(ValidationError):
            RequestIdentity('/v2/companies/',generation=value)
