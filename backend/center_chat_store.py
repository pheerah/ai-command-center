"""Secretary chat history: one row per message, kept per project and trimmed to the latest turns."""
from __future__ import annotations

from center_store import now

COLUMNS = 'id,turn_id,role,kind,body,provider,task_id,created_at'


def add_message(store, project_id, turn_id, role, kind, body, provider=None):
    with store.connection(write=True) as con:
        cursor = con.execute('INSERT INTO chat_messages(project_id,turn_id,role,kind,body,provider,created_at) VALUES(?,?,?,?,?,?,?)',
                             (project_id, turn_id, role, kind, body, provider, now()))
        return cursor.lastrowid


def history(store, project_id, limit=50):
    with store.connection() as con:
        rows = con.execute(f'SELECT {COLUMNS} FROM chat_messages WHERE project_id=? ORDER BY id DESC LIMIT ?', (project_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def message(store, project_id, message_id):
    with store.connection() as con:
        row = con.execute(f'SELECT {COLUMNS} FROM chat_messages WHERE project_id=? AND id=?', (project_id, message_id)).fetchone()
    return dict(row) if row else None


def find_turn(store, project_id, turn_id, role):
    with store.connection() as con:
        row = con.execute(f'SELECT {COLUMNS} FROM chat_messages WHERE project_id=? AND turn_id=? AND role=?', (project_id, turn_id, role)).fetchone()
    return dict(row) if row else None


def mark_confirmed(store, message_id, task_id):
    with store.connection(write=True) as con:
        con.execute('UPDATE chat_messages SET task_id=? WHERE id=?', (task_id, message_id))


def trim(store, project_id, keep_turns=50):
    """Keep the newest `keep_turns` turns (a turn is the user row plus the secretary row sharing a turn_id)."""
    with store.connection(write=True) as con:
        keep = [r[0] for r in con.execute('SELECT turn_id FROM chat_messages WHERE project_id=? GROUP BY turn_id ORDER BY MAX(id) DESC LIMIT ?', (project_id, keep_turns))]
        if not keep:
            return
        marks = ','.join('?' * len(keep))
        con.execute(f'DELETE FROM chat_messages WHERE project_id=? AND turn_id NOT IN ({marks})', (project_id, *keep))
