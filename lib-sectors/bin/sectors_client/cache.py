"""Private host-local SQLite cache, immutable versions and durable fetch ownership."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
from .models import (CachedResponse, CacheMiss, ValidationError, RequestInFlight,
                     UncertainOutcome, Throttled, RetryExhausted, instant)


def validate_payload(identity, payload):
    if not isinstance(payload, (dict, list)):
        raise ValidationError('invalid provider payload shape')
    if identity.path != '/v2/close/':
        return
    query = dict(identity.query)
    try:
        rows, p = payload['results'], payload['pagination']
        total, offset, limit = p['total_count'], p['offset'], p['limit']
        if not isinstance(rows, list) or any(type(v) is not int or v < 0 for v in (total, offset, limit)) or not limit:
            raise ValueError
        if offset != query.get('offset', 0) or limit != query.get('limit', 30):
            raise ValueError
        if len(rows) > limit or p['showing'] != len(rows) or offset + len(rows) > total:
            raise ValueError
        more = offset + len(rows) < total
        if type(p['has_next']) is not bool or p['has_next'] != more or (more and not rows):
            raise ValueError
        if more and p['next_offset'] != offset + limit or not more and p['next_offset'] is not None:
            raise ValueError
        seen = set()
        for row in rows:
            symbol = row['symbol']
            if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9]{0,11}(?:\.JK)?', symbol) or symbol in seen:
                raise ValueError
            seen.add(symbol)
            if row['date'] != query['date']:
                raise ValueError
            close = row['close']
            # Zero/null prices are missing evidence, not invented positive coverage.
            if close is not None and (isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close < 0):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValidationError('invalid close page identity or pagination') from None


class CacheStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValidationError('coordination store must not be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create privately before sqlite opens it. Do not change the caller's parent directory.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connection(write=True) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValidationError('unsupported coordination schema')
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT, digest TEXT, available_at TEXT, payload TEXT, provenance TEXT, imported INTEGER, PRIMARY KEY(key,digest,available_at))')
            db.execute('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, token TEXT, state TEXT, lease_until TEXT, attempts INTEGER, cooldown_until TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (token TEXT PRIMARY KEY, request_key TEXT, window TEXT, caller TEXT, cost INTEGER, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS limits (window TEXT, caller TEXT, maximum INTEGER, PRIMARY KEY(window,caller))')
            db.execute('CREATE TABLE IF NOT EXISTS reconciliations (token TEXT PRIMARY KEY, reserved_cost INTEGER, charged_cost INTEGER, evidence_digest TEXT)')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def get(self, identity, *, cutoff):
        cutoff = instant(cutoff).isoformat()
        with self.connection() as db:
            row = db.execute('SELECT * FROM cache WHERE key=? AND available_at<=? ORDER BY available_at DESC, rowid DESC LIMIT 1', (identity.key, cutoff)).fetchone()
        if row is None:
            raise CacheMiss('no provider cache version available at caller cutoff')
        return CachedResponse(identity, json.loads(row['payload']), instant(row['available_at']), row['provenance'], bool(row['imported']))

    def save(self, identity, payload, *, available_at, provenance, imported=False):
        validate_payload(identity, payload)
        stamp = instant(available_at).isoformat()
        if provenance not in ('provider-https', 'retained-local-close-pages'):
            raise ValidationError('unsupported response provenance')
        with self.connection(write=True) as db:
            return self._save(db, identity, payload, stamp, provenance, imported)

    def _save(self, db, identity, payload, stamp, provenance, imported):
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if imported and db.execute('SELECT 1 FROM cache WHERE key=? AND digest=? AND imported=1', (identity.key, digest)).fetchone():
            return False
        result = db.execute('INSERT OR IGNORE INTO cache VALUES (?,?,?,?,?,?)', (identity.key, digest, stamp, raw, provenance, int(imported)))
        return result.rowcount == 1

    def usage(self, window, caller):
        with self.connection() as db:
            host = db.execute('SELECT COALESCE(SUM(cost),0) FROM reservations WHERE window=?', (window,)).fetchone()[0]
            local = db.execute('SELECT COALESCE(SUM(cost),0) FROM reservations WHERE window=? AND caller=?', (window, caller)).fetchone()[0]
        return {'host_reserved': host, 'caller_reserved': local}

    def reserve(self, identity, config, *, max_cost, now, retry=False):
        from .budget import reserve_credits
        now = instant(now)
        with self.connection(write=True) as db:
            if db.execute('SELECT 1 FROM cache WHERE key=?', (identity.key,)).fetchone():
                return None
            row = db.execute('SELECT * FROM requests WHERE key=?', (identity.key,)).fetchone()
            attempts = row['attempts'] if row else 0
            if row:
                if row['state'] == 'fetching':
                    if instant(row['lease_until']) <= now:
                        raise UncertainOutcome('expired provider lease has unresolved billing outcome')
                    raise RequestInFlight('provider request is owned by another client')
                if row['state'] == 'uncertain':
                    raise UncertainOutcome('provider billing outcome requires explicit reconciliation')
                if row['state'] == 'throttled':
                    cooldown = (instant(row['cooldown_until']) - now).total_seconds() if row['cooldown_until'] else None
                    if not retry or cooldown is None or cooldown > 0:
                        raise Throttled(cooldown)
                if row['state'] == 'resolved' and not retry:
                    raise UncertainOutcome('reconciled request requires explicit retry authorization')
                if row['state'] == 'blocked':
                    raise UncertainOutcome('provider failure requires explicit reconciliation')
            if attempts >= config.max_attempts:
                raise RetryExhausted('provider retry allowance exhausted')
            token = uuid.uuid4().hex
            reserve_credits(db, config, identity.key, token, max_cost)
            db.execute('INSERT OR REPLACE INTO requests VALUES (?,?,?,?,?,?)', (identity.key, token, 'fetching', (now + timedelta(seconds=config.lease_seconds)).isoformat(), attempts + 1, None))
            return token

    def complete(self, identity, token, payload, *, now):
        validate_payload(identity, payload)
        with self.connection(write=True) as db:
            self._owner(db, identity, token)
            self._save(db, identity, payload, instant(now).isoformat(), 'provider-https', False)
            db.execute("UPDATE requests SET state='complete' WHERE key=?", (identity.key,))
            db.execute("UPDATE reservations SET state='spent' WHERE token=?", (token,))

    def failed(self, identity, token, *, now, kind, retry_after=None):
        if kind not in ('uncertain', 'blocked', 'throttled'):
            raise ValidationError('invalid request failure category')
        until = (instant(now) + timedelta(seconds=retry_after)).isoformat() if retry_after is not None else None
        with self.connection(write=True) as db:
            self._owner(db, identity, token)
            db.execute('UPDATE requests SET state=?, cooldown_until=? WHERE key=?', (kind, until, identity.key))
            # Every outcome retains the conservative cost. No credit assumptions.
            db.execute('UPDATE reservations SET state=? WHERE token=?', (kind, token))

    def request_status(self, identity):
        """Safe coordination metadata only. No provider payload or credential."""
        with self.connection() as db:
            row = db.execute('SELECT * FROM requests WHERE key=?', (identity.key,)).fetchone()
        return dict(row) if row is not None else None

    def reconcile(self, identity, *, token, charged_cost, evidence_digest, now=None):
        """Explicit administrative resolution backed by externally verified evidence.

        This does not verify provider billing itself. A digest names caller-retained
        authoritative evidence, never a response body or an account balance.
        """
        if type(charged_cost) is not int or charged_cost < 0 or not isinstance(evidence_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', evidence_digest):
            raise ValidationError('invalid billing reconciliation evidence')
        now = instant(now if now is not None else datetime.now(timezone.utc))
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM requests WHERE key=?', (identity.key,)).fetchone()
            reservation = db.execute('SELECT * FROM reservations WHERE token=? AND request_key=?', (token, identity.key)).fetchone()
            if not row or not reservation or row['token'] != token or charged_cost > reservation['cost']:
                raise ValidationError('billing reconciliation does not match reservation')
            if row['state'] not in ('uncertain', 'blocked', 'throttled', 'fetching') or row['state'] == 'fetching' and instant(row['lease_until']) > now:
                raise ValidationError('request is not eligible for billing reconciliation')
            if row['state'] == 'throttled' and row['cooldown_until'] and instant(row['cooldown_until']) > now:
                raise ValidationError('verified provider cooldown has not elapsed')
            db.execute('INSERT INTO reconciliations VALUES (?,?,?,?)', (token, reservation['cost'], charged_cost, evidence_digest))
            db.execute("UPDATE reservations SET cost=?, state='resolved' WHERE token=?", (charged_cost, token))
            db.execute("UPDATE requests SET state='resolved' WHERE key=?", (identity.key,))

    @staticmethod
    def _owner(db, identity, token):
        row = db.execute('SELECT token,state FROM requests WHERE key=?', (identity.key,)).fetchone()
        if not row or row['token'] != token or row['state'] != 'fetching':
            raise UncertainOutcome('provider request lease ownership was lost')
