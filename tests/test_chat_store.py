"""Chat storage: the chat_messages table, schema v4 and history trimming. No model is called."""
import sqlite3
import sys as _sys
import tempfile
import unittest
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_chat_store as chat_store
from center_runtime import Center
from center_store import Store
from test_api_vnext import make_repo


class ChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.center = Center(_Path(self.tmp.name) / 'state')
        self.center.register('alpha', make_repo(self.tmp.name, 'alpha'))
        self.store = self.center.store

    def version(self):
        with self.store.connection() as con:
            return con.execute("SELECT value FROM center_meta WHERE key='schema_version'").fetchone()[0]

    def test_fresh_db_is_schema_4_with_chat_table(self):
        self.assertEqual(self.version(), '4')
        with self.store.connection() as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('chat_messages', names)

    def test_v3_db_migrates_to_4_keeping_tasks(self):
        task = self.center.submit('alpha', 'Keep me', 'Create src/b.py', ['src'], ['b exists'], 'auto', 'mock')
        with self.store.connection(write=True) as con:
            con.execute('DROP TABLE chat_messages')
            con.execute("UPDATE center_meta SET value='3' WHERE key='schema_version'")
        reopened = Store(self.store.state)
        with reopened.connection() as con:
            self.assertEqual(con.execute("SELECT value FROM center_meta WHERE key='schema_version'").fetchone()[0], '4')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT title FROM tasks WHERE id=?', (task['id'],)).fetchone()[0], 'Keep me')

    def test_future_schema_5_is_rejected(self):
        with self.store.connection(write=True) as con:
            con.execute("UPDATE center_meta SET value='5' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError, 'newer than this Center'):
            Store(self.store.state)

    def test_history_is_oldest_first_and_trim_keeps_last_50_turns(self):
        for index in range(60):
            chat_store.add_message(self.store, 'alpha', f'turn-{index:04d}xx', 'user', 'text', f'q{index}')
            chat_store.add_message(self.store, 'alpha', f'turn-{index:04d}xx', 'secretary', 'reply', f'a{index}', 'codex')
        chat_store.trim(self.store, 'alpha', keep_turns=50)
        rows = chat_store.history(self.store, 'alpha', limit=500)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]['body'], 'q10')
        self.assertEqual(rows[-1]['body'], 'a59')
        self.assertEqual([r['id'] for r in rows], sorted(r['id'] for r in rows))
        self.assertEqual(len(chat_store.history(self.store, 'alpha', limit=4)), 4)
        self.assertEqual(chat_store.history(self.store, 'alpha', limit=4)[-1]['body'], 'a59')

    def test_duplicate_turn_and_role_is_rejected(self):
        chat_store.add_message(self.store, 'alpha', 'turn-0001xx', 'user', 'text', 'hello')
        with self.assertRaises(sqlite3.IntegrityError):
            chat_store.add_message(self.store, 'alpha', 'turn-0001xx', 'user', 'text', 'hello again')
        self.assertEqual(chat_store.find_turn(self.store, 'alpha', 'turn-0001xx', 'user')['body'], 'hello')
        self.assertIsNone(chat_store.find_turn(self.store, 'alpha', 'turn-0001xx', 'secretary'))

    def test_drop_turn_removes_both_rows_so_the_id_can_be_used_again(self):
        chat_store.add_message(self.store, 'alpha', 'turn-0003xx', 'user', 'text', 'q')
        chat_store.add_message(self.store, 'alpha', 'turn-0003xx', 'secretary', 'error', 'oops')
        chat_store.add_message(self.store, 'alpha', 'turn-0004xx', 'user', 'text', 'other')
        chat_store.drop_turn(self.store, 'alpha', 'turn-0003xx')
        self.assertIsNone(chat_store.find_turn(self.store, 'alpha', 'turn-0003xx', 'user'))
        self.assertIsNone(chat_store.find_turn(self.store, 'alpha', 'turn-0003xx', 'secretary'))
        self.assertIsNotNone(chat_store.find_turn(self.store, 'alpha', 'turn-0004xx', 'user'))
        chat_store.add_message(self.store, 'alpha', 'turn-0003xx', 'user', 'text', 'again')

    def test_mark_confirmed_sets_task_id(self):
        message_id = chat_store.add_message(self.store, 'alpha', 'turn-0002xx', 'secretary', 'draft_task', '{}', 'codex')
        self.assertIsNone(chat_store.message(self.store, 'alpha', message_id)['task_id'])
        chat_store.mark_confirmed(self.store, message_id, 'abcdef123456')
        self.assertEqual(chat_store.message(self.store, 'alpha', message_id)['task_id'], 'abcdef123456')
        self.assertIsNone(chat_store.message(self.store, 'beta', message_id))


if __name__ == '__main__':
    unittest.main()
