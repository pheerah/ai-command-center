"""Static guarantee: no Center code path can run commit, push, merge, deploy-style git actions.

This reads the source (it cannot prove a dynamic string is safe), so it also pins the
config guard that refuses auto_commit and any approval policy other than human_required.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from center_runtime import Center, load_config

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'commit', 'commit-tree', 'push', 'merge', 'rebase', 'cherry-pick', 'revert', 'tag', 'am', 'pull', 'fetch', 'remote', 'send-pack'}
SOURCES = sorted([*ROOT.glob('center_*.py'), ROOT / 'smart_router.py', ROOT / 'scripts' / 'install_project.py', ROOT / 'connector-template' / 'connector.py'])


def git_subcommands(path):
    """Every string constant that follows 'git' in a subprocess list, or is passed to the git() helper."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == 'git':
            found += [(e.value, node.lineno) for e in node.elts[1:] if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
            if name == 'git':
                found += [(a.value, node.lineno) for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return found


class NoGitActionTests(unittest.TestCase):
    def test_sources_are_found(self):
        self.assertGreaterEqual(len(SOURCES), 8)

    def test_no_forbidden_git_subcommand_appears_in_any_source(self):
        offenders = [f'{path.name}:{line} git {word}' for path in SOURCES for word, line in git_subcommands(path) if word in FORBIDDEN]
        self.assertEqual(offenders, [])

    def test_the_detector_would_catch_a_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / 'sample.py'
            sample.write_text("import subprocess\nsubprocess.run(['git', 'commit', '-m', 'x'])\ngit(root, 'push')\n", encoding='utf-8')
            self.assertLessEqual({'commit', 'push'}, {word for word, _ in git_subcommands(sample)})

    def test_no_shell_deploy_or_publish_commands_are_spawned(self):
        text = ' '.join(path.read_text(encoding='utf-8') for path in SOURCES)
        for needle in ('npm publish', 'git push', 'git commit', 'gh pr', 'vercel deploy', 'kubectl apply'):
            self.assertNotIn(needle, text.replace("'git', 'commit'", ''), needle)

    def test_config_refuses_auto_commit_or_non_human_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            (repo / 'src').mkdir(parents=True)
            (repo / 'src' / 'a.py').write_text('x = 1' + chr(10), encoding='utf-8')
            base = {'project_id': 'repo', 'name': 'repo', 'allowed_providers': ['codex'], 'quality_gates': [['python', '-c', 'pass']], 'prepare_commands': [],
                    'context_scope': ['src'], 'base_revision': 'HEAD'}
            import subprocess
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '-A'], cwd=repo, check=True)
            subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init'], cwd=repo, check=True)
            center = Center(Path(tmp) / 'state')
            for override in ({'auto_commit': True, 'approval_policy': 'human_required'}, {'auto_commit': False, 'approval_policy': 'automatic'}):
                (repo / 'project.config.json').write_text(json.dumps({**base, **override}), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'human_required'):
                    center.register('repo', repo, confirm_config_change=True)
        self.assertTrue(load_config())


if __name__ == '__main__':
    unittest.main()
