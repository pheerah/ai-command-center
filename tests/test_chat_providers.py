"""Which providers may answer the secretary, and in what order. No model is called."""
import sys as _sys
import tempfile
import time
import unittest
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
from center_chat import chat_provider_order
from center_runtime import Center


def window(percent):
    return {'remaining_percent': percent}


def reading(five_hour, weekly=100):
    return {'five_hour': window(five_hour), 'weekly': window(weekly)}


class ProviderOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.center = Center(_Path(self.tmp.name) / 'state')
        self.center.config['chat'] = {'providers': ['codex', 'claude', 'google'], 'adapter': 'live'}
        self.quota = {}
        self.center.quota_reader = lambda: self.quota

    def test_orders_by_most_quota_left_unknown_last(self):
        self.quota = {'codex': reading(40), 'claude': reading(90), 'google': None}
        self.assertEqual(chat_provider_order(self.center), ['claude', 'codex', 'google'])

    def test_skips_unavailable_cooldown_non_subscription_and_below_floor(self):
        self.center.set_provider('codex', 'unavailable', 'test outage')
        with self.center.store.connection(write=True) as con:
            con.execute('INSERT INTO provider_health VALUES(?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET cooldown_until=excluded.cooldown_until',
                        ('claude', 'available', 'cooling', time.time() + 600, '2026-01-01T00:00:00+00:00'))
        self.assertEqual(chat_provider_order(self.center), ['google'])
        self.center.config['providers']['google']['entitlement'] = 'api'
        self.assertEqual(chat_provider_order(self.center), [])

    def test_below_quota_floor_is_skipped(self):
        self.quota = {'codex': reading(5), 'claude': reading(90, weekly=10), 'google': reading(80)}
        self.assertEqual(chat_provider_order(self.center), ['google'])

    def test_below_five_percent_remaining_is_skipped(self):
        self.center.quota_floors = lambda: {'five_hour': 0.0, 'weekly': 0.0}
        self.quota = {'codex': reading(4), 'claude': reading(6), 'google': None}
        self.assertEqual(chat_provider_order(self.center), ['claude', 'google'])

    def test_only_configured_chat_providers_are_considered(self):
        self.center.config['chat'] = {'providers': ['codex', 'claude']}
        self.assertEqual(sorted(chat_provider_order(self.center)), ['claude', 'codex'])

    def test_empty_list_when_nothing_eligible(self):
        self.center.config['chat'] = {'providers': []}
        self.assertEqual(chat_provider_order(self.center), [])


if __name__ == '__main__':
    unittest.main()
