"""The installer can wire a project for Claude Code, Google Antigravity or both; the connector and registration are the same."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install_project  # noqa: E402


def repo():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    return tmp, root


class InstallIdeTests(unittest.TestCase):
    def install(self, ide=None, **kwargs):
        tmp, root = repo()
        self.addCleanup(tmp.cleanup)
        extra = {} if ide is None else {'ide': ide}
        result = install_project.install(root, 'demo', register=False, **extra, **kwargs)
        return root, result

    def test_the_default_is_antigravity(self):
        root, result = self.install()
        self.assertEqual(result['ide'], 'antigravity')
        rule = (root / '.agents/rules/ai-command-center.md').read_text(encoding='utf-8')
        self.assertIn('trigger: always_on', rule)
        self.assertIn('center.connection.json', rule)
        self.assertTrue((root / 'connector.py').exists())
        self.assertFalse((root / 'CLAUDE.local.md').exists())
        self.assertFalse((root / '.claude').exists())

    def test_claude_can_be_installed_explicitly(self):
        root, result = self.install('claude')
        self.assertEqual(result['ide'], 'claude')
        self.assertTrue((root / 'CLAUDE.local.md').exists())
        self.assertTrue((root / '.claude/hooks/center_guard.py').exists())
        self.assertFalse((root / '.agents').exists())

    def test_antigravity_gets_the_rule_and_skill_but_no_claude_files(self):
        root, result = self.install('antigravity')
        self.assertEqual(result['ide'], 'antigravity')
        rule = (root / '.agents/rules/ai-command-center.md').read_text(encoding='utf-8')
        self.assertIn('trigger: always_on', rule)
        self.assertIn('center.connection.json', rule)
        self.assertIn('name: ai-command-center', (root / '.agents/skills/ai-command-center/SKILL.md').read_text(encoding='utf-8'))
        self.assertTrue((root / 'connector.py').exists())
        self.assertFalse((root / 'CLAUDE.local.md').exists())
        self.assertFalse((root / '.claude').exists())

    def test_both_installs_each_ide(self):
        root, _ = self.install('both')
        self.assertTrue((root / 'CLAUDE.local.md').exists())
        self.assertTrue((root / '.agents/rules/ai-command-center.md').exists())

    def test_our_antigravity_files_are_git_excluded_so_the_checkout_stays_clean(self):
        root, _ = self.install('antigravity')
        status = subprocess.run(['git', 'status', '--porcelain', '-uall'], cwd=root, capture_output=True, text=True, check=True).stdout
        self.assertNotIn('.agents', status)
        self.assertNotIn('connector.py', status)

    def test_an_unknown_ide_is_refused(self):
        tmp, root = repo()
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(ValueError):
            install_project.install(root, 'demo', register=False, ide='vim')

    def test_the_antigravity_templates_do_not_use_the_old_handoff_protocol(self):
        base = Path(install_project.TEMPLATE) / '.agents'
        for path in base.rglob('*.md'):
            text = path.read_text(encoding='utf-8')
            for old in ('worker-start', 'heartbeat', 'claim TASK_ID'):
                self.assertNotIn(old, text, f'{path.name} still mentions {old}')


if __name__ == '__main__':
    unittest.main()
