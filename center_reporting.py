"""Read-only snapshots of tasks, sessions and providers for the API and dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path

import center_capacity
from center_store import now


def _activity(run_dir, limit=160):
    """Latest line the running step wrote (provider or gate log), for the dashboard card. Empty when nothing is readable."""
    try:
        logs = [p for p in Path(run_dir).rglob('*.log') if p.name == 'provider.log' or p.name.startswith('gate-')]
        newest = max(logs, key=lambda p: p.stat().st_mtime)
        with newest.open('rb') as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 4096))
            lines = [l.strip() for l in handle.read().decode('utf-8', errors='replace').splitlines() if l.strip()]
    except (TypeError, ValueError, OSError):
        return None
    if not lines:
        return None
    text = lines[-1]
    if text.startswith('{'):
        try:
            item = json.loads(text)
            body = (item.get('item') or {}).get('command') or (item.get('item') or {}).get('text') or item.get('message') or item.get('type') or ''
            text = f"[{item.get('type') or 'json'}] {body}" if isinstance(body, str) and body else text
        except (ValueError, AttributeError):
            pass
    return f"{newest.stem}: {text}"[:limit]


class ReportMixin:
    def report(self, task_id=None, project_id=None):
        with self.store.connection() as con:
            where = ' WHERE t.project_id=?' if project_id else ''
            params = (project_id,) if project_id else ()
            sessions = [dict(r) for r in con.execute('SELECT s.* FROM sessions s JOIN tasks t ON t.id=s.task_id' + where, params)]
            if task_id:
                task = self.store.task(task_id)
                if project_id and task['project_id'] != project_id:
                    raise ValueError('Task belongs to another project')
                events = [dict(r) for r in con.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]
                evidence = [dict(r) for r in con.execute("SELECT * FROM evidence WHERE task_id=? ORDER BY id", (task_id,))]
                authors = [dict(r) for r in con.execute("SELECT * FROM authorship WHERE task_id=? ORDER BY id", (task_id,))]
                return {"task": task, "events": events, "evidence": evidence, "authorship": authors, "sessions": [s for s in sessions if s["task_id"] == task_id]}
            task_filter = ' WHERE project_id=?' if project_id else ''
            tasks = [dict(r) for r in con.execute("SELECT id,project_id,title,status,provider,reviewer,attempt,mode,error,updated_at FROM tasks" + task_filter + " ORDER BY created_at DESC LIMIT 100", params)]
            projects = [dict(r) for r in con.execute("SELECT id,name,root_path FROM projects" + (' WHERE id=?' if project_id else ''), params)]
            run_dirs = {r[0]: r[1] for r in con.execute("SELECT id,run_dir FROM tasks" + task_filter + " ORDER BY created_at DESC LIMIT 100", params)}
            plans = {}
            for task_row in tasks:
                for row in con.execute("SELECT detail FROM events WHERE task_id=? AND event='dispatch_recorded' ORDER BY id", (task_row['id'],)):
                    detail = json.loads(row[0])
                    plans.setdefault(task_row['id'], {})[detail.get('role')] = {k: detail.get(k) for k in ('provider', 'model', 'effort', 'skills')}
        for task in tasks:
            task['plan'] = plans.get(task['id'], {})
            task['waiting_reason'] = None
            task['activity'] = _activity(run_dirs.get(task['id'])) if task['status'] in ('assigned', 'running', 'implementation_done', 'gates', 'review') else None
            if task['status'] in ('queued', 'retry_wait', 'waiting_for_independent_review'):
                role = 'review' if task['status'] == 'waiting_for_independent_review' else 'implementation'
                readiness = self.scheduling_readiness(task['id'], role, 'mock' if task['mode'] == 'mock' else 'live')
                task['waiting_reason'] = None if readiness['ready'] else readiness['reason']
                task['routing_reason'] = readiness['reason']
            elif task['status'] == 'blocked':
                task['waiting_reason'] = task['error'] or 'explicit_reconciliation_required'
        from center_service import service_status
        return {"storage": "sqlite", "projects": projects, "tasks": tasks, "sessions": sessions, "capacity": center_capacity.capacity_report(self.config, len(sessions)), "providers": self.provider_status(), "global_capacity": self.config["global_capacity"], "live_execution": self.config["live_execution"], 'service': service_status(self), 'task_window': {'limit': 100, 'ordering': 'latest_first'}, "updated": now()}
