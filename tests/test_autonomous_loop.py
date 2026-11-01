"""Stops that used to be silent dead ends in the autonomous loop: stalled queue, blocked provider, missing reviewer, card activity."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_smart_router as fixtures
from center_reporting import _activity
from center_runtime import load_config
from center_store import event, now, transition


class LoopTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup

    def prepare(self):
        self.center.config['live_execution'] = True
        self.center.quota_reader = lambda: {}
        return self.center.submit('project-a', 'Scoped change', 'Change one file', ['src'], ['Tests pass'], mode='live')

    def sql(self, statement, params=()):
        with self.center.store.connection(write=True) as con:
            con.execute(statement, params)

    def test_a_queued_task_nobody_can_take_is_blocked_after_the_deadline(self):
        task = self.prepare()
        for name in ('codex', 'claude', 'google'):
            self.center.set_provider(name, 'unavailable', 'test')
        self.center.config['queue_stall_seconds'] = 60
        self.assertEqual(self.center.expire_stalled_queue(), [])  # not waited long enough yet
        self.sql("UPDATE tasks SET updated_at='2000-01-01T00:00:00.000+00:00' WHERE id=?", (task['id'],))
        self.assertEqual(self.center.expire_stalled_queue(), [task['id']])
        row = self.center.store.task(task['id'])
        self.assertEqual((row['status'], row['error']), ('blocked', 'no_provider_available'))

    def test_a_wait_for_capacity_or_quota_is_never_expired(self):
        first = self.prepare()
        waiting = self.center.submit('project-a', 'Second change', 'Needs the first one', ['src'], ['Tests pass'], mode='live', dependencies=[first['id']])
        self.center.config['queue_stall_seconds'] = 1
        self.sql("UPDATE tasks SET updated_at='2000-01-01T00:00:00.000+00:00' WHERE id=?", (waiting['id'],))
        self.assertEqual(self.center.scheduling_readiness(waiting['id'], 'implementation', 'live')['reason'], 'dependency_not_approved')
        self.assertEqual(self.center.expire_stalled_queue(), [])
        self.assertEqual(self.center.store.task(waiting['id'])['status'], 'queued')

    def block_after_dispatch(self, task, provider, error, role='implementation'):
        with self.center.store.connection(write=True) as con:
            event(con, task['id'], 'dispatch_recorded', {'provider': provider, 'role': role})
            transition(con, task['id'], 'blocked', {'reason': error})
            con.execute('UPDATE tasks SET error=?,provider=?,attempt=1 WHERE id=?', (error, provider, task['id']))

    def test_a_blocked_provider_hands_the_task_to_one_that_was_not_tried(self):
        task = self.prepare()
        self.block_after_dispatch(task, 'google', 'provider_blocked')
        self.assertEqual(self.center.auto_failover(), [task['id']])
        row = self.center.store.task(task['id'])
        self.assertEqual(row['status'], 'queued')
        self.assertNotEqual(row['requested_provider'], 'google')

    def test_failover_never_returns_to_a_provider_that_already_failed(self):
        task = self.prepare()
        for name in ('codex', 'claude'):
            self.center.set_provider(name, 'unavailable', 'test')
        self.block_after_dispatch(task, 'google', 'needs_narrower_scope')
        self.assertEqual(self.center.auto_failover(), [])
        self.assertEqual(self.center.store.task(task['id'])['status'], 'blocked')

    def test_a_blocked_review_is_not_restarted_as_an_implementation(self):
        task = self.prepare()
        self.block_after_dispatch(task, 'claude', 'provider_blocked', role='review')
        self.assertEqual(self.center.auto_failover(), [])

    def test_the_implementer_is_chosen_only_if_an_independent_reviewer_is_left(self):
        task = self.prepare()
        for name in ('claude', 'google'):
            self.center.set_provider(name, 'unavailable', 'test')
        readiness = self.center.scheduling_readiness(task['id'], 'implementation', 'live')
        self.assertFalse(readiness['ready'])
        self.assertEqual(readiness['reason'], 'no_independent_reviewer_available')

    def test_an_earlier_author_cannot_be_the_only_remaining_reviewer(self):
        task = self.prepare()
        self.center.set_provider('google', 'unavailable', 'test')
        self.sql("INSERT INTO authorship(task_id,session_id,provider,attempt,created_at) VALUES(?,?,?,?,?)", (task['id'], 's1', 'claude', 1, now()))
        ready = self.center.scheduling_readiness(task['id'], 'implementation', 'live')
        # claude already authored, so codex cannot be picked (nobody else could review it) and claude cannot review itself.
        self.assertNotEqual(ready.get('provider'), 'codex')

    def test_the_card_activity_is_the_latest_log_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 's1'
            run.mkdir()
            (run / 'provider.log').write_text('{"type":"item.completed","item":{"command":"npm test"}}\n', encoding='utf-8')
            self.assertEqual(_activity(tmp), 'provider: [item.completed] npm test')
            time.sleep(0.02)
            (run / 'gate-1.log').write_text('typechecking src\n', encoding='utf-8')
            self.assertEqual(_activity(tmp), 'gate-1: typechecking src')
        self.assertIsNone(_activity(None))
        self.assertIsNone(_activity('/no/such/directory'))

    def test_the_shipped_config_enables_the_loop_safeguards_and_rejects_bad_values(self):
        config = load_config()
        self.assertIs(config['auto_failover'], True)
        self.assertGreater(config['queue_stall_seconds'], 0)
        base = json.loads((Path(__file__).resolve().parents[1] / 'center.config.json').read_text(encoding='utf-8'))
        for key, value in (('auto_failover', 'yes'), ('queue_stall_seconds', -1), ('queue_stall_seconds', True)):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'c.json'
                path.write_text(json.dumps({**base, key: value}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(path)


if __name__ == '__main__':
    unittest.main()
