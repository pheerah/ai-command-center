"""Acceptance check of the project edit-guard against the real Claude Code CLI (headless, `claude -p`).

It installs the connector into a throwaway git project (never a real project, no Center registration),
removes the prompt-level rules so only the PreToolUse hook can stop an edit, and makes two tiny
low-effort Haiku calls: (1) direct edit with no window must be refused by the hook, (2) the same
request after `connector.py allow-direct` must succeed. This proves the hook with the CLI engine;
it does NOT prove the VS Code extension honours the same settings, which still needs a manual check.

Usage: python scripts/claude_acceptance.py [--model claude-haiku-5-5]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
import install_project  # noqa: E402

PROMPT = 'Create the file src/hello.py containing exactly: print("hi"). Use the Write tool. Then reply with the single word DONE or BLOCKED.'


def ask(repo, model):
    command = ['cmd', '/c', 'claude'] if sys.platform == 'win32' else ['claude']
    run = subprocess.run([*command, '-p', PROMPT, '--model', model, '--effort', 'low', '--permission-mode', 'acceptEdits', '--output-format', 'json'],
                         cwd=repo, capture_output=True, text=True, timeout=300, check=False)
    try:
        reply = str(json.loads(run.stdout).get('result', ''))
    except ValueError:
        reply = (run.stdout or run.stderr)[:300]
    return reply.replace(chr(10), ' ')[:240]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', default='claude-haiku-5-5')
    args = parser.parse_args()
    if not shutil.which('claude') and sys.platform != 'win32':
        print(json.dumps({'status': 'blocked', 'reason': 'claude CLI not found'}))
        return 2
    base = Path(tempfile.mkdtemp(prefix='claude-acceptance-'))
    repo = base / 'project'
    (repo / 'src').mkdir(parents=True)
    (repo / 'src' / 'keep.py').write_text('x = 1' + chr(10), encoding='utf-8')
    git = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run([*git, 'add', '-A'], cwd=repo, check=True)
    subprocess.run([*git, 'commit', '-qm', 'init'], cwd=repo, check=True)
    install_project.install(repo, 'acceptance', scopes=['src'], register=False)
    (repo / 'CLAUDE.md').unlink()
    shutil.rmtree(repo / '.claude' / 'skills')
    target = repo / 'src' / 'hello.py'
    blocked_reply = ask(repo, args.model)
    blocked_ok = not target.exists()
    subprocess.run([sys.executable, str(repo / 'connector.py'), 'allow-direct', '--minutes', '5', '--reason', 'acceptance test'], cwd=repo, capture_output=True, check=False)
    window_reply = ask(repo, args.model)
    window_ok = target.exists()
    result = {'engine': 'claude CLI (headless), not the VS Code extension', 'model': args.model,
              'no_window_blocked': blocked_ok, 'no_window_reply': blocked_reply,
              'with_window_allowed': window_ok, 'with_window_reply': window_reply,
              'passed': blocked_ok and window_ok, 'sandbox_project': str(repo),
              'still_manual': 'repeat once in VS Code: open the project, ask Claude Code to edit src/, expect the hook message'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
