"""Model/effort/skill selection and quota-aware routing, with no CLI or model calls."""
import json
import sqlite3
import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_policy
import center_quota
from center_runtime import Center, load_config

CONFIG = load_config()
HIGH = ['low', 'medium', 'high', 'xhigh', 'max']


def reading(five, weekly=None):
    window = lambda left: {'remaining_percent': left, 'used_percent': 100 - left, 'window_minutes': 300, 'resets_at': None}
    return {'five_hour': window(five), 'weekly': window(five if weekly is None else weekly)}


def task(complexity=3, title='Add feature', prompt='Implement it'):
    return {'complexity': complexity, 'title': title, 'prompt': prompt}


class PlanTests(unittest.TestCase):
    def plan(self, provider='claude', role='implementation', quota=None, **kwargs):
        return center_policy.choose_plan(CONFIG, task(**kwargs), role, provider, quota)

    def test_effort_and_model_scale_with_complexity_to_save_tokens(self):
        light, heavy = self.plan(complexity=1), self.plan(complexity=5)
        self.assertEqual((light['model'], light['effort']), ('claude-haiku-5-5', 'low'))
        self.assertEqual((heavy['model'], heavy['effort']), ('claude-opus-5-5', 'xhigh'))
        self.assertEqual(self.plan(complexity=3)['model'], 'claude-sonnet-5-5')

    def test_review_never_runs_below_standard_unless_trivial(self):
        self.assertEqual(self.plan(role='review', complexity=2)['model'], 'claude-sonnet-5-5')
        self.assertEqual(self.plan(role='review', complexity=1)['model'], 'claude-haiku-5-5')

    def test_low_quota_downshifts_tier_and_effort(self):
        plan = self.plan(complexity=5, quota={'claude': reading(18)})
        self.assertEqual(plan['model'], 'claude-sonnet-5-5')
        self.assertIn('quota_pressure_18pct_downshift', plan['reasons'])
        critical = self.plan(complexity=5, quota={'claude': reading(6)})
        self.assertEqual(critical['effort'], 'low')

    def test_unknown_quota_is_not_a_penalty(self):
        self.assertEqual(self.plan(complexity=5, quota={'claude': None})['model'], 'claude-opus-5-5')

    def test_effort_is_clipped_to_what_the_model_supports(self):
        config = json.loads(json.dumps(CONFIG))
        config['providers']['codex']['models'] = [{'id': 'm', 'tier': 'heavy', 'efforts': ['low', 'medium']}]
        plan = center_policy.choose_plan(config, task(5), 'implementation', 'codex')
        self.assertEqual(plan['effort'], 'medium')

    def test_models_without_effort_levels_get_none(self):
        self.assertIsNone(self.plan(provider='google', complexity=3)['effort'])

    def test_a_model_group_with_low_quota_is_skipped_for_the_next_model(self):
        config = json.loads(json.dumps(CONFIG))
        # Synthetic catalog: a second quota group in the heavy tier, to exercise per-group routing.
        config['providers']['google']['models'].insert(2, {'id': 'other-group-heavy', 'tier': 'heavy', 'efforts': [], 'quota_group': 'Other models'})
        low = {'google': {'groups': {'Other models': reading(8), 'Gemini Models': reading(90)}}}
        self.assertEqual(center_policy.choose_plan(config, task(5), 'implementation', 'google', low)['model'], 'gemini-3.8-flash-high')
        healthy = {'google': {'groups': {'Other models': reading(90), 'Gemini Models': reading(90)}}}
        self.assertEqual(center_policy.choose_plan(config, task(5), 'implementation', 'google', healthy)['model'], 'other-group-heavy')

    def test_the_shipped_google_catalog_only_lists_models_verified_in_headless_mode(self):
        self.assertEqual({m['id'] for m in CONFIG['providers']['google']['models']},
                         {'gemini-3.8-flash-low', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high'})

    def test_title_decides_the_task_kind_over_incidental_prompt_words(self):
        self.assertEqual(center_policy.classify_kind('Test cancelling a task', 'add a comment explaining the gap'), 'test')
        self.assertEqual(center_policy.classify_kind('Add widget', 'fix the error path too'), 'bugfix')

    def test_skills_follow_task_kind_and_role(self):
        self.assertEqual(center_policy.classify_kind('Fix crash on save', 'it throws an exception'), 'bugfix')
        self.assertEqual(self.plan(title='Fix crash on save')['skills'], ['systematic-debugging'])
        self.assertEqual(center_policy.classify_kind('Rotate OAuth token storage', ''), 'security')
        self.assertEqual(self.plan(title='Add widget')['skills'], ['test-driven-development'])
        review = self.plan(role='review', title='Add widget')
        self.assertEqual(review['skills'], ['independent-code-review'])

    def test_skill_brief_is_bounded(self):
        brief = center_policy.skill_brief(CONFIG, ['test-driven-development', 'independent-code-review'], limit=80)
        self.assertLessEqual(len(brief), 80)

    def test_every_catalog_model_has_a_known_tier(self):
        for name, provider in CONFIG['providers'].items():
            self.assertTrue(provider.get('models'), name)
            self.assertEqual({m['tier'] for m in provider['models']} & set(center_policy.TIERS), set(center_policy.TIERS), name)


class FakeStore:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        for ddl in ('CREATE TABLE authorship(task_id TEXT,provider TEXT)', 'CREATE TABLE sessions(provider TEXT)',
                    'CREATE TABLE tasks(provider TEXT,status TEXT,error TEXT,mode TEXT,updated_at TEXT)',
                    'CREATE TABLE events(id INTEGER PRIMARY KEY,event TEXT,detail TEXT)'):
            self.db.execute(ddl)

    @contextmanager
    def connection(self, write=False):
        yield self.db


class RoutingTests(unittest.TestCase):
    def candidates(self, quota):
        health = {name: {**cfg, 'cooldown_until': 0} for name, cfg in CONFIG['providers'].items()}
        center = SimpleNamespace(store=FakeStore(), config=CONFIG, provider_status=lambda: health, quota_reader=lambda: quota, quota_floors=lambda: {'five_hour': 10.0, 'weekly': 15.0})
        row = {'id': 't', 'mode': 'live', 'complexity': 3, 'config_json': json.dumps({'allowed_providers': ['codex', 'claude', 'google']})}
        return Center.candidates(center, row, 'implementation')

    def test_prefers_the_provider_with_more_plan_left(self):
        order = self.candidates({'codex': reading(30), 'claude': reading(80), 'google': reading(60)})
        self.assertEqual(order, ['claude', 'google', 'codex'])

    def test_low_quota_providers_are_deprioritised_and_exhausted_ones_skipped(self):
        order = self.candidates({'codex': reading(15), 'claude': reading(3), 'google': None})
        self.assertEqual(order, ['google', 'codex'])

    def test_google_with_one_exhausted_group_still_routes_on_the_open_group(self):
        google = {'groups': {'Claude and GPT models': reading(2), 'Gemini Models': reading(90)}}
        self.assertIn('google', self.candidates({'google': google}))
        both = {'groups': {'Claude and GPT models': reading(2), 'Gemini Models': reading(1)}}
        self.assertNotIn('google', self.candidates({'google': both}))

    def test_unknown_quota_does_not_exclude_a_provider(self):
        self.assertEqual(set(self.candidates({})), {'codex', 'claude', 'google'})


class QuotaReaderTests(unittest.TestCase):
    def test_remaining_uses_tightest_window_and_handles_groups(self):
        self.assertEqual(center_quota.remaining(reading(60, 25)), 25)
        self.assertIsNone(center_quota.remaining(None))
        groups = {'groups': {'A': reading(70), 'B': reading(40)}}
        self.assertEqual(center_quota.remaining(groups), 40)
        self.assertEqual(center_quota.remaining(groups, 'A'), 70)

    def test_codex_reader_takes_latest_rate_limits_from_session_log(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as home:
            day = Path(home) / '.codex' / 'sessions' / '2026' / '10' / '31'
            day.mkdir(parents=True)
            old = {'payload': {'rate_limits': {'primary': {'used_percent': 90, 'window_minutes': 300, 'resets_at': 1}, 'secondary': {'used_percent': 90}}}}
            new = {'payload': {'rate_limits': {'primary': {'used_percent': 5, 'window_minutes': 300, 'resets_at': int(time.time()) + 3600}, 'secondary': {'used_percent': 37, 'window_minutes': 10080}}}}
            (day / 'rollout.jsonl').write_text(json.dumps(old) + '\nnot json\n' + json.dumps(new) + '\n', encoding='utf-8')
            result = center_quota.read_codex(home)
            self.assertEqual(result['five_hour']['remaining_percent'], 95)
            self.assertEqual(result['weekly']['remaining_percent'], 63)
            self.assertIsNone(center_quota.read_codex(Path(home) / 'missing'))


if __name__ == '__main__':
    unittest.main()
