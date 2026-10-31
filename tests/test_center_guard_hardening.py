"""The guard must not be removable by the agent it guards: control files, shell tricks and crashes all fail closed."""
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'connector-template' / 'hooks'))
import center_guard  # noqa: E402


class GuardHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'project.config.json').write_text(json.dumps({'context_scope': ['src']}), encoding='utf-8')

    def call(self, tool, **tool_input):
        stderr = io.StringIO()
        code = center_guard.main(stdin=io.StringIO(json.dumps({'tool_name': tool, 'tool_input': tool_input, 'cwd': str(self.root)})), stderr=stderr, now=time.time())
        return code, stderr.getvalue()

    def open_window(self):
        now = time.time()
        (self.root / '.center-direct-edit.json').write_text(json.dumps({'created_at': now, 'expires_at': now + 600, 'reason': 'test'}), encoding='utf-8')

    def test_control_files_are_protected_even_outside_the_scope(self):
        for name in ('.center-direct-edit.json', 'connector.py', 'center.connection.json', 'project.config.json',
                     '.claude/settings.local.json', '.claude/hooks/center_guard.py'):
            code, message = self.call('Write', file_path=str(self.root / name))
            self.assertEqual(code, 2, name)
            self.assertIn('cannot be changed by the agent', message)

    def test_control_files_stay_protected_during_an_override_window(self):
        self.open_window()
        self.assertEqual(self.call('Edit', file_path=str(self.root / '.center-direct-edit.json'))[0], 2)
        self.assertEqual(self.call('Edit', file_path=str(self.root / '.claude' / 'settings.local.json'))[0], 2)
        self.assertEqual(self.call('Edit', file_path=str(self.root / 'src' / 'app.py'))[0], 0)  # the window itself still works

    def test_ordinary_files_outside_the_scope_remain_editable(self):
        self.assertEqual(self.call('Write', file_path=str(self.root / 'notes.md'))[0], 0)
        self.assertEqual(self.call('Write', file_path=str(self.root / '.claude' / 'notes.md'))[0], 0)

    def test_shell_commands_that_open_a_window_or_touch_the_guard_are_refused(self):
        for command in ('python connector.py allow-direct --minutes 30 --reason x', 'echo {} > .center-direct-edit.json',
                        'del .claude\\hooks\\center_guard.py', 'sed -i s/x/y/ .claude/settings.local.json', 'type center.connection.json'):
            self.assertEqual(self.call('Bash', command=command)[0], 2, command)

    def test_ordinary_shell_commands_are_not_blocked(self):
        for command in ('git status', 'python connector.py submit --title t --prompt p --scope src --accept a', 'npm test'):
            self.assertEqual(self.call('Bash', command=command)[0], 0, command)

    def test_an_unreadable_project_config_guards_the_whole_project(self):
        (self.root / 'project.config.json').write_text('{ not json', encoding='utf-8')
        self.assertEqual(self.call('Write', file_path=str(self.root / 'anything.py'))[0], 2)

    def test_a_config_without_a_scope_list_guards_the_whole_project(self):
        (self.root / 'project.config.json').write_text(json.dumps({'context_scope': 'src'}), encoding='utf-8')
        self.assertEqual(self.call('Write', file_path=str(self.root / 'src' / 'a.py'))[0], 2)
        self.assertEqual(self.call('Write', file_path=str(self.root / 'docs' / 'a.md'))[0], 2)

    def test_a_crash_inside_the_guard_blocks_instead_of_allowing(self):
        original = center_guard._find_project_root
        center_guard._find_project_root = lambda start: 1 / 0
        self.addCleanup(setattr, center_guard, '_find_project_root', original)
        code, message = self.call('Write', file_path=str(self.root / 'src' / 'a.py'))
        self.assertEqual(code, 2)
        self.assertIn('failed unexpectedly', message)


if __name__ == '__main__':
    unittest.main()
