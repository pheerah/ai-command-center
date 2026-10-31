"""Findings from Codex's review of the guard and of auto_retry: shell writes, a deleted config, auth failures, bad evidence."""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / 'connector-template' / 'hooks'
sys.path.insert(0, str(HOOKS))
import center_guard  # noqa: E402


class GuardRound2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'project.config.json').write_text(json.dumps({'context_scope': ['src', 'tests']}), encoding='utf-8')

    def bash(self, command):
        stderr = io.StringIO()
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(self.root)}
        return center_guard.main(stdin=io.StringIO(json.dumps(payload)), stderr=stderr, now=time.time())

    def test_shell_writes_into_the_guarded_scope_are_refused(self):
        for command in ('printf x > src/file.py', 'echo hi | tee tests/a.py', 'sed -i s/a/b/ src/a.py', 'mv notes.txt src/notes.txt',
                        'rm -rf tests', 'python -c "open(\'src/a.py\',\'w\').write(\'x\')"', 'Set-Content -Path src\\a.py -Value x', 'git apply fix.patch && echo src'):
            self.assertEqual(self.bash(command), 2, command)

    def test_reading_and_ordinary_commands_are_still_allowed(self):
        for command in ('cat src/a.py', 'ls src', 'git status', 'git diff -- src', 'grep -rn TODO src tests', 'npm run lint',
                        'python connector.py status 0123456789ab', 'cat project.config.json', 'python -m pytest -q tests'):
            self.assertEqual(self.bash(command), 0, command)

    def test_a_write_outside_the_scope_is_not_blocked(self):
        self.assertEqual(self.bash('echo notes > NOTES.md'), 0)

    def test_the_override_window_lets_scope_writes_through_but_never_touches_control_files(self):
        now = time.time()
        (self.root / '.center-direct-edit.json').write_text(json.dumps({'created_at': now, 'expires_at': now + 600}), encoding='utf-8')
        self.assertEqual(self.bash('printf x > src/file.py'), 0)
        self.assertEqual(self.bash('rm project.config.json'), 2)
        self.assertEqual(self.bash('echo {} > .claude/settings.local.json'), 2)
        self.assertEqual(self.bash('echo x > connector.py'), 2)

    def test_deleting_project_config_does_not_switch_the_installed_guard_off(self):
        hooks = self.root / '.claude' / 'hooks'
        hooks.mkdir(parents=True)
        installed = hooks / 'center_guard.py'
        shutil.copyfile(HOOKS / 'center_guard.py', installed)
        (self.root / 'project.config.json').unlink()
        payload = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(self.root / 'src' / 'a.py')}, 'cwd': str(self.root)})
        run = subprocess.run([sys.executable, str(installed)], input=payload, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        elsewhere = subprocess.run([sys.executable, str(installed)], input=json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(Path(self.tmp.name).parent / 'outside.txt')}, 'cwd': str(self.root)}),
                                   capture_output=True, text=True)
        self.assertEqual(elsewhere.returncode, 0)  # files outside the project stay editable


if __name__ == '__main__':
    unittest.main()
