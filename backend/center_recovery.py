"""Getting stuck work moving again: lease recovery, reassignment, retries, provider failover and queue deadlines."""
from __future__ import annotations

import json
import time

from center_store import event, pid_alive, transition


class RecoveryMixin:
    def recover(self):
        recovered = []
        with self.store.connection() as con:
            sessions = [dict(r) for r in con.execute("SELECT * FROM sessions WHERE lease_until<?", (time.time(),))]
        for snapshot in sessions:
            # Never reuse a slot while an old process might still write. PID checks
            # are conservative; an alive/reused PID keeps capacity occupied.
            try:
                with self.store.connection(write=True) as con:
                    session = con.execute('SELECT * FROM sessions WHERE id=? AND lease_until<?', (snapshot['id'], time.time())).fetchone()
                    if not session or pid_alive(session['owner_pid']) or pid_alive(session['child_pid']):
                        continue
                    task = con.execute('SELECT * FROM tasks WHERE id=?', (session['task_id'],)).fetchone()
                    if session['adapter'] == 'handoff':
                        # Never assume an external IDE stopped. Cancellation is
                        # finalized only by worker-stopped acknowledgement.
                        if task['status'] not in ('blocked', 'cancelled', 'approved'):
                            transition(con, task['id'], 'blocked', {'reason': 'handoff_lease_expired_requires_worker_stop_ack'})
                        continue
                self.failure(session["id"], "cancelled_or_lease_lost")
                recovered.append(task['id'])
            except (ValueError, OSError):
                continue
        with self.store.connection(write=True) as con:
            orphans = con.execute("SELECT id FROM tasks WHERE status IN ('assigned','running','implementation_done','gates','review') AND NOT EXISTS(SELECT 1 FROM sessions WHERE sessions.task_id=tasks.id)").fetchall()
            for task in orphans:
                transition(con, task['id'], 'blocked', {'reason': 'orphaned_active_task_requires_worker_stop_reconciliation'})
                con.execute("UPDATE tasks SET error='orphaned_active_task' WHERE id=?", (task['id'],))
                recovered.append(task['id'])
        return {"recovered": recovered, "preserved_worktrees": True}

    def acknowledge_stop(self, sid, reason):
        session = self.session(sid)
        if session['adapter'] != 'handoff' or not reason.strip():
            raise ValueError('Only explicit IDE stop acknowledgements are accepted')
        with self.store.connection(write=True) as con:
            event(con, session['task_id'], 'external_worker_stopped', {'session_id': sid, 'reason': reason})
        return self.failure(sid, 'cancelled_or_lease_lost')

    def reconcile(self, task_id, reason, stopped=False, provider=None, rebuild_overlay=False):
        if not stopped or not reason.strip():
            raise ValueError("Explicit --worker-stopped and a reason are required before reassignment")
        task = self.store.task(task_id)
        if task['cancel_requested']:
            raise ValueError('Cancellation must be finalized, not requeued; acknowledge worker-stopped first')
        if not task["base_rev"] or not json.loads(task["config_json"]).get("allowed_providers"):
            raise ValueError("Legacy task lacks v2 ownership/scope evidence. Preserve its patch and submit a new task")
        with self.store.connection() as con:
            active = con.execute("SELECT * FROM sessions WHERE task_id=?", (task_id,)).fetchone()
            if active and (pid_alive(active["owner_pid"]) or pid_alive(active["child_pid"])):
                raise ValueError("A recorded process is still alive; stop it before reassignment")
        config = json.loads(task["config_json"])
        if rebuild_overlay and (config.get('dependency_policy') != 'overlay' or config.get('_dependency_overlay')):
            raise ValueError('Overlay rebuild is only for an incomplete overlay with no adopted provenance')
        if task["worktree"] and not rebuild_overlay and not self._restore_not_verified(task):
            self.save_checkpoint(task_id)
        if provider and provider not in config["allowed_providers"]:
            raise ValueError("Fallback provider not allowed")
        with self.store.connection(write=True) as con:
            current = con.execute("SELECT status,attempt,max_attempts,cancel_requested FROM tasks WHERE id=?", (task_id,)).fetchone()
            if current["status"] not in ("blocked", "failed"):
                raise ValueError("Only failed/blocked tasks can be reconciled")
            if current["attempt"] >= current["max_attempts"]:
                raise ValueError("Attempt limit reached; create a new task referencing this evidence")
            if current["cancel_requested"]:
                raise ValueError("Cancellation cannot be discarded by reassignment")
            live = con.execute("SELECT owner_pid,child_pid FROM sessions WHERE task_id=?", (task_id,)).fetchone()
            if live and (pid_alive(live["owner_pid"]) or pid_alive(live["child_pid"])):
                raise ValueError("A recorded process is still alive; stop it before reassignment")
            con.execute("DELETE FROM sessions WHERE task_id=?", (task_id,))
            transition(con, task_id, "queued", {"reason": reason, "previous_provider": task["provider"], "requested_provider": provider or task["requested_provider"]})
            if rebuild_overlay:
                event(con, task_id, 'incomplete_overlay_rebuild_authorized', {'reason': reason, 'preserved_checkpoint': task['checkpoint'], 'preserved_worktree': task['worktree']})
                con.execute('UPDATE tasks SET checkpoint=NULL,patch_hash=NULL WHERE id=?', (task_id,))
            if con.execute('SELECT cancel_requested FROM tasks WHERE id=?', (task_id,)).fetchone()[0]:
                raise ValueError('Cancellation cannot be discarded by reassignment')
            con.execute("UPDATE tasks SET requested_provider=?,not_before=0,error=NULL WHERE id=?", (provider or task["requested_provider"], task_id))
        return self.store.task(task_id)

    def auto_retry(self):
        """Send work back through routing after a failed gate or a rejected review, within the attempt budget.

        Only a task that failed on its own evidence qualifies: quality_gate_failed, or a current-patch review whose
        verdict is rejected. Cancelled, blocked (auth/config/model) and budget-exhausted tasks are left for a human.
        The previous gate log and review feedback travel with the task (_prior_attempt), and every attempt stays in authorship.
        """
        retried = []
        with self.store.connection() as con:
            candidates = [dict(r) for r in con.execute("SELECT * FROM tasks WHERE status='failed' AND cancel_requested=0 AND attempt<max_attempts")]
        for task in candidates:
            with self.store.connection() as con:
                if con.execute('SELECT 1 FROM sessions WHERE task_id=?', (task['id'],)).fetchone():
                    continue
                review = con.execute("SELECT payload FROM evidence WHERE task_id=? AND kind='review' AND base_rev=? AND patch_hash=? ORDER BY id DESC LIMIT 1",
                                     (task['id'], task['base_rev'], task['patch_hash'])).fetchone()
            try:
                rejected = bool(review) and json.loads(review[0]).get('verdict') == 'rejected' and not task['error']
            except (ValueError, TypeError, AttributeError):
                continue  # malformed evidence: leave this task to a human, keep going with the rest
            if task['error'] != 'quality_gate_failed' and not rejected:
                continue
            reason = 'auto_retry_after_quality_gate_failure' if task['error'] == 'quality_gate_failed' else 'auto_retry_after_rejected_review'
            try:
                self.reconcile(task['id'], reason, stopped=True)
            except ValueError:
                continue  # state moved on, a process is alive, or the budget ran out: leave it to a human
            retried.append(task['id'])
        return retried

    def auto_failover(self):
        """Send an implementation that a provider could not do (permission block, scope too big for it) to a provider not yet tried.

        Only blocked tasks whose last dispatch was an implementation, inside the attempt budget. A review that blocked is left to
        retry-review/resume-review, and a task with no untried provider stays blocked for a human.
        """
        moved = []
        with self.store.connection() as con:
            rows = [dict(r) for r in con.execute("SELECT id,error FROM tasks WHERE status='blocked' AND mode='live' AND cancel_requested=0 "
                                                 "AND attempt<max_attempts AND error IN ('provider_blocked','needs_narrower_scope')")]
        for row in rows:
            with self.store.connection() as con:
                if con.execute('SELECT 1 FROM sessions WHERE task_id=?', (row['id'],)).fetchone():
                    continue
                dispatches = [json.loads(r[0]) for r in con.execute("SELECT detail FROM events WHERE task_id=? AND event='dispatch_recorded' ORDER BY id", (row['id'],))]
                tried = {d.get('provider') for d in dispatches} | {r[0] for r in con.execute('SELECT DISTINCT provider FROM authorship WHERE task_id=?', (row['id'],))}
            if not dispatches or dispatches[-1].get('role') != 'implementation':
                continue
            options = [p for p in self.candidates(self.store.task(row['id']), 'implementation') if p not in tried]
            if not options:
                continue
            try:
                self.reconcile(row['id'], f"auto_failover_after_{row['error']}", stopped=True, provider=options[0])
            except ValueError:
                continue  # state moved on or a process is alive: leave it to a human
            moved.append(row['id'])
        return moved

    def expire_stalled_queue(self):
        """A queued task that no provider can ever take must say so instead of waiting silently (queue_stall_seconds, 0 = off)."""
        limit = self.config.get('queue_stall_seconds', 0)
        if not limit:
            return []
        from datetime import datetime
        expired = []
        with self.store.connection() as con:
            rows = [dict(r) for r in con.execute("SELECT id,updated_at FROM tasks WHERE status='queued' AND mode='live' AND cancel_requested=0")]
        for row in rows:
            try:
                waited = time.time() - datetime.fromisoformat(row['updated_at']).timestamp()
            except (TypeError, ValueError):
                continue
            if waited < limit:
                continue
            readiness = self.scheduling_readiness(row['id'], 'implementation', 'live')
            if readiness['ready'] or readiness['reason'] not in ('provider_unavailable_or_handoff_required', 'no_independent_reviewer_available'):
                continue  # capacity, quota floor, dependencies and retry backoff are legitimate waits
            with self.store.connection(write=True) as con:
                current = con.execute("SELECT status FROM tasks WHERE id=?", (row['id'],)).fetchone()
                if not current or current['status'] != 'queued':
                    continue
                transition(con, row['id'], 'blocked', {'reason': 'no_provider_available', 'waited_seconds': int(waited), 'last_reason': readiness['reason']})
                con.execute("UPDATE tasks SET error='no_provider_available' WHERE id=?", (row['id'],))
            expired.append(row['id'])
        return expired
