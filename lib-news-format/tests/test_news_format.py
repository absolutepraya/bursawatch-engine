from datetime import datetime
from types import SimpleNamespace
import sys

import pytest
import news_format as news


@pytest.mark.parametrize('route,currency,ticker,symbol', [('id_stocks_news','IDR','RAJA','RAJA.JK'), ('us_stocks_news','USD','BRK.B','BRK-B')])
def test_native_currency_snapshot_and_all_horizons(monkeypatch, route, currency, ticker, symbol):
    calls = []
    quote = SimpleNamespace(fast_info={'last_price':68,'previous_close':67,'currency':currency},
                            history=lambda **kw: {'Close':list(range(1,68))})
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
    quote = SimpleNamespace(fast_info={'last_price':10,'currency':'USD'},history=lambda **kw:{'Close':[9,10]})
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda value:quote))
    result = news.get_market_snapshot('META','us_stocks_news')
    assert result['one_day_change'] == 1
    assert result['one_week_change'] is None
    assert '1W: **-**' in news.market_block(result,'USD')


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
