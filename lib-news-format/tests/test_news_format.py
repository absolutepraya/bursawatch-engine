from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest
import pandas as pd
import news_format as news


@pytest.mark.parametrize('title,route,expected', [
    ('TLKM: spin off bisnis InfraNexia', 'id_stocks_news', 'TLKM: Spin off bisnis InfraNexia'),
    ('BRK.B: earnings rise as AI grows', 'us_stocks_news', 'BRK.B: Earnings rise as AI grows'),
    ('inflasi: BI mempertahankan suku bunga', 'macro_news', 'Inflasi: BI mempertahankan suku bunga'),
    ('2027: produksi migas meningkat', 'macro_news', '2027: Produksi migas meningkat'),
    ('📰 “ekspansi InfraNexia dan GPU”', 'id_industry_news', '📰 “Ekspansi InfraNexia dan GPU”'),
    ('TLKM: AI dan InfraNexia', 'id_stocks_news', 'TLKM: AI dan InfraNexia'),
    ('', 'macro_news', ''),
    ('2027 🔼', 'macro_news', '2027 🔼'),
])
def test_new_card_headline_preserves_names_and_capitalizes_subject(title, route, expected):
    heading = f'### <:source:1531272430985937086> {title}\n-# Publisher'
    rendered = news.render_card(heading, 'Fakta bersumber.', 'https://example.invalid/news', 'Source', route=route)
    assert rendered[0].splitlines()[0] == f'### <:source:1531272430985937086> {expected}'
    assert rendered[0].splitlines()[1] == '-# Publisher'


def test_freezing_normalizes_new_title_without_mutating_submission_or_saved_cards():
    item = dict(title='TLKM: spin off InfraNexia', summary='Fakta bersumber.', route='id_stocks_news')
    cards = news.freeze_cards([item], lambda row: f'### <:source:1531272430985937086> {row["title"]}',
                              'https://example.invalid/news', 'Source', fetch=lambda *_: None)
    assert item['title'] == 'TLKM: spin off InfraNexia'
    assert cards[0]['title'] == 'TLKM: Spin off InfraNexia'
    saved = [{**cards[0], 'title':item['title'], 'messages':['Previously frozen lowercase headline']}]
    assert news.validate_cards(saved) == saved


def fake_quote(closes, *, currency='USD', latest=None, previous=None, timezone='America/New_York'):
    index = pd.bdate_range(end='2026-10-01', periods=len(closes), tz=timezone)
    history = pd.DataFrame({'Close': closes}, index=index)
    metadata = {'regularMarketTime': (index[-1] + pd.Timedelta(hours=20)).timestamp(),
                'exchangeTimezoneName': timezone}
    return SimpleNamespace(fast_info={'last_price':latest,'previous_close':previous,'currency':currency},
                           history=lambda **kw: history, get_history_metadata=lambda: metadata)


@pytest.mark.parametrize('route,currency,ticker,symbol', [('id_stocks_news','IDR','RAJA','RAJA.JK'), ('us_stocks_news','USD','BRK.B','BRK-B')])
def test_native_currency_snapshot_and_all_horizons(monkeypatch, route, currency, ticker, symbol):
    calls = []
    quote = fake_quote(list(range(1,68)), currency=currency, latest=68, previous=67,
                       timezone='Asia/Jakarta' if currency == 'IDR' else 'America/New_York')
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value: calls.append(value) or quote))
    result = news.get_market_snapshot(ticker,route)
    assert calls == [symbol]
    assert result['currency'] == currency
    assert [result[key+'_change'] for key in ('one_day','one_week','one_month','three_month')] == [1,6,23,67]
    assert datetime.fromisoformat(result['as_of']).tzinfo is not None
    text = news.market_block(result,currency)
    assert f'Harga terakhir ({currency})' in text
    assert '+23' in text and '+67' in text


def test_partial_history_preserves_latest_and_available_horizons(monkeypatch):
    quote = fake_quote([9,10], latest=10)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    result = news.get_market_snapshot('META','us_stocks_news')
    assert result['one_day_change'] == 1
    assert result['one_week_change'] is None
    assert '1W: **-**' in news.market_block(result,'USD')


@pytest.mark.parametrize('metadata_state', ['stale', 'missing', 'invalid_timezone', 'raises'])
def test_unaligned_history_keeps_fast_quote_and_explicit_one_day_only(monkeypatch, metadata_state):
    # Equal last prices do not prove that the market dates match.
    quote = fake_quote(list(range(1,68)), latest=67, previous=66)
    metadata = quote.get_history_metadata()
    if metadata_state == 'stale':
        metadata['regularMarketTime'] += 24 * 60 * 60
    elif metadata_state == 'missing':
        metadata.pop('regularMarketTime')
    elif metadata_state == 'invalid_timezone':
        metadata['exchangeTimezoneName'] = 'Unknown/Exchange'
    else:
        quote.get_history_metadata = lambda: (_ for _ in ()).throw(RuntimeError('metadata unavailable'))
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    result = news.get_market_snapshot('META','us_stocks_news')
    assert result['latest_price'] == 67
    assert result['one_day_change'] == 1
    for key in ('one_week', 'one_month', 'three_month'):
        assert result[key+'_change'] is None
        assert result[key+'_percent'] is None
    quote.fast_info.pop('previous_close')
    assert news.get_market_snapshot('META','us_stocks_news')['one_day_change'] is None


def test_history_only_quote_anchors_to_its_own_final_session(monkeypatch):
    quote = fake_quote(list(range(1,68)))
    quote.get_history_metadata = lambda: {}
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    result = news.get_market_snapshot('META','us_stocks_news')
    assert result['latest_price'] == 67
    assert [result[key+'_change'] for key in ('one_day','one_week','one_month','three_month')] == [1,5,22,66]


def test_missing_closes_do_not_shift_other_horizon_sessions(monkeypatch):
    closes = list(range(1,68))
    closes[-6] = float('nan')
    closes[-10] = float('nan')
    quote = fake_quote(closes, latest=68, previous=67)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    result = news.get_market_snapshot('META','us_stocks_news')
    assert result['one_week_change'] is None
    assert result['one_month_change'] == 23
    assert result['three_month_change'] == 67


def test_datetime_market_time_uses_exchange_date(monkeypatch):
    quote = fake_quote(list(range(1,68)), latest=68, previous=67)
    metadata = quote.get_history_metadata()
    metadata['regularMarketTime'] = pd.Timestamp(metadata['regularMarketTime'], unit='s', tz='UTC')
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    assert news.get_market_snapshot('META','us_stocks_news')['one_month_change'] == 23


def test_currency_mismatch_and_provider_failure_are_unavailable(monkeypatch):
    quote = SimpleNamespace(fast_info={'last_price':10,'currency':'EUR'},history=lambda **kw:{'Close':[9,10]})
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    assert news.get_market_snapshot('SAP','us_stocks_news') is None
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:(_ for _ in ()).throw(RuntimeError('upstream'))))
    assert news.get_market_snapshot('BBCA') is None
    assert 'Harga terakhir (IDR): **-**' in news.market_block(None)


@pytest.mark.parametrize('summary',['Satu.','Satu.\n\nDua.','Satu.\n\nDua.\n\nTiga.','*(Ringkasan)* Satu.\n\n*(Ringkasan)* Dua.'])
def test_summary_style_never_blocks_and_marker_is_owned_once(summary):
    messages = news.render_card('### GIAA: Aksi korporasi\n-# DokterMarket',summary,'https://x.com/doktermarket/status/1','X',route='id_stocks_news')
    assert '\n\n'.join(messages).count('*(Ringkasan)*') == 1
    assert messages[-1].endswith('[View on X](<https://x.com/doktermarket/status/1>)')
    assert '3M: **-**' in '\n'.join(messages)


def test_independent_dividends_and_reopenings_get_six_price_cards():
    tickers=['DADA','NICL','ENRG','SINI','SMMT','SONA']
    items=[{'title':ticker+': Peristiwa dari sumber','summary':ticker+' memiliki perkembangan baru.','route':'id_stocks_news'} for ticker in tickers]
    calls=[]
    cards=news.freeze_cards(items,lambda item:'### '+item['title']+'\n-# DokterMarket','https://x.com/doktermarket/status/2105815054771970383','X',fetch=lambda ticker,route:calls.append(ticker),target_for=lambda item:'1525102508714889257')
    assert calls == tickers
    assert len(news.validate_cards(cards)) == 6
    for ticker,card in zip(tickers,cards):
        assert card['ticker'] == ticker
        assert card['messages'][0].count('Harga terakhir') == 1
        assert '2105815054771970383' in card['messages'][0]


def test_macro_avoids_quotes_and_failed_quote_keeps_issuer_card():
    calls=[]
    def failed(ticker,route):
        calls.append(ticker)
        raise RuntimeError('quote down')
    cards=news.freeze_cards([{'title':'Inflasi melemah','summary':'Inflasi melemah.','route':'macro_news'}, {'title':'UNTR: Buyback saham','summary':'UNTR akan membeli kembali saham.','route':'id_stocks_news'}],lambda item:'### '+item['title'],'https://example.test/news','Stockbit',fetch=failed)
    assert calls == ['UNTR']
    assert 'Harga terakhir' not in cards[0]['messages'][0]
    assert 'Harga terakhir (IDR): **-**' in cards[1]['messages'][0]


def test_long_copy_is_lossless_and_atomic_sections_remain_complete():
    summary=' '.join('Fakta'+str(n)+'.' for n in range(600))
    messages=news.render_card('### BBCA: Fakta sumber',summary,'https://example.test/news','X',route='id_stocks_news')
    assert all(len(m)<=2000 for m in messages)
    assert all('Fakta'+str(n)+'.' in '\n'.join(messages) for n in range(600))
    assert sum('*(Ringkasan)*' in m for m in messages) == 1
    assert sum('Harga terakhir' in m for m in messages) == 1
    assert messages[-1].endswith('[View on X](<https://example.test/news>)')


def test_slow_optional_quote_returns_placeholder_without_waiting_for_provider():
    import threading
    import time
    release=threading.Event()
    started=time.monotonic()
    try:
        assert news._bounded_quote(lambda *args:release.wait(5),'BBCA','id_stocks_news',0.01) is None
        assert time.monotonic()-started < 1
    finally:
        release.set()


def test_invalid_summary_and_frozen_card_shapes_remain_rejected():
    cards=news.freeze_cards([{'title':'BBCA: Laba meningkat','summary':'Laba meningkat.','route':'id_stocks_news'}],lambda item:'### '+item['title'],'https://example.test/news','X',fetch=lambda *args:None)
    news.validate_cards(cards)
    cards[0]['ticker']='UNTR'
    with pytest.raises(ValueError,match='ticker conflicts'):
        news.validate_cards(cards)


def test_emoji_length_uses_discord_utf16_units():
    summary=' '.join(['📈']*800)
    messages=news.render_card('### BBCA: Pembaruan','Fakta. '+summary,'https://example.test/news','X',route='id_stocks_news')
    assert len(messages)>1
    assert all(news.discord_length(message)<=2000 for message in messages)
    assert '\n'.join(messages).count('📈')==800
    assert '\n'.join(messages).count('[View on X]')==1


def test_duplicate_cards_keep_first_copy_and_distinct_stories_in_order():
    first = {'title':'DADA: Pembagian dividen','summary':'DADA membagikan dividen.','route':'id_stocks_news'}
    spacing = {**first, 'summary':'*(Ringkasan)* DADA  membagikan\n\ndividen.'}
    other_story = {**first, 'summary':'DADA melakukan aksi korporasi lain.'}
    other_issuer = {'title':'NICL: Pembagian dividen','summary':'NICL membagikan dividen.','route':'id_stocks_news'}
    items = [first, spacing, other_story, other_issuer, dict(first)]
    calls = []
    cards = news.freeze_cards(items, lambda item:'### '+item['title'], 'https://example.test/news', 'X',
                              fetch=lambda ticker,route:calls.append(ticker))
    assert calls == ['DADA', 'DADA', 'NICL']
    assert [card['summary'] for card in cards] == [first['summary'], other_story['summary'], other_issuer['summary']]
    assert news.deduplicate_items(items)[0] is first
    assert len(items) == 5
    assert len(news.validate_cards(cards)) == 3


def test_deduplication_is_per_submission_and_preserves_specialized_items():
    item = {'title':'DADA: Dividen','summary':'DADA membagikan dividen.','route':'id_stocks_news'}
    assert news.deduplicate_items([item]) == [item]
    assert news.deduplicate_items([item]) == [item]
    swing = {**item, 'route':'id_stocks_swing','sentiment':'Bullish'}
    assert news.deduplicate_items([swing,dict(swing)]) == [swing,swing]
    card = news.freeze_cards([item], lambda item:'### '+item['title'], 'https://example.test/news', 'X', fetch=lambda *args:None)[0]
    saved = [card, dict(card)]
    assert news.validate_cards(saved) is saved
    assert len(saved) == 2


RATING = {'strong_buy': 0, 'buy': 20, 'hold': 0, 'sell': 0, 'strong_sell': 0, 'n_analyst': 20, 'updated_on': '2026-09-02 17:00:00'}
OVERVIEW = {'sector': 'Energy', 'sub_industry': 'Coal Production', 'market_cap': 94416062590000}


def test_analyst_block_uses_consensus_emoji_and_padded_date():
    assert news.analyst_block(RATING) == (
        f'Konsensus analis: {news.UP} **BUY** (20 analis, 100% Buy)\n'
        'Strong Buy 0, Buy 20, Hold 0, Sell 0, Strong Sell 0 (per 02 Sep 2026)')
    mixed = {**RATING, 'buy': 3, 'hold': 4, 'sell': 1, 'updated_on': '2026-05-01'}
    assert news.analyst_block(mixed).startswith(f'Konsensus analis: {news.HOLD} **HOLD** (8 analis, 50% Hold)')
    assert news.analyst_block({**RATING, 'buy': 0, 'sell': 2}).startswith(f'Konsensus analis: {news.DOWN} **SELL**')
    assert news.analyst_block({**RATING, 'updated_on': None}).endswith('Strong Sell 0')


@pytest.mark.parametrize('rating', [None, {}, {**RATING, 'buy': 0}, {**RATING, 'buy': None}, {**RATING, 'buy': -1}, 'x'])
def test_analyst_block_is_omitted_for_missing_or_invalid_coverage(rating):
    assert news.analyst_block(rating) is None


def test_about_block_combines_first_sentence_and_indonesian_market_cap():
    context = {'overview': OVERVIEW, 'business_summary': 'PT Foo Tbk. engages in coal mining. It also runs ports.'}
    assert news.about_block('AADI', context) == (
        'Tentang AADI:\nPT Foo Tbk. engages in coal mining. Sektor Energy (Coal Production), kapitalisasi pasar Rp94,4 T.')
    assert news.about_block('BULL', {'overview': {'market_cap': 5763930412596}}) == 'Tentang BULL:\nKapitalisasi pasar Rp5,8 T.'
    assert news.about_block('BULL', {'overview': {'market_cap': 850e9}}).endswith('Rp850,0 M.')


def test_about_block_handles_partial_coverage():
    assert news.about_block('AADI', {'business_summary': 'Only Yahoo covers this.'}) == 'Tentang AADI:\nOnly Yahoo covers this.'
    assert news.about_block('AADI', {'overview': {'sector': 'Energy'}}) == 'Tentang AADI:\nSektor Energy.'
    assert news.about_block('AADI', {'overview': None, 'business_summary': None}) is None
    long = 'word ' * 100
    assert len(news.about_block('AADI', {'business_summary': long})) < 330


def test_card_inserts_context_after_prices_and_before_source_anchor():
    snapshot = {'latest_price': 12075, 'one_day_change': -50, 'one_day_percent': -0.41}
    context = {'rating': RATING, 'overview': OVERVIEW, 'business_summary': 'Coal miner.'}
    message = news.render_card('### AADI: Judul\n-# Tuntun', 'Fakta.', 'https://t.me/x/1', 'Telegram',
                               route='id_stocks_news', snapshot=snapshot, ticker='AADI', context=context)[0]
    assert message.index('Harga terakhir') < message.index('Konsensus analis') < message.index('Tentang AADI:') < message.index('[View on')
    assert '\n\nKonsensus analis' in message and '\n\nTentang AADI:' in message


def test_context_is_idr_only_and_optional():
    context = {'rating': RATING, 'overview': OVERVIEW}
    us = news.render_card('### BRK.B: x', 'Fakta.', 'https://t.me/x/1', 'Telegram', route='us_stocks_news', ticker='BRK.B', context=context)[0]
    macro = news.render_card('### x', 'Fakta.', 'https://t.me/x/1', 'Telegram', route='macro_news', ticker=None, context=context)[0]
    none = news.render_card('### AADI: x', 'Fakta.', 'https://t.me/x/1', 'Telegram', route='id_stocks_news', ticker='AADI', context=None)[0]
    assert 'Konsensus' not in us + macro + none and 'Tentang' not in us + macro + none


def test_freeze_cards_persists_context_in_messages_only():
    item = dict(title='AADI: batu bara', summary='Fakta bersumber.', route='id_stocks_news')
    calls = []
    cards = news.freeze_cards([item], lambda row: f'### {row["title"]}', 'https://t.me/x/1', 'Telegram', fetch=lambda *_: None,
                              context_fetch=lambda ticker, route: calls.append((ticker, route)) or {'rating': RATING})
    assert calls == [('AADI', 'id_stocks_news')]
    assert 'Konsensus analis' in cards[0]['messages'][0]
    assert set(cards[0]) == {'title', 'summary', 'route', 'ticker', 'market_data_as_of', 'messages', 'destination'}
    news.validate_cards(cards)


def test_injected_quote_fetch_keeps_legacy_cards_and_context_failure_is_ignored(monkeypatch):
    monkeypatch.setattr(news, 'get_company_context', lambda *_: pytest.fail('context fetched'))
    item = dict(title='AADI: batu bara', summary='Fakta bersumber.', route='id_stocks_news')
    cards = news.freeze_cards([item], lambda row: f'### {row["title"]}', 'https://t.me/x/1', 'Telegram', fetch=lambda *_: None)
    assert 'Konsensus' not in cards[0]['messages'][0]
    boom = news.freeze_cards([item], lambda row: f'### {row["title"]}', 'https://t.me/x/1', 'Telegram', fetch=lambda *_: None,
                             context_fetch=lambda *_: 1 / 0)
    assert 'Konsensus' not in boom[0]['messages'][0]


def test_get_company_context_merges_sources_and_caches(monkeypatch):
    news._CONTEXT_CACHE.clear()
    calls = []
    monkeypatch.setattr(news, '_fetch_sectors', lambda ticker, route: calls.append('sectors') or {'overview': OVERVIEW, 'rating': RATING})
    monkeypatch.setattr(news, '_fetch_business_summary', lambda ticker, route: calls.append('yahoo') or 'Coal miner.')
    first = news.get_company_context('AADI')
    assert first == {'overview': OVERVIEW, 'rating': RATING, 'business_summary': 'Coal miner.'}
    assert news.get_company_context('AADI') == first and calls == ['sectors', 'yahoo']
    assert news.get_company_context('BRK.B', 'us_stocks_news') is None and news.get_company_context('toolong') is None


def test_get_company_context_survives_either_provider_missing(monkeypatch):
    news._CONTEXT_CACHE.clear()
    monkeypatch.setattr(news, '_fetch_sectors', lambda *_: 1 / 0)
    monkeypatch.setattr(news, '_fetch_business_summary', lambda *_: 'Yahoo only.')
    assert news.get_company_context('AADI') == {'overview': None, 'rating': None, 'business_summary': 'Yahoo only.'}
    news._CONTEXT_CACHE.clear()
    monkeypatch.setattr(news, '_fetch_business_summary', lambda *_: None)
    assert news.get_company_context('AADI') is None


def sectors_client_for(tmp_path, transport):
    news._sectors_library()
    import sectors_client as sc
    config = sc.Config(store_path=tmp_path / 'cache.sqlite3', caller='news-context', billing_window='2026-10', cache_only=False, api_key='fake')
    return sc.SectorsClient(config, transport=transport)


class FakeTransport:
    def __init__(self, *payloads):
        self.payloads, self.requests = list(payloads), []
    def get(self, identity):
        self.requests.append(identity)
        return self.payloads.pop(0)


def test_sectors_fetch_uses_shared_client_with_weekly_generation_and_cache(monkeypatch, tmp_path):
    report = {'symbol': 'AADI.JK', 'overview': OVERVIEW, 'future': {'analyst_rating_breakdown': RATING}}
    transport = FakeTransport(report, {**report, 'overview': {'sector': 'Next week'}})
    monkeypatch.setattr(news, '_sectors_client', lambda now: sectors_client_for(tmp_path, transport))
    assert news._fetch_sectors('AADI', 'id_stocks_news') == {'overview': OVERVIEW, 'rating': RATING}
    assert news._fetch_sectors('AADI', 'id_stocks_news')['overview'] == OVERVIEW
    assert len(transport.requests) == 1
    assert transport.requests[0].url.startswith('https://api.sectors.app/v2/company/report/AADI/?sections=future')
    assert transport.requests[0].generation.startswith('news-context:')
    # A later ISO week is a new caller-owned generation and a separately budgeted fetch.
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2099, 1, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(news, 'datetime', Later)
    news._fetch_sectors('AADI', 'id_stocks_news')
    assert len(transport.requests) == 2


def test_sectors_lines_are_skipped_without_library_or_key_file(monkeypatch, tmp_path):
    monkeypatch.setattr(news, '_sectors_library', lambda: None)
    assert news._fetch_sectors('AADI', 'id_stocks_news') is None
    monkeypatch.setattr(news, '_sectors_library', lambda: tmp_path)
    assert news._fetch_sectors('AADI', 'id_stocks_news') is None


def test_sectors_key_file_prefers_hermes_credential_then_package_env(monkeypatch, tmp_path):
    news._sectors_library()
    package = tmp_path / 'lib-sectors'
    package.mkdir()
    monkeypatch.setattr(news, '_sectors_library', lambda: package)
    seen = []
    import sectors_client as sc
    monkeypatch.setattr(sc.Config, 'from_env_file', classmethod(lambda cls, path, **kw: seen.append(path) or cls(api_key='k', **kw)))
    monkeypatch.setattr(news, 'SECTORS_STORE_PATH', tmp_path / 'store.sqlite3')
    monkeypatch.setattr(news, 'SECTORS_KEY_FILE', tmp_path / 'bursawatch-sectors.env')
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    assert news._sectors_client(now) is None
    (package / '.env').write_text('SECTORS_API_KEY=a\n')
    news._sectors_client(now)
    (tmp_path / 'bursawatch-sectors.env').write_text('SECTORS_API_KEY=b\n')
    news._sectors_client(now)
    assert seen == [package / '.env', tmp_path / 'bursawatch-sectors.env']
