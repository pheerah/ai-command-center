"""Secretary answers are untrusted model output: only three well-formed shapes inside the project's scope may pass."""
import json
import sys as _sys
import tempfile
import unittest
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_chat
from center_chat import ChatOutputError, chat_settings, parse_secretary_output
from center_runtime import Center

SCOPE = ['src', 'docs/guide.md']


def draft(**overrides):
    value = {'kind': 'draft_task', 'title': 'Add b', 'prompt': 'Create src/b.py', 'scope': ['src'], 'accept': ['b exists'],
             'complexity': 2, 'provider': 'auto', 'related_task_id': None}
    value.update(overrides)
    return value


class ParseOutputTests(unittest.TestCase):
    def parse(self, value, scope=SCOPE):
        return parse_secretary_output(value if isinstance(value, str) else json.dumps(value), scope)

    def test_reply_clarify_and_draft_are_accepted(self):
        self.assertEqual(self.parse({'kind': 'reply', 'text': 'Because x', 'files': ['src/a.py']})['files'], ['src/a.py'])
        self.assertEqual(self.parse({'kind': 'clarify', 'questions': ['Which page?']})['questions'], ['Which page?'])
        result = self.parse(draft())
        self.assertEqual((result['kind'], result['scope'], result['complexity']), ('draft_task', ['src'], 2))

    def test_json_in_code_fence_or_with_surrounding_text_is_parsed(self):
        body = json.dumps({'kind': 'reply', 'text': 'hi', 'files': []})
        self.assertEqual(self.parse('```json\n' + body + '\n```')['text'], 'hi')
        self.assertEqual(self.parse('Sure! Here you go: ' + body + ' Hope that helps.')['text'], 'hi')

    def test_unknown_kind_missing_field_and_wrong_types_raise(self):
        for bad in ('not json', '[]', '{"kind":"other"}', '{"kind":"reply"}', '{"kind":"reply","text":5,"files":[]}',
                    json.dumps(draft(title=7)), json.dumps(draft(extra='x')), json.dumps({'kind': 'reply', 'text': '', 'files': []})):
            with self.assertRaises(ChatOutputError, msg=bad):
                self.parse(bad)

    def test_clarify_needs_one_to_three_questions(self):
        for count in (0, 4):
            with self.assertRaises(ChatOutputError):
                self.parse({'kind': 'clarify', 'questions': ['q'] * count})
        self.assertEqual(len(self.parse({'kind': 'clarify', 'questions': ['q'] * 3})['questions']), 3)

    def test_draft_scope_outside_context_scope_raises(self):
        for scope in (['other'], ['src', 'tests'], []):
            with self.assertRaises(ChatOutputError, msg=str(scope)):
                self.parse(draft(scope=scope))

    def test_draft_scope_with_generated_dependency_or_sensitive_path_raises(self):
        for scope in (['src/node_modules/x.js'], ['src/.env'], ['../x'], ['C:/x'], ['src/__pycache__/a.pyc'], ['src/secret_key.py'], ['/etc/passwd']):
            with self.assertRaises(ChatOutputError, msg=str(scope)):
                self.parse(draft(scope=scope))

    def test_draft_limits(self):
        for bad in (draft(scope=['src'] * 21), draft(accept=['x'] * 21), draft(complexity=0), draft(complexity=6),
                    draft(complexity=True), draft(complexity='2'), draft(title=''), draft(prompt=''), draft(provider='nope!')):
            with self.assertRaises(ChatOutputError, msg=str(bad)):
                self.parse(bad)
        self.assertEqual(self.parse(draft(scope=['src'] * 20, accept=['x'] * 20, complexity=5))['complexity'], 5)

    def test_draft_related_task_id_must_be_a_task_id_or_null(self):
        self.assertEqual(self.parse(draft(related_task_id='a1b2c3d4e5f6'))['related_task_id'], 'a1b2c3d4e5f6')
        with self.assertRaises(ChatOutputError):
            self.parse(draft(related_task_id='../../etc'))

    def test_flat_provider_shape_keeps_only_the_fields_of_its_kind(self):
        flat = {'kind': 'reply', 'text': 'hello', 'files': [], 'questions': [], 'title': '', 'prompt': '', 'scope': [], 'accept': [],
                'complexity': 0, 'provider': '', 'related_task_id': None}
        self.assertEqual(self.parse(flat), {'kind': 'reply', 'text': 'hello', 'files': []})
        self.assertEqual(self.parse({**flat, 'kind': 'clarify', 'text': '', 'questions': ['Which?']}), {'kind': 'clarify', 'questions': ['Which?']})
        result = self.parse({**flat, 'kind': 'draft_task', 'text': 'ignored', 'title': 'T', 'prompt': 'P', 'scope': ['src'], 'accept': ['a'],
                             'complexity': 3, 'related_task_id': ''})
        self.assertEqual((result['kind'], result['provider'], result['related_task_id'], result['complexity']), ('draft_task', 'auto', None, 3))
        with self.assertRaises(ChatOutputError):
            self.parse({**flat, 'kind': 'draft_task', 'title': 'T', 'prompt': 'P', 'scope': ['elsewhere'], 'accept': ['a'], 'complexity': 3})

    def test_reply_files_outside_scope_are_dropped_not_fatal(self):
        result = self.parse({'kind': 'reply', 'text': 'x', 'files': ['src/a.py', 'secrets/.env', '../x', 'other/b.py']})
        self.assertEqual(result['files'], ['src/a.py'])


class SettingsTests(unittest.TestCase):
    def center(self, chat=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        center = Center(_Path(tmp.name) / 'state')
        if chat is None:
            center.config.pop('chat', None)
        else:
            center.config['chat'] = chat
        return center

    def test_defaults(self):
        settings = chat_settings(self.center())
        self.assertEqual(settings, {'providers': ['claude'], 'timeout_seconds': 90, 'history_turns': 10,
                                    'max_message_chars': 4000, 'context_bytes': 65536, 'adapter': 'live'})

    def test_override_and_ignore_bad_values(self):
        settings = chat_settings(self.center({'providers': ['claude'], 'adapter': 'mock', 'timeout_seconds': 'soon', 'history_turns': -3}))
        self.assertEqual((settings['providers'], settings['adapter'], settings['timeout_seconds'], settings['history_turns']), (['claude'], 'mock', 90, 10))

    def test_unknown_providers_are_dropped(self):
        self.assertEqual(chat_settings(self.center({'providers': ['claude', 'bogus']}))['providers'], ['claude'])

    def test_repo_config_enables_claude_only_until_codex_isolation_is_proven(self):
        config = json.loads((_Path(center_chat.__file__).resolve().parents[1] / 'center.config.json').read_text(encoding='utf-8'))
        self.assertEqual(config['chat']['providers'], ['claude'])
        self.assertEqual(config['chat']['adapter'], 'live')


if __name__ == '__main__':
    unittest.main()
