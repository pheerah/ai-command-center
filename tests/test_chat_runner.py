"""Provider command lines and the runner. Real CLIs are replaced by tiny Python stand-ins; no model is called."""
import json
import sys as _sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path as _Path
from unittest.mock import patch

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_chat
from center_chat import RESPONSE_SCHEMA, ProviderFailure, chat_command, run_provider
from center_store import pid_alive

REPLY = {'kind': 'reply', 'text': 'hello', 'files': []}
FLAGS_THAT_WRITE_OR_RUN = ('Bash', 'Edit', 'Write', 'NotebookEdit', 'accept-edits', 'acceptEdits', 'workspace-write', 'danger-full-access',
                           '--dangerously-bypass-approvals-and-sandbox', '--full-auto', '--yolo')


def command(provider, directory):
    with patch.object(center_chat, 'cli_command', lambda name: [name + '-cli']):
        return chat_command(provider, _Path(directory) / 'schema.json')


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_schema_requires_every_property_and_names_the_three_kinds(self):
        self.assertFalse(RESPONSE_SCHEMA['additionalProperties'])
        self.assertEqual(sorted(RESPONSE_SCHEMA['required']), sorted(RESPONSE_SCHEMA['properties']))
        self.assertEqual(RESPONSE_SCHEMA['properties']['kind']['enum'], ['reply', 'clarify', 'draft_task'])

    def test_codex_command_is_read_only(self):
        argv = command('codex', self.tmp.name)
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'read-only')
        self.assertIn('--output-schema', argv)
        self.assertIn('--ignore-user-config', argv)

    def test_claude_command_has_no_tools_at_all(self):
        argv = command('claude', self.tmp.name)
        self.assertEqual(argv[argv.index('--tools') + 1], '')
        self.assertIn('--strict-mcp-config', argv)
        self.assertNotIn('--allowedTools', argv)

    def test_google_command_uses_plan_mode_and_never_embeds_the_prompt(self):
        argv = command('google', self.tmp.name)
        self.assertEqual(argv[argv.index('--mode') + 1], 'plan')
        self.assertFalse(any(a.startswith('--print') for a in argv))

    def test_no_command_can_write_or_run_anything(self):
        for provider in ('codex', 'claude', 'google'):
            argv = ' '.join(command(provider, self.tmp.name))
            for flag in FLAGS_THAT_WRITE_OR_RUN:
                self.assertNotIn(flag, argv, f'{provider} {flag}')
        self.assertNotIn('API_KEY', ' '.join(command('codex', self.tmp.name)))


FAKE = textwrap.dedent('''
    import json, os, sys
    argv = sys.argv[1:]
    payload = json.loads(open(os.environ["FAKE_PAYLOAD"], encoding="utf-8").read())
    if "--output-last-message" in argv:
        sys.stdin.read()
        open(argv[argv.index("--output-last-message") + 1], "w", encoding="utf-8").write(json.dumps(payload))
    elif any(a.startswith("--print=") for a in argv):
        print(json.dumps({"status": "SUCCESS", "structured_output": payload}))
    else:
        sys.stdin.read()
        print(json.dumps(payload["envelope"] if "envelope" in payload else {"structured_output": payload}))
''')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = _Path(self.tmp.name)
        (self.dir / 'fake.py').write_text(FAKE, encoding='utf-8')
        self.work = self.dir / 'work'
        self.work.mkdir()

    def run_fake(self, provider, payload, prompt='hi'):
        (self.dir / 'payload.json').write_text(json.dumps(payload), encoding='utf-8')
        with patch.object(center_chat, 'cli_command', lambda name: [_sys.executable, str(self.dir / 'fake.py')]), \
                patch.dict('os.environ', {'FAKE_PAYLOAD': str(self.dir / 'payload.json')}), \
                patch.object(center_chat, 'worker_env', lambda: {**__import__('os').environ}):
            return run_provider(provider, prompt, 20, self.work)

    def test_codex_answer_is_read_from_the_last_message_file(self):
        self.assertEqual(json.loads(self.run_fake('codex', REPLY)), REPLY)

    def test_claude_answer_comes_from_structured_output(self):
        self.assertEqual(json.loads(self.run_fake('claude', REPLY)), REPLY)

    def test_claude_falls_back_to_the_result_text(self):
        text = self.run_fake('claude', {'envelope': {'result': json.dumps(REPLY)}})
        self.assertEqual(json.loads(text), REPLY)

    def test_claude_error_envelope_is_unavailable(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.run_fake('claude', {'envelope': {'is_error': True, 'result': 'You have hit your usage limit sk-SECRET-VALUE'}})
        self.assertEqual(caught.exception.reason, 'unavailable')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_google_answer_comes_from_the_success_envelope(self):
        self.assertEqual(json.loads(self.run_fake('google', REPLY)), REPLY)

    def test_google_prompt_too_long_for_the_command_line_is_blocked(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.run_fake('google', REPLY, prompt='x' * 20001)
        self.assertEqual(caught.exception.reason, 'blocked')

    def test_missing_output_is_bad_output(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.run_fake('claude', {'envelope': {'unrelated': 1}})
        self.assertEqual(caught.exception.reason, 'bad_output')

    def test_nonzero_exit_is_unavailable_and_hides_the_raw_output(self):
        script = self.dir / 'fail.py'
        script.write_text('import sys\nprint("token=sk-ABCDEF123456 /home/me/secret")\nsys.exit(3)\n', encoding='utf-8')
        with patch.object(center_chat, 'cli_command', lambda name: [_sys.executable, str(script)]):
            with self.assertRaises(ProviderFailure) as caught:
                run_provider('codex', 'hi', 20, self.work)
        self.assertEqual(caught.exception.reason, 'unavailable')
        self.assertNotIn('sk-', str(caught.exception))
        self.assertNotIn('/home/me', str(caught.exception))

    def test_unavailable_cli_is_unavailable(self):
        def missing(name):
            raise ValueError('Provider CLI unavailable; install its subscription CLI first')
        with patch.object(center_chat, 'cli_command', missing):
            with self.assertRaises(ProviderFailure) as caught:
                run_provider('codex', 'hi', 5, self.work)
        self.assertEqual(caught.exception.reason, 'unavailable')

    def test_timeout_kills_the_process_tree(self):
        script = self.dir / 'hang.py'
        script.write_text(textwrap.dedent(f'''
            import subprocess, sys, time, os
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            open(r"{self.dir / 'pids.txt'}", "w").write(f"{{os.getpid()}} {{child.pid}}")
            time.sleep(60)
        '''), encoding='utf-8')
        started = time.monotonic()
        with patch.object(center_chat, 'cli_command', lambda name: [_sys.executable, str(script)]):
            with self.assertRaises(ProviderFailure) as caught:
                run_provider('codex', 'hi', 2, self.work)
        self.assertEqual(caught.exception.reason, 'timeout')
        self.assertLess(time.monotonic() - started, 15)
        time.sleep(0.5)
        parent, child = (int(p) for p in (self.dir / 'pids.txt').read_text().split())
        self.assertFalse(pid_alive(parent))
        self.assertFalse(pid_alive(child))


if __name__ == '__main__':
    unittest.main()
