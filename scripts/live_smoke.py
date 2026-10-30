"""Two minimal live tasks, subscription-only; never commits or approves.

prepare creates synthetic repositories from the existing README-only first
revision. run starts the real supervisor, bounded to one attempt per phase.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from center_runtime import Center
from center_workspace import git
from smart_router import service_status

CLAMP_GATE = """from src.bounds import clamp
assert clamp(-1, 0, 10) == 0
assert clamp(11, 0, 10) == 10
assert clamp(5, 0, 10) == 5
assert clamp(2, 2, 2) == 2
try:
    clamp(0, 2, 1)
except ValueError:
    pass
else:
    raise AssertionError('missing ValueError')
"""


def prepare():
    target = ROOT / 'sandbox/runs' / ('live-' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'center.config.json').read_text())
    config.update({'live_execution': True, 'global_capacity': 2, 'max_attempts': 1, 'worker_timeout_seconds': 360})
    for name in ('codex', 'claude'):
        config['providers'][name].update({'availability': 'available', 'reason': 'subscription_auth_verified_pending_live_smoke', 'capacity': 1})
    config_path = target / 'center.config.json'
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    center = Center(target / 'state', config_path)
    for provider in ('codex', 'claude'):
        center._check_live_login(provider)
    revision = git(ROOT, 'rev-list', '--max-parents=0', 'HEAD').splitlines()[0]
    if git(ROOT, 'ls-tree', '--name-only', revision).splitlines() != ['README.md']:
        raise ValueError('Synthetic fixture requires an existing README-only revision; no new commit will be made')
    examples = [
        ('live-python', 'codex', 'src/bounds.py',
         'Create only src/bounds.py defining clamp(value, lower, upper). Return lower if value is below lower, upper if above upper, otherwise value. Raise ValueError if lower > upper. Do not run commands or tests; Center runs the gate. Do not inspect .git or files outside scope. This is synthetic sample code, not a real project.',
         ['python', '-c', CLAMP_GATE]),
        ('live-node', 'claude', 'src/slug.js',
         "Create only src/slug.js exporting CommonJS slugify(text). Convert to lowercase, trim, replace each run of characters outside ASCII a-z and 0-9 with a hyphen, then remove leading/trailing hyphens. Examples: ' Hello, WORLD! ' -> 'hello-world', 'a___b' -> 'a-b', '---' -> ''. Do not run commands or tests; Center runs the gate. Do not inspect .git or files outside scope. This is synthetic sample code, not a real project.",
         ['node', '-e', "const a=require('node:assert/strict');const {slugify}=require('./src/slug.js');a.equal(slugify(' Hello, WORLD! '),'hello-world');a.equal(slugify('a___b'),'a-b');a.equal(slugify('---'),'');a.equal(slugify('abc123'),'abc123');a.equal(slugify(''),'');"]),
    ]
    tasks = []
    for project, provider, scope, requirement, gate in examples:
        root = target / project
        root.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
        shutil.copytree(ROOT / '.git/objects', root / '.git/objects', dirs_exist_ok=True)
        git(root, 'checkout', '--quiet', '--detach', revision)
        project_config = {'project_id': project, 'name': project, 'allowed_providers': ['codex', 'claude'],
                          'context_scope': ['src'], 'quality_gates': [gate], 'approval_policy': 'human_required', 'auto_commit': False,
                          'base_revision': 'HEAD'}
        file = root / '.git/center-project.json'
        file.write_text(json.dumps(project_config), encoding='utf-8')
        center.register(project, root, file)
        task = center.submit(project, 'Subscription live smoke: ' + project, requirement, [scope], ['Functional gate passes', 'Independent review by other provider', 'No source edits outside the requested file'], provider=provider, mode='live', complexity=1)
        tasks.append(task['id'])
    report = {'state_dir': str(center.store.state), 'config': str(config_path), 'tasks': tasks, 'fixture_base': revision}
    (target / 'run.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({**report, 'run_file': str(target / 'run.json')}, indent=2))


def run(run_file):
    record = json.loads(Path(run_file).read_text())
    center = Center(record['state_dir'], record['config'])
    log_path = Path(run_file).parent / 'supervisor.log'
    with log_path.open('ab') as output:
        proc = subprocess.Popen([sys.executable, str(ROOT / 'smart_router.py'), '--state-dir', record['state_dir'], '--config', record['config'], 'serve', '--mode', 'live'],
                                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 750
            last = None
            while time.monotonic() < deadline:
                tasks = [center.store.task(task) for task in record['tasks']]
                statuses = [(t['id'], t['status'], t['provider'], t['reviewer']) for t in tasks]
                if statuses != last:
                    print(json.dumps({'tasks': statuses}), flush=True)
                    last = statuses
                if all(t['status'] in ('ready_for_human_approval', 'failed', 'blocked', 'cancelled') for t in tasks):
                    break
                if proc.poll() is not None:
                    raise ValueError('Live supervisor exited early; inspect its log')
                time.sleep(0.5)
            else:
                for task in tasks:
                    if task['status'] not in ('ready_for_human_approval', 'failed', 'blocked', 'cancelled'):
                        center.cancel(task['id'])
                raise ValueError('Live smoke deadline exceeded; cancellation requested, worktrees preserved')
            reports = [center.report(task) for task in record['tasks']]
            result = {'run_file': str(Path(run_file).resolve()), 'tasks': reports,
                      'passed': all(r['task']['status'] == 'ready_for_human_approval' for r in reports),
                      'human_approval_performed': False, 'google_called': False}
            destination = Path(run_file).parent / 'live-result.json'
            destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps({'passed': result['passed'], 'result_file': str(destination)}, indent=2))
            return 0 if result['passed'] else 1
        finally:
            status = service_status(center)
            if status.get('instance'):
                (center.store.state / f"stop-{status['instance']}").touch()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # Do not kill a supervisor while a child may still be writing.
                print('Supervisor is draining; preserve the state and inspect service-status', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    p = sub.add_parser('run')
    p.add_argument('run_file')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    else:
        raise SystemExit(run(args.run_file))
