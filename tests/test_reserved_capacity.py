"""Part of the capacity is reserved for the interactive Claude Code session; autonomous workers never take it."""
import json
import unittest

import test_smart_router as fixtures
from center_runtime import load_config


class ReservedCapacityTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task

    def reserve(self, glob, reserved):
        self.center.config['global_capacity'] = glob
        self.center.config['ide_reserved_sessions'] = reserved

    def test_usable_capacity_is_global_minus_the_reservation(self):
        self.reserve(4, 1)
        self.assertEqual(self.center.usable_capacity(), 3)
        self.reserve(4, 0)
        self.assertEqual(self.center.usable_capacity(), 4)

    def test_a_reservation_blocks_the_last_slot_for_workers(self):
        self.reserve(2, 1)
        first, second = self.task(), self.task()
        self.assertIsNotNone(self.center.claim(first['id'], 'implementation', 'mock', 'codex'))
        readiness = self.center.scheduling_readiness(second['id'], 'implementation', 'mock')
        self.assertEqual((readiness['ready'], readiness['reason']), (False, 'global_capacity'))
        self.assertIsNone(self.center.claim(second['id'], 'implementation', 'mock', 'claude'))

    def test_without_a_reservation_the_same_slot_is_usable(self):
        self.reserve(2, 0)
        first, second = self.task(), self.task()
        self.assertIsNotNone(self.center.claim(first['id'], 'implementation', 'mock', 'codex'))
        self.assertIsNotNone(self.center.claim(second['id'], 'implementation', 'mock', 'claude'))

    def test_the_status_snapshot_reports_the_limits_honestly(self):
        self.reserve(4, 1)
        capacity = self.center.report()['capacity']
        self.assertEqual((capacity['configured_global'], capacity['ide_reserved'], capacity['usable_global']), (4, 1, 3))
        self.assertEqual(capacity['external_sessions'], 'unknown')
        self.assertIn('global_capacity', self.center.report())  # existing consumers keep working

    def test_an_invalid_reservation_is_rejected_when_the_config_loads(self):
        import tempfile
        from pathlib import Path
        base = json.loads((Path(__file__).resolve().parents[1] / 'center.config.json').read_text(encoding='utf-8'))
        for bad in (-1, 4, True, 1.5, '1'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.json'
                path.write_text(json.dumps({**base, 'global_capacity': 4, 'ide_reserved_sessions': bad}), encoding='utf-8')
                with self.assertRaises(ValueError, msg=repr(bad)):
                    load_config(path)

    def test_the_shipped_config_reserves_one_session_for_the_ide(self):
        config = load_config()
        self.assertEqual(config['ide_reserved_sessions'], 1)
        self.assertLess(config['ide_reserved_sessions'], config['global_capacity'])


if __name__ == '__main__':
    unittest.main()
