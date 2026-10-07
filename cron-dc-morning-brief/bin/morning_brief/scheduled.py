"""A single configured scheduler tick composes pre-cutoff inputs and delivery."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar import aware, SessionCalendar
from .config import load_operator_config_data, timing_for
from .host import private_file


@dataclass(frozen=True)
class ProducerConfig:
    version: int
    calendar_snapshot: str
    references: str
    source_cache: str
    economic_snapshots: tuple[str,...] = ()

    def __post_init__(self):
        paths=[self.calendar_snapshot,self.references,self.source_cache,*self.economic_snapshots]
        if (type(self.version) is not int or self.version!=1
                or len(self.economic_snapshots)>32
                or any(type(path) is not str or not Path(path).is_absolute() for path in paths)
                or len({str(Path(path).resolve()) for path in paths})!=len(paths)):
            raise ValueError('explicit distinct private producer paths required')

    @classmethod
    def from_file(cls,path):
        value=json.loads(private_file(path,max_bytes=16_384))
        return cls(**{**value,'economic_snapshots':tuple(value.get('economic_snapshots',()))})


class ScheduledRuntime:
    """Injected producers never run at/after the freeze or during recovery."""
    def __init__(self,host,producer,*,collect_rotation,collect_public,load_memberships,clock):
        self.host,self.producer=host,producer
        self.rotation,self.public,self.memberships=collect_rotation,collect_public,load_memberships
        self.clock=clock

    def tick(self):
        try:
            now=aware(self.clock());session=now.astimezone(ZoneInfo('Asia/Jakarta')).date()
            existing=self.host.store.get_run_for_session(session.isoformat())
            if existing and self.host.store.get_frozen(existing.run_id,'operator_config') is not None:
                return self.host.tick()
            snapshot=self.host.fetch_snapshot()
            from control_plane_client import ConfigSnapshot
            checked=ConfigSnapshot.from_payload(snapshot)
            if checked.watcher_id!='bursawatch-dc-morning-brief':
                raise ValueError('morning operator identity mismatch')
            settings=load_operator_config_data(checked.config);times=timing_for(session,settings)
            if now>=times['cutoff']:
                return self.host.tick(operator_snapshot=snapshot)
            raw=private_file(self.producer.calendar_snapshot,max_bytes=512_000);reference=json.loads(raw)
            calendar=SessionCalendar.from_file(self.producer.calendar_snapshot,expected_version=reference['version'],
                expected_amendment=reference['amendment'],as_of=now)
            if calendar.import_digest!=hashlib.sha256(raw).hexdigest():
                raise ValueError('calendar changed during scheduler tick')
            if not calendar.is_session(session):
                return self.host.beat(dict(phase='no_op',reason='non_session'))
            try:
                rotation=self.rotation(memberships=self.memberships(self.producer.references),calendar=calendar,
                    publication_session=session,cutoff=times['cutoff'],source_cache=self.producer.source_cache,now=now,
                    clock=self.clock)
            except Exception as error:
                rotation=dict(manifest_written=False,gaps=['rotation:'+type(error).__name__],posts=False)
            public=None
            observed=aware(self.clock())
            if times['cutoff']-timedelta(minutes=10)<=observed<times['cutoff']:
                path=Path(self.producer.source_cache)/'rotation-current.json'
                try:retained=json.loads(private_file(path)) if path.exists() else None
                except (OSError,ValueError,TypeError):retained=None;rotation['gaps']=[*rotation.get('gaps',[]),'rotation:retained_snapshot_unavailable']
                agenda=[];agenda_gaps=[]
                for path in self.producer.economic_snapshots:
                    try:agenda.append(json.loads(private_file(path,max_bytes=2_000_000)))
                    except (OSError,ValueError,TypeError):agenda_gaps.append('agenda:retained_snapshot_unavailable')
                try:
                    public=self.public(self.host.config,snapshot=snapshot,calendar_path=self.producer.calendar_snapshot,
                        source_cache=self.producer.source_cache,now=observed,clock=self.clock,rotation_snapshot=retained,
                        economic_snapshots=agenda)
                    if agenda_gaps:public={**public,'gaps':[*public.get('gaps',[]),*agenda_gaps]}
                except Exception as error:
                    public=dict(manifest_written=False,gaps=['public:'+type(error).__name__],posts=False)
            degraded=bool(rotation.get('gaps')) or not rotation.get('manifest_written')
            if public is not None:
                degraded=degraded or bool(public.get('gaps')) or bool(public.get('incomplete_sections')) or not public.get('manifest_written')
            return self.host.beat(dict(phase='input_preparation',gaps=int(degraded),
                producer=dict(rotation=rotation,public=public),receipt_outcome='none'))
        except Exception as error:
            return self.host.beat(dict(phase='fatal',reason=type(error).__name__))
