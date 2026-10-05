from datetime import datetime
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
