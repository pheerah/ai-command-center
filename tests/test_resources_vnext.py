"""Resource reservations are durable; no model or actual project install calls."""
from contextlib import contextmanager
import json
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
from center_resources import PORT_PREFIX, preparation_plan, release_port, reserve_port


class ResourceStore:
    def __init__(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
        self.con.execute('CREATE TABLE center_meta(key TEXT PRIMARY KEY,value TEXT)')
        self.con.executemany('INSERT INTO sessions VALUES(?)', [('first',), ('second',)])
        self.con.commit()

    @contextmanager
    def connection(self, write=False):
        try:
            if write:
                self.con.execute('BEGIN IMMEDIATE')
            yield self.con
            if write:
                self.con.commit()
        except BaseException:
            self.con.rollback()
            raise


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.store = ResourceStore()
        self.addCleanup(self.store.con.close)

    @patch('center_resources.socket.socket')
    def test_two_sessions_reserve_distinct_stable_ports_and_release(self, socket_factory):
        socket_factory.return_value.__enter__.return_value = MagicMock()
        first, second = reserve_port(self.store, 'first'), reserve_port(self.store, 'second')
        self.assertNotEqual(first, second)
        self.assertEqual(reserve_port(self.store, 'first'), first)
        self.assertEqual(socket_factory.call_count, 2)
        release_port(self.store, 'first')
        self.assertFalse(self.store.con.execute('SELECT 1 FROM center_meta WHERE key=?', (PORT_PREFIX + 'first',)).fetchone())

    @patch('center_resources.socket.socket')
    def test_os_collision_is_skipped_and_stale_owner_is_cleaned(self, socket_factory):
        probe = MagicMock()
        probe.bind.side_effect = [OSError('in use'), None]
        socket_factory.return_value.__enter__.return_value = probe
        self.store.con.execute('INSERT INTO center_meta VALUES(?,?)', (PORT_PREFIX + 'gone', json.dumps({'port': 22222})))
        self.store.con.commit()
        port = reserve_port(self.store, 'first')
        self.assertEqual(probe.bind.call_count, 2)
        self.assertNotEqual(probe.bind.call_args_list[0].args[0][1], port)
        self.assertFalse(self.store.con.execute('SELECT 1 FROM center_meta WHERE key=?', (PORT_PREFIX + 'gone',)).fetchone())

    def test_unknown_session_and_nonlocal_binding_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'active session'):
            reserve_port(self.store, 'gone')
        with self.assertRaisesRegex(ValueError, 'localhost'):
            reserve_port(self.store, 'first', '0.0.0.0')

    def test_only_explicit_argv_preparation_is_accepted(self):
        self.assertEqual(preparation_plan({}), [])
        plan = [['npm', 'ci', '--ignore-scripts'], ['python', '-m', 'venv', '.venv']]
        self.assertEqual(preparation_plan({'prepare_commands': plan}), plan)
        for bad in ['npm ci', ['npm ci'], [[]], [[1]], [['npm', '']], [['npm', 'x\x00y']]]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                preparation_plan({'prepare_commands': bad})
