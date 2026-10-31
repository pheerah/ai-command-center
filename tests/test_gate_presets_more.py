"""Reviewer findings on scripts/gate_presets.py: nothing is detected from files that do not really mark a project."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from gate_presets import detect_gates, explain  # noqa: E402


class MoreGatePresetTests(unittest.TestCase):
    def project(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, text in files.items():
            path = Path(tmp.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        return tmp.name

    def test_requirements_alone_do_not_make_a_python_project(self):
        self.assertEqual(detect_gates(self.project({'requirements.txt': 'pytest' + chr(10)})), [])

    def test_a_malformed_pytest_ini_is_skipped_not_trusted(self):
        self.assertEqual(detect_gates(self.project({'pytest.ini': 'this is not [valid ini', 'tests/test_a.py': 'x = 1'})),
                         [['python', '-m', 'unittest', 'discover', '-s', 'tests']])

    def test_requirements_choose_pytest_only_inside_a_real_python_project(self):
        project = self.project({'tests/test_a.py': 'x = 1', 'requirements-dev.txt': 'pytest==8' + chr(10)})
        self.assertEqual(detect_gates(project), [['python', '-m', 'pytest', '-q']])

    def test_explain_names_the_file_each_command_came_from(self):
        report = explain(self.project({'pytest.ini': '[pytest]' + chr(10)}))
        self.assertEqual(report['gates'][0]['source'] if 'gates' in report else report['commands'][0]['source'], 'pytest.ini')


if __name__ == '__main__':
    unittest.main()
