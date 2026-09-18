"""Admission and durable accounting contract, with an explicit wall clock."""
import asyncio
import sqlite3

import pytest

from wisp_backend.config import LedgerSettings
from wisp_backend.contracts import Outcome, RESERVATION, Usage
from wisp_backend.errors import ServiceError
from wisp_backend.ledger import SQLiteLedger


class Clock:
    now = 1_800_000_000.0
    def __call__(self):
        return self.now


def test_atomic_duplicates_reservation_and_replay(tmp_path):
    async def run():
        clock = Clock()
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings(), clock)
        results = await asyncio.gather(*(ledger.admit('one', 'digest') for _ in range(8)), return_exceptions=True)
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert [r.code for r in results if isinstance(r, ServiceError)] == ['request_in_progress'] * 7
        with pytest.raises(ServiceError, match='request_conflict'):
            await ledger.admit('one', 'changed')
        outcome = Outcome(200, b'{"text":"only in RAM"}')
        await ledger.settle('one', Usage(2, 3, 5), outcome)
        assert (await ledger.admit('one', 'digest')).replay == outcome
        await ledger.settle('one', Usage(9, 9, 18), outcome)
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            row = db.execute('SELECT requests,reserved,confirmed,uncertain,prompt,completion FROM days').fetchone()
            assert row == (1, 0, 5, 0, 2, 3)
        assert b'only in RAM' not in (tmp_path / 'ledger.sqlite').read_bytes()
    asyncio.run(run())


def test_crash_recovery_and_late_usage_once(tmp_path):
    async def run():
        path = tmp_path / 'ledger.sqlite'
        clock = Clock()
        ledger = await SQLiteLedger.open(path, LedgerSettings(), clock)
        await ledger.admit('one', 'digest')
        await ledger.close()
        ledger = await SQLiteLedger.open(path, LedgerSettings(), clock)
        with pytest.raises(ServiceError, match='request_conflict'):
            await ledger.admit('one', 'digest')
        await ledger.settle('one', Usage(2, 3, 5), None)
        await ledger.settle('one', Usage(9, 9, 18), None)
        await ledger.close()
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT confirmed,uncertain,reserved FROM days').fetchone() == (5, 0, 0)
    asyncio.run(run())


def test_boundaries_utc_ttl_and_backward_clock(tmp_path):
    async def run():
        clock = Clock()
        clock.now = 1_800_057_599.0  # final second of a UTC day
        policy = LedgerSettings(rate_limit=1, concurrent_limit=1, daily_requests=2, daily_tokens=RESERVATION)
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', policy, clock)
        await ledger.admit('one', 'digest')
        with pytest.raises(ServiceError, match='rate_limited'):
            await ledger.admit('two', 'digest')
        await ledger.settle('one', Usage(0, 0, 0), Outcome(200, b'{}'))
        clock.now += 60
        await ledger.admit('two', 'digest')
        await ledger.settle('two', None, None)
        clock.now -= 500
        with pytest.raises(ServiceError, match='rate_limited'):
            await ledger.admit('three', 'digest')
        clock.now += 560
        with pytest.raises(ServiceError, match='budget_exhausted'):
            await ledger.admit('three', 'digest')
        clock.now += 86_400
        await ledger.admit('one', 'changed')
        await ledger.close()
    asyncio.run(run())


def test_cap_refund_and_over_limit_usage_latches_until_operator_action(tmp_path):
    async def run():
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings(daily_tokens=RESERVATION))
        await ledger.admit('one', 'digest')
        with pytest.raises(ServiceError, match='budget_exhausted'):
            await ledger.admit('two', 'digest')
        await ledger.settle('one', Usage(0, 0, 0), Outcome(200, b'{}'))
        await ledger.admit('two', 'digest')
        await ledger.settle('two', Usage(RESERVATION, 1, RESERVATION + 1), None)
        with pytest.raises(ServiceError, match='upstream_unavailable'):
            await ledger.admit('three', 'digest')
        await ledger.close()
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings())
        with pytest.raises(ServiceError, match='upstream_unavailable'):
            await ledger.admit('three', 'digest')
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT confirmed FROM days').fetchone()[0] == RESERVATION + 1
    asyncio.run(run())


def test_cache_ttl_eviction_and_retention(tmp_path):
    async def run():
        clock = Clock()
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite',
            LedgerSettings(rate_limit=200, daily_requests=200), clock)
        for index in range(101):
            await ledger.admit(str(index), 'digest')
            await ledger.settle(str(index), Usage(0, 0, 0), Outcome(200, b'{}'))
        with pytest.raises(ServiceError, match='request_conflict'):
            await ledger.admit('0', 'digest')
        assert (await ledger.admit('100', 'digest')).replay
        clock.now += 600
        with pytest.raises(ServiceError, match='request_conflict'):
            await ledger.admit('100', 'digest')
        clock.now += 86_400
        await ledger.maintain()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT count(*) FROM entries').fetchone()[0] == 0
            assert db.execute('SELECT requests FROM days').fetchone()[0] == 101
        clock.now += 30 * 86_400
        await ledger.maintain()
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT count(*) FROM days').fetchone()[0] == 0
    asyncio.run(run())


def test_settlement_stays_in_original_utc_bucket(tmp_path):
    async def run():
        clock = Clock()
        clock.now = 20_000 * 86_400 + 86_399
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings(), clock)
        await ledger.admit('one', 'digest')
        clock.now += 2
        await ledger.settle('one', Usage(2, 3, 5), None)
        await ledger.admit('two', 'digest')
        await ledger.settle('two', Usage(1, 1, 2), None)
        clock.now -= 86_400
        await ledger.admit('three', 'digest')
        await ledger.settle('three', Usage(1, 1, 2), None)
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT bucket,requests,confirmed FROM days ORDER BY bucket').fetchall() == [(20_000, 1, 5), (20_001, 2, 4)]
    asyncio.run(run())


def test_disk_failure_fails_closed_and_preserves_reservation(tmp_path):
    async def run():
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings())
        await ledger.admit('one', 'digest')
        await ledger._run(lambda: ledger.db.execute('PRAGMA query_only=ON'))
        with pytest.raises(ServiceError, match='upstream_unavailable'):
            await ledger.settle('one', Usage(1, 1, 2), Outcome(200, b'{}'))
        with pytest.raises(ServiceError, match='upstream_unavailable'):
            await ledger.admit('two', 'digest')
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT reserved,confirmed FROM days').fetchone() == (RESERVATION, 0)
        ledger = await SQLiteLedger.open(tmp_path / 'ledger.sqlite', LedgerSettings())
        await ledger.close()
        with sqlite3.connect(tmp_path / 'ledger.sqlite') as db:
            assert db.execute('SELECT reserved,uncertain FROM days').fetchone() == (0, RESERVATION)
    asyncio.run(run())


def test_huge_over_limit_usage_preserved_and_halts(tmp_path):
    async def run():
        path = tmp_path / 'ledger.sqlite'
        ledger = await SQLiteLedger.open(path, LedgerSettings())
        await ledger.admit('one', 'digest')
        reported = 10**100
        await ledger.settle('one', Usage(reported, 1, reported + 1), None)
        with pytest.raises(ServiceError, match='upstream_unavailable'):
            await ledger.admit('two', 'digest')
        await ledger.close()
        with sqlite3.connect(path) as db:
            assert int(db.execute('SELECT confirmed FROM days').fetchone()[0]) == reported + 1
    asyncio.run(run())


def test_day_request_cap_and_no_new_charge_for_rejection(tmp_path):
    async def run():
        path = tmp_path / 'ledger.sqlite'
        ledger = await SQLiteLedger.open(path, LedgerSettings(daily_requests=1))
        await ledger.admit('one', 'digest')
        await ledger.settle('one', Usage(0,0,0), None)
        with pytest.raises(ServiceError, match='budget_exhausted') as error:
            await ledger.admit('two', 'digest')
        assert 1 <= error.value.retry_after_ms <= 86_400_000
        await ledger.close()
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT requests FROM days').fetchone()[0] == 1
    asyncio.run(run())
