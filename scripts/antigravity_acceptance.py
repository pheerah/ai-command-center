"""Prepare/check an isolated real-IDE acceptance run; never invokes any model.

Google availability is never changed by this script. A user must first confirm
their usage reset and deliberately enable only the isolated test state. check
reads evidence, reports missing steps, and never creates approval evidence.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from center_runtime import Center
from center_workspace import git, inside


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare(destination=None):
    target = Path(destination or ROOT / 'sandbox' / 'runs' / ('antigravity-' + uuid.uuid4().hex[:8])).resolve()
    if target.exists() or not inside(target, ROOT / 'sandbox' / 'runs'):
        raise ValueError('Acceptance preparation requires a new directory under workspace sandbox/runs')
    target.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'center.config.json').read_text(encoding='utf-8'))
    config['max_attempts'] = 1
    config['global_capacity'] = 2
    # Preserve provider availability exactly. In particular, do not mark Google
    # available, check auth, start a scheduler, or issue any model request.
    config_path = target / 'center.config.json'
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    center = Center(target / 'state', config_path)
    revision = git(ROOT, 'rev-list', '--max-parents=0', 'HEAD').splitlines()[0]
    if git(ROOT, 'ls-tree', '--name-only', revision).splitlines() != ['README.md']:
        raise ValueError('Acceptance sample requires the existing README-only first revision; no commit will be created')
    project_id, root = 'antigravity-acceptance', target / 'project'
    root.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    shutil.copytree(ROOT / '.git/objects', root / '.git/objects', dirs_exist_ok=True)
    git(root, 'checkout', '--quiet', '--detach', revision)
    shutil.copytree(ROOT / 'connector-template', root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    project_config = {'project_id': project_id, 'name': 'Isolated Antigravity acceptance',
                      'allowed_providers': ['google', 'codex', 'claude'], 'context_scope': ['src'],
                      'quality_gates': [['python', '-c', 'from src.acceptance import double; assert double(3)==6; assert double(0)==0; assert double(-2)==-4']],
                      'approval_policy': 'human_required', 'auto_commit': False, 'base_revision': 'HEAD',
                      'async_handoff_gates': True, 'prepare_commands': [],
                      'center': {'python': sys.executable, 'cli': str(ROOT / 'smart_router.py'),
                                 'state_dir': str(center.store.state), 'config': str(config_path)}}
    (root / 'project.config.json').write_text(json.dumps(project_config, indent=2), encoding='utf-8')
    with (root / '.git/info/exclude').open('a', encoding='utf-8') as exclude:
        exclude.write('\n/connector.py\n/project.config.json\n/.agents/\n')
    center.register(project_id, root)
    task = center.submit(project_id, 'Antigravity actual IDE acceptance',
                         'In the assigned task worktree create only src/acceptance.py with double(value) returning value * 2. '
                         'Use actual Google provider/session identity, acknowledge start, run the deterministic watcher, '
                         'submit the result in artifact_dir, and let Center run gates and independent review. '
                         'Do not edit the original checkout, commit, approve, or change provider availability.',
                         ['src'], ['double handles positive, zero and negative inputs', 'Actual IDE handoff and independent review evidence'],
                         provider='google', mode='live', complexity=1)
    record = {'project_id': project_id, 'project_root': str(root), 'state_dir': str(center.store.state),
              'config': str(config_path), 'task_id': task['id'], 'fixture_base': revision,
              'status': 'pending_live_verification', 'model_calls': 0,
              'google_availability_preserved': config['providers']['google']['availability']}
    run_file = target / 'run.json'
    run_file.write_text(json.dumps(record, indent=2), encoding='utf-8')
    prefix = '& ' + _ps(sys.executable) + ' ' + _ps(ROOT / 'smart_router.py') + ' --state-dir ' + _ps(center.store.state) + ' --config ' + _ps(config_path)
    checklist = f'''# One-shot actual Antigravity acceptance

Prepared task: {task['id']}. Project: {root}
Status: pending_live_verification. Preparation made ZERO model calls, changed
no provider availability and started no scheduler. Never probe quota with AI.

1. Wait until the user confirms Google usage is available. Only then the user
   may enable Google for this isolated state with:
   `{prefix} provider set google --availability available --reason user_confirmed_usage_reset`
2. Start only this isolated scheduler: `{prefix} start --mode live`.
3. Open the sample project in Antigravity. Read its local rules/skill. Run
   connector health/status; explicitly claim task {task['id']} as google.
4. Use the returned worktree/artifact directory. Confirm the IDE can write to
   that worktree; acknowledge worker-start with its actual session reference.
5. Run deterministic watch SESSION_ID in a background local process. Create
   only src/acceptance.py. Stop editing if renewal fails. Submit result JSON in
   the assigned artifact directory; do not approve or implement review yourself.
6. Let Center run real gates and independent Codex/Claude review. Report the
   resulting evidence and ready_for_human_approval to the user.
7. The user may perform interactive human approval separately. Also manually
   verify unavailable-Center behavior and cancellation/stop acknowledgement in
   a separately submitted sample task. Do not claim these scenarios passed
   merely because the happy path passed.
8. Run this program check once:
   `& {_ps(sys.executable)} {_ps(Path(__file__).resolve())} check --state-dir {_ps(center.store.state)} --config {_ps(config_path)} --task-id {task['id']}`
9. Stop the isolated scheduler: `{prefix} stop`. Preserve worktrees/evidence.

No paid APIs, account switching, automatic commits/merges/deployments, or
credential files are involved. Main Center availability/config is untouched.
'''
    (target / 'CHECKLIST.md').write_text(checklist, encoding='utf-8')
    return {**record, 'run_file': str(run_file), 'checklist': str(target / 'CHECKLIST.md')}


def check(center, task_id):
    report = center.report(task_id)
    task = report['task']
    missing = []
    if task['mode'] != 'live' or task['provider'] != 'google':
        missing.append('actual_google_implementation')
    dispatches, starts, heartbeats = {}, {}, set()
    for row in report['events']:
        detail = json.loads(row['detail']) if isinstance(row.get('detail'), str) else row.get('detail', {})
        if row['event'] == 'dispatch_recorded' and detail.get('provider') == 'google' and detail.get('adapter') == 'handoff' and detail.get('role') == 'implementation':
            dispatches[detail.get('session_id')] = detail
        elif row['event'] == 'worker_started' and detail.get('source') == 'ide_acknowledgement' and detail.get('reference'):
            starts[detail.get('session_id')] = detail
        elif row['event'] == 'handoff_heartbeat_observed':
            heartbeats.add(detail.get('session_id'))
    verified_sessions = set(dispatches) & set(starts)
    if not verified_sessions:
        missing.append('actual_ide_dispatch_and_start_reference')
    if not verified_sessions & heartbeats:
        missing.append('deterministic_handoff_heartbeat_evidence')
    if task['status'] not in ('ready_for_human_approval', 'approved'):
        missing.append('completed_gates_and_independent_review_lifecycle')
    try:
        center.validate_evidence(task_id)
    except (ValueError, OSError, KeyError) as exc:
        missing.append('current_gate_and_independent_review_evidence:' + type(exc).__name__)
    real_review = [row for row in report['evidence'] if row['kind'] == 'review' and not row.get('simulated') and row.get('provider') not in (None, 'google')
                   and row['base_rev'] == task['base_rev'] and row['patch_hash'] == task['patch_hash']]
    if not real_review:
        missing.append('real_cross_provider_review')
    if any(row['event'] == 'mock_pipeline_complete' for row in report['events']):
        missing.append('mock_evidence_cannot_validate_actual_ide')
    return {'task_id': task_id, 'status': task['status'], 'happy_path_verified': not missing,
            'overall_status': 'pending_manual_failure_scenarios' if not missing else 'pending_live_verification',
            'missing_steps': missing, 'ide_session_references': [starts[sid]['reference'] for sid in sorted(verified_sessions)],
            'human_approval': 'recorded' if task['status'] == 'approved' else 'pending_user',
            'pending_manual_scenarios': ['center_unreachable_reports_blocked', 'ide_stops_on_lease_loss', 'cancellation_and_worker_stop_ack'],
            'model_calls': 0, 'policy': 'check_only_no_approval_or_availability_changes'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare', help='Create isolated sample/checklist without any model calls')
    checker = commands.add_parser('check', help='Check actual IDE evidence once; never invoke models')
    checker.add_argument('--state-dir', required=True)
    checker.add_argument('--task-id', required=True)
    checker.add_argument('--config')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare()
        else:
            state = Path(args.state_dir).resolve()
            if not (state / 'tasks.sqlite3').is_file():
                raise ValueError('Check requires an existing isolated state database')
            center = Center(state, args.config or state.parent / 'center.config.json')
            result = check(center, args.task_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc), 'model_calls': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
