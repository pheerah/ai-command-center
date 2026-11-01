"""Codex pre-reads every in-scope file into its prompt, so an oversized scope is routed to a provider that reads files itself
instead of ending as blocked/needs_narrower_scope (found in the first real run on Horoscope)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_smart_router as fixtures
from center_context import source_bytes


def repo_with(files):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, size in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * size)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '-A', '-f'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init'], cwd=root, check=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    return tmp, root, head


class SourceBytesTests(unittest.TestCase):
    def test_counts_tracked_files_under_the_scope_only(self):
        tmp, root, head = repo_with({'tests/a.ts': 100, 'tests/sub/b.ts': 50, 'src/c.ts': 999})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(source_bytes(root, head, ['tests']), 150)
        self.assertEqual(source_bytes(root, head, ['tests', 'src/c.ts']), 1149)

    def test_skips_what_the_adapter_never_reads(self):
        tmp, root, head = repo_with({'tests/a.ts': 10, 'tests/node_modules/x.js': 5000, 'tests/coverage/y.js': 5000, 'tests/.env': 5000, 'tests/my_secret.ts': 5000})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(source_bytes(root, head, ['tests']), 10)

    def test_a_read_set_counts_only_the_named_files(self):
        tmp, root, head = repo_with({'tests/a.ts': 100, 'tests/b.ts': 7})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(source_bytes(root, head, ['tests'], ['tests/b.ts']), 7)
        self.assertEqual(source_bytes(root, head, ['tests'], ['tests/missing.ts']), 0)

    def test_an_unknown_revision_raises_so_the_caller_can_treat_the_size_as_unknown(self):
        tmp, root, _ = repo_with({'tests/a.ts': 1})
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(ValueError):
            source_bytes(root, 'deadbeef' * 5, ['tests'])


class RoutingTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup

    def add_sources(self, **files):
        """Commit files under src/ in project-a so the task's base revision really contains them."""
        for name, size in files.items():
            path = self.a / 'src' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * size)
        git = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
        subprocess.run([*git, 'add', '-A', '-f'], cwd=self.a, check=True)
        subprocess.run([*git, 'commit', '-qm', 'sources'], cwd=self.a, check=True)

    def live_task(self, **kwargs):
        return self.center.submit('project-a', 'Add scoped file', 'Create the requested sample file', ['src'], ['Tests pass'], mode='live', **kwargs)

    def candidates(self, task, role='implementation'):
        return self.center.candidates(self.center.store.task(task['id']), role)

    def test_an_oversized_scope_leaves_codex_out_but_keeps_the_providers_that_read_files_themselves(self):
        self.add_sources(big=200, small=5)
        self.center.config['max_model_context_bytes'] = 50
        names = self.candidates(self.live_task())
        self.assertNotIn('codex', names)
        self.assertIn('claude', names)

    def test_a_task_pinned_to_codex_falls_back_when_the_scope_cannot_fit(self):
        self.add_sources(big=200)
        self.center.config['max_model_context_bytes'] = 50
        task = self.live_task()
        row = self.center.store.task(task['id'])
        names = self.center.candidates(row, 'implementation', 'codex')
        self.assertNotIn('codex', names)
        self.assertTrue(names)
        self.assertTrue(any(n.startswith('requested_codex_unfit_scope_') for n in self.center.candidate_notes[task['id']]))

    def test_a_task_pinned_to_codex_stays_pinned_when_the_scope_fits(self):
        self.add_sources(small=5)
        self.center.config['max_model_context_bytes'] = 50
        row = self.center.store.task(self.live_task()['id'])
        self.assertEqual(self.center.candidates(row, 'implementation', 'codex'), ['codex'])

    def test_the_skip_is_recorded_for_the_audit_trail(self):
        self.add_sources(big=200)
        self.center.config['max_model_context_bytes'] = 50
        task = self.live_task()
        self.candidates(task)
        self.assertTrue(any(note.startswith('codex_skipped_scope_') for note in self.center.candidate_notes[task['id']]))

    def test_a_scope_that_fits_keeps_codex(self):
        self.add_sources(small=5)
        self.center.config['max_model_context_bytes'] = 50
        self.assertIn('codex', self.candidates(self.live_task()))

    def test_an_explicit_read_set_brings_codex_back_when_the_named_files_fit(self):
        self.add_sources(big=200, small=5)
        self.center.config['max_model_context_bytes'] = 50
        self.assertNotIn('codex', self.candidates(self.live_task()))
        self.assertIn('codex', self.candidates(self.live_task(read_set=['src/small'])))
        self.assertNotIn('codex', self.candidates(self.live_task(read_set=['src/big'])))

    def test_the_guard_can_be_switched_off_in_the_config(self):
        self.add_sources(big=200)
        self.center.config['max_model_context_bytes'] = 50
        self.assertNotIn('codex', self.candidates(self.live_task()))
        self.center.config['codex_context_guard'] = False
        self.assertIn('codex', self.candidates(self.live_task()))

    def test_the_shipped_config_keeps_the_guard_on_and_rejects_a_non_boolean(self):
        import json
        import tempfile
        from center_runtime import load_config
        self.assertIs(load_config()['codex_context_guard'], True)
        base = json.loads((Path(__file__).resolve().parents[1] / 'center.config.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({**base, 'codex_context_guard': 'no'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_mock_tasks_and_reviews_are_never_affected(self):
        self.add_sources(big=200)
        self.center.config['max_model_context_bytes'] = 50
        mock = self.center.submit('project-a', 'Mock', 'Create the requested sample file', ['src'], ['Tests pass'], mode='mock')
        self.assertIn('codex', self.candidates(mock))
        self.assertIn('codex', self.candidates(self.live_task(), role='review'))


if __name__ == '__main__':
    unittest.main()
