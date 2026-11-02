"""Situations the owner actually meets, played end to end on the real state machine: a provider goes down, quota runs low,
an apply fails after approval, a task is cancelled or decided twice. No model is called."""
import json
import unittest
from unittest.mock import patch

from test_review import ReviewFixture


class OwnerScenarioTests(ReviewFixture, unittest.TestCase):
    def mark_unavailable(self, provider, reason):
        self.center.set_provider(provider, 'unavailable', reason)

    # ---- provider down / quota low
    def test_when_the_provider_that_failed_is_down_the_owner_is_offered_the_other_one(self):
        task = self.stuck_task('blocked', 'provider_blocked')
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET provider='codex' WHERE id=?", (task['id'],))
        diagnosis = self.center.diagnose(task['id'])
        switch = next(a for a in diagnosis['actions'] if a['action'] == 'switch_provider')
        self.assertEqual(switch['providers'], ['claude'])
        self.assertEqual(self.center.retry_from_web(task['id'], 'claude')['requested_provider'], 'claude')

    def test_when_every_other_provider_is_down_switching_is_off_but_retrying_stays_possible(self):
        task = self.stuck_task('failed', 'usage_exhausted')
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET provider='codex' WHERE id=?", (task['id'],))
        self.mark_unavailable('claude', 'quota_low')
        diagnosis = self.center.diagnose(task['id'])
        self.assertEqual(diagnosis['reason_code'], 'usage_exhausted')
        switch = next(a for a in diagnosis['actions'] if a['action'] == 'switch_provider')
        retry = next(a for a in diagnosis['actions'] if a['action'] == 'retry')
        self.assertFalse(switch['enabled'])
        self.assertTrue(retry['enabled'])

    def test_low_quota_shows_up_in_the_health_facts_the_secretary_quotes(self):
        self.mark_unavailable('codex', 'quota_low')
        self.center.quota_reader = lambda: {'codex': {'five_hour': {'remaining_percent': 3.0}, 'weekly': {'remaining_percent': 40.0}}}
        health = self.center.health_summary()['providers']['codex']
        self.assertEqual(health['availability'], 'unavailable')
        self.assertEqual(health['reason'], 'quota_low')
        self.assertEqual(health['quota_left_percent'], 3.0)

    def test_a_scheduler_that_is_not_running_is_reported_as_such(self):
        self.assertFalse(self.center.health_summary()['scheduler']['running'])

    # ---- approve, then the apply fails
    def test_an_apply_that_fails_after_approval_leaves_an_approved_task_the_owner_can_apply_later(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)
        with patch.object(type(self.center), 'auto_apply', side_effect=ValueError('Patch does not apply cleanly')):
            with self.assertRaises(ValueError):
                self.center.apply_approved(task['id'])
        view = self.center.review_view(task['id'])
        self.assertEqual(view['task']['status'], 'approved')
        self.assertFalse(view['applied'])
        self.assertTrue(view['actions']['apply'])
        self.assertFalse((self.a / 'src' / 'center_mock.txt').exists())
        self.assertEqual(self.center.apply_approved(task['id'])['status'], 'applied')
        self.assertTrue((self.a / 'src' / 'center_mock.txt').is_file())

    # ---- decisions are one-shot
    def test_a_second_decision_on_the_same_task_is_refused(self):
        task = self.ready_task()
        self.center.reject(task['id'], 'not wanted')
        for call in (lambda: self.center.reject(task['id'], 'again'), lambda: self.center.rework(task['id'], 'more'),
                     lambda: self.center.approve(task['id'], interactive=False), lambda: self.center.apply_approved(task['id'])):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.center.store.task(task['id'])['status'], 'rejected')

    def test_an_approved_task_can_no_longer_be_rejected_or_sent_back(self):
        task = self.ready_task()
        self.center.approve(task['id'], interactive=False)
        for call in (lambda: self.center.reject(task['id'], 'late'), lambda: self.center.rework(task['id'], 'late')):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.center.store.task(task['id'])['status'], 'approved')

    def test_a_rejected_task_cannot_be_cancelled_into_another_state(self):
        task = self.ready_task()
        self.center.reject(task['id'], 'no')
        with self.assertRaises(ValueError):
            self.center.cancel(task['id'])
        stored = self.center.store.task(task['id'])
        self.assertEqual((stored['status'], stored['cancel_requested']), ('rejected', 0))

    # ---- cancel while it waits for another attempt
    def test_cancelling_a_task_that_was_sent_back_stops_it_for_good(self):
        task = self.ready_task()
        self.center.rework(task['id'], 'one more change')
        cancelled = self.center.cancel(task['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        with self.assertRaises(ValueError):
            self.center.retry_from_web(task['id'])
        self.assertEqual(self.center.diagnose(task['id'])['reason_code'], None)

    # ---- the whole round trip through the API, as the browser drives it
    def test_the_browser_round_trip_review_send_back_review_again(self):
        task = self.ready_task()
        view = self.api('review', task['id'])['data']
        self.assertTrue(view['actions']['rework'])
        sent = self.api('rework', task['id'], {'instructions': 'rename the file'})
        self.assertTrue(sent['ok'], sent)
        self.assertEqual(sent['data']['task']['status'], 'queued')
        after = self.api('review', task['id'])['data']
        self.assertEqual(after['rework_requests'], ['rename the file'])
        self.assertFalse(any(after['actions'].values()))
        self.assertEqual(json.loads(json.dumps(after))['task']['id'], task['id'])


if __name__ == '__main__':
    unittest.main()
