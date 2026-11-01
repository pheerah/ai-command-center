"""Unit tests for Windows auto-start script."""
from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

# Insert the scripts directory into sys.path using Path(__file__).resolve().parents[1] / "scripts"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import autostart
from autostart import (
    TASK_DASHBOARD,
    TASK_SCHEDULER,
    build_commands,
    build_status_commands,
    build_uninstall_commands,
    get_python,
    main,
)


class TestAutostart(unittest.TestCase):
    def test_build_commands(self):
        root = "C:\\Projects\\AI Command Center"
        python = "C:\\Python311\\python.exe"
        node = "node"

        commands = build_commands(root, python, node)
        self.assertEqual(len(commands), 2)

        sched_cmd, dash_cmd = commands

        # Task names
        self.assertIn("/TN", sched_cmd)
        self.assertEqual(sched_cmd[sched_cmd.index("/TN") + 1], TASK_SCHEDULER)
        self.assertEqual(TASK_SCHEDULER, "AI Command Center Scheduler")

        self.assertIn("/TN", dash_cmd)
        self.assertEqual(dash_cmd[dash_cmd.index("/TN") + 1], TASK_DASHBOARD)
        self.assertEqual(TASK_DASHBOARD, "AI Command Center Dashboard")

        # Switches: ONLOGON, LIMITED, /F
        for cmd in (sched_cmd, dash_cmd):
            self.assertEqual(cmd[0], "schtasks")
            self.assertEqual(cmd[1], "/Create")
            self.assertIn("/SC", cmd)
            self.assertEqual(cmd[cmd.index("/SC") + 1], "ONLOGON")
            self.assertIn("/RL", cmd)
            self.assertEqual(cmd[cmd.index("/RL") + 1], "LIMITED")
            self.assertIn("/F", cmd)

            # Never use /RU SYSTEM or /RL HIGHEST
            cmd_str = " ".join(cmd)
            self.assertNotIn("SYSTEM", cmd_str)
            self.assertNotIn("HIGHEST", cmd_str)
            self.assertNotIn("/RU", cmd)

        # Quoted /TR value, root and python quoted, cd /d to root
        tr_sched = sched_cmd[sched_cmd.index("/TR") + 1]
        self.assertIn(f'cd /d "{root}"', tr_sched)
        self.assertIn(f'"{python}" backend\\smart_router.py start --mode live', tr_sched)

        tr_dash = dash_cmd[dash_cmd.index("/TR") + 1]
        self.assertIn(f'cd /d "{root}"', tr_dash)
        self.assertIn("node server.js", tr_dash)

    def test_build_commands_keeps_spaces_quoted_and_rejects_command_injection(self):
        root = 'C:\\My Center'
        python = 'C:\\Python Path\\python.exe'
        node = 'C:\\Program Files\\nodejs\\node.exe'
        sched_cmd, dash_cmd = build_commands(root, python, node)
        tr_sched = sched_cmd[sched_cmd.index("/TR") + 1]
        self.assertIn('cd /d "C:\\My Center"', tr_sched)
        self.assertIn('"C:\\Python Path\\python.exe"', tr_sched)
        tr_dash = dash_cmd[dash_cmd.index("/TR") + 1]
        self.assertIn('"C:\\Program Files\\nodejs\\node.exe"', tr_dash)
        for bad_root in ('C:\\a" && calc && "b', 'C:\\%PATH%\\x', 'C:\\x' + chr(10) + 'y'):
            with self.assertRaises(ValueError):
                build_commands(bad_root, python, node)

    def test_install_refusing_without_yes(self):
        # Must refuse and exit non-zero, printing commands and clear message to stderr
        for plat in ("win32", "linux", "darwin"):
            with patch("sys.platform", plat), \
                 patch("subprocess.run") as mock_run, \
                 patch("sys.stderr", new=io.StringIO()) as fake_stderr:
                rc = main(["install"])
                self.assertNotEqual(rc, 0, f"Expected non-zero exit on {plat} without --yes")
                mock_run.assert_not_called()

                err = fake_stderr.getvalue()
                self.assertIn("--yes", err)
                self.assertIn(TASK_SCHEDULER, err)
                self.assertIn(TASK_DASHBOARD, err)

    def test_install_refusing_on_non_windows(self):
        # When --yes is passed on non-Windows, must refuse and print commands + message to stderr
        for plat in ("linux", "darwin", "freebsd"):
            with patch("sys.platform", plat), \
                 patch("subprocess.run") as mock_run, \
                 patch("sys.stderr", new=io.StringIO()) as fake_stderr:
                rc = main(["install", "--yes"])
                self.assertNotEqual(rc, 0, f"Expected non-zero exit on {plat} even with --yes")
                mock_run.assert_not_called()

                err = fake_stderr.getvalue()
                self.assertTrue("win32" in err or "Windows" in err)
                self.assertIn(TASK_SCHEDULER, err)
                self.assertIn(TASK_DASHBOARD, err)

    def test_install_calling_subprocess_run(self):
        expected = build_commands(autostart.ROOT, get_python(autostart.ROOT), "node")

        with patch("sys.platform", "win32"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            rc = main(["install", "--yes"])
            self.assertEqual(rc, 0)
            self.assertEqual(mock_run.call_count, 2)
            self.assertEqual(mock_run.call_args_list[0][0][0], expected[0])
            self.assertEqual(mock_run.call_args_list[1][0][0], expected[1])

    def test_uninstall_calling_subprocess_run(self):
        expected = [
            ["schtasks", "/Delete", "/TN", TASK_SCHEDULER, "/F"],
            ["schtasks", "/Delete", "/TN", TASK_DASHBOARD, "/F"],
        ]
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            rc = main(["uninstall"])
            self.assertEqual(rc, 0)
            self.assertEqual(mock_run.call_count, 2)
            self.assertEqual(mock_run.call_args_list[0][0][0], expected[0])
            self.assertEqual(mock_run.call_args_list[1][0][0], expected[1])

    def test_status_calling_subprocess_run(self):
        expected = [
            ["schtasks", "/Query", "/TN", TASK_SCHEDULER],
            ["schtasks", "/Query", "/TN", TASK_DASHBOARD],
        ]
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            rc = main(["status"])
            self.assertEqual(rc, 0)
            self.assertEqual(mock_run.call_count, 2)
            self.assertEqual(mock_run.call_args_list[0][0][0], expected[0])
            self.assertEqual(mock_run.call_args_list[1][0][0], expected[1])

    def test_print_shows_commands_and_runs_nothing(self):
        with patch("subprocess.run") as mock_run, \
             patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            rc = main(["print"])
            self.assertEqual(rc, 0)
            mock_run.assert_not_called()

            out = fake_stdout.getvalue()
            self.assertIn(TASK_SCHEDULER, out)
            self.assertIn(TASK_DASHBOARD, out)
            self.assertIn("/SC ONLOGON", out)
            self.assertIn("/RL LIMITED", out)

    def test_subprocess_exit_code_propagation(self):
        with patch("sys.platform", "win32"), \
             patch("subprocess.run", return_value=MagicMock(returncode=42)):
            rc = main(["install", "--yes"])
            self.assertEqual(rc, 42)

        with patch("subprocess.run", return_value=MagicMock(returncode=7)):
            rc = main(["status"])
            self.assertEqual(rc, 7)

        with patch("subprocess.run", return_value=MagicMock(returncode=13)):
            rc = main(["uninstall"])
            self.assertEqual(rc, 13)


if __name__ == "__main__":
    unittest.main()
