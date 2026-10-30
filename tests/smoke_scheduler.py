"""Bounded real-supervisor smoke test, using mock workers and local fixtures."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from test_smart_router import ROOT, make_project
from center_runtime import Center
from smart_router import service_status


def main():
    target = ROOT / '.ai-team' / 'scheduler-smoke' / uuid.uuid4().hex[:8]
    target.mkdir(parents=True)
    center = Center(target / 'state')
    for project in ('a', 'b'):
        root = target / project
        cfg = make_project(root, project)
        center.register(project, root, cfg)
    tasks = [center.submit(project, 'Scheduled mock task', 'Create mock sample file', ['src'], ['Gate passes'],
                           provider=provider, mode='mock', mock={'sleep': 1})['id']
             for project, provider in [('a', 'codex'), ('a', 'claude'), ('b', 'codex'), ('b', 'claude')]]
    with (target / 'service.log').open('wb') as log:
        proc = subprocess.Popen([sys.executable, str(ROOT / 'smart_router.py'), '--state-dir', str(center.store.state), 'serve', '--mode', 'mock'],
                                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        max_active = 0
        try:
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                report = center.report()
                max_active = max(max_active, len(report['sessions']))
                done = all(any(e['event'] == 'mock_pipeline_complete' for e in center.report(t)['events']) for t in tasks)
                if done:
                    break
                if proc.poll() is not None:
                    raise AssertionError('Scheduler exited before completing mock work')
                time.sleep(0.2)
            else:
                raise AssertionError('Scheduler smoke deadline exceeded')
            assert max_active >= 2, 'No concurrent dispatch observed'
            assert all(center.store.task(t)['status'] == 'waiting_for_independent_review' for t in tasks)
            assert not center.report()['sessions']
            result = {'tasks': tasks, 'projects': 2, 'max_active_sessions_observed': max_active,
                      'real_ai_calls': 0, 'state': 'mock_pipeline_complete_waiting_for_real_review', 'state_dir': str(center.store.state)}
            (target / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            status = service_status(center)
            if status.get('instance'):
                (center.store.state / f"stop-{status['instance']}").touch()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == '__main__':
    main()
