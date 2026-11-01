"""Wire one project to this Center so its VS Code Claude Code session can use it through the HTTP API.

Run by the Center's owner, from the Center. It registers the project, issues a
per-project API token and writes connection details into the project. The project
never receives a path into the Center and never needs to read its files.

Adds to the project: connector.py (HTTP client), center.connection.json (URL + token,
git-excluded), project.config.json (gates/scope, no secrets), the Claude Code skill,
CLAUDE.md rules, a local Claude Code deny rule for reading the Center directory, and a PreToolUse edit-guard hook
(.claude/hooks/center_guard.py) that blocks direct edits of the project's context_scope files unless the user opens a
time-limited window with connector.py allow-direct.
It never calls a model, edits global Claude/IDE settings, commits, or touches other projects.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
TEMPLATE = ROOT / 'connector-template'
BEGIN, END = '<!-- ai-command-center:begin -->', '<!-- ai-command-center:end -->'
LOCAL_ONLY = ('/connector.py', '/project.config.json', '/center.connection.json', '/.claude/settings.local.json',
              '/.center-direct-edit.json', '/.claude/hooks/')
HOOK_MATCHER = 'Edit|Write|MultiEdit|NotebookEdit|Bash'
# Center refuses a dirty checkout, so files it added must not show up as untracked.
OPTIONAL_LOCAL = ('/CLAUDE.local.md', '/.claude/skills/ai-command-center/', '/.agents/rules/ai-command-center.md', '/.agents/skills/ai-command-center/')
IDES = ('claude', 'antigravity', 'both')
DEFAULT_URL = 'http://127.0.0.1:3939'


def _strip_legacy_block(claude_md):
    """Earlier installs appended the Center rules to the tracked CLAUDE.md, which dirtied the checkout. Remove only that block."""
    if not claude_md.exists():
        return False
    with open(claude_md, encoding='utf-8', newline='') as stream:  # newline='' keeps the file's own line endings byte for byte
        text = stream.read()
    if BEGIN not in text or END not in text:
        return False
    eol = '\r\n' if '\r\n' in text else '\n'
    head, rest = text.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]
    cleaned = head.rstrip('\r\n') + eol + tail.lstrip('\r\n')
    with open(claude_md, 'w', encoding='utf-8', newline='') as stream:
        stream.write(cleaned if cleaned.strip() else '')
    return True


def parse_command(text):
    """A command as an argv list: a JSON array, or plain text such as `npm run lint`.

    Windows PowerShell 5.1 strips the double quotes from native-command arguments, so a JSON array typed in a
    PowerShell window arrives mangled; plain text avoids the problem and is split without invoking a shell.
    """
    text = text.strip()
    if text.startswith('['):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Not valid JSON ({exc.msg}). In Windows PowerShell write the command as plain text instead, for example: --gate "npm run lint"') from exc
    else:
        value = shlex.split(text)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError('A command must be a non-empty list of strings, e.g. "npm run lint"')
    return value


def _claude_path(path):
    """Claude Code permission rules address absolute paths as //drive/..., with forward slashes."""
    text = Path(path).resolve().as_posix()
    return '//' + text[0].lower() + text[2:] if len(text) > 1 and text[1] == ':' else '/' + text


def _install_claude(root):
    """Claude Code: skill, CLAUDE.local.md rules, deny-read rule for the Center and the PreToolUse edit guard."""
    skill_target = root / '.claude' / 'skills' / 'ai-command-center'
    skill_target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE / '.claude/skills/ai-command-center/SKILL.md', skill_target / 'SKILL.md')
    rules = (TEMPLATE / 'CLAUDE.md').read_text(encoding='utf-8').strip()
    block = f'{BEGIN}\n{rules}\n{END}\n'
    # Claude Code loads CLAUDE.local.md (untracked, personal) next to CLAUDE.md, so the project's tracked CLAUDE.md stays untouched
    # and the checkout stays clean for the Center.
    local_rules = root / 'CLAUDE.local.md'
    existing = local_rules.read_text(encoding='utf-8') if local_rules.exists() else ''
    if BEGIN in existing and END in existing:
        head, rest = existing.split(BEGIN, 1)
        existing = head + block + rest.split(END, 1)[1].lstrip('\n')
    else:
        existing = (existing.rstrip() + '\n\n' if existing.strip() else '') + block
    local_rules.write_text(existing if existing.endswith('\n') else existing + '\n', encoding='utf-8')
    legacy_removed = _strip_legacy_block(root / 'CLAUDE.md')
    # Local (personal) Claude Code settings: deny reads of the Center directory. Merged, never replaced.
    settings_file = root / '.claude' / 'settings.local.json'
    settings = json.loads(settings_file.read_text(encoding='utf-8')) if settings_file.exists() else {}
    rule = f'Read({_claude_path(ROOT)}/**)'
    deny = settings.setdefault('permissions', {}).setdefault('deny', [])
    if rule not in deny:
        deny.append(rule)
    hook_target = root / '.claude' / 'hooks'
    hook_target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE / 'hooks' / 'center_guard.py', hook_target / 'center_guard.py')
    command = f'"{sys.executable}" "{hook_target / "center_guard.py"}"'
    groups = settings.setdefault('hooks', {}).setdefault('PreToolUse', [])
    if not any(h.get('command') == command for g in groups for h in g.get('hooks', [])):
        groups.append({'matcher': HOOK_MATCHER, 'hooks': [{'type': 'command', 'command': command}]})
    settings_file.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    return legacy_removed


def _install_antigravity(root):
    """Google Antigravity: workspace rule (always on), skill, and git pre-commit guard."""
    for relative in ('rules/ai-command-center.md', 'skills/ai-command-center/SKILL.md'):
        target = root / '.agents' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATE / '.agents' / relative, target)

    hooks_dir = root / '.git' / 'hooks'
    if hooks_dir.is_dir():
        guard_script = '#!/bin/sh\nif [ -f .center-direct-edit.json ]; then\n    exit 0\nfi\necho "AI Command Center Guard: Direct commit blocked. Use: python connector.py plan \'<instruction>\' --submit"\nexit 1\n'
        hook_path = hooks_dir / 'pre-commit'
        hook_path.write_text(guard_script, encoding='utf-8')
        try:
            os.chmod(hook_path, 0o755)
        except OSError:
            pass


def install(path, project_id, name=None, gates=None, scopes=None, providers=None, force=False, register=True, url=DEFAULT_URL, state=None, config=None, prepare=None, update=False, ide='antigravity'):
    if ide not in IDES:
        raise ValueError(f'ide must be one of {IDES}')
    root = Path(path).resolve()
    if not root.is_dir() or not (root / '.git').exists():
        raise ValueError('Project path must be an existing git repository')
    if root == ROOT or ROOT in root.parents or root in ROOT.parents:
        raise ValueError('The project and the Center must be separate directories (neither may contain the other)')
    config_file = root / 'project.config.json'
    if update:
        # Refresh the files the Center ships (connector, hook, skill, rules) without touching registration, token or gates.
        if not (root / 'center.connection.json').exists() or not config_file.exists():
            raise ValueError('--update needs a project that was already installed (center.connection.json and project.config.json)')
        register = False
    else:
        if config_file.exists() and not force:
            raise ValueError('project.config.json already exists; pass --force to rewrite it')
        project_config = json.loads((TEMPLATE / 'project.config.json').read_text(encoding='utf-8'))
        project_config.update(project_id=project_id, name=name or project_id)
        project_config.pop('center', None)  # the project must not know where the Center lives on disk
        if gates is not None:
            project_config['quality_gates'] = gates
        if prepare is not None:
            project_config['prepare_commands'] = prepare  # e.g. [["npm", "ci"]]; Center never guesses an install command
        if scopes:
            project_config['context_scope'] = scopes
        if providers:
            project_config['allowed_providers'] = providers
        config_file.write_text(json.dumps(project_config, indent=2), encoding='utf-8')
    shutil.copyfile(TEMPLATE / 'connector.py', root / 'connector.py')
    legacy_removed = _install_claude(root) if ide in ('claude', 'both') else False
    if ide in ('antigravity', 'both'):
        _install_antigravity(root)
    exclude = root / '.git' / 'info' / 'exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    known = exclude.read_text(encoding='utf-8') if exclude.exists() else ''

    def untracked(rel):
        return subprocess.run(['git', 'ls-files', '--error-unmatch', rel], cwd=root, capture_output=True, check=False).returncode != 0
    hidden = [*LOCAL_ONLY, *(line for line in OPTIONAL_LOCAL if untracked(line.strip('/')))]
    missing = [line for line in hidden if line not in known.splitlines()]
    if missing:
        with exclude.open('a', encoding='utf-8') as stream:
            stream.write(('' if known.endswith('\n') or not known else '\n') + '\n'.join(missing) + '\n')
    result = {'project_id': project_id, 'path': str(root), 'ide': ide, 'registered': False, 'api_url': url,
              'legacy_claude_md_block_removed': legacy_removed,
              'review_note': 'Everything the installer adds is untracked and git-excluded, and the tracked CLAUDE.md is left as it was (an earlier block, if any, is removed), so Center sees a clean checkout.'}
    if register:
        import center_api
        from center_runtime import Center
        if subprocess.run(['git', 'ls-files', '--error-unmatch', 'center.connection.json'], cwd=root, capture_output=True, check=False).returncode == 0:
            raise ValueError('center.connection.json is tracked by git; untrack it before a token is written there')
        center = Center(state, config)
        center.register(project_id, root, confirm_config_change=force)
        token = center_api.create_token(center.store.state, project_id, 'installer')
        connection = root / 'center.connection.json'
        connection.write_text(json.dumps({'url': url, 'token': token}, indent=2), encoding='utf-8')
        try:
            connection.chmod(0o600)
        except OSError:
            pass
        result['registered'] = True
        result['token_note'] = 'Token written only to center.connection.json (git-excluded). Revoke with: smart_router.py token revoke <id>'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', required=True, help='Project git repository root')
    parser.add_argument('--id', required=True, help='Unique project id in the Center')
    parser.add_argument('--name')
    parser.add_argument('--gate', action='append', help='Quality gate, repeatable: plain text like "npm run lint" (recommended in Windows PowerShell) or a JSON array')
    parser.add_argument('--detect-gates', action='store_true', help='Use only the gate commands the project really defines (scripts/gate_presets.py) when no --gate is given')
    parser.add_argument('--prepare', action='append', help='Command run once in each fresh worktree before the gates, repeatable: plain text like "npm ci" or a JSON array')
    parser.add_argument('--scope', action='append', help='Context scope path, repeatable')
    parser.add_argument('--provider', action='append', choices=['claude', 'codex', 'google'])
    parser.add_argument('--url', default=DEFAULT_URL, help='Where projects reach the Center API')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing project.config.json and accept the policy change')
    parser.add_argument('--ide', choices=IDES, default='antigravity', help='Which IDE session sends tasks to the Center: Claude Code, Google Antigravity, or both')
    parser.add_argument('--no-register', action='store_true')
    parser.add_argument('--update', action='store_true', help='Refresh connector, hook, skill and rules in an already installed project; keeps its registration, token and gates')
    args = parser.parse_args()
    try:
        gates = [parse_command(g) for g in args.gate] if args.gate else None
        if gates is None and args.detect_gates:
            import gate_presets
            gates = gate_presets.detect_gates(args.path)
            if not gates:
                raise ValueError('No quality gate could be detected; pass --gate explicitly. Nothing is invented.')
        prepare = [parse_command(p) for p in args.prepare] if args.prepare else None
        result = install(args.path, args.id, args.name, gates, args.scope, args.provider, args.force, not args.no_register, args.url, prepare=prepare, update=args.update, ide=args.ide)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc), 'model_calls': 0}, ensure_ascii=False))
        return 2
    print(json.dumps({**result, 'model_calls': 0}, ensure_ascii=False, indent=2))
    return 0 if result['registered'] or args.no_register or args.update else 1


if __name__ == '__main__':
    raise SystemExit(main())
