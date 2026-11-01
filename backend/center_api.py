"""Project-facing API: per-project tokens, validated operations and path-free responses.

Other projects talk to the Center only through these operations (served by
server.js under /api/v1). A token is bound to exactly one registered project.
Responses are built from an allowlist so no Center path, worktree, config or
credential detail ever reaches a caller, and patches are handed over as data
instead of letting a project read the Center's files.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

import center_chat
import center_chat_store as chat_store
from center_store import now
from center_workspace import safe_relative

TOKEN_FILE = 'api-tokens.json'
ID = re.compile(r'^[a-f0-9]{12}$')
# patch_hash is deliberately absent: the interactive approval phrase is derived from it, so exposing it would let a project's agent compute it.
PUBLIC_TASK = ('id', 'project_id', 'title', 'status', 'provider', 'reviewer', 'attempt', 'mode', 'error', 'created_at', 'updated_at',
               'requested_provider', 'base_rev', 'complexity', 'approved_at')
MAX_ACTIVE_TASKS = 20
EVENT_DETAIL = ('provider', 'role', 'model', 'effort', 'skills', 'task_kind', 'verdict', 'reason', 'status', 'plan_reasons', 'eligible_candidates')
MAX_PATCH_BYTES = 5 * 1024 * 1024


class ApiError(ValueError):
    """Bad request from a project; message is safe to return."""


# ---- tokens -------------------------------------------------------------------------------------------------------

def _token_path(state):
    return Path(state) / TOKEN_FILE


def _load(state):
    try:
        return json.loads(_token_path(state).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(state, data):
    path = _token_path(state)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class _Locked:
    """Cross-process lock around read-modify-write of the token store, so a revocation can never be lost."""

    def __init__(self, state):
        self.path = Path(state) / (TOKEN_FILE + '.lock')

    def __enter__(self):
        deadline = time.time() + 5
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    if time.time() - self.path.stat().st_mtime > 30:  # stale lock from a crashed process
                        self.path.unlink(missing_ok=True)
                        continue
                    raise ApiError('Token store is busy; try again')
                time.sleep(0.05)

    def __exit__(self, *exc):
        os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_token(state, project_id, label=''):
    """Return a new token. Only its hash is stored, so it cannot be shown again."""
    token = 'cc_' + secrets.token_urlsafe(32)
    with _Locked(state):
        data = _load(state)
        data[_digest(token)] = {'project_id': project_id, 'label': label[:80], 'created_at': now(), 'revoked': False}
        _save(state, data)
    return token


def list_tokens(state):
    return [{'id': key[:12], 'project_id': value['project_id'], 'label': value.get('label', ''), 'created_at': value['created_at'], 'revoked': value['revoked']}
            for key, value in _load(state).items()]


def revoke_token(state, token_id):
    with _Locked(state):
        data = _load(state)
        matches = [key for key in data if key.startswith(token_id) and len(token_id) >= 8]
        if len(matches) != 1:
            raise ApiError('Token id must identify exactly one token')
        data[matches[0]]['revoked'] = True
        _save(state, data)
    return {'revoked': token_id}


def project_for_token(state, token):
    entry = _load(state).get(_digest(token or ''))
    return entry['project_id'] if entry and not entry['revoked'] else None


# ---- validation ---------------------------------------------------------------------------------------------------

def _text(body, key, maximum, required=True):
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ApiError(f'{key} must be a non-empty string up to {maximum} characters')
    return value


def _strings(body, key, items, maximum, required=True):
    value = body.get(key, [] if not required else None)
    if not isinstance(value, list) or (required and not value) or len(value) > items \
            or not all(isinstance(v, str) and v.strip() and len(v) <= maximum for v in value):
        raise ApiError(f'{key} must be a list of up to {items} non-empty strings (max {maximum} characters each)')
    return value


def _task_id(value):
    if not isinstance(value, str) or not ID.match(value):
        raise ApiError('Invalid task id')
    return value


# ---- responses ----------------------------------------------------------------------------------------------------

def public_task(task, plan=None):
    result = {key: task.get(key) for key in PUBLIC_TASK}
    if plan is not None:
        result['plan'] = plan
    return result


def _plans(con, task_ids):
    plans = {}
    for task_id in task_ids:
        for row in con.execute("SELECT detail FROM events WHERE task_id=? AND event='dispatch_recorded' ORDER BY id", (task_id,)):
            detail = json.loads(row[0])
            plans.setdefault(task_id, {})[detail.get('role')] = {k: detail.get(k) for k in ('provider', 'model', 'effort', 'skills')}
    return plans


def _own_task(center, project_id, task_id):
    try:
        task = center.store.task(_task_id(task_id))
    except ValueError as exc:
        if isinstance(exc, ApiError):
            raise
        raise ApiError('Task not found') from exc
    if task['project_id'] != project_id:
        raise ApiError('Task not found')  # same message as a missing task: never confirm another project's ids
    return task


def _task_detail(center, project_id, task_id):
    _own_task(center, project_id, task_id)
    report = center.report(task_id, project_id)
    with center.store.connection() as con:
        plan = _plans(con, [task_id]).get(task_id, {})
    events = []
    for row in report['events']:
        detail = json.loads(row['detail']) if row.get('detail') else {}
        events.append({'event': row['event'], 'at': row['created_at'],
                       'detail': {k: detail[k] for k in EVENT_DETAIL if isinstance(detail, dict) and k in detail}})
    evidence = []
    for row in report['evidence']:
        payload = json.loads(row['payload']) if row.get('payload') else {}
        evidence.append({'kind': row['kind'], 'provider': row['provider'], 'simulated': bool(row['simulated']), 'at': row['created_at'],
                         'verdict': payload.get('verdict') if isinstance(payload, dict) else None,
                         'passed': payload.get('passed') if isinstance(payload, dict) else None})
    return {'task': public_task(report['task'], plan), 'events': events, 'evidence': evidence,
            'authors': sorted({a['provider'] for a in report['authorship']})}


def export_patch(center, project_id, task_id):
    task = _own_task(center, project_id, task_id)
    if task['status'] not in ('ready_for_human_approval', 'approved') or not task.get('checkpoint'):
        raise ApiError('Patch is only available after gates and independent review (ready_for_human_approval or approved)')
    saved = Path(task['checkpoint'])
    manifest = json.loads((saved / 'manifest.json').read_text(encoding='utf-8'))
    tracked = (saved / 'tracked.patch').read_bytes()
    # Recompute the identity exactly as the checkpoint did: what is exported must be what review and approval covered.
    payload = json.dumps({'base_rev': manifest['base_rev'], 'manifest': manifest['manifest']}, sort_keys=True, separators=(',', ':')).encode()
    identity = hashlib.sha256(payload + b'\0' + tracked).hexdigest()
    if identity != task['patch_hash']:
        raise ApiError('Checkpoint does not match the reviewed patch; refusing to export')
    files, total = [], len(tracked)
    for item in manifest['manifest']:
        if not item.get('untracked'):
            continue
        name = safe_relative(item['path'])
        if '.git' in Path(name).parts:
            raise ApiError('Unsafe path in patch')
        data = (saved / 'files' / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ApiError('Checkpoint integrity check failed')
        total += len(data)
        files.append({'path': item['path'], 'sha256': item['sha256'], 'size': len(data), 'content_base64': base64.b64encode(data).decode('ascii')})
    if total > MAX_PATCH_BYTES:
        raise ApiError('Patch is too large to export through the API')
    return {'task_id': task_id, 'status': task['status'], 'base_rev': task['base_rev'],
            'content_id': hashlib.sha256(b'center-api-v1:' + identity.encode()).hexdigest()[:16],  # display id, not usable to approve
            'approved': task['status'] == 'approved', 'tracked_patch_base64': base64.b64encode(tracked).decode('ascii'), 'files': files}


# ---- operations ---------------------------------------------------------------------------------------------------

def call(center, project_id, op, task_id=None, body=None):
    body = body if isinstance(body, dict) else {}
    if op == 'health':
        from center_service import service_status
        service = service_status(center)
        center.project(project_id)  # raises when the project is not registered
        return {'ok': True, 'ready': service['running'] is True, 'scheduler': service['reason'], 'project': project_id,
                'providers': {name: info['availability'] for name, info in center.provider_status().items()}}
    if op == 'submit':
        provider = body.get('provider', 'auto')
        if provider != 'auto' and provider not in center.config['providers']:
            raise ApiError('Unknown provider')
        complexity = body.get('complexity', 2)
        if type(complexity) is not int or complexity not in range(1, 6):
            raise ApiError('complexity must be an integer 1-5')
        depends = _strings(body, 'depends_on', 10, 12, required=False)
        if not all(ID.match(d) for d in depends):
            raise ApiError('Invalid dependency id')
        request_id = body.get('request_id')
        if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', request_id)):
            raise ApiError('request_id must be 8-64 letters, digits, _ or -')
        key = f'api_req:{project_id}:{request_id}' if request_id else None
        claim = None
        if key:
            known, claim = _claim_request(center, key)
            if known:  # a retried request returns the original task instead of creating a duplicate
                return {'task': public_task(center.store.task(known)), 'duplicate_request': True}
        try:
            with center.store.connection() as con:
                active = con.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND status NOT IN ('approved','cancelled','failed','blocked','rejected','ready_for_human_approval')", (project_id,)).fetchone()[0]
            if active >= MAX_ACTIVE_TASKS:
                raise ApiError(f'Too many active tasks for this project (limit {MAX_ACTIVE_TASKS}); wait for some to finish')
            read_files = _strings(body, 'read_files', 20, 200, required=False)
            task = center.submit(project_id, _text(body, 'title', 200), _text(body, 'prompt', 12000), _strings(body, 'scope', 20, 200),
                                 _strings(body, 'accept', 20, 500), provider, 'live', depends, complexity, read_set=read_files or None)
        except BaseException:
            if claim:
                _settle_request(center, key, claim, None)
            raise
        if claim:
            _settle_request(center, key, claim, task['id'])
        return {'task': public_task(task)}
    if op in ('chat', 'chat_history', 'chat_confirm'):
        return _chat(center, project_id, op, body)
    if op == 'list':
        with center.store.connection() as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC LIMIT 50', (project_id,))]
            plans = _plans(con, [r['id'] for r in rows])
        return {'tasks': [public_task(r, plans.get(r['id'], {})) for r in rows]}
    if op == 'get':
        return _task_detail(center, project_id, task_id)
    if op == 'cancel':
        _own_task(center, project_id, task_id)
        return {'task': public_task(center.cancel(task_id))}
    if op == 'patch':
        return export_patch(center, project_id, task_id)
    raise ApiError('Unknown operation')


def _chat(center, project_id, op, body):
    """Secretary chat operations (dashboard only: server.js does not route them for project tokens)."""
    if not isinstance(body, dict):
        raise ApiError('Body must be an object')
    if op == 'chat_history':
        return {'messages': chat_store.history(center.store, project_id, 100)}
    if op == 'chat':
        message, turn = body.get('message'), body.get('client_turn_id')
        if not isinstance(message, str) or not isinstance(turn, str):
            raise ApiError('message and client_turn_id are required strings')
        return center_chat.run_turn(center, project_id, message, turn)
    message_id = body.get('message_id')
    try:
        submit_body, _ = center_chat.prepare_confirmation(center, project_id, message_id, body.get('edits'))
    except center_chat.AlreadyConfirmed as done:
        return {'task': public_task(center.store.task(done.task_id)), 'duplicate_request': True}
    except ValueError as exc:
        raise ApiError(str(exc)) from None
    answer = call(center, project_id, 'submit', body=submit_body)
    chat_store.mark_confirmed(center.store, message_id, answer['task']['id'])
    return answer


CLAIM_PENDING = 'pending:'
CLAIM_STALE_SECONDS = 120


def _claim_request(center, key):
    """Reserve a request_id before the task exists, so concurrent retries cannot each create one.

    Returns (task_id, None) when an earlier call already created the task, else (None, claim) when this call owns the claim.
    """
    claim = f'{CLAIM_PENDING}{time.time()}:{secrets.token_hex(6)}'
    deadline = time.monotonic() + 30
    while True:
        with center.store.connection(write=True) as con:
            con.execute('INSERT OR IGNORE INTO center_meta(key,value) VALUES(?,?)', (key, claim))
            value = con.execute('SELECT value FROM center_meta WHERE key=?', (key,)).fetchone()[0]
            if value == claim:
                return None, claim
            if not value.startswith(CLAIM_PENDING):
                return value, None
            started = float(value[len(CLAIM_PENDING):].split(':', 1)[0] or 0)
            if time.time() - started > CLAIM_STALE_SECONDS:  # the first caller died before it created the task
                con.execute('UPDATE center_meta SET value=? WHERE key=? AND value=?', (claim, key, value))
                continue
        if time.monotonic() > deadline:
            raise ApiError('The same request is still being processed; retry shortly')
        time.sleep(0.05)


def _settle_request(center, key, claim, task_id):
    """Record the created task under the claim, or drop the claim when creating it failed."""
    with center.store.connection(write=True) as con:
        if task_id:
            con.execute('UPDATE center_meta SET value=? WHERE key=? AND value=?', (task_id, key, claim))
        else:
            con.execute('DELETE FROM center_meta WHERE key=? AND value=?', (key, claim))


PATHLIKE = re.compile(r'(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|var|etc|mnt)/)[^\s"\'<>|]*')


def scrub(value):
    """Replace anything that looks like a filesystem path in free-form text, recursively."""
    if isinstance(value, str):
        return PATHLIKE.sub('<path>', value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def run(center, project_id, request):
    """Entry for the CLI bridge; converts failures into a stable, path-free error shape."""
    try:
        data = call(center, project_id, request.get('op'), request.get('task_id'), request.get('body'))
        return {'ok': True, 'status': 200, 'data': data if request.get('op') == 'patch' else scrub(data)}
    except ApiError as exc:
        return {'ok': False, 'status': 404 if str(exc) == 'Task not found' else 400, 'error': str(exc)}
    except ValueError as exc:
        message = str(exc).replace(str(center.store.state), '<center>').replace(str(Path(__file__).resolve().parent.parent), '<center>')
        return {'ok': False, 'status': 409, 'error': scrub(message)[:300]}
    except Exception:  # never leak internals or paths
        return {'ok': False, 'status': 500, 'error': 'Center could not complete the request'}
