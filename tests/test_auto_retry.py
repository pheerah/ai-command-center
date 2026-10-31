"""Gate failures and rejected reviews go back through routing by themselves, but only within the attempt budget."""
import json
import unittest

import test_smart_router as fixtures


class AutoRetryTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task

    def fail_gates(self):
        cfg = json.loads(self.ca.read_text())
        cfg['quality_gates'] = [['python', '-c', 'raise SystemExit(9)']]
        self.ca.write_text(json.dumps(cfg))
        self.center.register('project-a', self.a, self.ca, confirm_config_change=True)

    def status(self, task_id):
        return self.center.store.task(task_id)

    def test_a_failed_gate_is_requeued_and_stops_exactly_at_the_attempt_budget(self):
        self.fail_gates()
        task = self.task()
        budget = self.status(task['id'])['max_attempts']
        for attempt in range(1, budget + 1):
            self.assertEqual(self.center.run_phase(task['id'], 'implementation', 'mock', 'codex')['state'], 'failed')
            self.assertEqual(self.status(task['id'])['attempt'], attempt)
            retried = self.center.auto_retry()
            self.assertEqual(retried, [task['id']] if attempt < budget else [])
        final = self.status(task['id'])
        self.assertEqual((final['status'], final['error'], final['attempt']), ('failed', 'quality_gate_failed', budget))
        self.assertEqual(self.center.auto_retry(), [])

    def test_every_attempt_is_kept_in_the_audit_trail(self):
        self.fail_gates()
        task = self.task()
        self.center.run_phase(task['id'], 'implementation', 'mock', 'codex')
        self.center.auto_retry()
        events = [row['event'] for row in self.center.report(task['id'])['events']]
        self.assertEqual(events.count('failed'), 1)
        self.assertIn('queued', events[events.index('failed'):])
        queued = [json.loads(row['detail']) for row in self.center.report(task['id'])['events'] if row['event'] == 'queued' and row['detail']]
        self.assertTrue(any(str(d.get('reason', '')).startswith('auto_retry_after_quality_gate_failure') for d in queued))

    def test_a_cancelled_or_blocked_task_is_never_retried(self):
        self.fail_gates()
        task = self.task()
        self.center.run_phase(task['id'], 'implementation', 'mock', 'codex')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET cancel_requested=1 WHERE id=?', (task['id'],))
        self.assertEqual(self.center.auto_retry(), [])
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET cancel_requested=0,status='blocked',error='auth' WHERE id=?", (task['id'],))
        self.assertEqual(self.center.auto_retry(), [])

    def test_a_failure_that_is_not_a_gate_or_review_result_is_left_for_a_human(self):
        self.fail_gates()
        task = self.task()
        self.center.run_phase(task['id'], 'implementation', 'mock', 'codex')
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET error='worker_failure' WHERE id=?", (task['id'],))
        self.assertEqual(self.center.auto_retry(), [])

    def review_evidence(self, task_id, payload):
        row = self.status(task_id)
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET patch_hash='h' WHERE id=?", (task_id,))
            con.execute("INSERT INTO evidence(task_id,kind,base_rev,patch_hash,provider,session_id,simulated,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (task_id, 'review', row['base_rev'], 'h', 'claude', 's', 0, payload, '2026-01-01T00:00:00Z'))

    def test_a_rejected_review_retries_only_when_no_other_error_is_recorded(self):
        task = self.task()
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET status='failed',error='auth',attempt=1 WHERE id=?", (task['id'],))
        self.review_evidence(task['id'], json.dumps({'verdict': 'rejected'}))
        self.assertEqual(self.center.auto_retry(), [], 'an auth failure must stay with a human even if an old rejection exists')
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET error=NULL WHERE id=?", (task['id'],))
        self.assertEqual(self.center.auto_retry(), [task['id']])

    def test_one_malformed_evidence_row_does_not_stop_the_rest_of_the_batch(self):
        self.fail_gates()
        broken, healthy = self.task(), self.task()
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET status='failed',attempt=1 WHERE id=?", (broken['id'],))
        self.review_evidence(broken['id'], '{ not json')
        self.center.run_phase(healthy['id'], 'implementation', 'mock', 'codex')
        self.assertEqual(self.status(healthy['id'])['status'], 'failed')
        self.assertEqual(self.center.auto_retry(), [healthy['id']])

    def test_the_shipped_config_enables_it(self):
        from center_runtime import load_config
        self.assertIs(load_config().get('auto_retry'), True)


if __name__ == '__main__':
    unittest.main()
