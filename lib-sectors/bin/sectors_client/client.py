"""Cache-backed client. Network use requires explicit configuration. Credit limits are optional."""
from datetime import datetime, timezone
import time
from .cache import CacheStore
from .models import (CacheMiss, RequestIdentity, RequestInFlight, SessionResult,
                     SectorsError, Throttled, UncertainOutcome, ValidationError, instant)
from .transport import HTTPTransport


class SectorsClient:
    def __init__(self, config, *, store=None, transport=None, clock=None):
        self.config = config
        self.store = store if store is not None else CacheStore(config.store_path)
        if self.store.path.resolve() != config.store_path.resolve():
            raise ValidationError('client store differs from configured coordination store')
        self.transport = transport if transport is not None else HTTPTransport(config)
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def get(self, identity, *, cutoff, max_cost=1, retry=False):
        cutoff = instant(cutoff)
        deadline = time.monotonic() + self.config.wait_seconds
        while True:
            try:
                return self.store.get(identity, cutoff=cutoff)
            except CacheMiss:
                if self.config.cache_only:
                    raise
            try:
                token = self.store.reserve(identity, self.config, max_cost=max_cost, now=self.clock(), retry=retry)
            except RequestInFlight:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
                continue
            if token is None:
                # A version exists, but was unavailable at this cutoff. Do not refetch.
                return self.store.get(identity, cutoff=cutoff)
            try:
                payload = self.transport.get(identity)
                self.store.complete(identity, token, payload, now=self.clock())
            except Throttled as error:
                self.store.failed(identity, token, now=self.clock(), kind='throttled', retry_after=error.retry_after)
                raise
            except UncertainOutcome:
                self.store.failed(identity, token, now=self.clock(), kind='uncertain')
                raise
            except SectorsError:
                self.store.failed(identity, token, now=self.clock(), kind='blocked')
                raise
            except Exception:
                self.store.failed(identity, token, now=self.clock(), kind='uncertain')
                raise UncertainOutcome('provider request billing outcome is uncertain') from None
            return self.store.get(identity, cutoff=cutoff)

    def close_session(self, session, *, cutoff, page_limit=30, max_cost=1, retry=False, max_pages=1000):
        if type(max_pages) is not int or not 0 < max_pages <= 10000:
            raise ValidationError('invalid pagination bound')
        pages, rows, seen = [], [], set()
        offset, total = 0, None
        for _ in range(max_pages):
            identity = RequestIdentity('/v2/close/', {'date':session, 'offset':offset, 'limit':page_limit})
            try:
                cached = self.get(identity, cutoff=cutoff, max_cost=max_cost, retry=retry)
            except CacheMiss:
                missing = tuple(range(offset, total, page_limit)) if total is not None else (0,)
                return SessionResult(session, tuple(rows), tuple(pages), total or 0, False, missing)
            payload = cached.payload
            p = payload['pagination']
            if total is not None and p['total_count'] != total:
                raise ValidationError('close session pagination totals changed')
            total = p['total_count']
            for row in payload['results']:
                if row['symbol'] in seen:
                    raise ValidationError('duplicate symbol across close session pages')
                seen.add(row['symbol'])
                rows.append(row)
            pages.append(cached)
            if not p['has_next']:
                if len(rows) != total:
                    raise ValidationError('close session count does not match total')
                return SessionResult(session, tuple(rows), tuple(pages), total, True)
            offset = p['next_offset']
        raise ValidationError('close session exceeds bounded pagination plan')
