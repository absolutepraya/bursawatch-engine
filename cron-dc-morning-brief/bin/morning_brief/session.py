"""Morning Brief session policy shared by scheduling, dispatch and recovery.

Adapters supply I/O explicitly. This module never discovers credentials, invokes
providers, changes schedules, or owns delivery retries. Frozen slot interpretation
and the decisions about which work may run belong here.
"""
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo
from typing import Literal

from .calendar import aware, restored_calendar
from .config import OWNER, load_operator_config_data, retained_operator_config, timing_for, weekday_delivery
from .store import FreezeConflict


ZONE = ZoneInfo('Asia/Jakarta')


@dataclass(frozen=True)
class SessionConfiguration:
    snapshot: dict | None
    settings: dict
    times: dict
    destination: str | None
    logos: dict | None


@dataclass(frozen=True)
class ProducerDecision:
    action: Literal['recover', 'weekend', 'dispatch', 'collect']
    configuration: SessionConfiguration | None = None


class MorningSession:
    def __init__(self, store, now):
        self._store = store
        self.now = aware(now)
        self.date = self.now.astimezone(ZONE).date()
        self._run = store.get_run_for_session(self.date.isoformat())
        self._operator_config = self._record('operator_config')

    def _record(self, slot):
        return self._store.get_frozen(self._run.run_id, slot) if self._run else None

    def _configuration(self, snapshot, settings, destination, logos):
        return SessionConfiguration(snapshot, settings, timing_for(self.date, settings), destination, logos)

    def _operator_configuration(self, fetch_snapshot, supplied_snapshot=None):
        from control_plane_client import ConfigSnapshot
        # A frozen snapshot remains authoritative even while the config reader is down.
        raw = (self._operator_config.payload if self._operator_config is not None else
               supplied_snapshot if supplied_snapshot is not None else fetch_snapshot())
        checked = ConfigSnapshot.from_payload(raw)
        if checked.watcher_id != OWNER:
            raise ValueError('morning configuration identity mismatch')
        settings = load_operator_config_data(checked.config)
        return self._configuration(raw, settings, settings['destination_channel_id'], settings['logos'])

    def producers(self, fetch_snapshot):
        if self._operator_config is not None:
            return ProducerDecision('recover')
        config = self._operator_configuration(fetch_snapshot)
        if weekday_delivery(config.settings) and self.date.weekday() >= 5:
            return ProducerDecision('weekend', config)
        if self.now >= config.times['cutoff']:
            return ProducerDecision('dispatch', config)
        return ProducerDecision('collect', config)

    def dispatch(self, *, fetch_snapshot, supplied_snapshot, load_inputs,
                 writer_factory, chart_inputs, run, beat):
        """Resolve the permitted dispatcher work without exposing frozen slots to the host."""
        config = self._operator_configuration(fetch_snapshot, supplied_snapshot)
        settings, times = config.settings, config.times
        if weekday_delivery(settings) and self.date.weekday() >= 5 and not self._run:
            return beat({'phase': 'no_op', 'reason': 'weekend'})
        if not config.destination:
            raise ValueError('morning destination unavailable')
        if self.now < times['cutoff']:
            return beat({'phase': 'before_freeze'})
        publication, upstream = self._record('publication'), self._record('upstream')
        if publication:
            calendar, inputs = None, {}
        elif upstream:
            calendar = self._calendar(upstream)
            inputs = {**upstream.payload, 'chart': upstream.payload.get('chart_context')}
        else:
            if self.now > times['deadline']:
                return beat({'phase': 'missed_session', 'gaps': 1})
            try:
                calendar, inputs = load_inputs(cutoff=times['cutoff'], allow_calendar_gap=weekday_delivery(settings))
            except (OSError, ValueError, KeyError, TypeError):
                if not weekday_delivery(settings):
                    raise
                calendar, inputs = None, {}
        selected, bundle = self._record('selection'), self._record('writer_bundle')
        model, version, prompt_version = None, 'hermes-current-unavailable', 'source-scenario-v2'
        if not publication and not selected and calendar is not None and calendar.is_session(self.date):
            model, version = writer_factory()
        if bundle:
            retained_version = bundle.payload['versions']['model']
            if version != retained_version:
                model = None
            version, prompt_version = retained_version, bundle.payload['versions']['prompt']
        chart_client, chart_request = None, None
        if not publication and not selected:
            try:
                chart_client, chart_request = chart_inputs(inputs, times['cutoff'])
            except (ValueError, KeyError, OSError):
                pass
        return run(config.snapshot, calendar=calendar,
            numerical=inputs.get('numerical', {}), global_inputs=inputs.get('global_inputs', []),
            calendar_snapshots=inputs.get('calendar_snapshots', []), model=model,
            model_version=version, prompt_version=prompt_version, preview=False,
            chart_client=chart_client, chart_request=chart_request, chart_context=inputs.get('chart'))

    def run_configuration(self, snapshot, destination, logos):
        """Retain the reviewed compatibility path for explicitly injected local runs."""
        if self._operator_config:
            snapshot = self._operator_config.payload
            destination, logos = snapshot['config']['destination_channel_id'], snapshot['config']['logos']
        if snapshot is not None:
            settings = load_operator_config_data(snapshot['config'])
        elif self._run:
            settings = retained_operator_config(self._store, self._run.run_id)
        else:
            settings = dict(version=1, timezone='Asia/Jakarta', cutoff_time='07:30', delivery_time='08:00',
                fallback_minutes=5, retry_minutes=15, destination_channel_id=destination,
                instruments=['KOSPI', 'Nikkei', 'SPY', 'QQQ', 'EIDO', 'USDIDR'], logos=dict(logos or {}))
        return self._configuration(snapshot, settings, destination, logos)

    def bind_run(self, run, *, snapshot, preview, lease, now):
        """Freeze configuration and fence preview/live identity under the caller's lease."""
        self._run = run
        if snapshot is not None and self._operator_config is None:
            if self._record('run_mode') is not None:
                raise FreezeConflict('legacy session cannot acquire a new operator configuration')
            self._operator_config = self._store.freeze(run.run_id, 'operator_config', snapshot, lease=lease, now=now())
        mode = 'preview' if preview else 'live'
        record = self._record('run_mode')
        if record is None:
            if any(self._record(slot) is not None for slot in ('upstream', 'source_manifest', 'selection', 'publication')):
                raise FreezeConflict('legacy run mode is unknown; use separate state')
            record = self._store.freeze(run.run_id, 'run_mode', {'mode': mode}, lease=lease, now=now())
        if record.payload.get('mode') != mode:
            raise FreezeConflict('frozen run mode mismatch; use separate preview state')

    def publication_recovery(self, *, preview, destination):
        publication = self._record('publication')
        if publication is None or preview:
            return False
        if destination != publication.payload['destination']:
            raise ValueError('frozen destination mismatch')
        return True

    @staticmethod
    def _calendar(upstream):
        return restored_calendar(upstream.payload['calendar']) if upstream.payload['calendar'] else None

    def preparation(self, calendar, config):
        upstream = self._record('upstream')
        if upstream:
            calendar = self._calendar(upstream)
        cutoff = config.times['cutoff']
        weekdays = weekday_delivery(config.settings)
        if calendar is not None:
            checked = aware(calendar.amendment_checked_at)
            if checked > cutoff or cutoff - checked > timedelta(days=7):
                if not weekdays:
                    raise ValueError('calendar amendment unavailable')
                calendar = None
        if calendar is None and not weekdays:
            raise ValueError('calendar amendment unavailable')
        eligible = self.date.weekday() < 5 if weekdays else calendar.is_session(self.date)
        return upstream, calendar, eligible
