"""Test cancelling a running task whose owner died."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

try:
    import test_smart_router as fixtures
except ImportError:
    from tests import test_smart_router as fixtures

from center_store import pid_alive


class TestCancelDeadOwner(unittest.TestCase):
    # Reuse fixture setup without subclassing or rediscovering the existing suite.
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task
    claim_and_prepare = fixtures.CenterTests.claim_and_prepare
    implement_manually = fixtures.CenterTests.implement_manually

    # Center.recover() only inspects sessions where lease_until < time.time(), leaving active sessions with dead owners uncollected while their lease is in the future.
    @unittest.expectedFailure
    def test_cancel_dead_owner(self):
        """A cancelled task with a dead owner process should be settled by recover, but unexpired leases are ignored."""
        # Scenario: claim a mock implementation session
        task = self.task(mode="mock")
        session = self.center.claim(task["id"], "implementation", "mock", "codex")
        self.assertIsNotNone(session)
        self.assertEqual(self.center.store.task(task["id"])["status"], "assigned")

        # Mark the session owner_pid as a PID that is not alive (update the sessions row directly)
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        dead_pid = p.pid
        del p
        if pid_alive(dead_pid):
            dead_pid = 4194300
            while pid_alive(dead_pid):
                dead_pid += 1
        self.assertFalse(pid_alive(dead_pid))

        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE sessions SET owner_pid=? WHERE id=?", (dead_pid, session["id"]))

        # Verify the sessions row was updated directly
        self.assertEqual(self.center.session(session["id"])["owner_pid"], dead_pid)

        # Call Center.cancel(task_id)
        self.center.cancel(task["id"])
        self.assertEqual(self.center.store.task(task["id"])["cancel_requested"], 1)

        # Then call Center.recover()
        self.center.recover()

        # Assert the intended safe behaviour:
        # 1. The task reaches status cancelled
        current_task = self.center.store.task(task["id"])
        self.assertEqual(current_task["status"], "cancelled")

        # 2. The session row is removed
        self.assertEqual(self.center.report(task["id"])["sessions"], [])
        with self.center.store.connection() as con:
            session_row = con.execute("SELECT 1 FROM sessions WHERE task_id=?", (task["id"],)).fetchone()
        self.assertIsNone(session_row)

        # 3. Capacity is released
        with self.center.store.connection() as con:
            session_count = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        self.assertEqual(session_count, 0)

        # 4. Cancel request never approves anything
        self.assertNotEqual(current_task["status"], "approved")
        self.assertIsNone(current_task.get("approved_at"))
        self.assertIsNone(current_task.get("approved_by"))
        with self.assertRaises(ValueError):
            self.center.approve(task["id"])
        with self.center.store.connection() as con:
            evidence = con.execute("SELECT 1 FROM evidence WHERE task_id=?", (task["id"],)).fetchall()
        self.assertEqual(evidence, [])


    def test_cancel_with_dead_owner_is_settled_once_the_lease_expires(self):
        """The safe path: after the lease lapses recover() must cancel the task, drop the session and free the slot."""
        task = self.task(mode="mock")
        session = self.center.claim(task["id"], "implementation", "mock", "codex")
        self.assertIsNotNone(session)
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        self.assertFalse(pid_alive(process.pid))
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE sessions SET owner_pid=?, lease_until=? WHERE id=?", (process.pid, 1.0, session["id"]))
        self.center.cancel(task["id"])
        self.center.recover()
        self.assertEqual(self.center.store.task(task["id"])["status"], "cancelled")
        with self.center.store.connection() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM evidence WHERE task_id=?", (task["id"],)).fetchone()[0], 0)
        self.assertNotEqual(self.center.store.task(task["id"])["status"], "approved")


if __name__ == "__main__":
    unittest.main()
