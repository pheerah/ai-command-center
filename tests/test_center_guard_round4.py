"""Second real run in VS Code: a harmless read chained with a connector call was refused. Each piece is now judged alone."""
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'connector-template' / 'hooks'))
import center_guard  # noqa: E402

PROMPT = '--prompt "Add a Vitest unit test for cn; touch nothing else, copy no files, patch > none, mkdir no dirs"'
SUBMIT = f'python connector.py submit --title "Add unit test for cn" {PROMPT} --scope tests --accept "ok; passes" --complexity 1'


class ChainedCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'project.config.json').write_text(json.dumps({'context_scope': ['src', 'tests']}), encoding='utf-8')

    def bash(self, command):
        stderr = io.StringIO()
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(self.root)}
        return center_guard.main(stdin=io.StringIO(json.dumps(payload)), stderr=stderr, now=time.time()), stderr.getvalue()

    def test_the_exact_command_from_the_run_is_allowed(self):
        self.assertEqual(self.bash(f'ls src/lib | head -50 && {SUBMIT}')[0], 0)

    def test_harmless_commands_can_be_chained_with_connector_calls(self):
        for command in (f'ls src/lib | head -50; {SUBMIT}', f'git status && {SUBMIT}', f'{SUBMIT} && python connector.py wait 0123456789ab',
                        f'cat src/a.ts{chr(10)}{SUBMIT}', f'grep -rn cn src tests 2>&1 | head && python connector.py report 0123456789ab'):
            self.assertEqual(self.bash(command)[0], 0, command)

    def test_a_semicolon_or_ampersand_inside_quotes_does_not_split_the_command(self):
        self.assertEqual(self.bash('python connector.py submit --title "a; b && c | d" --prompt "x" --scope tests --accept y')[0], 0)

    def test_a_write_chained_after_a_connector_call_is_still_refused_and_the_message_names_the_part(self):
        code, message = self.bash('python connector.py status 0123456789ab; echo owned > src/a.py')
        self.assertEqual(code, 2)
        self.assertIn('echo owned', message)

    def test_a_write_before_a_connector_call_is_refused_too(self):
        self.assertEqual(self.bash(f'printf x > src/a.py && {SUBMIT}')[0], 2)
        self.assertEqual(self.bash(f'rm -rf tests | {SUBMIT}')[0], 2)

    def test_a_connector_call_with_a_redirect_or_subshell_is_not_a_plain_call(self):
        for command in ('python connector.py status x > src/a.py', 'python connector.py status $(rm -rf src)', 'python connector.py status `rm -rf src`'):
            self.assertEqual(self.bash(command)[0], 2, command)

    def test_the_override_command_is_refused_wherever_it_is_chained(self):
        self.assertEqual(self.bash('ls; python connector.py allow-direct --minutes 30 --reason x')[0], 2)


if __name__ == '__main__':
    unittest.main()
