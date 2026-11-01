"""Validate the Claude Code discovery format and the project installer without invoking any model."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_project


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        raise ValueError('Missing YAML frontmatter')
    return yaml.safe_load(text.split('---', 2)[1])


class ConnectorDiscoveryTests(unittest.TestCase):
    def test_skill_has_name_and_discovery_description(self):
        metadata = frontmatter(ROOT / 'connector-template/.claude/skills/ai-command-center/SKILL.md')
        self.assertEqual(metadata['name'], 'ai-command-center')
        self.assertTrue(metadata['description'])

    def test_skill_uses_the_http_connector_and_forbids_reading_the_center(self):
        text = (ROOT / 'connector-template/.claude/skills/ai-command-center/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('connector.py submit', text)
        self.assertIn('Never open, read, search or edit anything inside the Center', text)

    def test_rules_forbid_git_actions_and_self_review(self):
        text = (ROOT / 'connector-template/CLAUDE.md').read_text(encoding='utf-8')
        for phrase in ('git commit', 'Never review or approve work yourself', 'Stay out of the Center', 'ready_for_human_approval'):
            self.assertIn(phrase, text)


class InstallProjectTests(unittest.TestCase):
    def make_repo(self, parent):
        repo = Path(parent) / 'sample'
        repo.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
        return repo

    def test_install_is_idempotent_and_preserves_existing_claude_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            (repo / 'CLAUDE.md').write_text('# Existing rules\nKeep me.\n', encoding='utf-8')
            for git_args in (['add', 'CLAUDE.md'], ['commit', '-qm', 'rules']):
                subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *git_args], cwd=repo, check=True)
            install_project.install(repo, 'sample-project', gates=[['python', '-c', 'pass']], register=False, ide='claude')
            install_project.install(repo, 'sample-project', force=True, register=False, ide='claude')
            self.assertEqual((repo / 'CLAUDE.md').read_text(encoding='utf-8'), '# Existing rules\nKeep me.\n')  # the tracked file is never touched
            local = (repo / 'CLAUDE.local.md').read_text(encoding='utf-8')
            self.assertEqual(local.count(install_project.BEGIN), 1)
            self.assertIn('Stay out of the Center', local)
            config = json.loads((repo / 'project.config.json').read_text(encoding='utf-8'))
            self.assertEqual(config['project_id'], 'sample-project')
            self.assertNotIn('center', config)  # the project must not learn where the Center lives
            self.assertTrue((repo / '.claude/skills/ai-command-center/SKILL.md').is_file())
            exclude = (repo / '.git/info/exclude').read_text(encoding='utf-8').splitlines()
            self.assertEqual(exclude.count('/connector.py'), 1)
            self.assertEqual(exclude.count('/project.config.json'), 1)
            self.assertNotIn('/CLAUDE.md', exclude)  # the project's own file is never hidden
            self.assertIn('/CLAUDE.local.md', exclude)
            self.assertIn('/.claude/skills/ai-command-center/', exclude)

    def test_new_claude_md_is_excluded_so_checkout_stays_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            install_project.install(repo, 'clean-project', register=False, ide='claude')
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True, check=True).stdout
            self.assertEqual(status.strip(), '')

    def test_api_install_registers_issues_a_token_and_leaks_no_center_path(self):
        import center_api
        from center_runtime import Center
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            (repo / 'src').mkdir()
            (repo / 'src' / 'a.py').write_text('x = 1' + chr(10), encoding='utf-8')
            for git_args in (['add', '-A'], ['commit', '-qm', 'init']):
                subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *git_args], cwd=repo, check=True)
            state = Path(tmp) / 'state'
            result = install_project.install(repo, 'api-sample', scopes=['src'], gates=[['python', '-c', 'pass']], state=state, ide='claude')
            self.assertTrue(result['registered'])
            connection = json.loads((repo / 'center.connection.json').read_text(encoding='utf-8'))
            self.assertEqual(center_api.project_for_token(Center(state).store.state, connection['token']), 'api-sample')
            for path in repo.rglob('*'):
                if path.is_file() and '.git' not in path.parts:
                    text = path.read_text(encoding='utf-8', errors='replace')
                    self.assertNotIn(str(ROOT), text, path.name)
                    if path.name != 'settings.local.json':  # the deny rule must name the Center path; nothing else may
                        self.assertNotIn(ROOT.as_posix(), text.replace(chr(92), '/'), path.name)
            settings = json.loads((repo / '.claude/settings.local.json').read_text(encoding='utf-8'))
            self.assertTrue(any(rule.startswith('Read(//') for rule in settings['permissions']['deny']))
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True, check=True).stdout
            self.assertEqual(status.strip(), '')

    def test_install_adds_the_edit_guard_hook_and_keeps_it_out_of_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            install_project.install(repo, 'hooked', register=False, ide='claude')
            settings = json.loads((repo / '.claude/settings.local.json').read_text(encoding='utf-8'))
            group = settings['hooks']['PreToolUse'][0]
            self.assertEqual(group['matcher'], install_project.HOOK_MATCHER)
            self.assertIn('center_guard.py', group['hooks'][0]['command'])
            self.assertTrue((repo / '.claude/hooks/center_guard.py').is_file())
            install_project.install(repo, 'hooked', force=True, register=False, ide='claude')
            again = json.loads((repo / '.claude/settings.local.json').read_text(encoding='utf-8'))
            self.assertEqual(len(again['hooks']['PreToolUse']), 1)  # idempotent
            exclude = (repo / '.git/info/exclude').read_text(encoding='utf-8').splitlines()
            for entry in ('/.claude/hooks/', '/.center-direct-edit.json'):
                self.assertIn(entry, exclude)
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True, check=True).stdout
            self.assertEqual(status.strip(), '')

    def test_the_installed_hook_really_blocks_a_direct_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            (repo / 'src').mkdir()
            install_project.install(repo, 'blocked', scopes=['src'], register=False, ide='claude')
            payload = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(repo / 'src' / 'a.py')}, 'cwd': str(repo)})
            run = subprocess.run([sys.executable, str(repo / '.claude/hooks/center_guard.py')], input=payload, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('connector.py', run.stderr)

    def test_prepare_commands_are_written_only_when_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            install_project.install(repo, 'prep', prepare=[['npm', 'ci']], register=False, ide='claude')
            self.assertEqual(json.loads((repo / 'project.config.json').read_text(encoding='utf-8'))['prepare_commands'], [['npm', 'ci']])
            install_project.install(repo, 'prep', force=True, register=False, ide='claude')
            self.assertEqual(json.loads((repo / 'project.config.json').read_text(encoding='utf-8'))['prepare_commands'], [])

    def test_commands_accept_plain_text_and_explain_mangled_powershell_json(self):
        self.assertEqual(install_project.parse_command('npm run lint'), ['npm', 'run', 'lint'])
        self.assertEqual(install_project.parse_command('python -m unittest discover -s "my tests"'), ['python', '-m', 'unittest', 'discover', '-s', 'my tests'])
        self.assertEqual(install_project.parse_command('["npm","ci"]'), ['npm', 'ci'])
        with self.assertRaisesRegex(ValueError, 'plain text'):
            install_project.parse_command('[npm,ci]')  # what PowerShell 5.1 delivers for a JSON array
        for bad in ('', '   ', '[]', '[1]'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                install_project.parse_command(bad)

    def test_a_legacy_block_in_the_tracked_claude_md_is_removed_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            original = '# Rules' + chr(10) + 'Keep me.' + chr(10)
            (repo / 'CLAUDE.md').write_text(original, encoding='utf-8')
            for git_args in (['add', 'CLAUDE.md'], ['commit', '-qm', 'rules']):
                subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *git_args], cwd=repo, check=True)
            (repo / 'CLAUDE.md').write_text(original + chr(10) + install_project.BEGIN + chr(10) + 'old rules' + chr(10) + install_project.END + chr(10), encoding='utf-8')
            self.assertNotEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True).stdout.strip(), '')
            result = install_project.install(repo, 'legacy', register=False, ide='claude')
            self.assertTrue(result['legacy_claude_md_block_removed'])
            self.assertEqual((repo / 'CLAUDE.md').read_text(encoding='utf-8'), original)
            self.assertEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True).stdout.strip(), '')

    def test_removing_a_legacy_block_keeps_crlf_and_lf_files_byte_identical(self):
        for eol in (chr(10), chr(13) + chr(10)):
            with tempfile.TemporaryDirectory() as tmp:
                repo = self.make_repo(tmp)
                original = ('# Rules' + eol + 'Keep me.' + eol).encode('utf-8')
                block = (eol + install_project.BEGIN + eol + 'old rules' + eol + install_project.END + eol).encode('utf-8')
                (repo / 'CLAUDE.md').write_bytes(original + block)
                install_project.install(repo, 'eol', register=False, ide='claude')
                self.assertEqual((repo / 'CLAUDE.md').read_bytes(), original, repr(eol))

    def test_update_refreshes_shipped_files_but_keeps_registration_and_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            install_project.install(repo, 'upd', gates=[['npm', 'run', 'lint']], register=False, ide='claude')
            (repo / 'center.connection.json').write_text(json.dumps({'url': 'http://127.0.0.1:3939', 'token': 'cc_keep'}), encoding='utf-8')
            (repo / '.claude' / 'hooks' / 'center_guard.py').write_text('stale', encoding='utf-8')
            install_project.install(repo, 'upd', update=True, ide='claude')
            self.assertIn('def main', (repo / '.claude' / 'hooks' / 'center_guard.py').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((repo / 'center.connection.json').read_text(encoding='utf-8'))['token'], 'cc_keep')
            self.assertEqual(json.loads((repo / 'project.config.json').read_text(encoding='utf-8'))['quality_gates'], [['npm', 'run', 'lint']])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'already installed'):
                install_project.install(self.make_repo(tmp), 'never', update=True, ide='claude')

    def test_refuses_non_git_dir_overwrite_and_center_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                install_project.install(tmp, 'x', register=False)
            repo = self.make_repo(tmp)
            install_project.install(repo, 'x', register=False)
            with self.assertRaises(ValueError):
                install_project.install(repo, 'x', register=False)
        with self.assertRaises(ValueError):
            install_project.install(ROOT, 'x', register=False)


if __name__ == '__main__':
    unittest.main()
