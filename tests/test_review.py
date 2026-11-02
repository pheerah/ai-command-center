"""The owner's review view and decisions: what changed, reject with a reason, send back for changes, retry, apply, health facts."""
import json
import sys
import unittest
from pathlib import Path

import test_smart_router as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import center_api
import center_review
from center_store import TRANSITIONS


class ReviewFixture:
    """Shared setup: two registered projects, and helpers that drive a task to the states the owner meets."""
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task
    claim_and_prepare = fixtures.CenterTests.claim_and_prepare
    implement_manually = fixtures.CenterTests.implement_manually

    def ready_task(self):
        t = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        session = self.center.claim(t['id'], 'review', 'handoff', 'claude')
        self.center.started(session['id'], 'synthetic-review-fixture')
        self.center.complete(session['id'], {'task_id': t['id'], 'base_rev': t['base_rev'], 'patch_hash': t['patch_hash'],
                                             'verdict': 'approved', 'summary': 'Looks good to me', 'simulated': False})
        task = self.center.store.task(t['id'])
        self.assertEqual(task['status'], 'ready_for_human_approval')
        return task

    def stuck_task(self, status='failed', error='quality_gate_failed'):
        task = self.task(mode='live')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET status=?,error=? WHERE id=?', (status, error, task['id']))
        return self.center.store.task(task['id'])

    def events(self, task_id):
        return [r['event'] for r in self.center.report(task_id)['events']]

    def api(self, op, task_id, body=None, project='project-a'):
        return center_api.run(self.center, project, {'op': op, 'task_id': task_id, 'body': body})



class ReviewTests(ReviewFixture, unittest.TestCase):
    # ---- the review view
    def test_review_view_shows_changes_gates_review_and_the_actions_open_to_the_owner(self):
        task = self.ready_task()
        view = self.center.review_view(task['id'])
        self.assertTrue(view['changes']['available'], view['changes'])
        self.assertIn('src/center_mock.txt', [f['path'] for f in view['changes']['files']])
        self.assertEqual(view['changes']['patch_hash_short'], task['patch_hash'][:12])
        self.assertTrue(view['gates'] and all(g['passed'] for g in view['gates']))
        self.assertEqual((view['review']['verdict'], view['review']['summary']), ('approved', 'Looks good to me'))
        self.assertEqual(view['actions'], {'approve': True, 'reject': True, 'rework': True, 'apply': False})
        self.assertFalse(view['applied'])
        self.assertIsNone(view['suggested_commit_message'])

    def test_review_view_never_shows_a_diff_that_approval_would_not_cover(self):
        task = self.ready_task()
        saved = Path(task['checkpoint'])
        (saved / 'tracked.patch').write_bytes(b'diff --git a/x b/x\n+tampered\n')
        view = self.center.review_view(task['id'])
        self.assertEqual(view['changes'], {'available': False, 'reason': 'checkpoint_mismatch'})

    def test_changes_are_not_available_before_the_task_is_ready(self):
        task = self.task(mode='live')
        self.assertEqual(self.center.review_view(task['id'])['changes'], {'available': False, 'reason': 'not_ready'})

    def test_count_changes_counts_added_and_removed_lines_per_file(self):
        diff = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n keep\n-old\n+new\n+newer\ndiff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n'
        self.assertEqual(center_review.count_changes(diff), [{'path': 'a.py', 'added': 2, 'removed': 1}, {'path': 'b.py', 'added': 1, 'removed': 1}])

    # ---- reject
    def test_reject_needs_a_reason_and_ends_the_task_without_applying_anything(self):
        task = self.ready_task()
        for reason in (None, '', '   ', 'x' * 1001):
            with self.assertRaises(ValueError, msg=str(reason)[:5]):
                self.center.reject(task['id'], reason)
        self.assertEqual(self.center.store.task(task['id'])['status'], 'ready_for_human_approval')
        rejected = self.center.reject(task['id'], 'ไม่ตรงกับที่ขอ')
        self.assertEqual((rejected['status'], rejected['error']), ('rejected', 'rejected_by_owner'))
        self.assertIn('rejected', self.events(task['id']))
        self.assertFalse((self.a / 'src' / 'center_mock.txt').exists())
        self.assertEqual(TRANSITIONS['rejected'], set())
        view = self.center.review_view(task['id'])
        self.assertEqual(view['rejected_reason'], 'ไม่ตรงกับที่ขอ')
        self.assertFalse(any(view['actions'].values()))

    def test_only_a_task_waiting_for_approval_can_be_rejected(self):
        for task in (self.task(mode='live'), self.stuck_task()):
            with self.assertRaises(ValueError):
                self.center.reject(task['id'], 'no')

    # ---- rework in the same task
    def test_rework_sends_the_task_back_with_the_owners_instructions(self):
        task = self.ready_task()
        with self.assertRaises(ValueError):
            self.center.rework(task['id'], '  ')
        again = self.center.rework(task['id'], 'ใช้ชื่อไฟล์ที่ลงท้ายด้วย _v2')
        self.assertEqual(again['status'], 'queued')
        self.assertEqual(again['attempt'], task['attempt'])
        self.assertIn('human_rework_requested', self.events(task['id']))
        prior = self.center._prior_attempt(self.center.store.task(task['id']))
        self.assertEqual(prior['human_instructions'], 'ใช้ชื่อไฟล์ที่ลงท้ายด้วย _v2')
        self.assertEqual(self.center.review_view(task['id'])['rework_requests'], ['ใช้ชื่อไฟล์ที่ลงท้ายด้วย _v2'])

    def test_rework_never_relaxes_the_attempt_limit(self):
        task = self.ready_task()
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET max_attempts=attempt WHERE id=?', (task['id'],))
        with self.assertRaisesRegex(ValueError, 'Attempt limit reached'):
            self.center.rework(task['id'], 'try again')
        self.assertEqual(self.center.store.task(task['id'])['status'], 'ready_for_human_approval')
        self.assertFalse(self.center.review_view(task['id'])['actions']['rework'])

    def test_rework_is_refused_while_a_worker_owns_the_task(self):
        task = self.ready_task()
        with self.center.store.connection(write=True) as con:
            con.execute("INSERT INTO sessions(id,task_id,provider,role,adapter,owner_pid,lease_until,created_at) VALUES('s1',?,?,?,?,?,?,?)",
                        (task['id'], 'claude', 'review', 'handoff', 1, 9e12, '2026-01-01T00:00:00+00:00'))
        with self.assertRaises(ValueError):
            self.center.rework(task['id'], 'later')

    # ---- retry and switching provider
    def test_retry_from_web_requeues_a_failed_task_and_a_provider_switch_must_be_allowed(self):
        task = self.stuck_task()
        with self.assertRaises(ValueError):
            self.center.retry_from_web(task['id'], 'google')  # not in allowed_providers
        retried = self.center.retry_from_web(task['id'], 'claude')
        self.assertEqual((retried['status'], retried['requested_provider']), ('queued', 'claude'))
        second = self.stuck_task()
        self.assertEqual(self.center.retry_from_web(second['id'])['status'], 'queued')

    def test_retry_never_discards_a_cancellation_or_a_spent_budget(self):
        spent = self.stuck_task()
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET max_attempts=attempt WHERE id=?', (spent['id'],))
        with self.assertRaisesRegex(ValueError, 'Attempt limit reached'):
            self.center.retry_from_web(spent['id'])
        cancelled = self.stuck_task()
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET cancel_requested=1 WHERE id=?', (cancelled['id'],))
        with self.assertRaises(ValueError):
            self.center.retry_from_web(cancelled['id'])

    # ---- why is it stuck
    def test_diagnose_explains_each_failure_in_thai_and_offers_only_actions_that_can_work(self):
        task = self.stuck_task('failed', 'quality_gate_failed')
        diagnosis = self.center.diagnose(task['id'])
        self.assertEqual(diagnosis['reason_code'], 'quality_gate_failed')
        self.assertRegex(diagnosis['explanation'], '[฀-๿]')
        retry = next(a for a in diagnosis['actions'] if a['action'] == 'retry')
        self.assertTrue(retry['enabled'])
        switch = next(a for a in diagnosis['actions'] if a['action'] == 'switch_provider')
        self.assertTrue(switch['enabled'])
        self.assertTrue(set(switch['providers']) <= {'codex', 'claude'})

    def test_diagnose_disables_actions_when_the_budget_is_spent_and_names_the_limit(self):
        task = self.stuck_task('blocked', 'provider_blocked')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET max_attempts=attempt WHERE id=?', (task['id'],))
        diagnosis = self.center.diagnose(task['id'])
        self.assertEqual(diagnosis['reason_code'], 'attempt_limit')
        self.assertEqual(diagnosis['actions'], [])

    def test_diagnose_has_a_known_answer_for_unknown_errors_and_nothing_for_healthy_tasks(self):
        self.assertEqual(self.center.diagnose(self.stuck_task('failed', 'something_new')['id'])['reason_code'], 'unknown')
        healthy = self.center.diagnose(self.task(mode='live')['id'])
        self.assertEqual((healthy['reason_code'], healthy['actions']), (None, []))

    def test_every_advice_entry_is_thai_and_only_offers_known_actions(self):
        for code, (explanation, actions) in center_review.FAILURE_ADVICE.items():
            self.assertRegex(explanation, '[฀-๿]', code)
            self.assertTrue(set(actions) <= {'retry', 'switch_provider'}, code)

    # ---- apply (never commit)
    def test_apply_applies_an_approved_patch_once_and_never_commits(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)  # approval only: the web route also applies, this simulates a failed apply
        view = self.center.review_view(task['id'])
        self.assertEqual(view['actions']['apply'], True)
        self.assertTrue(view['suggested_commit_message'])
        self.assertLessEqual(len(view['suggested_commit_message']), 72)
        head_before = fixtures.git(self.a, 'rev-parse', 'HEAD')
        applied = self.center.apply_approved(task['id'])
        self.assertEqual(applied['status'], 'applied')
        self.assertTrue((self.a / 'src' / 'center_mock.txt').is_file())
        with self.assertRaisesRegex(ValueError, 'already been applied'):
            self.center.apply_approved(task['id'])
        self.assertTrue(self.center.review_view(task['id'])['applied'])
        self.assertEqual(fixtures.git(self.a, 'rev-parse', 'HEAD'), head_before)  # applied to the working tree, nothing committed

    def test_apply_refuses_to_overwrite_a_different_file_and_changes_nothing(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)
        mine = self.a / 'src' / 'center_mock.txt'
        mine.write_text('my own unsaved work\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite src/center_mock.txt'):
            self.center.apply_approved(task['id'])
        self.assertEqual(mine.read_text(encoding='utf-8'), 'my own unsaved work\n')
        view = self.center.review_view(task['id'])
        self.assertEqual((view['task']['status'], view['applied'], view['actions']['apply']), ('approved', False, True))
        self.assertNotIn('auto_applied_to_workspace', self.events(task['id']))
        mine.unlink()
        self.assertEqual(self.center.apply_approved(task['id'])['status'], 'applied')

    def test_apply_accepts_a_file_that_is_already_identical(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)
        (self.a / 'src' / 'center_mock.txt').write_text('Center mock implementation\n', encoding='utf-8')
        self.assertEqual(self.center.apply_approved(task['id'])['status'], 'applied')

    def test_apply_refuses_when_a_folder_is_in_the_way(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)
        (self.a / 'src' / 'center_mock.txt').mkdir()
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            self.center.apply_approved(task['id'])
        self.assertTrue((self.a / 'src' / 'center_mock.txt').is_dir())

    def test_the_web_approval_path_reports_a_refusal_and_leaves_an_approved_task_to_apply_later(self):
        task = self.ready_task()
        (self.a / 'src' / 'center_mock.txt').write_text('mine\n', encoding='utf-8')
        self.center.approve(task['id'], interactive=False)
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            self.center.auto_apply(task['id'])
        self.assertEqual(self.center.store.task(task['id'])['status'], 'approved')
        self.assertEqual((self.a / 'src' / 'center_mock.txt').read_text(encoding='utf-8'), 'mine\n')

    def test_only_an_approved_task_can_be_applied(self):
        with self.assertRaises(ValueError):
            self.center.apply_approved(self.ready_task()['id'])

    # ---- the API layer
    def test_api_review_returns_a_public_scrubbed_view_with_a_diagnosis(self):
        task = self.ready_task()
        answer = self.api('review', task['id'])
        self.assertTrue(answer['ok'], answer)
        data = answer['data']
        self.assertNotIn('patch_hash', data['task'])
        self.assertIsNone(data['diagnosis']['reason_code'])
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertNotIn('worktree', data['task'])

    def test_api_decisions_work_and_other_projects_cannot_touch_the_task(self):
        task = self.ready_task()
        for op, body in (('reject', {'reason': 'no'}), ('rework', {'instructions': 'x'}), ('review', {}), ('apply', {}), ('retry', {}), ('diagnose', {})):
            self.assertFalse(self.api(op, task['id'], body, project='project-b')['ok'], op)
        self.assertFalse(self.api('reject', task['id'], {})['ok'])  # no reason
        self.assertFalse(self.api('switch_provider', task['id'], {'provider': 'nope'})['ok'])
        answer = self.api('reject', task['id'], {'reason': 'not what I asked'})
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['data']['task']['status'], 'rejected')

    def test_api_error_for_a_missing_task_is_the_same_as_for_another_projects_task(self):
        task = self.ready_task()
        missing = self.api('review', 'abcdef123456')
        foreign = self.api('review', task['id'], project='project-b')
        self.assertEqual((missing['ok'], missing['error']), (foreign['ok'], foreign['error']))

    def test_review_ops_are_not_reachable_through_project_token_routes(self):
        server = (Path(__file__).resolve().parents[1] / 'server.js').read_text(encoding='utf-8')
        routes = server[server.index('const V1_ROUTES'):server.index('function readBody')]
        for op in center_api.REVIEW_OPS:
            self.assertNotIn(f"op: '{op}'", routes)

    # ---- E: facts about the system
    def test_health_summary_has_scheduler_providers_and_counts_but_no_paths(self):
        self.stuck_task()
        summary = self.center.health_summary()
        self.assertIn('running', summary['scheduler'])
        self.assertTrue({'codex', 'claude'} <= set(summary['providers']))
        self.assertGreaterEqual(summary['tasks_by_status'].get('failed', 0), 1)
        self.assertEqual(summary['stuck_tasks'][0]['error'], 'quality_gate_failed')
        text = json.dumps(summary)
        self.assertNotIn(str(self.root), text)

    def test_the_secretary_prompt_carries_the_health_block_and_still_cannot_change_anything(self):
        import center_chat
        self.center.config['chat'] = {'providers': ['claude'], 'adapter': 'live'}
        context = center_chat.build_context(self.center, 'project-a', 'ทำไมงานค้าง', [])
        self.assertIn('system health', context['prompt'])
        self.assertIn('scheduler', context['prompt'])
        self.assertIn('cannot create, change, cancel, approve or apply', center_chat.SYSTEM_RULES)


if __name__ == '__main__':
    unittest.main()
