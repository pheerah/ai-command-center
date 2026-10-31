"""Center must not START work on a provider whose 5-hour or weekly quota is below the configured floor (found when
Claude, with 8% weekly left, was handed three tasks because it was the only candidate left)."""
import unittest

import test_smart_router as fixtures
from center_quota import floor_check

FLOORS = {'five_hour': 10.0, 'weekly': 15.0}


def reading(five, weekly):
    window = lambda left, minutes: {'remaining_percent': left, 'used_percent': 100 - left, 'window_minutes': minutes, 'resets_at': None}
    return {'five_hour': window(five, 300), 'weekly': window(weekly, 10080)}


class FloorCheckTests(unittest.TestCase):
    def test_a_low_weekly_window_blocks_even_when_the_five_hour_window_is_healthy(self):
        ok, detail = floor_check(reading(62, 8), FLOORS)
        self.assertFalse(ok)
        self.assertEqual(detail, 'weekly_8pct_below_15')

    def test_a_low_five_hour_window_blocks_even_when_the_week_is_healthy(self):
        self.assertEqual(floor_check(reading(5, 90), FLOORS), (False, 'five_hour_5pct_below_10'))

    def test_both_windows_are_reported(self):
        self.assertEqual(floor_check(reading(4, 3), FLOORS)[1], 'five_hour_4pct_below_10,weekly_3pct_below_15')

    def test_the_boundary_is_allowed_and_just_under_is_not(self):
        self.assertTrue(floor_check(reading(10, 15), FLOORS)[0])
        self.assertFalse(floor_check(reading(9.9, 15), FLOORS)[0])
        self.assertFalse(floor_check(reading(10, 14.9), FLOORS)[0])

    def test_unknown_quota_never_blocks(self):
        self.assertEqual(floor_check(None, FLOORS), (True, ''))
        self.assertEqual(floor_check({'five_hour': None, 'weekly': None}, FLOORS), (True, ''))
        self.assertTrue(floor_check({'five_hour': reading(50, 50)['five_hour'], 'weekly': None}, FLOORS)[0])

    def test_a_grouped_provider_is_fine_while_one_group_is_above_both_floors(self):
        groups = {'groups': {'Gemini Models': reading(76, 80), 'Claude and GPT models': reading(100, 3)}}
        self.assertTrue(floor_check(groups, FLOORS)[0])
        self.assertFalse(floor_check({'groups': {'A': reading(76, 5), 'B': reading(4, 80)}}, FLOORS)[0])


class RoutingFloorTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup

    def task(self):
        return self.center.submit('project-a', 'Add scoped file', 'Create the requested sample file', ['src'], ['Tests pass'], mode='live')

    def candidates(self, task):
        return self.center.candidates(self.center.store.task(task['id']), 'implementation')

    def test_a_provider_under_the_weekly_floor_is_left_out_and_the_reason_is_recorded(self):
        self.center.quota_reader = lambda: {'claude': reading(62, 8), 'codex': reading(60, 58)}
        task = self.task()
        names = self.candidates(task)
        self.assertEqual(names, ['codex'])
        self.assertIn('quota_floor_skipped_claude_weekly_8pct_below_15', self.center.candidate_notes[task['id']])

    def test_when_every_candidate_is_under_the_floor_the_task_waits_with_a_named_reason(self):
        self.center.config['live_execution'] = True
        self.center.quota_reader = lambda: {'claude': reading(62, 8), 'codex': reading(5, 58)}
        readiness = self.center.scheduling_readiness(self.task()['id'], 'implementation', 'live')
        self.assertEqual((readiness['ready'], readiness['reason']), (False, 'provider_quota_floor'))

    def test_claim_refuses_instead_of_starting_work_on_an_exhausted_provider(self):
        self.center.config['live_execution'] = True
        self.center.quota_reader = lambda: {'claude': reading(62, 8), 'codex': reading(5, 58)}
        with self.assertRaisesRegex(ValueError, 'No eligible provider'):
            self.center.claim(self.task()['id'], 'implementation', 'live', None)

    def test_the_floor_is_configurable(self):
        self.center.config['quota_floor'] = {'five_hour': 10, 'weekly': 5}
        self.center.quota_reader = lambda: {'claude': reading(62, 8), 'codex': reading(60, 58)}
        self.assertIn('claude', self.candidates(self.task()))
        self.center.config['quota_floor'] = {'five_hour': 10, 'weekly': 20}
        self.center.quota_reader = lambda: {'claude': reading(62, 18), 'codex': reading(60, 58)}
        self.assertNotIn('claude', self.candidates(self.task()))

    def test_an_invalid_floor_is_rejected_when_the_config_loads(self):
        import json
        import tempfile
        from pathlib import Path
        from center_runtime import load_config
        base = json.loads((Path(__file__).resolve().parents[1] / 'center.config.json').read_text(encoding='utf-8'))
        self.assertEqual(load_config()['quota_floor'], {'five_hour': 10, 'weekly': 15})
        for bad in ({'weekly': 101}, {'weekly': -1}, {'daily': 5}, {'weekly': True}, {'weekly': '15'}, 'x'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.json'
                path.write_text(json.dumps({**base, 'quota_floor': bad}), encoding='utf-8')
                with self.assertRaises(ValueError, msg=repr(bad)):
                    load_config(path)


if __name__ == '__main__':
    unittest.main()
