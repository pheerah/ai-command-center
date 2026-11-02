"""Secretary chat history: one row per message, kept per project and trimmed to the latest turns."""
from __future__ import annotations

from datetime import datetime, timezone

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


def drop_unanswered_turn(store, project_id, turn_id, older_than_seconds):
    """Delete a user row that never got a secretary row and is older than `older_than_seconds`. Returns True when one was dropped."""
    with store.connection(write=True) as con:
        row = con.execute('SELECT id,created_at FROM chat_messages WHERE project_id=? AND turn_id=? AND role=?', (project_id, turn_id, 'user')).fetchone()
        answered = con.execute('SELECT 1 FROM chat_messages WHERE project_id=? AND turn_id=? AND role=?', (project_id, turn_id, 'secretary')).fetchone()
        if not row or answered:
            return False
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row['created_at'])).total_seconds()
        if age <= older_than_seconds:
            return False
        con.execute('DELETE FROM chat_messages WHERE id=?', (row['id'],))
        return True


def drop_turn(store, project_id, turn_id):
    """Delete both rows of a turn so the same turn id can be asked again (used only after the turn ended in an error)."""
    with store.connection(write=True) as con:
        con.execute('DELETE FROM chat_messages WHERE project_id=? AND turn_id=?', (project_id, turn_id))
