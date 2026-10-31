"""Claude audit regressions in disposable state; no providers or real approvals."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test_runtime_vnext as runtime_fixtures
import test_smart_router as fixtures
from center_context import read_policy


class AuditRegressionTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task
    claim_and_prepare = fixtures.CenterTests.claim_and_prepare
    implement_manually = fixtures.CenterTests.implement_manually
    change_config = runtime_fixtures.RuntimeVnextTests.change_config
    human_review_fixture = runtime_fixtures.RuntimeVnextTests.human_review_fixture

    def overlay_task(self, mode='mock'):
        return self.center.submit('project-a', 'Synthetic overlay recovery', 'Exercise preparation failures', ['src'],
                                  ['Overlay preparation is explicit'], mode=mode, dependency_policy='overlay')

    def source_file(self, task_id, name='center_mock.txt', content='Center mock implementation\n'):
        current = self.center.store.task(task_id)
        target = Path(current['worktree']) / 'src' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def test_assigned_rate_and_quota_failures_retry_without_start_ack(self):
        for provider, error in [('codex', 'rate_limit'), ('claude', 'quota_exhausted')]:
            with self.subTest(error=error):
                task = self.task(mode='live')
                assignment = self.center.claim(task['id'], 'implementation', 'handoff', provider)
                self.assertEqual(self.center.store.task(task['id'])['status'], 'assigned')
                result = self.center.failure(assignment['id'], error)
                self.assertEqual(result['state'], 'retry_wait')
                self.assertFalse(self.center.report(task['id'])['authorship'])
                self.assertFalse(self.center.report(task['id'])['sessions'])

    def test_empty_failed_overlay_checkpoint_is_recomposed_on_normal_retry(self):
        task = self.overlay_task()
        assignment = self.center.claim(task['id'], 'implementation', 'mock', 'codex')
        with patch('center_integration.compose_dependencies', side_effect=ValueError('SYNTHETIC compose failed before bytes')):
            with self.assertRaisesRegex(ValueError, 'before bytes'):
                self.center.prepare(task['id'])
        self.center.failure(assignment['id'], 'config')
        failed = self.center.store.task(task['id'])
        saved = Path(failed['checkpoint'])
        self.assertEqual(json.loads((saved / 'manifest.json').read_text())['manifest'], [])
        self.center.reconcile(task['id'], 'SYNTHETIC empty overlay retry', True, 'claude')
        second = self.center.claim(task['id'], 'implementation', 'mock', 'claude')
        from center_integration import compose_dependencies
        with patch('center_integration.compose_dependencies', wraps=compose_dependencies) as compose:
            prepared = self.center.prepare(task['id'])
        self.assertEqual(compose.call_count, 1)
        self.assertIn('_dependency_overlay', json.loads(prepared['config_json']))
        self.assertIsNone(prepared['checkpoint'])
        self.assertTrue(saved.is_dir(), 'Failed checkpoint must remain available')
        self.assertNotEqual(second['id'], assignment['id'])

    def test_partial_overlay_requires_explicit_rebuild_after_repeated_preparation_failure(self):
        task = self.overlay_task()
        first = self.center.claim(task['id'], 'implementation', 'mock', 'codex')

        def fail_after_bytes(center, current, worktree):
            self.source_file(current['id'], 'partial.txt', 'SYNTHETIC partial dependency bytes\n')
            raise ValueError('SYNTHETIC incomplete overlay after bytes')

        with patch('center_integration.compose_dependencies', side_effect=fail_after_bytes):
            with self.assertRaises(ValueError):
                self.center.prepare(task['id'])
        self.center.failure(first['id'], 'config')
        failed = self.center.store.task(task['id'])
        first_checkpoint = Path(failed['checkpoint'])
        first_worktree = Path(failed['worktree'])
        self.assertTrue(json.loads((first_checkpoint / 'manifest.json').read_text())['manifest'])
        self.center.reconcile(task['id'], 'SYNTHETIC retry without dropping partial bytes', True, 'claude')
        second = self.center.claim(task['id'], 'implementation', 'mock', 'claude')
        with self.assertRaisesRegex(ValueError, 'rebuild-overlay'):
            self.center.prepare(task['id'])
        self.center.failure(second['id'], 'config')
        current = self.center.store.task(task['id'])
        self.assertTrue(json.loads((Path(current['checkpoint']) / 'manifest.json').read_text())['manifest'],
                        'A second failed prepare must not replace the partial checkpoint guard with an empty checkout')
        self.center.reconcile(task['id'], 'SYNTHETIC explicit decision to rebuild partial overlay', True, 'codex', rebuild_overlay=True)
        self.center.claim(task['id'], 'implementation', 'mock', 'codex')
        prepared = self.center.prepare(task['id'])
        self.assertIn('_dependency_overlay', json.loads(prepared['config_json']))
        self.assertEqual((first_worktree / 'src/partial.txt').read_text(), 'SYNTHETIC partial dependency bytes\n')
        self.assertTrue((first_checkpoint / 'files/src/partial.txt').is_file())

    def test_auth_failure_before_worker_does_not_author_inherited_overlay(self):
        task = self.overlay_task(mode='live')
        assignment = self.center.claim(task['id'], 'implementation', 'handoff', 'claude')

        def fixture_overlay(center, current, worktree):
            target = self.source_file(current['id'])
            return {'overlay_hash': 'SYNTHETIC_OVERLAY', 'dependencies': [], 'inherited_providers': ['codex'],
                    'manifest': [{'path': 'src/center_mock.txt', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'size': target.stat().st_size, 'executable': 0}]}

        with patch('center_integration.compose_dependencies', side_effect=fixture_overlay):
            self.center.prepare(task['id'])
        self.center.failure(assignment['id'], 'auth')
        report = self.center.report(task['id'])
        self.assertEqual({row['provider'] for row in report['authorship']}, {'codex'})
        self.assertNotIn('worker_started', [row['event'] for row in report['events']])

    def test_max_attempt_blocked_reviewer_can_be_replaced_by_explicit_human_review(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET review_attempt=max_attempts-1 WHERE id=?', (task['id'],))
        review = self.center.claim(task['id'], 'review', 'handoff', 'claude')
        self.center.started(review['id'], 'SYNTHETIC_LAST_REVIEW')
        self.assertEqual(self.center.failure(review['id'], 'auth')['state'], 'blocked')
        blocked = self.center.store.task(task['id'])
        self.assertEqual(blocked['review_attempt'], blocked['max_attempts'])
        reviewed = self.human_review_fixture(blocked)
        self.assertEqual(reviewed['status'], 'ready_for_human_approval')
        self.assertFalse(reviewed['approved_at'], 'Synthetic human review is separate from final approval')

    def test_last_quota_review_restores_local_attempt_budget_and_waits(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET review_attempt=max_attempts-1 WHERE id=?', (task['id'],))
        review = self.center.claim(task['id'], 'review', 'handoff', 'claude')
        result = self.center.failure(review['id'], 'quota_exhausted')
        current = self.center.store.task(task['id'])
        self.assertEqual(result['state'], 'waiting_for_independent_review')
        self.assertEqual(current['review_attempt'], current['max_attempts'] - 1)
        self.assertEqual(self.center.provider_status()['claude']['availability'], 'unavailable')

    def test_background_spawn_failure_recovers_via_stop_ack_and_fresh_gates(self):
        self.change_config(async_handoff_gates=True)
        task = self.task(mode='live')
        assignment = self.claim_and_prepare(task, 'handoff', 'codex')
        self.source_file(task['id'])
        current = self.center.store.task(task['id'])
        real_popen = subprocess.Popen

        def selective_spawn(argv, *args, **kwargs):
            if isinstance(argv, list) and 'finish-gates' in argv:
                raise OSError('SYNTHETIC background supervisor spawn failure')
            return real_popen(argv, *args, **kwargs)

        with patch('subprocess.Popen', side_effect=selective_spawn):
            with self.assertRaisesRegex(OSError, 'SYNTHETIC'):
                self.center.complete(assignment['id'], {'task_id': task['id'], 'base_rev': current['base_rev'], 'simulated': False})
        self.assertEqual(self.center.store.task(task['id'])['status'], 'implementation_done')
        self.center.acknowledge_stop(assignment['id'], 'SYNTHETIC supervisor never started; IDE stopped')
        result = self.center.recheck_gates(task['id'], 'SYNTHETIC recover deterministic gates only')
        self.assertEqual(result['state'], 'waiting_for_independent_review')
        self.assertEqual(self.center.store.task(task['id'])['attempt'], 1)
        self.assertFalse(self.center.report(task['id'])['sessions'])

    def test_drift_adoption_requires_stopped_identity_and_new_gate_evidence(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        self.source_file(task['id'], 'drift.txt', 'SYNTHETIC drift from a second author\n')
        for provider, reason, stopped in [('claude', 'fixture', False), ('unknown', 'fixture', True), ('claude', '', True)]:
            with self.assertRaises(ValueError):
                self.center.adopt_drift(task['id'], provider, reason, stopped)
        review = self.center.claim(task['id'], 'review', 'handoff', 'claude')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE sessions SET lease_until=0 WHERE id=?', (review['id'],))
        self.center.recover()
        with self.assertRaisesRegex(ValueError, 'worker'):
            self.center.adopt_drift(task['id'], 'claude', 'SYNTHETIC active worker must not be replaced', True)
        self.center.acknowledge_stop(review['id'], 'SYNTHETIC expired reviewer stopped')
        attributed = self.center.adopt_drift(task['id'], 'claude', 'SYNTHETIC explicit author attribution', True)
        self.assertEqual(attributed['error'], 'attributed_drift_requires_gates')
        with self.assertRaisesRegex(ValueError, 'gates'):
            self.center.validate_evidence(task['id'], require_review=False)
        self.assertEqual(self.center.recheck_gates(task['id'], 'SYNTHETIC test attributed patch')['state'], 'waiting_for_independent_review')
        self.assertEqual({row['provider'] for row in self.center.report(task['id'])['authorship']}, {'codex', 'claude'})
        self.assertEqual(self.center.candidates(self.center.store.task(task['id']), 'review'), [])

    def test_stricter_registered_policy_blocks_approval_and_invalidates_old_review(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        self.human_review_fixture(task)
        cfg = json.loads(self.ca.read_text())
        self.change_config(quality_gates=[*cfg['quality_gates'], ['python', '-c', 'assert 2 + 2 == 4']])
        with self.assertRaisesRegex(ValueError, 'refresh-policy'):
            self.center.approve(task['id'])
        refreshed = self.center.refresh_policy(task['id'], 'SYNTHETIC accept additional quality gate')
        self.assertEqual(refreshed['error'], 'policy_changed_requires_gates')
        with self.assertRaises(ValueError):
            self.center.validate_evidence(task['id'])
        self.assertEqual(self.center.recheck_gates(task['id'], 'SYNTHETIC new gate policy')['state'], 'waiting_for_independent_review')
        with self.assertRaisesRegex(ValueError, 'review|approval'):
            self.center.validate_evidence(task['id'])

    def test_immutable_base_policy_ignores_worktree_added_instruction(self):
        task = self.task()
        self.claim_and_prepare(task)
        current = self.center.store.task(task['id'])
        original = json.loads(current['config_json'])['_policy_snapshot']
        injected = Path(current['worktree']) / 'AGENTS.md'
        injected.write_text('SYNTHETIC_WORKTREE_POLICY_INJECTION\n')
        base = read_policy(current['worktree'], ['src'], base_rev=current['base_rev'])
        self.assertEqual(base['sha256'], original['sha256'])
        self.assertNotIn('SYNTHETIC_WORKTREE_POLICY_INJECTION', json.dumps(base))
        self.assertIn('SYNTHETIC_WORKTREE_POLICY_INJECTION', json.dumps(read_policy(current['worktree'], ['src'])))



    def test_failed_gate_recheck_port_failure_releases_its_session(self):
        self.change_config(quality_gates=[["python", "-c", "raise SystemExit(1)"]])
        task = self.task()
        assignment = self.claim_and_prepare(task)
        self.source_file(task['id'])
        self.center.complete(assignment['id'], {'task_id': task['id'], 'base_rev': task['base_rev'], 'simulated': True})
        before = self.center.store.task(task['id'])
        self.assertEqual(before['status'], 'failed')
        with patch('center_resources.reserve_port', side_effect=ValueError('SYNTHETIC port unavailable')):
            with self.assertRaisesRegex(ValueError, 'port unavailable'):
                self.center.recheck_gates(task['id'], 'SYNTHETIC gate retry resource failure')
        self.assertEqual(self.center.store.task(task['id'])['status'], 'blocked')
        self.assertEqual(self.center.store.task(task['id'])['patch_hash'], before['patch_hash'])
        self.assertFalse(self.center.report(task['id'])['sessions'])

    def test_restore_failure_never_replaces_nonempty_checkpoint_with_pristine_worktree(self):
        task = self.task()
        assignment = self.claim_and_prepare(task)
        self.source_file(task['id'])
        self.center.failure(assignment['id'], 'worker_failure')
        first = self.center.store.task(task['id'])
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET not_before=0 WHERE id=?', (task['id'],))
        second = self.center.claim(task['id'], 'implementation', 'mock', 'claude')
        with patch('center_runtime.restore', side_effect=ValueError('SYNTHETIC transient restore failure')):
            with self.assertRaisesRegex(ValueError, 'restore failure'):
                self.center.prepare(task['id'])
        self.center.failure(second['id'], 'config')
        failed = self.center.store.task(task['id'])
        with self.assertRaisesRegex(ValueError, 'before the existing checkpoint'):
            self.center.adopt_drift(task['id'], 'human', 'SYNTHETIC must not adopt pristine failed restore', True)
        self.assertEqual(failed['checkpoint'], first['checkpoint'])
        self.assertEqual(failed['patch_hash'], first['patch_hash'])
        self.assertEqual({row['provider'] for row in self.center.report(task['id'])['authorship']}, {'codex'})
        self.center.reconcile(task['id'], 'SYNTHETIC retry preserved complete checkpoint', True, 'claude')
        third = self.center.claim(task['id'], 'implementation', 'mock', 'claude')
        prepared = self.center.prepare(task['id'])
        self.assertEqual((Path(prepared['worktree']) / 'src/center_mock.txt').read_text(), 'Center mock implementation\n')
        self.center.failure(third['id'], 'config')


    def test_implementation_start_refuses_unprepared_assignment(self):
        task = self.task(mode='live')
        assignment = self.center.claim(task['id'], 'implementation', 'handoff', 'codex')
        with self.assertRaisesRegex(ValueError, 'before worktree preparation'):
            self.center.started(assignment['id'], 'SYNTHETIC premature start')
        self.assertIsNone(self.center.session(assignment['id'])['started_at'])
        self.assertEqual(self.center.store.task(task['id'])['status'], 'assigned')
        self.center.failure(assignment['id'], 'config')

if __name__ == '__main__':
    unittest.main()
