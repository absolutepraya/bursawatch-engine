"""Restart-safe immutable run records with single-session fenced writer leases."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from .calendar import aware, iso_date


class FreezeConflict(ValueError): pass
class LeaseBusy(RuntimeError): pass
class LeaseLost(RuntimeError): pass


def canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(payload) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def stamp(now):
    return aware(now).astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    session: str
    freeze_at: str
    phase: str
    fallback_reason: str | None


@dataclass(frozen=True)
class Lease:
    run_id: str
    owner: str
    generation: int
    expires_at: str


@dataclass(frozen=True)
class FrozenRecord:
    run_id: str
    slot: str
    digest: str
    payload: dict
    dependencies: dict[str,str]
    frozen_at: str


class RunStore:
    """Payload slots retain evidence/text/image/omission/version manifests without schema churn.

    Only freeze, receipt and mutable progress writes require an active fenced lease.
    Publication payloads and receipt observations are immutable, even under raw SQL.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError('run store must not be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self._db() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('unsupported morning run schema')
            db.executescript('''
                PRAGMA user_version=1;
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES(1);
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY, session TEXT UNIQUE NOT NULL,
                    freeze_at TEXT NOT NULL, phase TEXT NOT NULL, fallback_reason TEXT);
                CREATE TABLE IF NOT EXISTS leases(
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id), owner TEXT NOT NULL,
                    generation INTEGER NOT NULL, expires_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS freezes(
                    run_id TEXT REFERENCES runs(run_id), slot TEXT, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, dependencies TEXT NOT NULL, frozen_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,slot));
                CREATE TABLE IF NOT EXISTS receipts(
                    run_id TEXT, slot TEXT, operation_key TEXT, payload_digest TEXT,
                    receipt_digest TEXT, receipt TEXT, observed_at TEXT,
                    PRIMARY KEY(run_id,slot,receipt_digest),
                    FOREIGN KEY(run_id,slot) REFERENCES freezes(run_id,slot));
                CREATE TABLE IF NOT EXISTS checkpoints(
                    run_id TEXT REFERENCES runs(run_id), name TEXT, value TEXT NOT NULL,
                    PRIMARY KEY(run_id,name));
                CREATE TRIGGER IF NOT EXISTS frozen_no_update BEFORE UPDATE ON freezes
                    BEGIN SELECT RAISE(ABORT,'immutable freeze'); END;
                CREATE TRIGGER IF NOT EXISTS frozen_no_delete BEFORE DELETE ON freezes
                    BEGIN SELECT RAISE(ABORT,'immutable freeze'); END;
                CREATE TRIGGER IF NOT EXISTS receipt_no_update BEFORE UPDATE ON receipts
                    BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
                CREATE TRIGGER IF NOT EXISTS receipt_no_delete BEFORE DELETE ON receipts
                    BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
                CREATE TRIGGER IF NOT EXISTS run_identity_no_update
                    BEFORE UPDATE OF run_id,session,freeze_at ON runs
                    BEGIN SELECT RAISE(ABORT,'immutable run identity'); END;
            ''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_run(self, session: str, *, freeze_at: datetime, run_id: str | None = None) -> RunRecord:
        iso_date(session)
        freeze = stamp(freeze_at)
        with self._db() as db:
            existing = db.execute('SELECT * FROM runs WHERE session=?',(session,)).fetchone()
            if existing:
                if existing['freeze_at'] != freeze: raise FreezeConflict('session freeze instant already fixed')
                return RunRecord(**dict(existing))
            identity = run_id or uuid.uuid4().hex
            if not identity: raise ValueError('run identity required')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,NULL)',(identity,session,freeze,'created'))
            return RunRecord(identity,session,freeze,'created',None)

    def get_run(self, run_id: str) -> RunRecord:
        with self._db() as db:
            row = db.execute('SELECT * FROM runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None: raise KeyError(run_id)
            return RunRecord(**dict(row))

    def acquire_lease(self, run_id: str, owner: str, *, now: datetime, seconds: int = 60) -> Lease:
        if not owner or type(seconds) is not int or seconds <= 0: raise ValueError('invalid lease')
        instant, expiry = stamp(now), stamp(now+timedelta(seconds=seconds))
        with self._db() as db:
            if not db.execute('SELECT 1 FROM runs WHERE run_id=?',(run_id,)).fetchone(): raise KeyError(run_id)
            old = db.execute('SELECT * FROM leases WHERE run_id=?',(run_id,)).fetchone()
            if old and old['expires_at'] > instant:
                raise LeaseBusy('session already leased; renew with current lease')
            generation = old['generation']+1 if old else 1
            db.execute('INSERT INTO leases VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET owner=excluded.owner,generation=excluded.generation,expires_at=excluded.expires_at',
                       (run_id,owner,generation,expiry))
            return Lease(run_id,owner,generation,expiry)

    def _check_lease(self, db, run_id, lease, now):
        row = db.execute('SELECT * FROM leases WHERE run_id=?',(run_id,)).fetchone()
        if (lease.run_id != run_id or row is None or row['owner'] != lease.owner
                or row['generation'] != lease.generation or row['expires_at'] <= stamp(now)):
            raise LeaseLost('session lease lost or expired')

    def renew_lease(self, lease: Lease, *, now: datetime, seconds: int = 60) -> Lease:
        if type(seconds) is not int or seconds <= 0: raise ValueError('invalid lease duration')
        expiry = stamp(now+timedelta(seconds=seconds))
        with self._db() as db:
            self._check_lease(db,lease.run_id,lease,now)
            db.execute('UPDATE leases SET expires_at=? WHERE run_id=?',(expiry,lease.run_id))
        return Lease(lease.run_id,lease.owner,lease.generation,expiry)

    def release_lease(self, lease: Lease, *, now: datetime):
        """Expire a completed writer while retaining its fencing generation."""
        with self._db() as db:
            self._check_lease(db,lease.run_id,lease,now)
            db.execute('UPDATE leases SET expires_at=? WHERE run_id=?',(stamp(now),lease.run_id))

    @staticmethod
    def _frozen(row):
        return FrozenRecord(row['run_id'],row['slot'],row['digest'],json.loads(row['payload']),
                            json.loads(row['dependencies']),row['frozen_at'])

    def get_frozen(self, run_id: str, slot: str) -> FrozenRecord | None:
        with self._db() as db:
            row = db.execute('SELECT * FROM freezes WHERE run_id=? AND slot=?',(run_id,slot)).fetchone()
            return self._frozen(row) if row else None

    def freeze(self, run_id: str, slot: str, payload: dict, *, lease: Lease, now: datetime,
               dependencies: dict[str,str] | None = None) -> FrozenRecord:
        if not slot or not isinstance(payload,dict): raise ValueError('named dictionary freeze required')
        dependencies = dict(dependencies or {})
        # Dependency identities participate in the immutable manifest hash.
        content_digest = digest({'payload':payload,'dependencies':dependencies})
        with self._db() as db:
            self._check_lease(db,run_id,lease,now)
            for dep, required in dependencies.items():
                row = db.execute('SELECT digest FROM freezes WHERE run_id=? AND slot=?',(run_id,dep)).fetchone()
                if row is None or row['digest'] != required: raise FreezeConflict('frozen dependency mismatch')
            old = db.execute('SELECT * FROM freezes WHERE run_id=? AND slot=?',(run_id,slot)).fetchone()
            if old:
                if old['digest'] != content_digest: raise FreezeConflict('immutable slot already frozen')
                return self._frozen(old)
            timestamp = stamp(now)
            db.execute('INSERT INTO freezes VALUES(?,?,?,?,?,?)',(run_id,slot,content_digest,canonical(payload),canonical(dependencies),timestamp))
            return FrozenRecord(run_id,slot,content_digest,json.loads(canonical(payload)),dependencies,timestamp)

    def append_receipt(self, run_id: str, slot: str, *, operation_key: str, payload_digest: str,
                       receipt: dict, lease: Lease, now: datetime) -> str:
        with self._db() as db:
            self._check_lease(db,run_id,lease,now)
            row = db.execute('SELECT payload FROM freezes WHERE run_id=? AND slot=?',(run_id,slot)).fetchone()
            frozen = json.loads(row['payload']) if row else {}
            if not operation_key or frozen.get('operation_key') != operation_key or frozen.get('digest') != payload_digest:
                raise FreezeConflict('receipt identity does not match frozen operation')
            receipt_digest = digest(receipt)
            db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?,?)',
                       (run_id,slot,operation_key,payload_digest,receipt_digest,canonical(receipt),stamp(now)))
            return receipt_digest

    def get_receipts(self, run_id: str, slot: str) -> tuple[dict,...]:
        with self._db() as db:
            return tuple(json.loads(r['receipt']) for r in db.execute('SELECT receipt FROM receipts WHERE run_id=? AND slot=? ORDER BY observed_at,receipt_digest',(run_id,slot)))

    def transition(self, run_id: str, phase: str, *, lease: Lease, now: datetime, fallback_reason: str | None = None):
        if not phase: raise ValueError('phase required')
        with self._db() as db:
            self._check_lease(db,run_id,lease,now)
            db.execute('UPDATE runs SET phase=?,fallback_reason=? WHERE run_id=?',(phase,fallback_reason,run_id))

    def set_checkpoint(self, run_id: str, name: str, value: str, *, lease: Lease, now: datetime):
        if not name: raise ValueError('checkpoint name required')
        with self._db() as db:
            self._check_lease(db,run_id,lease,now)
            db.execute('INSERT INTO checkpoints VALUES(?,?,?) ON CONFLICT(run_id,name) DO UPDATE SET value=excluded.value',(run_id,name,value))

    def get_checkpoint(self, run_id: str, name: str) -> str | None:
        with self._db() as db:
            row = db.execute('SELECT value FROM checkpoints WHERE run_id=? AND name=?',(run_id,name)).fetchone()
            return row['value'] if row else None
