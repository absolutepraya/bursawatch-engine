from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from PIL import Image
import pytest

from morning_brief.calendar import SessionCalendar
from morning_brief.public_sources import yahoo_sessions, ihsg_benchmark
from morning_brief.rendering import render_yahoo_ihsg
from morning_brief.store import RunStore, digest
from morning_brief.yahoo_chart import prepare_chart, PROFILE
from test_runner import Source, HeartbeatDelivery, FREEZE, NOW
from test_publication import FakeProjection


def fixture():
    # Synthetic explicit fixture sessions; not a production IDX calendar.
    days = tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(278)
                 if (date(2026, 1, 1) + timedelta(days=i)).weekday() < 5)
    calendar = SessionCalendar('synthetic-chart', 'fixture', 'IDX', 'https://fixture.test/calendar',
        'a' * 64, 'b' * 64, FREEZE - timedelta(days=1), date(2026, 1, 1), date(2026, 12, 31), days)
    closes = [7000 + i * 2 + (i % 7 - 3) * 10 for i in range(len(days))]
    stamps = [int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=2).timestamp()) for day in days]
    daily = {'chart': {'error': None, 'result': [{
        'meta': {'symbol': '^JKSE', 'exchangeTimezoneName': 'Asia/Jakarta', 'dataGranularity': '1d'},
        'timestamp': stamps, 'indicators': {'quote': [{'open': [v - 3 for v in closes],
            'high': [v + 15 for v in closes], 'low': [v - 20 for v in closes], 'close': closes}]}}]}}
    hourly = deepcopy(daily); meta = hourly['chart']['result'][0]['meta']
    periods = [dict(start=int(datetime(2026, 10, day, 2, tzinfo=timezone.utc).timestamp()),
                    end=int(datetime(2026, 10, day, 9, tzinfo=timezone.utc).timestamp())) for day in (1, 2)]
    meta.update(dataGranularity='60m', tradingPeriods=[[period] for period in periods],
                currentTradingPeriod={'regular': periods[-1]})
    observed = FREEZE - timedelta(hours=1)
    sessions = yahoo_sessions('IHSG', hourly, retrieved_at=observed, cutoff=FREEZE)
    context = dict(provider='yahoo', profile_revision=PROFILE, cutoff=FREEZE.isoformat(),
        daily=dict(payload=daily, payload_sha256=digest(daily), source_sha256='c' * 64,
                   source_url='https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?range=1y&interval=1d',
                   retrieved_at=observed.isoformat()), sessions=sessions)
    return calendar, context


def prepared():
    calendar, context = fixture()
    return prepare_chart(context, calendar, publication_session=date(2026, 10, 5), cutoff=FREEZE)


def test_three_month_chart_with_full_indicator_warmup_and_bound_manifest():
    series = prepared(); artifact = render_yahoo_ihsg(series, publication_session=date(2026, 10, 5))
    assert (artifact.width, artifact.height) == (1600, 1160)
    assert Image.open(BytesIO(artifact.data)).format == 'PNG'
    manifest = artifact.manifest
    assert manifest['candles'][0]['session'] == '2026-07-02'
    assert manifest['candles'][-1]['session'] == '2026-10-02'
    assert set(manifest['moving_averages']) == {'10', '20', '50', '100'}
    assert all(len(values) == len(manifest['candles']) for values in manifest['moving_averages'].values())
    # Fixture close formula is independent of renderer calculations.
    index = 130  # 2 July is the 131st explicit fixture weekday.
    expected = sum(7000 + i * 2 + (i % 7 - 3) * 10 for i in range(index - 99, index + 1)) / 100
    assert manifest['moving_averages']['100'][0] == pytest.approx(expected)
    assert manifest['provenance']['rsi_method'] == 'Wilder'
    assert manifest['provenance']['calendar_digest'] == 'b' * 64
    assert all(0 <= value <= 100 for value in manifest['rsi'])
    assert all(0 <= x0 < x1 <= 1600 and 0 <= y0 < y1 <= 1160 for x0, y0, x1, y1 in manifest['text_bounds'])
    assert render_yahoo_ihsg(series, publication_session=date(2026, 10, 5)).data == artifact.data


@pytest.mark.parametrize('change', ['digest', 'future', 'cutoff', 'symbol', 'missing_latest', 'missing_visible', 'missing_warmup', 'insufficient_calendar', 'source'])
def test_invalid_yahoo_chart_never_uses_stale_or_filled_data(change):
    calendar, context = fixture(); row = context['daily']['payload']['chart']['result'][0]
    if change == 'digest': context['daily']['payload_sha256'] = '0' * 64
    if change == 'future': context['daily']['retrieved_at'] = (FREEZE + timedelta(seconds=1)).isoformat()
    if change == 'cutoff': context['cutoff'] = (FREEZE - timedelta(seconds=1)).isoformat()
    if change == 'symbol': row['meta']['symbol'] = 'OTHER'
    if change.startswith('missing_'):
        index = {'missing_latest': -2, 'missing_visible': 150, 'missing_warmup': 70}[change]
        row['timestamp'].pop(index)
        for values in row['indicators']['quote'][0].values(): values.pop(index)
    if change == 'insufficient_calendar': calendar = replace(calendar, sessions=calendar.sessions[80:])
    if change == 'source': context['daily']['source_url'] = 'https://example.test/invented'
    if change not in ('digest',): context['daily']['payload_sha256'] = digest(context['daily']['payload'])
    with pytest.raises(ValueError): prepare_chart(context, calendar, publication_session=date(2026, 10, 5), cutoff=FREEZE)


def test_yahoo_chart_freezes_and_recovery_ignores_replacement_data(tmp_path):
    from morning_brief.runner import MorningRunner
    calendar, context = fixture()
    store = RunStore(tmp_path / 'runs'); source = Source(); delivery = HeartbeatDelivery()
    runner = MorningRunner(store, source, delivery, FakeProjection(), clock=lambda: NOW)
    args = dict(calendar=calendar, numerical=ihsg_benchmark(context['daily']['payload'], context['sessions'], calendar,
        publication_session=date(2026, 10, 5), retrieved_at=datetime.fromisoformat(context['daily']['retrieved_at']), cutoff=FREEZE),
        global_inputs=[], calendar_snapshots=[], model=None, model_version='fixture', prompt_version='fixture',
        preview=True, chart_context=context)
    assert runner.run(**args)['phase'] == 'preview'
    run = store.get_run_for_session('2026-10-05')
    selection = store.get_frozen(run.run_id, 'selection')
    assert selection.payload['images'][0]['manifest']['provider'] == 'yahoo'
    args['chart_context'] = {'provider': 'yahoo', 'daily': {}}
    assert runner.run(**args)['phase'] == 'preview'
    assert store.get_frozen(run.run_id, 'selection').digest == selection.digest
    assert source.captures == 1 and delivery.sent == []


def test_official_non_session_null_placeholder_is_not_a_missing_candle():
    calendar, context = fixture()
    holiday = date(2026, 8, 17)
    index = calendar.sessions.index(holiday)
    calendar = replace(calendar, sessions=tuple(day for day in calendar.sessions if day != holiday))
    quote = context['daily']['payload']['chart']['result'][0]['indicators']['quote'][0]
    for values in quote.values(): values[index] = None
    context['daily']['payload_sha256'] = digest(context['daily']['payload'])
    series = prepare_chart(context, calendar, publication_session=date(2026, 10, 5), cutoff=FREEZE)
    assert holiday not in [bar.session for bar in series['bars']]
    assert all(value is not None for value in series['averages']['100'])
