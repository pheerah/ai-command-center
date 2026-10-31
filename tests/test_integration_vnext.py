"""Real Git/checkpoint overlay tests; approval is a synthetic fixture only."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest

from center_integration import compose_dependencies, verify_dependencies
from center_workspace import checkpoint, git, patch

ROOT = Path(__file__).resolve().parents[1]


class FixtureStore:
    def __init__(self, state):
        self.state, self.tasks = state, {}
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE authorship(task_id TEXT, provider TEXT)')

    def task(self, task_id):
        return dict(self.tasks[task_id])

    @contextmanager
    def connection(self):
        yield self.con


class FixtureCenter:
    def __init__(self, state):
        self.store = FixtureStore(state)
        self.config = {'max_checkpoint_bytes': 1024 * 1024}

    def validate_evidence(self, task_id):
        task = self.store.task(task_id)
        current = patch(task['worktree'], task['base_rev'], json.loads(task['scope_json']))
        if current['patch_hash'] != task['patch_hash']:
            raise ValueError('Fixture approved patch drifted')


class DependencyOverlayTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='center_dependency_tests_')).resolve()
        self.addCleanup(self.cleanup)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(self.repo)], check=True)
        shutil.copytree(ROOT / '.git/objects', self.repo / '.git/objects', dirs_exist_ok=True)
        self.base = git(ROOT, 'rev-parse', 'HEAD')
        git(self.repo, 'checkout', '--quiet', '--detach', self.base)
        self.center = FixtureCenter(self.root / 'state')
        self.addCleanup(self.center.store.con.close)

    def cleanup(self):
        if self.root.parent != Path(tempfile.gettempdir()).resolve() or not self.root.name.startswith('center_dependency_tests_'):
            raise ValueError('Unsafe fixture cleanup')
        def retry(func, name, error):
            if not isinstance(error, PermissionError):
                raise error
            Path(name).chmod(stat.S_IWRITE)
            func(name)
        shutil.rmtree('\\\\?\\' + str(self.root) if __import__('os').name == 'nt' else self.root, onexc=retry)

    def checkout(self, name):
        destination = self.root / name
        git(self.repo, 'worktree', 'add', '--quiet', '--detach', str(destination), self.base)
        return destination

    def task(self, name, dependencies=None, policy='overlay', scope=None):
        return {'id': name, 'project_id': 'fixture', 'mode': 'live', 'base_rev': self.base,
                'dependencies_json': json.dumps(dependencies or []), 'config_json': json.dumps({'dependency_policy': policy}),
                'scope_json': json.dumps(scope or ['src', 'server.js'])}

    def approved_fixture(self, name, changes, dependencies=None, provider='claude'):
        root = self.checkout(name)
        task = self.task(name, dependencies)
        for filename, content in changes.items():
            path = root / filename
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        data = patch(root, self.base, json.loads(task['scope_json']))
        saved = self.center.store.state / 'checkpoints' / name / '1'
        checkpoint(root, data, saved)
        task.update({'worktree': str(root), 'checkpoint': str(saved), 'status': 'approved', 'patch_hash': data['patch_hash']})
        self.center.store.tasks[name] = task
        self.center.store.con.execute('INSERT INTO authorship VALUES(?,?)', (name, provider))
        return task

    def test_consumer_receives_tracked_and_new_approved_code(self):
        original = (self.repo / 'server.js').read_bytes()
        self.approved_fixture('a', {'src/api.py': b'VALUE = 42\n', 'server.js': original + b'\n// dependency fixture\n'})
        task, target = self.task('b', ['a']), self.checkout('b')
        result = compose_dependencies(self.center, task, target)
        self.assertEqual((target / 'src/api.py').read_bytes(), b'VALUE = 42\n')
        self.assertIn(b'// dependency fixture', (target / 'server.js').read_bytes())
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(result['inherited_providers'], ['claude'])
        self.assertEqual(verify_dependencies(self.center, task, result['dependencies']), result['dependencies'])

    def test_chain_replays_complete_descendant_without_double_applying_ancestor(self):
        self.approved_fixture('a', {'src/api.py': b'VALUE = 1\n'})
        self.approved_fixture('b', {'src/api.py': b'VALUE = 2\n', 'src/b.py': b'from api import VALUE\n'}, ['a'], 'codex')
        result = compose_dependencies(self.center, self.task('c', ['b']), self.checkout('c'))
        self.assertEqual((self.root / 'c/src/api.py').read_bytes(), b'VALUE = 2\n')
        self.assertEqual([d['task_id'] for d in result['dependencies']], ['a', 'b'])
        self.assertEqual(result['inherited_providers'], ['claude', 'codex'])

    def test_descendant_reverting_new_ancestor_file_does_not_resurrect_it(self):
        self.approved_fixture('a', {'src/removed.py': b'old\n'})
        self.approved_fixture('b', {'src/replacement.py': b'new\n'}, ['a'])
        target = self.checkout('c')
        compose_dependencies(self.center, self.task('c', ['b']), target)
        self.assertFalse((target / 'src/removed.py').exists())
        self.assertTrue((target / 'src/replacement.py').exists())

    def test_unrelated_conflicts_fail_before_any_destination_change(self):
        self.approved_fixture('a', {'src/api.py': b'one\n'})
        self.approved_fixture('b', {'src/api.py': b'two\n'})
        target = self.checkout('c')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            compose_dependencies(self.center, self.task('c', ['a', 'b']), target)
        self.assertEqual(git(target, 'status', '--porcelain'), '')

    def test_approved_drift_or_checkpoint_corruption_is_rejected(self):
        dependency = self.approved_fixture('a', {'src/api.py': b'one\n'})
        task, target = self.task('b', ['a']), self.checkout('b')
        (Path(dependency['worktree']) / 'src/api.py').write_bytes(b'unreviewed\n')
        with self.assertRaisesRegex(ValueError, 'drifted'):
            compose_dependencies(self.center, task, target)
        (Path(dependency['worktree']) / 'src/api.py').write_bytes(b'one\n')
        (Path(dependency['checkpoint']) / 'tracked.patch').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'identity'):
            compose_dependencies(self.center, task, target)
        self.assertEqual(git(target, 'status', '--porcelain'), '')

    def test_overlay_requires_explicit_policy_and_scope(self):
        self.approved_fixture('a', {'src/api.py': b'one\n'})
        target = self.checkout('b')
        result = compose_dependencies(self.center, self.task('b', ['a'], policy='ordering'), target)
        self.assertEqual(result['dependencies'], [])
        self.assertFalse((target / 'src/api.py').exists())
        with self.assertRaisesRegex(ValueError, 'scope'):
            compose_dependencies(self.center, self.task('b', ['a'], scope=['src/other.py']), target)

    def test_stale_dependency_identity_and_cycles_fail_closed(self):
        self.approved_fixture('a', {'src/api.py': b'one\n'})
        task, target = self.task('b', ['a']), self.checkout('b')
        result = compose_dependencies(self.center, task, target)
        wrong = [{**result['dependencies'][0], 'patch_hash': 'stale'}]
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            verify_dependencies(self.center, task, wrong)
        self.center.store.tasks['a']['dependencies_json'] = '["a"]'
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            verify_dependencies(self.center, task, result['dependencies'])
