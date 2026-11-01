"""Chat operations of the project API: ask, history and confirm-to-submit. A fake provider answers; no model is called."""
import json
import sys as _sys
import tempfile
import threading
import unittest
from pathlib import Path as _Path
from unittest.mock import patch

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_api
import center_chat
import center_chat_store as chat_store
from center_runtime import Center
from test_api_vnext import make_repo

DRAFT = {'kind': 'draft_task', 'title': 'Add b', 'prompt': 'Create src/b.py', 'scope': ['src'], 'accept': ['b exists'],
         'complexity': 1, 'provider': 'auto', 'related_task_id': None}


def fake_runner(provider, prompt, timeout, workdir):
    if 'new message from the user\nwhy' in prompt:
        return json.dumps({'kind': 'reply', 'text': 'Because.', 'files': []})
    return json.dumps(DRAFT)


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.center = Center(_Path(self.tmp.name) / 'state')
        for name in ('alpha', 'beta'):
            self.center.register(name, make_repo(self.tmp.name, name))
        self.center.config['chat'] = {'providers': ['codex'], 'adapter': 'live'}
        self.center.quota_reader = lambda: {}
        patcher = patch.object(center_chat, 'RUNNER', fake_runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.turn = 0

    def call(self, project, op, body=None):
        return center_api.run(self.center, project, {'op': op, 'body': body})

    def chat(self, message='please add src/b.py', project='alpha'):
        self.turn += 1
        return self.call(project, 'chat', {'message': message, 'client_turn_id': f'turn-{self.turn:08d}'})

    def confirm(self, message_id, edits=None, project='alpha'):
        body = {'message_id': message_id}
        if edits is not None:
            body['edits'] = edits
        return self.call(project, 'chat_confirm', body)

    def tasks(self):
        with self.center.store.connection() as con:
            return [dict(r) for r in con.execute('SELECT id,title,prompt,scope_json FROM tasks')]

    def test_chat_op_returns_the_row_and_history_lists_it(self):
        answer = self.chat('why')
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['data']['kind'], 'reply')
        history = self.call('alpha', 'chat_history')
        self.assertTrue(history['ok'])
        self.assertEqual([m['role'] for m in history['data']['messages']], ['user', 'secretary'])
        self.assertEqual(self.call('beta', 'chat_history')['data']['messages'], [])

    def test_chat_requires_message_and_turn_id(self):
        for body in (None, {}, {'message': 'x'}, {'client_turn_id': 'turn-00000001'}, {'message': 5, 'client_turn_id': 'turn-00000001'}):
            self.assertFalse(self.call('alpha', 'chat', body)['ok'], body)

    def test_confirm_creates_exactly_one_task_and_links_the_message(self):
        draft = self.chat()['data']
        self.assertEqual(self.tasks(), [])
        answer = self.confirm(draft['id'])
        self.assertTrue(answer['ok'], answer)
        task_id = answer['data']['task']['id']
        self.assertEqual(len(self.tasks()), 1)
        self.assertEqual(chat_store.message(self.center.store, 'alpha', draft['id'])['task_id'], task_id)
        with self.center.store.connection() as con:
            key = f"api_req:alpha:chat-{draft['id']:08d}"
            self.assertEqual(con.execute('SELECT value FROM center_meta WHERE key=?', (key,)).fetchone()[0], task_id)

    def test_confirm_twice_returns_the_same_task(self):
        draft = self.chat()['data']
        first = self.confirm(draft['id'])['data']
        again = self.confirm(draft['id'])
        self.assertTrue(again['ok'], again)
        self.assertEqual(first['task']['id'], again['data']['task']['id'])
        self.assertTrue(again['data']['duplicate_request'])
        self.assertEqual(len(self.tasks()), 1)

    def test_confirm_from_four_threads_creates_one_task(self):
        draft = self.chat()['data']
        barrier = threading.Barrier(4)
        answers = []

        def go():
            barrier.wait()
            answers.append(self.confirm(draft['id']))

        threads = [threading.Thread(target=go) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertTrue(all(a['ok'] for a in answers), answers)
        self.assertEqual(len({a['data']['task']['id'] for a in answers}), 1)
        self.assertEqual(len(self.tasks()), 1)

    def test_confirm_a_draft_of_another_project_is_rejected(self):
        draft = self.chat(project='alpha')['data']
        answer = self.confirm(draft['id'], project='beta')
        self.assertFalse(answer['ok'])
        self.assertEqual(self.tasks(), [])

    def test_confirm_a_message_that_is_not_a_draft_is_rejected(self):
        reply = self.chat('why')['data']
        user_row = chat_store.history(self.center.store, 'alpha')[0]
        for message_id in (reply['id'], user_row['id'], 99999, True, '1', None):
            self.assertFalse(self.confirm(message_id)['ok'], message_id)
        self.assertEqual(self.tasks(), [])

    def test_edits_change_title_and_scope_but_unknown_edit_keys_are_rejected(self):
        draft = self.chat()['data']
        self.assertFalse(self.confirm(draft['id'], {'provider': 'claude'})['ok'])
        self.assertFalse(self.confirm(draft['id'], {'request_id': 'sneaky-0001'})['ok'])
        self.assertEqual(self.tasks(), [])
        answer = self.confirm(draft['id'], {'title': 'Edited title', 'accept': ['edited']})
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(self.tasks()[0]['title'], 'Edited title')

    def test_edited_scope_is_still_checked_by_submit_and_the_draft_stays_confirmable(self):
        draft = self.chat()['data']
        bad = self.confirm(draft['id'], {'scope': ['outside']})
        self.assertFalse(bad['ok'])
        self.assertEqual(self.tasks(), [])
        self.assertIsNone(chat_store.message(self.center.store, 'alpha', draft['id'])['task_id'])
        self.assertTrue(self.confirm(draft['id'])['ok'])
        self.assertEqual(len(self.tasks()), 1)

    def test_the_active_task_limit_still_applies(self):
        for index in range(center_api.MAX_ACTIVE_TASKS):
            self.assertTrue(center_api.run(self.center, 'alpha', {'op': 'submit', 'body': {
                'title': f'Task {index}', 'prompt': 'Create src/b.py', 'scope': ['src'], 'accept': ['x'], 'complexity': 1}})['ok'])
        draft = self.chat()['data']
        answer = self.confirm(draft['id'])
        self.assertFalse(answer['ok'])
        self.assertIn('Too many active tasks', answer['error'])
        self.assertIsNone(chat_store.message(self.center.store, 'alpha', draft['id'])['task_id'])

    def test_related_task_is_noted_in_the_prompt_not_made_a_dependency(self):
        related = self.chat('please add src/b.py')['data']
        first = self.confirm(related['id'])['data']['task']['id']
        with patch.object(center_chat, 'RUNNER', lambda *a: json.dumps({**DRAFT, 'title': 'Follow up', 'related_task_id': first})):
            follow = self.chat('fix the follow up')['data']
        task = self.confirm(follow['id'])['data']['task']
        stored = [t for t in self.tasks() if t['id'] == task['id']][0]
        self.assertIn(first, stored['prompt'])


if __name__ == '__main__':
    unittest.main()
