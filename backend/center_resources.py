"""Durable session ports and explicit, audited worktree preparation plans.

Port reservations prevent collisions between Center sessions and probe the OS
before assignment. The probe socket is then closed: unrelated local processes
can still race to bind, so gates must report bind failures rather than claim
absolute OS isolation. No package install commands are inferred automatically.
"""
from __future__ import annotations

import hashlib
import json
import socket


PORT_PREFIX = 'session_port:'


def reserve_port(store, session_id, host='127.0.0.1'):
    if host != '127.0.0.1':
        raise ValueError('Test ports are localhost only')
    with store.connection(write=True) as con:
        active = {row[0] for row in con.execute('SELECT id FROM sessions')}
        if session_id not in active:
            raise ValueError('Port reservation requires an active session')
        used = set()
        existing = None
        for row in con.execute('SELECT key,value FROM center_meta WHERE key GLOB ?', (PORT_PREFIX + '*',)).fetchall():
            sid = row['key'][len(PORT_PREFIX):]
            if sid not in active:
                con.execute('DELETE FROM center_meta WHERE key=?', (row['key'],))
                continue
            port = int(json.loads(row['value'])['port'])
            used.add(port)
            if sid == session_id:
                existing = port
        if existing is not None:
            return existing
        start = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) % 30000
        for offset in range(30000):
            port = 20000 + (start + offset) % 30000
            if port in used:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind((host, port))
            except OSError:
                continue
            con.execute('INSERT INTO center_meta(key,value) VALUES(?,?)', (PORT_PREFIX + session_id, json.dumps({'host': host, 'port': port})))
            return port
    raise ValueError('No free local test port; preserve task and retry when resources are available')


def release_port(store, session_id):
    with store.connection(write=True) as con:
        con.execute('DELETE FROM center_meta WHERE key=?', (PORT_PREFIX + session_id,))


def preparation_plan(project):
    """Return explicit argv plans only; execution/evidence belongs to the owner.

    Project registration and its reviewed config snapshot authorize these
    commands. This does not make arbitrary project commands safe or sandboxed.
    Environment secrets are neither discovered nor copied by this helper.
    """
    commands = project.get('prepare_commands', [])
    if not isinstance(commands, list) or len(commands) > 16:
        raise ValueError('prepare_commands must be an explicit bounded argv list')
    result = []
    for command in commands:
        if not isinstance(command, list) or not command or len(command) > 128:
            raise ValueError('Preparation commands must be arrays of arguments, never shell strings')
        if any(not isinstance(arg, str) or not arg or '\x00' in arg or len(arg) > 8192 for arg in command):
            raise ValueError('Invalid preparation argument')
        result.append(list(command))
    return result
