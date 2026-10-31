"""Project-facing API: tokens, validation, project isolation and path-free responses. No model is called."""
import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import center_api
from center_runtime import Center

GIT = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']


def make_repo(parent, name):
    repo = Path(parent) / name
    (repo / 'src').mkdir(parents=True)
    (repo / 'src' / 'a.py').write_text('x = 1\n', encoding='utf-8')
    (repo / 'project.config.json').write_text(json.dumps({
        'project_id': name, 'name': name, 'allowed_providers': ['claude', 'codex'], 'quality_gates': [['python', '-c', 'pass']],
        'prepare_commands': [], 'approval_policy': 'human_required', 'context_scope': ['src'], 'base_revision': 'HEAD', 'auto_commit': False}), encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run([*GIT, 'add', '-A'], cwd=repo, check=True)
    subprocess.run([*GIT, 'commit', '-qm', 'init'], cwd=repo, check=True)
    return repo


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.center = Center(Path(self.tmp.name) / 'state')
        self.repos = {}
        for name in ('alpha', 'beta'):
            self.repos[name] = make_repo(self.tmp.name, name)
            self.center.register(name, self.repos[name])
        self.state = self.center.store.state

    def call(self, project, op, task_id=None, body=None):
        return center_api.run(self.center, project, {'op': op, 'task_id': task_id, 'body': body})

    def submit(self, project='alpha', **overrides):
        body = {'title': 'Add b', 'prompt': 'Create src/b.py', 'scope': ['src'], 'accept': ['b exists'], 'complexity': 1, **overrides}
        return self.call(project, 'submit', body=body)

    def test_tokens_store_only_a_hash_and_bind_to_one_project(self):
        token = center_api.create_token(self.state, 'alpha', 'test')
        self.assertNotIn(token, (self.state / center_api.TOKEN_FILE).read_text(encoding='utf-8'))
        self.assertEqual(center_api.project_for_token(self.state, token), 'alpha')
        self.assertIsNone(center_api.project_for_token(self.state, token + 'x'))
        self.assertIsNone(center_api.project_for_token(self.state, ''))
        listing = center_api.list_tokens(self.state)
        self.assertEqual([t['project_id'] for t in listing], ['alpha'])
        self.assertNotIn('token', json.dumps(listing))
        center_api.revoke_token(self.state, listing[0]['id'])
        self.assertIsNone(center_api.project_for_token(self.state, token))

    def test_submit_validates_input_without_touching_the_center(self):
        for bad in ({'title': ''}, {'prompt': 'x' * 12001}, {'scope': []}, {'scope': ['../etc']}, {'accept': 'not a list'},
                    {'complexity': 9}, {'complexity': True}, {'provider': 'unknown'}, {'depends_on': ['not-an-id']}):
            answer = self.submit(**bad)
            self.assertFalse(answer['ok'], bad)
            self.assertIn(answer['status'], (400, 409), bad)
        self.assertEqual(self.call('alpha', 'list')['data']['tasks'], [])

    def test_responses_never_contain_center_or_project_paths(self):
        task_id = self.submit()['data']['task']['id']
        for answer in (self.call('alpha', 'get', task_id), self.call('alpha', 'list'), self.submit(title='Another')):
            text = json.dumps(answer)
            for forbidden in (str(self.state), str(self.repos['alpha']), 'worktree', 'run_dir', 'config_json', 'workspace'):
                self.assertNotIn(forbidden, text)

    def test_a_project_cannot_see_or_cancel_another_projects_task(self):
        task_id = self.submit('alpha')['data']['task']['id']
        for op in ('get', 'cancel', 'patch'):
            answer = self.call('beta', op, task_id)
            self.assertEqual((answer['ok'], answer['status']), (False, 404), op)
        self.assertEqual(self.call('beta', 'get', 'ffffffffffff')['status'], 404)   # indistinguishable from a foreign id
        self.assertEqual(self.call('beta', 'list')['data']['tasks'], [])
        self.assertEqual(len(self.call('alpha', 'list')['data']['tasks']), 1)

    def test_malformed_task_ids_are_rejected(self):
        for bad in ('../../x', 'ZZZ', '12345678901234567890', None):
            self.assertFalse(self.call('alpha', 'get', bad)['ok'])

    def test_cancel_and_unknown_operation(self):
        task_id = self.submit()['data']['task']['id']
        self.assertEqual(self.call('alpha', 'cancel', task_id)['data']['task']['status'], 'cancelled')
        self.assertEqual(self.call('alpha', 'nope')['status'], 400)

    def test_patch_is_withheld_until_review_then_exported_with_integrity(self):
        task_id = self.submit()['data']['task']['id']
        self.assertEqual(self.call('alpha', 'patch', task_id)['status'], 400)
        saved = self.state / 'checkpoints' / task_id / '1-x'
        (saved / 'files' / 'src').mkdir(parents=True)
        content = b'y = 2\n'
        (saved / 'files' / 'src' / 'b.py').write_bytes(content)
        (saved / 'tracked.patch').write_text('', encoding='utf-8')
        digest = hashlib.sha256(content).hexdigest()
        manifest = [{'path': 'src/b.py', 'untracked': True, 'sha256': digest, 'size': len(content)}]
        (saved / 'manifest.json').write_text(json.dumps({'base_rev': 'x', 'manifest': manifest}), encoding='utf-8')
        identity = hashlib.sha256(json.dumps({'base_rev': 'x', 'manifest': manifest}, sort_keys=True, separators=(',', ':')).encode() + bytes([0])).hexdigest()
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET status='ready_for_human_approval',checkpoint=?,patch_hash=? WHERE id=?", (str(saved), identity, task_id))
        exported = self.call('alpha', 'patch', task_id)['data']
        self.assertFalse(exported['approved'])
        # The approval phrase is derived from patch_hash, so neither the hash nor its prefix may ever be handed to a project.
        self.assertNotIn(identity[:12], json.dumps(exported) + json.dumps(self.call('alpha', 'get', task_id)))
        self.assertNotIn('patch_hash', json.dumps(exported))
        self.assertEqual(base64.b64decode(exported['files'][0]['content_base64']), content)
        self.assertNotIn(str(self.state), json.dumps(exported))
        (saved / 'files' / 'src' / 'b.py').write_bytes(b'tampered' + bytes([10]))
        self.assertEqual(self.call('alpha', 'patch', task_id)['status'], 400)
        (saved / 'files' / 'src' / 'b.py').write_bytes(content)
        (saved / 'tracked.patch').write_text('diff --git a/src/a.py b/src/a.py' + chr(10), encoding='utf-8')  # changed after review
        self.assertIn('does not match the reviewed patch', self.call('alpha', 'patch', task_id)['error'])

    def test_a_tracked_patch_that_is_not_valid_utf8_still_exports(self):
        task_id = self.submit()['data']['task']['id']
        saved = self.state / 'checkpoints' / task_id / '1-z'
        saved.mkdir(parents=True)
        tracked = bytes([0xFF, 0xFE, 10]) + b'binary-ish patch'
        (saved / 'tracked.patch').write_bytes(tracked)
        (saved / 'manifest.json').write_text(json.dumps({'base_rev': 'x', 'manifest': []}), encoding='utf-8')
        identity = hashlib.sha256(json.dumps({'base_rev': 'x', 'manifest': []}, sort_keys=True, separators=(',', ':')).encode() + bytes([0]) + tracked).hexdigest()
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET status='ready_for_human_approval',checkpoint=?,patch_hash=? WHERE id=?", (str(saved), identity, task_id))
        answer = self.call('alpha', 'patch', task_id)
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(base64.b64decode(answer['data']['tracked_patch_base64']), tracked)

    def test_unsafe_manifest_paths_are_never_exported(self):
        task_id = self.submit()['data']['task']['id']
        saved = self.state / 'checkpoints' / task_id / '1-y'
        saved.mkdir(parents=True)
        (saved / 'tracked.patch').write_text('', encoding='utf-8')
        for bad in ('../escape.py', '.git/hooks/pre-commit', 'C:/x.py'):
            manifest = [{'path': bad, 'untracked': True, 'sha256': 'a' * 64, 'size': 1}]
            (saved / 'manifest.json').write_text(json.dumps({'base_rev': 'x', 'manifest': manifest}), encoding='utf-8')
            identity = hashlib.sha256(json.dumps({'base_rev': 'x', 'manifest': manifest}, sort_keys=True, separators=(',', ':')).encode() + bytes([0])).hexdigest()
            with self.center.store.connection(write=True) as con:
                con.execute("UPDATE tasks SET status='ready_for_human_approval',checkpoint=?,patch_hash=? WHERE id=?", (str(saved), identity, task_id))
            answer = self.call('alpha', 'patch', task_id)
            self.assertFalse(answer['ok'], bad)

    def test_retried_submit_with_the_same_request_id_returns_the_same_task(self):
        first = self.submit(request_id='retry-0000001')['data']
        again = self.submit(request_id='retry-0000001')['data']
        self.assertEqual(first['task']['id'], again['task']['id'])
        self.assertTrue(again['duplicate_request'])
        self.assertNotEqual(self.submit(request_id='retry-0000002')['data']['task']['id'], first['task']['id'])
        self.assertFalse(self.submit(request_id='bad id!')['ok'])
        # The same id from another project is a different request, not a leak.
        self.assertNotEqual(self.submit('beta', request_id='retry-0000001')['data']['task']['id'], first['task']['id'])

    def test_a_project_cannot_flood_the_queue(self):
        for index in range(center_api.MAX_ACTIVE_TASKS):
            self.assertTrue(self.submit(title=f'Task {index}')['ok'])
        flooded = self.submit(title='One too many')
        self.assertFalse(flooded['ok'])
        self.assertIn('Too many active tasks', flooded['error'])
        self.assertTrue(self.submit('beta')['ok'])  # other projects are unaffected

    def test_free_form_text_is_scrubbed_of_paths(self):
        cleaned = center_api.scrub({'error': 'failed in C:\\Users\\spc\\Center\\x.py and /home/me/secret/y', 'items': ['ok', 'D:/state/runs/1']})
        self.assertNotIn('Users', json.dumps(cleaned))
        self.assertNotIn('/home/me', json.dumps(cleaned))
        self.assertNotIn('state/runs', json.dumps(cleaned))
        self.assertEqual(cleaned['items'][0], 'ok')

    def test_concurrent_token_changes_never_lose_a_revocation(self):
        import threading
        tokens = [center_api.create_token(self.state, 'alpha', f't{i}') for i in range(6)]
        ids = [t['id'] for t in center_api.list_tokens(self.state)]
        threads = [threading.Thread(target=center_api.revoke_token, args=(self.state, i)) for i in ids[:3]]
        threads += [threading.Thread(target=center_api.create_token, args=(self.state, 'beta', 'extra')) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        listing = center_api.list_tokens(self.state)
        self.assertEqual(sum(1 for t in listing if t['revoked']), 3)
        self.assertEqual(len(listing), 9)
        self.assertTrue(all(center_api.project_for_token(self.state, t) == 'alpha' for t in tokens[3:]))

    def test_health_reports_provider_availability_only(self):
        health = self.call('alpha', 'health')['data']
        self.assertEqual(health['project'], 'alpha')
        self.assertEqual(set(health['providers']), {'codex', 'claude', 'google'})
        self.assertNotIn('model', json.dumps(health))


if __name__ == '__main__':
    unittest.main()
