import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from center_capacity import capacity_report, effective_capacity, reserved_sessions


class EffectiveCapacityTests(unittest.TestCase):
    def test_subtracts_reservation(self):
        self.assertEqual(effective_capacity(8, 3), 5)

    def test_never_returns_negative(self):
        self.assertEqual(effective_capacity(0, 0), 0)

    def test_rejects_negative_values(self):
        for args in ((-1, 0), (1, -1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                effective_capacity(*args)

    def test_rejects_bool_and_float(self):
        for args in ((True, 0), (1, False), (1.0, 0), (1, 0.5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                effective_capacity(*args)

    def test_rejects_reservation_larger_than_capacity(self):
        with self.assertRaises(ValueError):
            effective_capacity(2, 3)


class ReservedSessionsTests(unittest.TestCase):
    def test_missing_reservation_defaults_to_zero(self):
        self.assertEqual(reserved_sessions({"global_capacity": 4}), 0)

    def test_accepts_valid_reservation(self):
        self.assertEqual(
            reserved_sessions({"global_capacity": 4, "ide_reserved_sessions": 2}), 2
        )

    def test_rejects_equal_to_global_capacity(self):
        with self.assertRaises(ValueError):
            reserved_sessions({"global_capacity": 3, "ide_reserved_sessions": 3})

    def test_rejects_invalid_reservation_and_global_values(self):
        configs = (
            {"global_capacity": 3, "ide_reserved_sessions": -1},
            {"global_capacity": 3, "ide_reserved_sessions": True},
            {"global_capacity": 3, "ide_reserved_sessions": 1.5},
            {"global_capacity": -1},
            {"global_capacity": True},
        )
        for config in configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                reserved_sessions(config)


class CapacityReportTests(unittest.TestCase):
    def test_reports_reserved_capacity_and_unknown_external_sessions(self):
        report = capacity_report(
            {"global_capacity": 8, "ide_reserved_sessions": 2}, 4
        )
        self.assertEqual(report["configured_global"], 8)
        self.assertEqual(report["ide_reserved"], 2)
        self.assertEqual(report["usable_global"], 6)
        self.assertEqual(report["active_center_sessions"], 4)
        self.assertEqual(report["free_slots"], 2)
        self.assertEqual(report["external_sessions"], "unknown")
        self.assertIn("นับไม่ได้", report["note"])
        self.assertIn("ไม่ใช่ค่าที่วัดได้", report["note"])

    def test_free_slots_never_negative(self):
        report = capacity_report({"global_capacity": 3, "ide_reserved_sessions": 1}, 5)
        self.assertEqual(report["free_slots"], 0)

    def test_external_sessions_is_always_unknown(self):
        for config, active in (
            ({"global_capacity": 1}, 0),
            ({"global_capacity": 4, "ide_reserved_sessions": 1}, 20),
        ):
            with self.subTest(config=config, active=active):
                self.assertEqual(
                    capacity_report(config, active)["external_sessions"], "unknown"
                )

    def test_rejects_invalid_active_session_count(self):
        for active in (-1, True, 1.5):
            with self.subTest(active=active), self.assertRaises(ValueError):
                capacity_report({"global_capacity": 4}, active)


if __name__ == "__main__":
    unittest.main()
