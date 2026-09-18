"""One-worker durable admission; all SQLite operations run on a worker thread."""
import asyncio
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from wisp_backend.config import LedgerSettings
from wisp_backend.contracts import Admission, Outcome, RESERVATION, Usage
from wisp_backend.errors import ServiceError

ID_TTL = 86_400
CACHE_TTL = 600


class SQLiteLedger:
    def __init__(self, path: Path, policy: LedgerSettings, clock: Callable[[], float]):
        self.path, self.policy, self.clock = path, policy, clock
        self.lock = threading.Lock()
        self.cache: OrderedDict[str, tuple[float, Outcome]] = OrderedDict()
        self.failed = False

    @classmethod
    async def open(cls, path: Path, policy: LedgerSettings, clock=time.time):
        ledger = cls(path, policy, clock)
        try:
            await ledger._run(ledger._initialize)
        except ServiceError:
            await ledger.close()
            raise
        return ledger

    async def _run(self, operation, *args):
        def guarded():
            with self.lock:
                if self.failed:
                    raise ServiceError("upstream_unavailable")
                try:
                    return operation(*args)
                except (sqlite3.Error, OSError):
                    self.failed = True
                    raise ServiceError("upstream_unavailable") from None
        return await asyncio.to_thread(guarded)

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=0.25, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value REAL NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('clock',0), ('halt',0);
            CREATE TABLE IF NOT EXISTS days (
                bucket INTEGER PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0, confirmed NOT NULL DEFAULT 0,
                uncertain INTEGER NOT NULL DEFAULT 0, prompt NOT NULL DEFAULT 0,
                completion NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, admitted REAL NOT NULL,
                bucket INTEGER NOT NULL, state TEXT NOT NULL, corrected INTEGER NOT NULL DEFAULT 0);
        ''')
        with self.db:
            for row in self.db.execute("SELECT id FROM entries WHERE state='flight'").fetchall():
                self._settle(row['id'], None, None)
            self._cleanup(self._now())

    def _now(self):
        now = max(self.clock(), self.db.execute("SELECT value FROM meta WHERE key='clock'").fetchone()[0])
        self.db.execute("UPDATE meta SET value=? WHERE key='clock'", (now,))
        return now

    def _cleanup(self, now):
        self.db.execute("DELETE FROM entries WHERE admitted<=? AND state!='flight'", (now - ID_TTL,))
        self.db.execute("DELETE FROM days WHERE bucket<=?", (int(now // ID_TTL) - 30,))
        for key, (created, _) in list(self.cache.items()):
            if created + CACHE_TTL <= now:
                del self.cache[key]

    async def admit(self, request_id: str, digest: str, legacy_digest: str | None = None) -> Admission:
        return await self._run(self._admit, request_id, digest, legacy_digest)

    def _admit(self, request_id, digest, legacy_digest):
        # A single process lock plus SQLite transaction covers every admission decision.
        with self.db:
            now = self._now()
            self._cleanup(now)
            row = self.db.execute("SELECT * FROM entries WHERE id=?", (request_id,)).fetchone()
            if row:
                if row['digest'] != digest and (legacy_digest is None or row['digest'] != legacy_digest):
                    raise ServiceError("request_conflict")
                if row['state'] == 'flight':
                    raise ServiceError("request_in_progress")
                if row['state'] == 'confirmed' and request_id in self.cache:
                    return Admission(self.cache[request_id][1])
                raise ServiceError("request_conflict")
            if self.db.execute("SELECT value FROM meta WHERE key='halt'").fetchone()[0]:
                raise ServiceError("upstream_unavailable")
            active = self.db.execute("SELECT count(*) FROM entries WHERE state='flight'").fetchone()[0]
            recent = self.db.execute("SELECT admitted FROM entries WHERE admitted>? ORDER BY admitted", (now - 60,)).fetchall()
            if active >= self.policy.concurrent_limit:
                raise ServiceError("rate_limited", 1000)
            if len(recent) >= self.policy.rate_limit:
                raise ServiceError("rate_limited", max(1, math.ceil((recent[0][0] + 60 - now) * 1000)))
            bucket = int(now // ID_TTL)
            self.db.execute("INSERT OR IGNORE INTO days(bucket) VALUES (?)", (bucket,))
            day = self.db.execute("SELECT * FROM days WHERE bucket=?", (bucket,)).fetchone()
            if (day['requests'] >= self.policy.daily_requests or
                    day['reserved'] + int(day['confirmed']) + day['uncertain'] + RESERVATION > self.policy.daily_tokens):
                raise ServiceError("budget_exhausted", max(1, math.ceil(((bucket + 1) * ID_TTL - now) * 1000)))
            self.db.execute("INSERT INTO entries(id,digest,admitted,bucket,state) VALUES (?,?,?,?,'flight')",
                            (request_id, digest, now, bucket))
            self.db.execute("UPDATE days SET requests=requests+1,reserved=reserved+? WHERE bucket=?", (RESERVATION, bucket))
        return Admission()

    async def settle(self, request_id: str, usage: Usage | None, outcome: Outcome | None,
                     deadline: float | None = None, cancelled: threading.Event | None = None):
        await self._run(self._terminal, request_id, usage, outcome, deadline, cancelled)

    def _terminal(self, request_id, usage, outcome, deadline, cancelled):
        with self.db:
            cacheable = self._settle(request_id, usage, outcome)
            now = self._now()
        # Cache only after successful durable commit and before the caller's
        # deadline. Slow disk cannot turn an already returned timeout into replay.
        if (cacheable and outcome and (deadline is None or time.monotonic() < deadline)
                and (cancelled is None or not cancelled.is_set())):
            self.cache[request_id] = (now, outcome)
            while len(self.cache) > 100:
                self.cache.popitem(last=False)

    def _settle(self, request_id, usage, outcome):
        row = self.db.execute("SELECT * FROM entries WHERE id=?", (request_id,)).fetchone()
        if not row or row['state'] == 'confirmed' or row['corrected']:
            return
        if row['state'] == 'uncertain' and usage is None:
            return
        if usage and usage.total > RESERVATION:
            self.db.execute("UPDATE meta SET value=1 WHERE key='halt'")
        reserved_delta = -RESERVATION if row['state'] == 'flight' else 0
        uncertain_delta = (0 if usage else RESERVATION) - (RESERVATION if row['state'] == 'uncertain' else 0)
        day = self.db.execute("SELECT * FROM days WHERE bucket=?", (row['bucket'],)).fetchone()
        # An untrusted provider may report a huge integer. Preserve its exact value
        # without overflowing SQLite's signed 64-bit binding, and latch admission.
        def bind(value):
            return value if value <= 2**63 - 1 else str(value)
        self.db.execute('''UPDATE days SET reserved=reserved+?, confirmed=?,
            uncertain=uncertain+?,prompt=?,completion=? WHERE bucket=?''',
            (reserved_delta, bind(int(day['confirmed']) + (usage.total if usage else 0)), uncertain_delta,
             bind(int(day['prompt']) + (usage.prompt if usage else 0)),
             bind(int(day['completion']) + (usage.completion if usage else 0)), row['bucket']))
        state = 'confirmed' if usage else 'uncertain'
        self.db.execute("UPDATE entries SET state=?,corrected=? WHERE id=?",
                        (state, int(row['state'] == 'uncertain'), request_id))
        # A late correction updates only accounting, never resurrects a response.
        return row['state'] == 'flight' and usage is not None and outcome is not None and len(outcome.body) <= 16 * 1024

    async def maintain(self):
        await self._run(self._maintenance)

    def _maintenance(self):
        with self.db:
            self._cleanup(self._now())
        # DELETE journal + secure_delete wipes reclaimed content; no persistent WAL.
        self.db.execute("PRAGMA incremental_vacuum")

    async def close(self):
        def close():
            with self.lock:
                self.cache.clear()
                if hasattr(self, 'db'):
                    self.db.close()
        await asyncio.to_thread(close)
