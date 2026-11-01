"""Scheduler preflight/fairness regressions without workers or provider calls."""
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from concurrent.futures import Future
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from center_service import service_status
from smart_router import _retry_pause, dispatch_ready, serve


class MemoryStore:
    def __init__(self, rows=()):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE tasks(id TEXT,status TEXT,project_id TEXT,mode TEXT,not_before REAL,created_at INTEGER)')
        self.db.execute('CREATE TABLE events(task_id TEXT,event TEXT)')
        self.db.execute('CREATE TABLE center_meta(key TEXT PRIMARY KEY,value TEXT)')
        self.db.executemany('INSERT INTO tasks VALUES(?,?,?,?,?,?)', rows)

    @contextmanager
    def connection(self, write=False):
        yield self.db


class RecordingPool:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append(args)
        result = Future()
        result.set_result({'state': 'not_claimed'})
        return result


class SchedulerTests(unittest.TestCase):
    def center(self, rows, blocked=(), capacity=4, **config):
        store = MemoryStore(rows)
        self.addCleanup(store.db.close)
        calls = []

        def readiness(task_id, role, adapter):
            calls.append((task_id, role, adapter))
            return {'ready': task_id not in blocked, 'reason': 'dependency_not_approved' if task_id in blocked else 'ready', 'provider': 'codex'}

        center = SimpleNamespace(store=store, config={'global_capacity': capacity, **config}, usable_capacity=lambda: capacity, scheduling_readiness=readiness,
                                 run_phase=lambda *_: None)
        center.readiness_calls = calls
        return center

    def test_blocked_oldest_capacity_does_not_starve_runnable_fifth(self):
        rows = [(f't{i}', 'queued', 'a', 'live', 0, i) for i in range(1, 6)]
        center = self.center(rows, blocked={'t1', 't2', 't3', 't4'})
        pool = RecordingPool()
        for _ in range(5):
            futures = {}
            dispatch_ready(center, 'live', pool, futures)
            self.assertEqual(set(futures), {'t5'})
        self.assertEqual([args[0] for args in pool.calls], ['t5'] * 5)

    def test_projects_interleave_and_rotate_across_ticks(self):
        rows = [('a1', 'queued', 'a', 'live', 0, 1), ('a2', 'queued', 'a', 'live', 0, 2),
                ('b1', 'queued', 'b', 'live', 0, 3), ('b2', 'queued', 'b', 'live', 0, 4)]
        center = self.center(rows, capacity=1)
        pool = RecordingPool()
        last = dispatch_ready(center, 'live', pool, {})
        last = dispatch_ready(center, 'live', pool, {}, last)
        self.assertEqual([args[0] for args in pool.calls], ['a1', 'b1'])
        self.assertEqual(last, 'b')

    def test_project_capacity_and_mock_completed_review_do_not_occupy_slots(self):
        rows = [('a1', 'queued', 'a', 'mock', 0, 1), ('a2', 'queued', 'a', 'mock', 0, 2),
                ('b1', 'waiting_for_independent_review', 'b', 'mock', 0, 3), ('c1', 'queued', 'c', 'mock', 0, 4)]
        center = self.center(rows, project_capacity=1)
        center.store.db.execute("INSERT INTO events VALUES('b1','mock_pipeline_complete')")
        pool = RecordingPool()
        futures = {}
        dispatch_ready(center, 'mock', pool, futures)
        self.assertEqual(set(futures), {'a1', 'c1'})
        self.assertTrue(all(args[2] == 'mock' for args in pool.calls))

    def test_readiness_provider_is_pinned_and_review_role_preserved(self):
        center = self.center([('r1', 'waiting_for_independent_review', 'a', 'live', 0, 1)])
        pool = RecordingPool()
        dispatch_ready(center, 'live', pool, {})
        self.assertEqual(pool.calls, [('r1', 'review', 'live', 'codex')])


class ServiceHealthTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.db.close)
        self.center = SimpleNamespace(store=self.store)

    def test_absent_or_stale_scheduler_not_healthy_despite_readable_database(self):
        self.assertEqual(service_status(self.center)['reason'], 'not_started')
        self.store.db.execute('INSERT INTO center_meta VALUES(?,?)', ('service', json.dumps({'pid': 123, 'mode': 'live', 'heartbeat': 70})))
        with patch('center_service.pid_alive', return_value=True), patch('center_service.time.time', return_value=100):
            status = service_status(self.center)
        self.assertFalse(status['running'])
        self.assertEqual(status['reason'], 'heartbeat_stale')
        self.assertEqual(status['heartbeat_age_seconds'], 30)

    def test_fresh_heartbeat_requires_live_process_and_malformed_record_is_unhealthy(self):
        self.store.db.execute('INSERT INTO center_meta VALUES(?,?)', ('service', json.dumps({'pid': 123, 'mode': 'mock', 'heartbeat': 99})))
        with patch('center_service.pid_alive', return_value=True), patch('center_service.time.time', return_value=100):
            status = service_status(self.center)
        self.assertTrue(status['running'])
        self.assertEqual(status['mode'], 'mock')
        with patch('center_service.pid_alive', return_value=False):
            self.assertFalse(service_status(self.center)['running'])
        self.store.db.execute("UPDATE center_meta SET value='[]'")
        self.assertEqual(service_status(self.center)['reason'], 'invalid_service_record')


class SchedulerDatabaseResilienceTests(unittest.TestCase):
    def run_scheduler(self, phase, errors, logs=None):
        """Exercise the actual loop; only local in-memory DB faults are injected."""
        with tempfile.TemporaryDirectory(prefix='center_service_test_') as directory:
            store = MemoryStore()
            self.addCleanup(store.db.close)
            store.state = Path(directory)
            original_connection = store.connection
            counts = {'connection': 0, 'recover': 0, 'dispatch': 0}
            pending = list(errors)
            pauses = []
            logs = [] if logs is None else logs

            @contextmanager
            def connection(write=False):
                counts['connection'] += 1
                if phase == 'heartbeat' and counts['connection'] == 2 and pending:
                    raise pending.pop(0)
                if phase == 'cleanup' and counts['connection'] == 4 and pending:
                    raise pending.pop(0)
                with original_connection(write) as con:
                    yield con

            def recover():
                counts['recover'] += 1
                if phase == 'recover' and pending:
                    raise pending.pop(0)

            def dispatch(*args):
                counts['dispatch'] += 1
                if phase == 'dispatch' and pending:
                    raise pending.pop(0)
                result = dispatch_ready(*args)
                (store.state / 'stop-fixture').touch()
                return result

            store.connection = connection
            center = SimpleNamespace(store=store, config={'global_capacity': 1}, usable_capacity=lambda: 1, recover=recover, expire_stalled_queue=lambda: [], run_phase=lambda *_: None)
            with patch('smart_router.uuid.uuid4', return_value=SimpleNamespace(hex='fixture')), patch('smart_router.dispatch_ready', side_effect=dispatch), patch('smart_router._retry_pause', side_effect=lambda stop, delay: pauses.append(delay)), patch('smart_router.time.sleep'), patch('smart_router.print_json', side_effect=logs.append):
                serve(center, 'mock')
            return counts, pauses, logs, store.db.execute("SELECT value FROM center_meta WHERE key='service'").fetchone(), (store.state / 'stop-fixture').exists()

    def test_transient_heartbeat_recover_or_dispatch_lock_recovers_instead_of_stopping(self):
        for phase in ('heartbeat', 'recover', 'dispatch'):
            with self.subTest(phase=phase):
                counts, pauses, logs, record, stop_exists = self.run_scheduler(phase, [sqlite3.OperationalError('database is locked')])
                self.assertEqual(pauses, [0.5])
                self.assertGreaterEqual(counts['dispatch'], 1)
                self.assertEqual(len([row for row in logs if row['event'] == 'scheduler_database_busy']), 1)
                self.assertFalse(stop_exists)
                self.assertIsNone(record)

    def test_repeated_busy_errors_have_capped_backoff_then_recover(self):
        _, pauses, logs, record, _ = self.run_scheduler('recover', [sqlite3.OperationalError('database is busy') for _ in range(7)])
        self.assertEqual(pauses, [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 5.0])
        self.assertTrue(all(row['retrying'] for row in logs))
        self.assertIsNone(record)

    def test_corrupt_or_readonly_database_fails_closed_without_private_error_text(self):
        for error in (sqlite3.DatabaseError('file is not a database PRIVATE_SENTINEL'), sqlite3.OperationalError('attempt to write readonly database PRIVATE_SENTINEL')):
            with self.subTest(error_type=type(error).__name__):
                logs = []
                with self.assertRaisesRegex(ValueError, 'database failure') as raised:
                    self.run_scheduler('recover', [error], logs)
                self.assertNotIn('PRIVATE_SENTINEL', str(raised.exception))
                self.assertNotIn('PRIVATE_SENTINEL', repr(logs))
                self.assertEqual(logs, [{'event': 'scheduler_database_error', 'retrying': False, 'error_type': type(error).__name__}])

    def test_stop_interrupts_monotonic_retry_wait(self):
        clock = [0.0]
        stop_requested = [False]
        delays = []
        stop = SimpleNamespace(exists=lambda: stop_requested[0])

        def sleep(delay):
            delays.append(delay)
            clock[0] += delay
            if clock[0] >= 0.2:
                stop_requested[0] = True

        with patch('smart_router.time.monotonic', side_effect=lambda: clock[0]), patch('smart_router.time.sleep', side_effect=sleep):
            _retry_pause(stop, 5)
        self.assertLess(clock[0], 5)
        self.assertTrue(all(delay <= 0.1 for delay in delays))

    def test_busy_cleanup_preserves_record_and_stop_request_still_completes(self):
        _, pauses, logs, record, stop_exists = self.run_scheduler('cleanup', [sqlite3.OperationalError('database is locked')])
        self.assertFalse(pauses)
        self.assertIsNotNone(record, 'An unverified service record must not be deleted')
        self.assertFalse(stop_exists)
        self.assertEqual(logs[-1]['event'], 'scheduler_database_cleanup_deferred')


if __name__ == '__main__':
    unittest.main()
