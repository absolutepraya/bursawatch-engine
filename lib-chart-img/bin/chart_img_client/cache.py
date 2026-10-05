"""Shared immutable images and independent conservative Chart-IMG allowance."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import math
import sqlite3
from uuid import uuid4

from .models import ChartImgError, ImageArtifact, RenderRequest, aware, validate_image
from .transport import ProviderTransport


class RenderCache:
    """One provider account uses one store across all opted-in consumers.

    Construction has no I/O. initialize() explicitly creates the local store.
    Attempts are never refunded, including abandoned or uncertain requests.
    """
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def _db(self, *, write=False):
        db = None
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
            db.row_factory = sqlite3.Row
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.Error:
            if db is not None:
                db.rollback()
            raise ChartImgError('cache_unavailable') from None
        finally:
            if db is not None:
                db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.path, timeout=5) as db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS artifacts (
                        identity TEXT PRIMARY KEY, identity_json TEXT NOT NULL,
                        data BLOB NOT NULL, sha256 TEXT NOT NULL, retrieved REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS attempts (
                        attempt_id TEXT PRIMARY KEY, identity TEXT NOT NULL,
                        started REAL NOT NULL, lease_until REAL NOT NULL,
                        state TEXT NOT NULL, error_code TEXT);
                    CREATE INDEX IF NOT EXISTS attempts_identity ON attempts(identity);
                    CREATE INDEX IF NOT EXISTS attempts_started ON attempts(started);
                    CREATE TABLE IF NOT EXISTS throttle (
                        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                        blocked_until REAL);
                    INSERT OR IGNORE INTO throttle(singleton) VALUES(1);
                    CREATE TABLE IF NOT EXISTS audits (
                        attempt_id TEXT NOT NULL, resolved REAL NOT NULL,
                        evidence_ref TEXT NOT NULL);
                ''')
            self.path.chmod(0o600)
        except (OSError, sqlite3.Error):
            raise ChartImgError('cache_unavailable') from None

    def _artifact(self, row, request):
        if row is None:
            return None
        try:
            if row['identity_json'] != request.identity_json:
                raise ChartImgError('cache_corrupt')
            artifact = validate_image(bytes(row['data']), 'image/png', request,
                                      datetime.fromtimestamp(row['retrieved'], timezone.utc))
            if artifact.sha256 != row['sha256']:
                raise ChartImgError('cache_corrupt')
            return artifact
        except Exception:
            raise ChartImgError('cache_corrupt') from None

    def get(self, request: RenderRequest) -> ImageArtifact | None:
        with self._db() as db:
            return self._artifact(db.execute('SELECT * FROM artifacts WHERE identity=?',
                                            (request.identity,)).fetchone(), request)

    def reserve(self, request: RenderRequest, *, now: datetime, lease_seconds: float = 120) -> str | ImageArtifact:
        now = aware(now)
        stamp = now.timestamp()
        if not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 300:
            raise ChartImgError('invalid_request')
        error = None
        result = None
        with self._db(write=True) as db:
            artifact = self._artifact(db.execute('SELECT * FROM artifacts WHERE identity=?',
                                                (request.identity,)).fetchone(), request)
            if artifact is not None:
                return artifact
            row = db.execute("SELECT * FROM attempts WHERE identity=? AND state IN ('pending','unknown') ORDER BY started DESC LIMIT 1",
                             (request.identity,)).fetchone()
            if row is not None:
                if row['state'] == 'pending' and row['lease_until'] > stamp:
                    error = ChartImgError('render_in_progress', retry_at=datetime.fromtimestamp(row['lease_until'], timezone.utc))
                else:
                    db.execute("UPDATE attempts SET state='unknown' WHERE attempt_id=?", (row['attempt_id'],))
                    error = ChartImgError('outcome_unknown')
            else:
                throttle = db.execute('SELECT * FROM throttle WHERE singleton=1').fetchone()
                unknown_throttle = db.execute("SELECT 1 FROM attempts WHERE state='unknown' AND error_code='throttled' LIMIT 1").fetchone()
                if unknown_throttle:
                    error = ChartImgError('throttle_unknown')
                elif throttle['blocked_until'] is not None and throttle['blocked_until'] > stamp:
                    error = ChartImgError('throttled', retry_at=datetime.fromtimestamp(throttle['blocked_until'], timezone.utc))
                else:
                    recent = db.execute('SELECT started FROM attempts WHERE started>? ORDER BY started',
                                        (stamp - 86400,)).fetchall()
                    latest = db.execute('SELECT MAX(started) FROM attempts').fetchone()[0]
                    if len(recent) >= 50:
                        error = ChartImgError('allowance_exhausted', retry_at=datetime.fromtimestamp(recent[0]['started'] + 86400, timezone.utc))
                    elif latest is not None and stamp < latest + 1:
                        error = ChartImgError('rate_limited', retry_at=datetime.fromtimestamp(latest + 1, timezone.utc))
                    else:
                        result = uuid4().hex
                        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,NULL)',
                                   (result, request.identity, stamp, stamp + lease_seconds, 'pending'))
        if error:
            raise error
        return result

    def complete(self, attempt_id: str, artifact: ImageArtifact):
        # Public completion cannot persist arbitrary bytes/forged dimensions.
        valid = validate_image(artifact.data, artifact.content_type, artifact.request, artifact.retrieved_at)
        if valid.sha256 != artifact.sha256:
            raise ChartImgError('invalid_image')
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None or row['state'] != 'pending' or row['identity'] != valid.request.identity:
                raise ChartImgError('reservation_lost')
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',
                       (valid.request.identity, valid.request.identity_json, valid.data, valid.sha256, valid.retrieved_at.timestamp()))
            db.execute("UPDATE attempts SET state='complete' WHERE attempt_id=?", (attempt_id,))

    def fail(self, attempt_id: str, error: ChartImgError, *, now: datetime):
        stamp = aware(now).timestamp()
        uncertain = error.code in {'transport_failed', 'deadline_exceeded', 'invalid_response'}
        unknown_throttle = error.code == 'throttled' and error.retry_at is None
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None or row['state'] != 'pending':
                raise ChartImgError('reservation_lost')
            db.execute('UPDATE attempts SET state=?,error_code=? WHERE attempt_id=?',
                       ('unknown' if uncertain or unknown_throttle else 'failed', error.code, attempt_id))
            if error.code == 'throttled':
                if unknown_throttle:
                    # Every unresolved unknown 429 is a global gate. Keep the
                    # latest observation's full cooldown for safe recovery.
                    db.execute('UPDATE throttle SET blocked_until=MAX(COALESCE(blocked_until,0),?) WHERE singleton=1',
                               (stamp + 86400,))
                else:
                    db.execute('UPDATE throttle SET blocked_until=MAX(COALESCE(blocked_until,0),?) WHERE singleton=1',
                               (aware(error.retry_at).timestamp(),))

    def allowance(self, *, now: datetime) -> dict:
        stamp = aware(now).timestamp()
        with self._db() as db:
            used = db.execute('SELECT COUNT(*) FROM attempts WHERE started>?', (stamp - 86400,)).fetchone()[0]
            return {'used': used, 'remaining': max(0, 50 - used), 'window_seconds': 86400}

    def unresolved(self) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM attempts WHERE state IN ('pending','unknown') ORDER BY started,attempt_id")]

    def resolve_unknown(self, attempt_id: str, *, now: datetime, evidence_ref: str):
        """Audit externally verified stopped writers; never refund the reservation.

        An unknown 429 also requires a full 24-hour cooldown. This method does
        not itself contact the provider or verify the supplied evidence.
        """
        stamp = aware(now).timestamp()
        if not isinstance(evidence_ref, str) or not evidence_ref.strip() or len(evidence_ref) > 500:
            raise ChartImgError('resolution_requires_evidence')
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None or row['state'] not in {'pending', 'unknown'} or (row['state'] == 'pending' and row['lease_until'] > stamp):
                raise ChartImgError('resolution_not_allowed')
            throttle = db.execute('SELECT * FROM throttle WHERE singleton=1').fetchone()
            if row['state'] == 'unknown' and row['error_code'] == 'throttled':
                if stamp < throttle['blocked_until']:
                    raise ChartImgError('resolution_not_allowed')
            db.execute("UPDATE attempts SET state='resolved' WHERE attempt_id=?", (attempt_id,))
            db.execute('INSERT INTO audits VALUES(?,?,?)', (attempt_id, stamp, evidence_ref))

    def audit_log(self) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM audits ORDER BY resolved,attempt_id')]


class ChartImgClient:
    """No hidden retries or sleeping. A cache-only client needs no credential."""
    def __init__(self, cache: RenderCache, provider: ProviderTransport | None = None, *, clock=None):
        self.cache = cache
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def render(self, request: RenderRequest, *, cache_only=True, max_age_seconds=None) -> ImageArtifact:
        if type(cache_only) is not bool:
            raise ChartImgError('invalid_request')
        now = aware(self.clock())
        if max_age_seconds is not None and (not math.isfinite(max_age_seconds) or max_age_seconds < 0):
            raise ChartImgError('invalid_request')
        artifact = self.cache.get(request)
        if artifact is not None:
            if max_age_seconds is not None and (now - artifact.retrieved_at).total_seconds() > max_age_seconds:
                raise ChartImgError('stale_cache')
            return artifact
        if cache_only:
            raise ChartImgError('cache_miss')
        if self.provider is None:
            raise ChartImgError('transport_required')
        reservation = self.cache.reserve(request, now=now,
                                         lease_seconds=self.provider.timeout_seconds + 30)
        if isinstance(reservation, ImageArtifact):
            return reservation
        try:
            artifact = self.provider.render(request, now=now, clock=self.clock)
        except ChartImgError as error:
            self.cache.fail(reservation, error, now=aware(self.clock()))
            raise
        self.cache.complete(reservation, artifact)
        return artifact
