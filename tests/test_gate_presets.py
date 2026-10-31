"""Unit tests for quality-gate detection helper."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

# insert the scripts directory into sys.path using Path(__file__).resolve().parents[1] / "scripts"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import gate_presets
from gate_presets import detect_gates, explain, main


class TestGatePresets(unittest.TestCase):
    def test_node_all_scripts(self):
        """Cover: node project with all scripts."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            pkg = {
                "name": "all-scripts-pkg",
                "scripts": {
                    "test": "vitest run",
                    "build": "vite build",
                    "lint": "eslint .",
                    "typecheck": "tsc --noEmit",
                    "test:e2e": "playwright test",
                    "start": "node index.js",
                    "deploy": "sh deploy.sh",
                },
            }
            (project_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

            gates = detect_gates(project_dir)
            expected = [
                ["npm", "run", "lint"],
                ["npm", "run", "typecheck"],
                ["npm", "run", "test"],
                ["npm", "run", "build"],
                ["npm", "run", "test:e2e"],
            ]
            self.assertEqual(gates, expected)

            explanation = explain(project_dir)
            self.assertIn("commands", explanation)
            self.assertEqual(len(explanation["commands"]), 5)
            for idx, item in enumerate(explanation["commands"]):
                self.assertEqual(item["command"], expected[idx])
                self.assertEqual(item["file"], "package.json")

    def test_node_only_some_scripts_order_kept(self):
        """Cover: only some scripts (order kept, missing ones absent)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            # Define in arbitrary order in package.json
            pkg = {
                "scripts": {
                    "build": "vite build",
                    "test:e2e": "playwright test",
                    "lint": "eslint .",
                }
            }
            (project_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

            gates = detect_gates(project_dir)
            expected = [
                ["npm", "run", "lint"],
                ["npm", "run", "build"],
                ["npm", "run", "test:e2e"],
            ]
            self.assertEqual(gates, expected)

            # Another combination
            pkg2 = {
                "scripts": {
                    "test": "jest",
                    "typecheck": "tsc",
                }
            }
            (project_dir / "package.json").write_text(json.dumps(pkg2), encoding="utf-8")

            gates2 = detect_gates(project_dir)
            expected2 = [
                ["npm", "run", "typecheck"],
                ["npm", "run", "test"],
            ]
            self.assertEqual(gates2, expected2)

    def test_malformed_package_json(self):
        """Cover: malformed package.json."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            pkg_file = project_dir / "package.json"

            # 1. Invalid JSON syntax
            pkg_file.write_text("{ not a valid json syntax ...", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])
            self.assertEqual(explain(project_dir), {"commands": []})

            # 2. JSON is not an object
            pkg_file.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 3. scripts is not a dict
            pkg_file.write_text('{"scripts": "npm test"}', encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 4. scripts value is null
            pkg_file.write_text('{"scripts": null}', encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 5. individual script values are not strings
            pkg_file.write_text('{"scripts": {"test": 12345, "lint": null}}', encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

    def test_python_project_with_pytest_ini(self):
        """Cover: python project with pytest.ini."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "pytest.ini").write_text("[pytest]\nminversion = 6.0\n", encoding="utf-8")


            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "pytest", "-q"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "pytest", "-q"])
            self.assertEqual(info["commands"][0]["file"], "pytest.ini")

    def test_python_project_with_pyproject_toml_tool_pytest(self):
        """Cover: python project declaring pytest in pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "pyproject.toml").write_text(
                "[build-system]\nrequires = [\"setuptools\"]\n\n"
                "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
                encoding="utf-8",
            )

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "pytest", "-q"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "pytest", "-q"])
            self.assertEqual(info["commands"][0]["file"], "pyproject.toml")

    def test_malformed_pyproject_toml(self):
        """Cover: malformed pyproject.toml is skipped and does not produce pytest gate."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            # Malformed TOML that contains tool.pytest in text but is syntactically invalid
            (project_dir / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\n"
                "addopts = \"unclosed string syntax...\n"
                "invalid = = = = {\n",
                encoding="utf-8",
            )

            # Without other sources, malformed pyproject.toml should be skipped
            self.assertEqual(detect_gates(project_dir), [])
            self.assertEqual(explain(project_dir), {"commands": []})

            # If test files exist alongside malformed pyproject.toml, it falls back to unittest
            tests_dir = project_dir / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_suite.py").write_text("import unittest\n", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "unittest", "discover", "-s", "tests"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "unittest", "discover", "-s", "tests"])
            self.assertEqual(info["commands"][0]["file"], "tests/test_suite.py")

    def test_python_project_with_requirements_pytest(self):
        """Cover: python project declaring pytest in requirements*.txt."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "requirements.txt").write_text(
                "requests>=2.28.0\npytest>=7.0.0\npytest-cov\n",
                encoding="utf-8",
            )
            # requirements.txt alone is not a Python-project marker; a tests directory is.
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_sample.py").write_text("x = 1", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "pytest", "-q"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "pytest", "-q"])
            self.assertEqual(info["commands"][0]["file"], "requirements.txt")

    def test_python_project_with_requirements_dev_pytest(self):
        """Cover: pytest declared in requirements-dev.txt with setup.cfg."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            (project_dir / "setup.cfg").write_text("[metadata]\nname = mypkg\n", encoding="utf-8")
            (project_dir / "requirements-dev.txt").write_text("pytest\nflake8\n", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "pytest", "-q"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "pytest", "-q"])
            self.assertEqual(info["commands"][0]["file"], "requirements-dev.txt")

    def test_unittest_only_project(self):
        """Cover: unittest-only project reports the test_*.py file supporting the command."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            tests_dir = project_dir / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_main.py").write_text("import unittest\n", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "unittest", "discover", "-s", "tests"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "unittest", "discover", "-s", "tests"])
            self.assertEqual(info["commands"][0]["file"], "tests/test_main.py")

    def test_unittest_nested_in_tests(self):
        """Cover: test_*.py nested in subdirectories under tests/."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            sub_tests = project_dir / "tests" / "unit"
            sub_tests.mkdir(parents=True)
            (sub_tests / "test_core.py").write_text("import unittest\n", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(gates, [["python", "-m", "unittest", "discover", "-s", "tests"]])

            info = explain(project_dir)
            self.assertEqual(len(info["commands"]), 1)
            self.assertEqual(info["commands"][0]["command"], ["python", "-m", "unittest", "discover", "-s", "tests"])
            self.assertEqual(info["commands"][0]["file"], "tests/unit/test_core.py")

    def test_empty_directory(self):
        """Cover: empty directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            self.assertEqual(detect_gates(project_dir), [])
            self.assertEqual(explain(project_dir), {"commands": []})

    def test_nothing_invented(self):
        """Cover: that nothing is invented."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)

            # 1. Project with only unrelated files
            (project_dir / "README.md").write_text("# Documentation", encoding="utf-8")
            (project_dir / "main.py").write_text("print('hello')", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 2. Python project with setup.cfg but NO pytest and NO test_*.py in tests
            (project_dir / "setup.cfg").write_text("[metadata]\nname = pkg", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 3. Python project with pyproject.toml but NO pytest section and NO tests
            (project_dir / "pyproject.toml").write_text("[project]\nname = 'pkg'", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 4. requirements.txt with other dependencies but NO pytest
            (project_dir / "requirements.txt").write_text("requests==2.28.1\nflask>=2.0\n", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 5. tests directory exists but has NO test_*.py files
            tests_dir = project_dir / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "helper.py").write_text("def helper(): pass", encoding="utf-8")
            (tests_dir / "README.md").write_text("tests guide", encoding="utf-8")
            self.assertEqual(detect_gates(project_dir), [])

            # 6. package.json exists with only non-gate scripts (e.g. start, demo)
            (project_dir / "package.json").write_text(
                json.dumps({"scripts": {"start": "node index.js", "demo": "node demo.js"}}),
                encoding="utf-8",
            )
            # setup.cfg, pyproject.toml, requirements (no pytest), tests (no test_*.py), package.json (no gate scripts)
            # Nothing should be invented!
            self.assertEqual(detect_gates(project_dir), [])
            self.assertEqual(explain(project_dir), {"commands": []})

    def test_hybrid_project(self):
        """Cover: hybrid project with both Node and Python quality gates."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            pkg = {"scripts": {"lint": "eslint .", "test": "vitest run"}}
            (project_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
            (project_dir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

            gates = detect_gates(project_dir)
            self.assertEqual(
                gates,
                [
                    ["npm", "run", "lint"],
                    ["npm", "run", "test"],
                    ["python", "-m", "pytest", "-q"],
                ],
            )

    def test_missing_or_nonexistent_directory(self):
        """Cover: missing/nonexistent path never raises and returns empty."""
        nonexistent = Path(tempfile.gettempdir()) / "nonexistent_dir_random_12345"
        self.assertEqual(detect_gates(nonexistent), [])
        self.assertEqual(explain(nonexistent), {"commands": []})

    def test_cli_prints_explain_as_json(self):
        """Cover: command-line interface prints explain() as JSON and does nothing else."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            pkg = {"scripts": {"lint": "eslint ."}}
            (project_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

            with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
                exit_code = main([str(project_dir)])
                self.assertEqual(exit_code, 0)
                output = fake_stdout.getvalue()

            data = json.loads(output)
            self.assertEqual(data, explain(project_dir))
            self.assertEqual(len(data["commands"]), 1)
            self.assertEqual(data["commands"][0]["command"], ["npm", "run", "lint"])
            self.assertEqual(data["commands"][0]["file"], "package.json")


if __name__ == "__main__":
    unittest.main()
