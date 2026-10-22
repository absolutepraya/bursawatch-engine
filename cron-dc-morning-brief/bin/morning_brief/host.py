"""Explicit production composition around the shared, receipt-gated owner.

No import performs IO. Retained inputs are produced separately before cutoff;
this dispatcher never promotes preview inputs or fetches paid provider data.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import stat
from zoneinfo import ZoneInfo

from .calendar import SessionCalendar, aware
from .config import OWNER, load_operator_config_data, timing_for, weekday_delivery
from .runner import MorningRunner
from .store import RunStore
from .session import MorningSession

CONTROL_URL = 'http://127.0.0.1:9120'
DELIVERY_URL = 'http://127.0.0.1:9140'
ZONE = ZoneInfo('Asia/Jakarta')


def private_file(path, *, max_bytes=25_000_000):
    path = Path(path)
    details = path.lstat()
    if (not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077
            or details.st_size > max_bytes):
        raise ValueError('private bounded regular file required')
    return path.read_bytes()


def token(path):
    value = private_file(path, max_bytes=1024).decode().strip()
    if len(value) < 32 or any(c.isspace() for c in value):
        raise ValueError('invalid private credential')
    return value


@dataclass(frozen=True)
class HostConfig:
    version: int
    run_store: str
    input_manifest: str
    config_token_file: str
    source_token_file: str
    publication_token_file: str
    delivery_token_file: str
    hermes_root: str
    chart_store: str | None = None

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError('unsupported host configuration version')
        paths = [getattr(self, name) for name in self.__dataclass_fields__ if name != 'version']
        if (any(getattr(self, name) is None for name in self.__dataclass_fields__ if name not in {'version', 'chart_store'})
                or any(type(p) is not str or not Path(p).is_absolute() for p in paths if p is not None)):
            raise ValueError('host paths must be explicit and absolute')
        # Stores, input data and credentials must never alias each other.
        concrete = [str(Path(p).resolve()) for p in paths if p is not None]
        if len(set(concrete)) != len(concrete):
            raise ValueError('host paths must be distinct')

    @classmethod
    def from_file(cls, path):
        return cls(**json.loads(private_file(path, max_bytes=16_384)))


def load_inputs(path, *, cutoff, allow_calendar_gap=False):
    value = json.loads(private_file(path))
    if (set(value) - {'version', 'provenance', 'available_at', 'calendar', 'numerical',
                     'global_inputs', 'calendar_snapshots', 'chart'}
            or type(value.get('version')) is not int or value['version'] != 1
            or value.get('provenance') != 'live-retained'
            or aware(datetime.fromisoformat(value['available_at'])) > cutoff):
        raise ValueError('cutoff-visible live input manifest required')
    for name, kind in [('numerical', dict), ('global_inputs', list), ('calendar_snapshots', list)]:
        if type(value.get(name)) is not kind:
            raise ValueError('explicit live input sections required')
    try:
        reference = value['calendar']
        if type(reference['path']) is not str or not Path(reference['path']).is_absolute():
            raise ValueError('explicit absolute calendar path required')
        raw = private_file(reference['path'], max_bytes=512_000)
        if hashlib.sha256(raw).hexdigest() != reference['sha256']:
            raise ValueError('calendar snapshot checksum mismatch')
        calendar = SessionCalendar.from_file(reference['path'],
            expected_version=reference['version'], expected_amendment=reference['amendment'], as_of=cutoff)
        if calendar.import_digest != reference['sha256']:
            raise ValueError('calendar changed while loading')
    except (OSError,ValueError,KeyError,TypeError):
        if not allow_calendar_gap:
            raise
        calendar=None
        value={**value,'numerical':{}}
        value.pop('chart',None)
    return calendar, value


class VerifiedChartCache:
    """Use the shared cache and bind external proof to its exact returned bytes."""
    def __init__(self, client, proof):
        self.client, self.proof = client, proof

    def render(self, request, *, cache_only=True):
        if cache_only is not True:
            raise ValueError('morning dispatcher cannot fetch a chart')
        return self.client.render(request, cache_only=True).with_verification(self.proof)


def chart_inputs(config, value, cutoff):
    chart = value.get('chart')
    if chart is None or isinstance(chart, dict) and chart.get('provider') == 'yahoo':
        return None, None
    if not config.chart_store or not Path(config.chart_store).is_file():
        raise ValueError('shared chart store unavailable')
    from chart_img_client import AsOfVerification, ChartImgClient, RenderCache, RenderRequest
    request = RenderRequest(**{**chart['request'], 'cutoff': datetime.fromisoformat(chart['request']['cutoff'])})
    proof = AsOfVerification(**{**chart['verification'],
        'verified_at': datetime.fromisoformat(chart['verification']['verified_at'])})
    if request.cutoff != cutoff or proof.verified_at > cutoff:
        raise ValueError('chart verification unavailable at cutoff')
    return VerifiedChartCache(ChartImgClient(RenderCache(config.chart_store)), proof), request


class HostRuntime:
    def __init__(self, config, store, runner, *, fetch_snapshot, writer_factory, clock):
        self.config, self.store, self.runner = config, store, runner
        self.fetch_snapshot, self.writer_factory, self.clock = fetch_snapshot, writer_factory, clock

    def tick(self, *, operator_snapshot=None):
        try:
            session = MorningSession(self.store, self.clock())
            return session.dispatch(fetch_snapshot=self.fetch_snapshot, supplied_snapshot=operator_snapshot,
                load_inputs=lambda **kwargs: load_inputs(self.config.input_manifest, **kwargs),
                writer_factory=self.writer_factory,
                chart_inputs=lambda inputs, cutoff: chart_inputs(self.config, inputs, cutoff),
                run=self.runner.run_from_snapshot, beat=self.beat)
        except Exception as error:
            return self.beat({'phase': 'fatal', 'reason': type(error).__name__})

    def beat(self, result):
        return self.runner._heartbeat(result, preview=False, preview_dir=None, accounting={})


def production_runtime(config, *, clock=None):
    from control_plane_client import fetch_config
    from source_evidence_client import SourceEvidenceClient
    from publication_client import PublicationClient
    from bursawatch_discord_delivery import DeliveryClient
    from .hermes_writer import current_writer
    clock = clock or (lambda: datetime.now(timezone.utc))
    store = RunStore(config.run_store)
    delivery = DeliveryClient(DELIVERY_URL, token_file=config.delivery_token_file)
    runner = MorningRunner(store, SourceEvidenceClient(CONTROL_URL, token(config.source_token_file)),
        delivery, PublicationClient(CONTROL_URL, token(config.publication_token_file)), clock=clock)
    def fetch():
        from dataclasses import asdict
        return {'api_version': 1, **asdict(fetch_config(CONTROL_URL, OWNER, token(config.config_token_file)))}
    return HostRuntime(config, store, runner, fetch_snapshot=fetch,
        writer_factory=lambda: current_writer(config.hermes_root), clock=clock)


def failure_heartbeat(config, error):
    from bursawatch_discord_delivery import DeliveryClient
    # Initialization can fail before the run store/source clients exist.
    runner = MorningRunner(None, None,
        DeliveryClient(DELIVERY_URL, token_file=config.delivery_token_file), None,
        clock=lambda: datetime.now(timezone.utc))
    return runner._heartbeat({'phase': 'fatal', 'reason': type(error).__name__},
        preview=False, preview_dir=None, accounting={})


def readiness(config, *, snapshot, now):
    """No store writes, model calls, capture, provider fetch, or Discord calls."""
    from control_plane_client import ConfigSnapshot
    checked = ConfigSnapshot.from_payload(snapshot)
    if checked.watcher_id != OWNER:
        raise ValueError('morning configuration identity mismatch')
    settings = load_operator_config_data(checked.config)
    cutoff = timing_for(now.astimezone(ZONE).date(), settings)['cutoff']
    gaps = []
    if not settings['destination_channel_id']:
        gaps.append('destination_unavailable')
    for field in ('config_token_file', 'source_token_file', 'publication_token_file', 'delivery_token_file'):
        try:
            token(getattr(config, field))
        except (OSError, ValueError):
            gaps.append(field + '_unavailable')
    try:
        calendar, values = load_inputs(config.input_manifest, cutoff=cutoff,
            allow_calendar_gap=weekday_delivery(settings))
        if calendar is None:
            gaps.append('idx_calendar_unavailable')
        elif calendar.is_session(now.astimezone(ZONE).date()):
            # Readiness is conservative. Per-section gaps still degrade at runtime.
            from .runner import _attested
            numerical = values['numerical']
            benchmark = numerical.get('benchmark', {})
            proof = numerical.get('benchmark_attestation', {})
            previous = calendar.last_sessions(now.astimezone(ZONE).date(), 2)[0].isoformat()
            close = benchmark.get(previous)
            if (not _attested(benchmark, proof, cutoff, set()) or not proof.get('version')
                    or type(close) not in (int, float) or not math.isfinite(close) or close <= 0):
                gaps.append('benchmark_unavailable')
    except (OSError, KeyError, ValueError, TypeError):
        gaps.append('verified_live_inputs_unavailable')
    if not Path(config.hermes_root, 'hermes_cli', 'config.py').is_file():
        gaps.append('hermes_runtime_unavailable')
    optional={'verified_live_inputs_unavailable','idx_calendar_unavailable','benchmark_unavailable'} if weekday_delivery(settings) else set()
    return {'ready': not (set(gaps)-optional), 'gaps': gaps, 'config_revision': checked.revision,
            'delivery_days':settings.get('delivery_days','idx_sessions'),
            'cutoff_time': settings['cutoff_time'], 'delivery_time': settings['delivery_time'],
            'network': 'configuration_read_only', 'posts': False, 'provider_fetches': False}
