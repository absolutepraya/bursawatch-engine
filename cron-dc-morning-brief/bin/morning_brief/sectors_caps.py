"""Caller-owned 30-day cap snapshots over the shared Sectors cache and ledger."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from sectors_client import RequestIdentity
from sectors_client.models import CacheMiss, SectorsError
from .calendar import aware
from .host import private_file
from .inputs import positive, symbol
from .public_collector import write_once
from .store import canonical, digest, stamp

TTL = timedelta(days=30)


def _read(cache, reference, now):
    identity=reference['sha256']
    if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('cap snapshot digest required')
    raw=private_file(cache/('sectors-caps-'+identity+'.json'),max_bytes=2_100_000)
    if hashlib.sha256(raw).hexdigest()!=identity:
        raise ValueError('cap snapshot digest mismatch')
    value=json.loads(raw)
    if aware(datetime.fromisoformat(value['collected_at']))>now:
        raise ValueError('future cap snapshot')
    return value


def collect_caps(client, *, cache, index, persist, now, cutoff, request_limit, clock=None):
    """Commit only complete pagination. Failed refresh keeps the original snapshot.

    Pending generations survive ticks and failures. The shared client decides
    whether a page can be fetched; this owner never authorizes retries.
    """
    now=aware(now);cutoff=aware(cutoff)
    clock=clock or (lambda:now)
    state=index.setdefault('sectors_caps',{})
    previous=_read(cache,state['current'],now) if state.get('current') else None
    if previous and now-datetime.fromisoformat(previous['collected_at'])<TTL:
        return previous,0,[]
    if client is None:
        return previous,0,['caps:sectors_configuration_unavailable']
    generation=state.setdefault('pending','morning-caps:'+digest(dict(previous=state.get('current'),started=stamp(now)))[:40])
    persist()
    offset=0;total=None;values={};seen=set();pages=[];attempts=0
    try:
        for _ in range(10):
            observed=aware(clock())
            if observed>=cutoff:
                return previous,attempts,['caps:cutoff_reached']
            identity=RequestIdentity('/v2/companies/',dict(where='sector IS NOT NULL',order_by='market_cap',
                include_query_values=True,limit=200,offset=offset),generation=generation)
            try:
                page=client.store.get(identity,cutoff=min(observed,cutoff))
            except CacheMiss:
                if attempts>=request_limit:
                    return previous,attempts,['caps:refresh_incomplete']
                attempts+=1
                page=client.get(identity,cutoff=cutoff,max_cost=1,retry=False)
            visible=aware(page.available_at)
            if visible>min(aware(clock()),cutoff) or page.imported or page.provenance!='provider-https':
                raise ValueError('cutoff-visible native cap page required')
            payload=page.payload;meta=payload['pagination'];rows=payload['results']
            count=meta['total_count']
            if (type(count) is not int or not 0<count<=2000 or (total is not None and count!=total)
                    or meta['offset']!=offset or meta['limit']!=200 or meta['showing']!=len(rows)
                    or len(rows)!=min(200,count-offset)):
                raise ValueError('complete stable cap pagination required')
            total=count
            for row in rows:
                ticker=symbol(row['symbol'])
                if ticker in seen:raise ValueError('duplicate cap symbol')
                seen.add(ticker)
                try:values[ticker]=positive(row['query_values']['market_cap'])
                except (KeyError,ValueError,TypeError):pass
            pages.append(dict(key=identity.key,source_url=identity.url,sha256=digest(payload),available_at=stamp(visible)))
            offset+=len(rows);more=offset<total
            if meta['has_next'] is not more or meta.get('next_offset')!=(offset if more else None):
                raise ValueError('cap continuation mismatch')
            if not more:
                if not values:raise ValueError('no usable market caps')
                collected=max(datetime.fromisoformat(p['available_at']) for p in pages)
                value=dict(identity=generation,collected_at=stamp(collected),effective_date=None,values=values,
                    provenance=dict(source_url='https://api.sectors.app/v2/companies/',digest=digest(pages),
                        method='sectors-companies-cap/collection-date-economic-date-unverified',
                        reference=canonical(dict(generation=generation,pages=pages))))
                encoded=canonical(value).encode();identity=hashlib.sha256(encoded).hexdigest()
                write_once(cache/('sectors-caps-'+identity+'.json'),encoded)
                state['current']=dict(sha256=identity);state.pop('pending',None);persist()
                return value,attempts,[]
        raise ValueError('cap pagination bound exceeded')
    except Exception as error:
        return previous,attempts,['caps:'+type(error).__name__]


def configured_rotation(producer, collect_rotation):
    """Lazy provider construction: checks, recovery and post-cutoff ticks do no IO."""
    def collect(**kwargs):
        client=None
        if producer.sectors_store_path is not None:
            from sectors_client import Config, SectorsClient
            from zoneinfo import ZoneInfo
            now=kwargs['now']
            try:
                config=Config.from_env_file(producer.sectors_key_file,store_path=Path(producer.sectors_store_path),
                    caller='morning-brief',billing_window=now.astimezone(ZoneInfo('Asia/Jakarta')).strftime('%Y-%m'),
                    cache_only=False,timeout_seconds=10,wait_seconds=0)
                client=SectorsClient(config,clock=kwargs.get('clock'))
            except (OSError, ValueError, SectorsError):
                client=None
        return collect_rotation(**kwargs,sectors_client=client)
    return collect
