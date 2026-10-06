"""Explicit offline morning owner configuration, separate from provider credentials."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class MorningConfig:
    run_store_path: Path
    sectors_store_path: Path
    mode: str = 'cache_only'

    def __post_init__(self):
        object.__setattr__(self, 'run_store_path', Path(self.run_store_path))
        object.__setattr__(self, 'sectors_store_path', Path(self.sectors_store_path))
        if self.run_store_path.resolve() == self.sectors_store_path.resolve():
            raise ValueError('morning and provider stores must be separate')
        if self.mode not in {'cache_only', 'synthetic_preview'}:
            raise ValueError('only explicit offline modes supported')

    @classmethod
    def from_mapping(cls, fields: Mapping):
        if set(fields) - {'run_store_path', 'sectors_store_path', 'mode'}:
            raise ValueError('unknown morning configuration field')
        return cls(**fields)


# Operator configuration contains no credentials, paths or provider budgets.
INSTRUMENTS = ('KOSPI', 'Nikkei', 'SPY', 'QQQ', 'EIDO', 'USDIDR')
OWNER = 'bursawatch-dc-morning-brief'


def default_operator_config():
    return dict(version=1, timezone='Asia/Jakarta', cutoff_time='06:00',
                delivery_time='07:00', fallback_minutes=5, retry_minutes=15,
                destination_channel_id=None, instruments=list(INSTRUMENTS), logos={})


def load_operator_config_data(value):
    import re
    if type(value) is not dict or set(value) != set(default_operator_config()):
        raise ValueError('morning configuration fields do not match version 1')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('version must be 1')
    if value['timezone'] != 'Asia/Jakarta':
        raise ValueError('timezone must remain Asia/Jakarta')
    minutes = []
    for field in ('cutoff_time', 'delivery_time'):
        if type(value[field]) is not str or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value[field]):
            raise ValueError(field + ' must use HH:MM')
        hour, minute = map(int, value[field].split(':'))
        minutes.append(hour * 60 + minute)
    for field, low, high in [('fallback_minutes', 1, 30), ('retry_minutes', 1, 60)]:
        if type(value[field]) is not int or not low <= value[field] <= high:
            raise ValueError(field + ' is outside its bounds')
    if not minutes[0] < minutes[1] - value['fallback_minutes'] or minutes[1] + value['retry_minutes'] >= 1440:
        raise ValueError('require cutoff before fallback before delivery, and same-day retry deadline')
    channel = value['destination_channel_id']
    if channel is not None and (type(channel) is not str or not re.fullmatch(r'[0-9]{17,20}', channel)):
        raise ValueError('destination_channel_id must be a Discord channel ID or null')
    instruments = value['instruments']
    if (type(instruments) is not list or not instruments or
            any(type(x) is not str or x not in INSTRUMENTS for x in instruments) or
            len(set(instruments)) != len(instruments)):
        raise ValueError('instruments must be a nonempty unique supported list')
    logos = value['logos']
    if type(logos) is not dict or any(k not in INSTRUMENTS or (v is not None and (type(v) is not str or
            not re.fullmatch(r'<:[A-Za-z0-9_]+:[0-9]{17,20}>', v))) for k, v in logos.items()):
        raise ValueError('logos must map supported instruments to custom emoji markup')
    # JSON copy keeps a caller's subsequent edits out of the validated value.
    import json
    return json.loads(json.dumps(value))


def timing_for(session, config):
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo
    config = load_operator_config_data(config)
    def at(field):
        return datetime.combine(session, time.fromisoformat(config[field]), tzinfo=ZoneInfo(config['timezone']))
    target = at('delivery_time')
    return dict(cutoff=at('cutoff_time'), target=target,
                fallback=target-timedelta(minutes=config['fallback_minutes']),
                deadline=target+timedelta(minutes=config['retry_minutes']))


def retained_operator_config(store, run_id):
    record = store.get_frozen(run_id, 'operator_config')
    if record is not None:
        return load_operator_config_data(record.payload['config'])
    # Historical local runs retain the originally reviewed timing.
    config = default_operator_config()
    config.update(cutoff_time='07:30', delivery_time='08:00')
    return config
