"""The owner's side of a finished task: what changed and did it pass (review view), the decisions only the owner takes
(reject, send back for changes, apply an approved patch), and a plain explanation of why work is stuck.

Nothing here commits, pushes or merges: applying only reuses Center.auto_apply (git apply --check, then git apply).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from center_store import event, transition
from center_workspace import safe_relative

MAX_DIFF_BYTES = 200 * 1024
PREVIEW_CHARS = 2000
MAX_REASON = 1000
MAX_INSTRUCTIONS = 2000
ACTIVE_SESSION = 'SELECT 1 FROM sessions WHERE task_id=?'

# reason code -> (Thai explanation, actions that can help). One table, used by diagnose() and the tests.
FAILURE_ADVICE = {
    'quality_gate_failed': ('โค้ดที่เขียนยังไม่ผ่านการตรวจอัตโนมัติ (gates) ระบบเก็บผลไว้ให้ AI แก้รอบถัดไป', ('retry', 'switch_provider')),
    'review_rejected': ('ผู้ตรวจจากอีกค่ายปฏิเสธงานนี้ ข้อสังเกตของผู้ตรวจจะถูกส่งต่อให้ AI ตอนลองใหม่', ('retry', 'switch_provider')),
    'provider_blocked': ('AI ที่รับงานทำต่อไม่ได้ (ติดสิทธิ์หรือขอบเขต) ลองให้ค่ายอื่นรับงานแทนได้', ('switch_provider', 'retry')),
    'needs_narrower_scope': ('ขอบเขตไฟล์ของงานใหญ่เกินกว่า AI ตัวนี้รับได้ ลองให้ค่ายอื่นรับ หรือสร้างงานใหม่ที่แคบลง', ('switch_provider',)),
    'usage_exhausted': ('โควตาของ AI ค่ายนี้หมด ระบบพักค่ายนี้ไว้จนกว่าโควตาจะรีเซ็ต ลองให้ค่ายอื่นรับงานแทนได้', ('switch_provider', 'retry')),
    'rate_limit': ('AI ค่ายนี้ถูกจำกัดความถี่ชั่วคราว รอสักครู่แล้วลองใหม่ หรือให้ค่ายอื่นรับงานแทน', ('retry', 'switch_provider')),
    'quota_low': ('โควตาของ AI ค่ายนี้ต่ำกว่าเกณฑ์ที่ตั้งไว้ ระบบจึงไม่ให้เริ่มงานใหม่กับค่ายนี้', ('switch_provider', 'retry')),
    'auth': ('ค่ายนี้ยังไม่ได้ล็อกอินหรือสิทธิ์หมดอายุ ต้องล็อกอิน CLI ของค่ายนั้นใหม่ (ทำจากเว็บไม่ได้)', ('switch_provider',)),
    'timeout': ('AI ใช้เวลานานเกินกำหนดจึงถูกหยุด ลองใหม่หรือให้ค่ายอื่นรับงานแทน', ('retry', 'switch_provider')),
    'orphaned_active_task': ('งานค้างอยู่หลังระบบหยุดกลางคัน ระบบเก็บงานเดิมไว้ให้แล้ว ลองใหม่ได้', ('retry',)),
    'cancelled_or_lease_lost': ('ตัวรันงานหยุดกลางคัน (หรือหมดสิทธิ์ถือครองงาน) ลองใหม่ได้', ('retry',)),
    'worker_failure': ('ตัวรันงานล้มเหลวโดยไม่มีสาเหตุที่ระบุได้ ลองใหม่ หรือให้ค่ายอื่นรับงานแทน', ('retry', 'switch_provider')),
    'human_rework_requested': ('คุณสั่งให้แก้งานนี้ กำลังรอคิวทำรอบใหม่', ()),
    'rejected_by_owner': ('คุณปฏิเสธงานนี้แล้ว (จบงาน) ถ้ายังต้องการ ให้สร้างงานใหม่', ()),
    'attempt_limit': ('ลองครบจำนวนครั้งสูงสุดแล้ว ต้องสร้างงานใหม่โดยอ้างหลักฐานของงานนี้', ()),
    'unknown': ('ยังบอกสาเหตุที่แน่ชัดไม่ได้ ดูไทม์ไลน์เหตุการณ์ของงานประกอบ', ('retry',)),
}
STUCK_STATUSES = ('failed', 'blocked')
DIFF_HEADER = re.compile(r'^diff --git a/(.+?) b/(.+)$')


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit]


def count_changes(diff_text):
    """[{path, added, removed}] for each file of a unified git diff."""
    files, current = [], None
    for line in diff_text.split('\n'):
        header = DIFF_HEADER.match(line)
        if header:
            current = {'path': header.group(2), 'added': 0, 'removed': 0}
            files.append(current)
        elif current and line.startswith('+') and not line.startswith('+++'):
            current['added'] += 1
        elif current and line.startswith('-') and not line.startswith('---'):
            current['removed'] += 1
    return files


class ReviewMixin:
    # ---- decisions only the owner takes --------------------------------------------------------------------------------
    def reject(self, task_id, reason):
        reason = (reason or '').strip()
        if not reason or len(reason) > MAX_REASON:
            raise ValueError(f'A reason of 1-{MAX_REASON} characters is required')
        with self.store.connection(write=True) as con:
            row = con.execute('SELECT status,cancel_requested FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row['status'] != 'ready_for_human_approval' or row['cancel_requested']:
                raise ValueError('Only a task waiting for approval can be rejected')
            transition(con, task_id, 'rejected', {'source': 'web_ui', 'reason': reason})
            con.execute("UPDATE tasks SET error='rejected_by_owner' WHERE id=?", (task_id,))
        return self.store.task(task_id)

    def rework(self, task_id, instructions):
        """Send a task waiting for approval back for another attempt, carrying the owner's instructions.

        The attempt budget is never relaxed: when it is used up the owner must create a new task.
        """
        instructions = (instructions or '').strip()
        if not instructions or len(instructions) > MAX_INSTRUCTIONS:
            raise ValueError(f'Instructions of 1-{MAX_INSTRUCTIONS} characters are required')
        task = self.store.task(task_id)
        if task['status'] != 'ready_for_human_approval' or task['cancel_requested']:
            raise ValueError('Only a task waiting for approval can be sent back for changes')
        if task['attempt'] >= task['max_attempts']:
            raise ValueError('Attempt limit reached; create a new task referencing this evidence')
        with self.store.connection(write=True) as con:
            if con.execute(ACTIVE_SESSION, (task_id,)).fetchone():
                raise ValueError('A worker still owns this task; stop it first')
            current = con.execute('SELECT status,cancel_requested FROM tasks WHERE id=?', (task_id,)).fetchone()
            if current['status'] != 'ready_for_human_approval' or current['cancel_requested']:
                raise ValueError('Task changed while it was being sent back')
            transition(con, task_id, 'waiting_for_independent_review', {'reason': 'human_rework_requested'})
            transition(con, task_id, 'blocked', {'reason': 'human_rework_requested'})
            event(con, task_id, 'human_rework_requested', {'instructions': instructions})
            con.execute("UPDATE tasks SET error='human_rework_requested' WHERE id=?", (task_id,))
        return self.reconcile(task_id, 'human_rework_requested', stopped=True)

    def retry_from_web(self, task_id, provider=None):
        reason = 'owner_switch_provider_from_web' if provider else 'owner_retry_from_web'
        return self.reconcile(task_id, reason, stopped=True, provider=provider)

    def apply_approved(self, task_id):
        """Apply an approved patch that was not applied yet (for example, the project moved on between approval and apply)."""
        task = self.store.task(task_id)
        if task['status'] != 'approved':
            raise ValueError('Only an approved task can be applied')
        with self.store.connection() as con:
            if con.execute("SELECT 1 FROM events WHERE task_id=? AND event='auto_applied_to_workspace'", (task_id,)).fetchone():
                raise ValueError('This task has already been applied')
        return self.auto_apply(task_id)

    # ---- what the owner sees ---------------------------------------------------------------------------------------------
    def _reviewed_changes(self, task):
        if task['status'] not in ('ready_for_human_approval', 'approved') or not task.get('checkpoint') or not task.get('patch_hash'):
            return {'available': False, 'reason': 'not_ready'}
        saved = Path(task['checkpoint'])
        try:
            manifest = json.loads((saved / 'manifest.json').read_text(encoding='utf-8'))
            tracked = (saved / 'tracked.patch').read_bytes()
            identity = hashlib.sha256(json.dumps({'base_rev': manifest['base_rev'], 'manifest': manifest['manifest']}, sort_keys=True,
                                                 separators=(',', ':')).encode() + b'\0' + tracked).hexdigest()
        except (OSError, ValueError, KeyError, TypeError):
            return {'available': False, 'reason': 'checkpoint_missing'}
        if identity != task['patch_hash']:
            return {'available': False, 'reason': 'checkpoint_mismatch'}  # never show a diff that approval would not cover
        text = tracked.decode('utf-8', errors='replace')
        untracked = []
        for item in manifest['manifest']:
            if not item.get('untracked'):
                continue
            name = safe_relative(item['path'])
            preview = ''
            try:
                with (saved / 'files' / name).open('rb') as stream:
                    preview = _clip(stream.read(PREVIEW_CHARS * 4).decode('utf-8', errors='replace'), PREVIEW_CHARS)
            except OSError:
                pass
            untracked.append({'path': name, 'size': item.get('size'), 'preview': preview})
        files = [{**f, 'status': 'changed'} for f in count_changes(text)] + [{'path': u['path'], 'status': 'added', 'added': None, 'removed': None} for u in untracked]
        return {'available': True, 'files': files, 'diff': _clip(text, MAX_DIFF_BYTES), 'truncated': len(tracked) > MAX_DIFF_BYTES,
                'untracked': untracked, 'patch_hash_short': task['patch_hash'][:12]}

    def review_view(self, task_id):
        task = self.store.task(task_id)
        with self.store.connection() as con:
            evidence = [dict(r) for r in con.execute('SELECT kind,payload,provider,simulated,patch_hash,created_at FROM evidence WHERE task_id=? ORDER BY id', (task_id,))]
            applied = con.execute("SELECT 1 FROM events WHERE task_id=? AND event='auto_applied_to_workspace'", (task_id,)).fetchone() is not None
            owned = con.execute(ACTIVE_SESSION, (task_id,)).fetchone() is not None
            rework = [json.loads(r[0]).get('instructions') for r in con.execute("SELECT detail FROM events WHERE task_id=? AND event='human_rework_requested' ORDER BY id", (task_id,))]
            rejected = con.execute("SELECT detail FROM events WHERE task_id=? AND event='rejected' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()

        def latest(kind):
            rows = [e for e in evidence if e['kind'] == kind and e['patch_hash'] == task['patch_hash']]
            if not rows:
                return None, None
            try:
                return json.loads(rows[-1]['payload']), rows[-1]
            except ValueError:
                return None, rows[-1]

        gates_payload, _ = latest('gates')
        gates = [{'command': ' '.join(str(a) for a in o.get('argv', [])), 'passed': o.get('code') == 0 and not o.get('error')}
                 for o in (gates_payload or {}).get('outcomes', [])]
        review_payload, review_row = latest('review')
        review = None if not review_payload else {'verdict': review_payload.get('verdict'), 'summary': str(review_payload.get('summary', ''))[:3000],
                                                    'provider': review_row['provider'], 'simulated': bool(review_row['simulated'])}
        human_payload, _ = latest('human_review')
        status = task['status']
        waiting = status == 'ready_for_human_approval' and not task['cancel_requested']
        return {
            'task': task, 'changes': self._reviewed_changes(task), 'gates': gates, 'review': review,
            'human_review': None if not human_payload else {'summary': str(human_payload.get('summary', ''))[:1000]},
            'applied': applied, 'rework_requests': [r for r in rework if r],
            'rejected_reason': None if not rejected else json.loads(rejected[0]).get('reason'),
            'actions': {'approve': waiting, 'reject': waiting,
                        'rework': waiting and not owned and task['attempt'] < task['max_attempts'],
                        'apply': status == 'approved' and not applied},
            'suggested_commit_message': self.suggested_commit_message(task) if status == 'approved' else None,
        }

    @staticmethod
    def suggested_commit_message(task):
        """Text for the owner to copy: Center itself never commits."""
        return _clip(' '.join(str(task['title']).split()), 72)

    # ---- why is it stuck, and what can the owner do about it ---------------------------------------------------------------
    def diagnose(self, task_id):
        task = self.store.task(task_id)
        status = task['status']
        with self.store.connection() as con:
            review = con.execute("SELECT payload FROM evidence WHERE task_id=? AND kind='review' AND patch_hash IS ? ORDER BY id DESC LIMIT 1",
                                 (task_id, task['patch_hash'])).fetchone()
            live = con.execute(ACTIVE_SESSION, (task_id,)).fetchone() is not None
            tried = {r[0] for r in con.execute('SELECT DISTINCT provider FROM authorship WHERE task_id=?', (task_id,))}
        try:
            rejected_review = bool(review) and json.loads(review[0]).get('verdict') == 'rejected'
        except (ValueError, TypeError, AttributeError):
            rejected_review = False
        if status not in STUCK_STATUSES and task['error'] not in ('rejected_by_owner', 'human_rework_requested'):
            return {'task_id': task_id, 'reason_code': None, 'explanation': None, 'actions': []}
        error = task['error'] or ''
        code = error if error in FAILURE_ADVICE else ('review_rejected' if rejected_review and not error else 'unknown')
        if task['attempt'] >= task['max_attempts'] and status in STUCK_STATUSES:
            code = 'attempt_limit'
        explanation, wanted = FAILURE_ADVICE[code]
        config = json.loads(task['config_json'] or '{}')
        status_ok = status in STUCK_STATUSES and not task['cancel_requested'] and not live and task['attempt'] < task['max_attempts']
        health = self.provider_status()
        untried = [p for p in config.get('allowed_providers', []) if p != task['provider'] and p not in tried and health.get(p, {}).get('availability') != 'unavailable']
        actions = []
        for action in wanted:
            if action == 'retry':
                actions.append({'action': 'retry', 'enabled': status_ok})
            elif action == 'switch_provider':
                actions.append({'action': 'switch_provider', 'enabled': status_ok and bool(untried), 'providers': untried})
        return {'task_id': task_id, 'status': status, 'reason_code': code, 'explanation': explanation, 'actions': actions}

    # ---- facts about the system, for the secretary (read-only) -----------------------------------------------------------------
    def health_summary(self):
        from center_service import service_status
        service = service_status(self)
        quota = self.quota_reader() or {}
        providers = {}
        for name, info in self.provider_status().items():
            providers[name] = {'availability': info.get('availability'), 'reason': info.get('reason'),
                               'quota_left_percent': center_quota_remaining(quota.get(name))}
        with self.store.connection() as con:
            counts = {r[0]: r[1] for r in con.execute('SELECT status,COUNT(*) FROM tasks GROUP BY status')}
            stuck = [dict(r) for r in con.execute("SELECT id,project_id,title,status,error FROM tasks WHERE status IN ('failed','blocked') ORDER BY updated_at DESC LIMIT 5")]
        return {'scheduler': {'running': service.get('running'), 'mode': service.get('mode'), 'reason': service.get('reason')},
                'live_execution': bool(self.config.get('live_execution')), 'providers': providers, 'tasks_by_status': counts, 'stuck_tasks': stuck}


def center_quota_remaining(reading):
    import center_quota
    value = center_quota.remaining(reading, best_group=True)
    return None if value is None else round(value, 1)
