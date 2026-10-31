"""False positives found in the first real run in VS Code: stderr redirects and quoted prompt words must not block."""
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'connector-template' / 'hooks'))
import center_guard  # noqa: E402


class GuardFalsePositiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'src').mkdir()
        (self.root / 'project.config.json').write_text(json.dumps({'context_scope': ['src', 'tests']}), encoding='utf-8')

    def bash(self, command):
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(self.root)}
        return center_guard.main(stdin=io.StringIO(json.dumps(payload)), stderr=io.StringIO(), now=time.time())

    def test_reading_with_stderr_plumbing_is_allowed(self):
        for command in ('ls src/guard-check.txt 2>&1', 'ls src/guard-check.txt 2>/dev/null', 'cat src/a.ts 2>&1 | head -5',
                        'grep -rn cn src tests 2>nul', 'git status 2>&1'):
            self.assertEqual(self.bash(command), 0, command)

    def test_connector_calls_are_allowed_whatever_their_quoted_text_says(self):
        for command in (
            'python connector.py submit --title "Add cn test" --prompt "Add a unit test; do not touch config, copy nothing > here" --scope tests --accept "tests pass" --complexity 1',
            "python connector.py submit --title t --prompt 'check the patch and remove nothing' --scope tests --accept a",
            'python connector.py wait 0123456789ab', 'python connector.py report 0123456789ab', 'python connector.py apply 0123456789ab --dry-run',
            'python connector.py patch 0123456789ab', 'python connector.py health', 'py connector.py status 0123456789ab',
        ):
            self.assertEqual(self.bash(command), 0, command)

    def test_the_connector_shortcut_cannot_smuggle_a_second_command(self):
        for command in ('python connector.py status 0123456789ab; echo x > src/a.py', 'python connector.py status x && rm -rf src',
                        'python connector.py status x | tee src/a.py', 'python connector.py status x > src/a.py',
                        'python connector.py status x' + chr(10) + 'echo y > src/a.py', 'python connector.py status $(rm -rf src)'):
            self.assertEqual(self.bash(command), 2, command)

    def test_the_override_commands_stay_blocked_even_as_connector_calls(self):
        for command in ('python connector.py allow-direct --minutes 30 --reason "x"', 'python connector.py revoke-direct'):
            self.assertEqual(self.bash(command), 2 if 'allow-direct' in command else 0, command)

    def test_real_writes_are_still_refused(self):
        for command in ('printf x > src/file.py', 'echo hi | tee tests/a.py', 'sed -i s/a/b/ src/a.ts', 'echo "x" >> "src/a.py"', 'ls src 2>&1 > src/out.txt'):
            self.assertEqual(self.bash(command), 2, command)


if __name__ == '__main__':
    unittest.main()
