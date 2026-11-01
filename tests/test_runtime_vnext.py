"""Real isolated runtime regressions; all provider and human actions are fixtures.

No provider CLI, credentials, main state, or real human approvals are used.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_smart_router as fixtures
from center_context import read_policy, read_sources
from center_store import event
from center_workspace import git


class RuntimeVnextTests(unittest.TestCase):
    # Reuse fixture setup without subclassing/discovering the existing suite.
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task
    claim_and_prepare = fixtures.CenterTests.claim_and_prepare
    implement_manually = fixtures.CenterTests.implement_manually

    def change_config(self, **updates):
        cfg = json.loads(self.ca.read_text())
        cfg.update(updates)
        self.ca.write_text(json.dumps(cfg))
        self.center.register('project-a', self.a, self.ca, confirm_config_change=True)
        return cfg

    def human_review_fixture(self, task):
        current = self.center.store.task(task['id'])
        phrase = f"REVIEW {current['id']} {current['patch_hash'][:12]}"
        with patch('center_runtime.sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=phrase):
            return self.center.human_review(current['id'], 'SYNTHETIC UNIT TEST review only; not a real person or main-state approval')

    def test_quota_exhaustion_opens_circuit_and_preserves_retry_budget(self):
        task = self.task(mode='live')
        initial_budget = task['max_attempts'] - task['attempt']
        assignment = self.claim_and_prepare(task, 'handoff', 'claude')
        with patch.object(self.center, '_check_live_login', side_effect=AssertionError('No provider invocation permitted')):
            result = self.center.failure(assignment['id'], 'quota_exhausted')
        current = self.center.store.task(task['id'])
        self.assertEqual(result['state'], 'retry_wait')
        self.assertEqual(current['max_attempts'] - current['attempt'], initial_budget)
        self.assertEqual(current['attempt'], 1, 'Historical attempt/worktree identity must not be reused')
        health = self.center.provider_status()['claude']
        self.assertEqual((health['availability'], health['reason'], health['reset_at']), ('unavailable', 'usage_exhausted', 'unknown'))
        self.assertNotIn('claude', self.center.candidates(current, 'implementation'))
        self.assertIn('provider_circuit_opened', [row['event'] for row in self.center.report(task['id'])['events']])

    def test_quota_health_follows_observed_usage_both_ways(self):
        def reading(used, stale=False):
            window = {'used_percent': used, 'remaining_percent': 100 - used, 'window_minutes': 300, 'resets_at': None}
            return {'five_hour': window, 'weekly': {**window, 'window_minutes': 10080}, 'stale': stale}
        self.center.set_provider('claude', 'unavailable', 'usage_exhausted')
        self.assertEqual(self.center.reconcile_quota_health({'claude': reading(20, stale=True)}), {}, 'stale readings change nothing')
        self.assertEqual(self.center.reconcile_quota_health({'claude': reading(20)}), {'claude': 'available'})
        self.assertEqual(self.center.provider_status()['claude']['availability'], 'available')
        self.assertEqual(self.center.reconcile_quota_health({'claude': reading(98)}), {'claude': 'unavailable'})
        self.assertEqual(self.center.provider_status()['claude']['reason'], 'quota_low')
        self.assertEqual(self.center.reconcile_quota_health({'claude': reading(10)}), {'claude': 'available'})
        self.center.set_provider('claude', 'unavailable', 'auth')
        self.assertEqual(self.center.reconcile_quota_health({'claude': reading(10)}), {}, 'a non-quota block is never lifted')

    def test_readiness_skips_dependency_and_requested_google_and_busy_provider(self):
        dependency = self.task()
        child = self.center.submit('project-a', 'Dependent', 'Wait for first task', ['src'], ['Dependency ready'], mode='mock', dependencies=[dependency['id']])
        self.assertEqual(self.center.scheduling_readiness(child['id'], 'implementation', 'mock')['reason'], 'dependency_not_approved')
        cfg = json.loads(self.ca.read_text())
        self.change_config(allowed_providers=[*cfg['allowed_providers'], 'google'])
        google = self.task(mode='live', provider='google')
        self.center.config['live_execution'] = True
        self.center.set_provider('google', 'unavailable', 'usage_exhausted')  # shipped config enables Google; model exhausted quota
        blocked = self.center.scheduling_readiness(google['id'], 'implementation', 'live')
        self.assertFalse(blocked['ready'])
        self.assertEqual(blocked['reason'], 'provider_unavailable_or_handoff_required')
        self.center.config['providers']['codex']['capacity'] = 1
        occupied = self.task(provider='codex')
        self.assertIsNotNone(self.center.claim(occupied['id'], 'implementation', 'mock', 'codex'))
        later = self.task(provider='codex')
        self.assertEqual(self.center.scheduling_readiness(later['id'], 'implementation', 'mock')['reason'], 'provider_capacity')

    def test_policy_changes_require_confirmation_and_keep_hash_history(self):
        original = self.center.project('project-a')
        before = self.center._policy_hash(original)
        cfg = json.loads(self.ca.read_text())
        cfg['quality_gates'] = [['python', '-c', 'assert 1 + 1 == 2']]
        self.ca.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'confirm-config-change'):
            self.center.register('project-a', self.a, self.ca)
        self.assertEqual(self.center._policy_hash(self.center.project('project-a')), before)
        self.center.register('project-a', self.a, self.ca, confirm_config_change=True)
        after = self.center._policy_hash(self.center.project('project-a'))
        self.assertNotEqual(before, after)
        with self.center.store.connection() as con:
            history = [json.loads(row[0]) for row in con.execute("SELECT value FROM center_meta WHERE key LIKE 'project_policy_history:project-a:%' ORDER BY key")]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]['previous_hash'], before)
        self.assertTrue(history[-1]['confirmed'])

    def test_blocked_review_resumes_without_reimplementing_or_losing_patch(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        review = self.center.claim(task['id'], 'review', 'handoff', 'claude')
        self.center.started(review['id'], 'SYNTHETIC_REVIEW_SESSION')
        self.assertEqual(self.center.failure(review['id'], 'auth')['state'], 'blocked')
        resumed = self.center.resume_review(task['id'], 'SYNTHETIC fixture auth restored')
        self.assertEqual(resumed['status'], 'waiting_for_independent_review')
        self.assertEqual((resumed['attempt'], resumed['worktree'], resumed['patch_hash']), (task['attempt'], task['worktree'], task['patch_hash']))
        self.assertEqual(resumed['review_attempt'], 1)
        self.assertEqual(len([row for row in self.center.report(task['id'])['events'] if row['event'] == 'assigned']), 1)

    def test_human_review_is_explicit_evidence_before_separate_approval(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        with patch('center_runtime.sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive'):
                self.center.human_review(task['id'], 'This piped request must not pass')
        reviewed = self.human_review_fixture(task)
        self.assertEqual(reviewed['status'], 'ready_for_human_approval')
        self.assertFalse(reviewed['approved_at'])
        evidence = [row for row in self.center.report(task['id'])['evidence'] if row['kind'] == 'human_review']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['provider'], 'human')
        self.assertIn('SYNTHETIC UNIT TEST', json.loads(evidence[0]['payload'])['summary'])

    def test_final_approval_still_refuses_pipe_after_human_review(self):
        task = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        self.human_review_fixture(task)
        with patch('center_runtime.sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive'):
                self.center.approve(task['id'])
        self.assertEqual(self.center.store.task(task['id'])['status'], 'ready_for_human_approval')

    def test_gate_receives_reserved_port_and_records_policy_bound_evidence(self):
        task = self.task()
        observed = []

        def fake_gate(argv, cwd, log, timeout, tick, started, env_extra=None):
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('SYNTHETIC successful gate')
            self.assertTrue(tick())
            sid = env_extra['AI_CENTER_SESSION_ID']
            with self.center.store.connection() as con:
                stored = json.loads(con.execute('SELECT value FROM center_meta WHERE key=?', ('session_port:' + sid,)).fetchone()[0])
            self.assertEqual(int(env_extra['AI_CENTER_TEST_PORT']), stored['port'])
            observed.append(stored['port'])
            return {'code': 0, 'error': None, 'pid': None}

        with patch('center_runtime.execute', side_effect=fake_gate):
            completed = self.implement_manually(task)
        evidence = [row for row in self.center.report(task['id'])['evidence'] if row['kind'] == 'gates']
        payload = json.loads(evidence[0]['payload'])
        self.assertEqual(payload['test_port'], observed[0])
        self.assertEqual(payload['policy_hash'], json.loads(completed['config_json'])['policy_hash'])
        self.assertTrue(payload['passed'])

    def test_prior_attempt_contains_bounded_gate_failure_and_review_feedback(self):
        self.change_config(quality_gates=[['python', '-c', "print('SYNTHETIC_GATE_FAILURE'); print('api_key=not_a_real_key'); raise SystemExit(9)"]])
        task = self.implement_manually(self.task())
        self.assertEqual(task['status'], 'failed')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET review_result=? WHERE id=?', (json.dumps({'summary': 'SYNTHETIC review: boundary case missing'}), task['id']))
        prior = self.center._prior_attempt(self.center.store.task(task['id']))
        self.assertTrue(prior['restored_checkpoint'])
        self.assertIn('SYNTHETIC_GATE_FAILURE', prior['gate_failure_excerpt'])
        self.assertNotIn('not_a_real_key', prior['gate_failure_excerpt'])
        self.assertIn('[redacted]', prior['gate_failure_excerpt'])
        self.assertIn('boundary case missing', prior['review_feedback'])
        self.assertLessEqual(len(prior['gate_failure_excerpt'].encode()), 3200)

    def test_explicit_read_set_avoids_unrelated_large_file_without_expanding_scope(self):
        task = self.center.submit('project-a', 'Targeted context', 'Read small source', ['src'], ['Targeted read'], mode='mock', read_set=['src/small.py'])
        self.claim_and_prepare(task)
        current = self.center.store.task(task['id'])
        source = Path(current['worktree']) / 'src'
        source.mkdir()
        (source / 'small.py').write_text('answer = 42\n')
        (source / 'large.txt').write_text('x' * 100000)
        read_set = json.loads(current['config_json'])['read_set']
        snapshot = read_sources(current['worktree'], ['src'], names=read_set)
        self.assertEqual([row['path'] for row in snapshot], ['src/small.py'])
        with self.assertRaisesRegex(ValueError, 'context limit'):
            read_sources(current['worktree'], ['src'])
        with self.assertRaises(ValueError):
            self.center.submit('project-a', 'Invalid context', 'Must not read outside scope', ['src'], ['x'], mode='mock', read_set=['server.js'])

    def test_post_gate_drift_is_preserved_but_not_adopted_as_new_authorship(self):
        task = self.implement_manually(self.task())
        target = Path(task['worktree']) / 'src/center_mock.txt'
        target.write_text(target.read_text() + 'SYNTHETIC unattributed edit\n')
        with self.assertRaisesRegex(ValueError, 'Unattributed'):
            self.center.save_checkpoint(task['id'])
        current = self.center.store.task(task['id'])
        self.assertEqual((current['patch_hash'], current['checkpoint']), (task['patch_hash'], task['checkpoint']))
        drift = [row for row in self.center.report(task['id'])['events'] if row['event'] == 'unattributed_drift_detected']
        self.assertEqual(len(drift), 1)
        self.assertTrue(Path(json.loads(drift[0]['detail'])['preserved_checkpoint']).is_dir())
        with self.assertRaisesRegex(ValueError, 'Patch changed'):
            self.center.validate_evidence(task['id'], require_review=False)

    def test_real_runtime_overlay_carries_approved_code_and_authorship(self):
        source = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        self.human_review_fixture(source)
        # Synthetic approval only in this test's temporary DB; never main state.
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET status='approved',approved_by='SYNTHETIC_UNIT_TEST' WHERE id=?", (source['id'],))
            event(con, source['id'], 'synthetic_approval_fixture', {'not_a_real_human_approval': True})
        base = git(self.a, 'rev-parse', 'HEAD')
        consumer = self.center.submit('project-a', 'Consume approved code', 'Use predecessor file', ['src'], ['Predecessor available'],
                                      mode='live', dependencies=[source['id']], dependency_policy='overlay')
        assignment = self.claim_and_prepare(consumer, 'handoff', 'claude')
        current = self.center.store.task(consumer['id'])
        self.assertEqual((Path(current['worktree']) / 'src/center_mock.txt').read_text(), 'Center mock implementation\n')
        overlay = json.loads(current['config_json'])['_dependency_overlay']
        self.assertEqual(overlay['inherited_providers'], ['codex'])
        self.assertEqual(overlay['dependencies'][0]['task_id'], source['id'])
        (Path(current['worktree']) / 'src/consumer.txt').write_text('SYNTHETIC consumer output\n')
        self.center.complete(assignment['id'], {'task_id': current['id'], 'base_rev': current['base_rev'], 'simulated': False})
        completed = self.center.store.task(consumer['id'])
        self.assertEqual(completed['status'], 'waiting_for_independent_review')
        authors = {row['provider'] for row in self.center.report(consumer['id'])['authorship']}
        self.assertEqual(authors, {'codex', 'claude'})
        self.assertEqual(self.center.candidates(completed, 'review'), [])
        self.assertEqual(git(self.a, 'rev-parse', 'HEAD'), base, 'Dependency overlays never commit or merge')
        (Path(source['worktree']) / 'src/center_mock.txt').write_text('SYNTHETIC invalidated predecessor\n')
        with self.assertRaises(ValueError):
            self.center.validate_evidence(consumer['id'], require_review=False)

    def test_background_handoff_returns_before_gates_and_has_one_gate_owner(self):
        self.change_config(async_handoff_gates=True)
        task = self.task(mode='live')
        assignment = self.claim_and_prepare(task, 'handoff', 'codex')
        current = self.center.store.task(task['id'])
        source = Path(current['worktree']) / 'src'
        source.mkdir()
        (source / 'center_mock.txt').write_text('Center mock implementation\n')
        launches = []
        real_popen = subprocess.Popen

        def selective_launch(argv, *args, **kwargs):
            if isinstance(argv, list) and 'finish-gates' in argv:
                launches.append((argv, kwargs))
                return SimpleNamespace(pid=99999999)
            return real_popen(argv, *args, **kwargs)

        # Only capture the background supervisor; Git subprocesses remain real.
        with patch('subprocess.Popen', side_effect=selective_launch):
            result = self.center.complete(assignment['id'], {'task_id': task['id'], 'base_rev': current['base_rev'], 'simulated': False})
        self.assertEqual(result['state'], 'implementation_done')
        self.assertEqual(result['gates'], 'dispatched_background')
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0][0][-2:], ['finish-gates', assignment['id']])
        self.assertEqual(self.center.store.task(task['id'])['status'], 'implementation_done')
        self.assertFalse(self.center.report(task['id'])['evidence'])
        finished = self.center.finish_gates(assignment['id'])
        self.assertEqual(finished['state'], 'waiting_for_independent_review')
        self.assertFalse(self.center.report(task['id'])['sessions'])
        self.assertEqual(len([row for row in self.center.report(task['id'])['evidence'] if row['kind'] == 'gates']), 1)
        with self.assertRaisesRegex(ValueError, 'No pending'):
            self.center.finish_gates(assignment['id'])
        if os.name == 'nt':
            self.assertEqual(launches[0][1]['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_parallel_real_gate_processes_bind_distinct_reserved_ports(self):
        markers = self.root / 'parallel-gate-markers'
        markers.mkdir()
        script = ("import json,os,socket,time; from pathlib import Path; "
                  f"root=Path({str(markers)!r}); "
                  "port=int(os.environ['AI_CENTER_TEST_PORT']); "
                  "s=socket.socket(); s.bind(('127.0.0.1',port)); s.listen(); "
                  "(root/(os.environ['AI_CENTER_TASK_ID']+'.json')).write_text(json.dumps({'port':port})); "
                  "deadline=time.monotonic()+12; "
                  "exec(\"while len(list(root.glob('*.json'))) < 2 and time.monotonic() < deadline:\\n time.sleep(0.02)\"); "
                  "assert len(list(root.glob('*.json')))==2, 'parallel gate did not overlap'; "
                  "time.sleep(0.1); s.close(); print('bound',port)")
        self.change_config(quality_gates=[['python', '-c', script]])
        tasks = [self.task(), self.task()]
        assignments = [self.claim_and_prepare(task, 'mock', provider) for task, provider in zip(tasks, ['codex', 'claude'])]
        ports = [self.center.session(assignment['id'])['test_port'] for assignment in assignments]
        self.assertEqual(len(set(ports)), 2)
        responses = []
        for task in tasks:
            current = self.center.store.task(task['id'])
            source = Path(current['worktree']) / 'src'
            source.mkdir()
            (source / 'center_mock.txt').write_text('Center mock implementation\n')
            responses.append({'task_id': task['id'], 'base_rev': current['base_rev'], 'simulated': True})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.center.complete, assignment['id'], response) for assignment, response in zip(assignments, responses)]
            results = [future.result(timeout=40) for future in futures]
        logs = [self.center.store.state / 'runs' / task['id'] / assignment['id'] / 'gate-0.log' for task, assignment in zip(tasks, assignments)]
        self.assertTrue(all(result['state'] == 'waiting_for_independent_review' for result in results), [log.read_text() if log.exists() else 'missing gate log' for log in logs])
        observed = [json.loads(marker.read_text())['port'] for marker in markers.glob('*.json')]
        self.assertEqual(sorted(observed), sorted(ports))
        for task, port in zip(tasks, ports):
            gates = [row for row in self.center.report(task['id'])['evidence'] if row['kind'] == 'gates']
            self.assertEqual(json.loads(gates[0]['payload'])['test_port'], port)


class PolicySnapshotTests(unittest.TestCase):
    def test_root_nested_and_rules_policy_hashes_are_scoped_and_change_with_content(self):
        with tempfile.TemporaryDirectory(prefix='center_policy_test_') as directory:
            root = Path(directory)
            (root / 'src/nested').mkdir(parents=True)
            (root / 'src/other').mkdir()
            (root / '.agents/rules').mkdir(parents=True)
            (root / 'AGENTS.md').write_text('Root policy fixture\n')
            nested = root / 'src/nested/CLAUDE.md'
            nested.write_text('Nested policy fixture\n')
            (root / 'src/other/GEMINI.md').write_text('Unrelated policy must not be loaded\n')
            (root / '.agents/rules/center.md').write_text('Project rule fixture\n')
            first = read_policy(root, ['src/nested/a.py'])
            self.assertEqual({row['path'] for row in first['files']}, {'AGENTS.md', 'src/nested/CLAUDE.md', '.agents/rules/center.md'})
            nested.write_text('Changed nested policy fixture\n')
            second = read_policy(root, ['src/nested/a.py'])
            self.assertNotEqual(first['sha256'], second['sha256'])
            first_root = next(row for row in first['files'] if row['path'] == 'AGENTS.md')
            second_root = next(row for row in second['files'] if row['path'] == 'AGENTS.md')
            self.assertEqual(first_root['sha256'], second_root['sha256'])


if __name__ == '__main__':
    unittest.main()
