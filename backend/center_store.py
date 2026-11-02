"""SQLite persistence. Python alone owns queue claims; transactions stay short."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


TRANSITIONS = {
    "queued": {"assigned", "blocked", "cancelled"},
    "retry_wait": {"assigned", "blocked", "cancelled"},
    "assigned": {"running", "retry_wait", "blocked", "cancelled"},
    "running": {"implementation_done", "retry_wait", "blocked", "failed", "cancelled"},
    "implementation_done": {"gates", "blocked", "cancelled"},
    "gates": {"waiting_for_independent_review", "failed", "blocked", "cancelled"},
    "waiting_for_independent_review": {"review", "gates", "ready_for_human_approval", "blocked", "cancelled"},
    "review": {"ready_for_human_approval", "waiting_for_independent_review", "failed", "blocked", "cancelled"},
    "ready_for_human_approval": {"approved", "waiting_for_independent_review", "rejected", "cancelled"},
    "blocked": {"queued", "gates", "waiting_for_independent_review", "cancelled"},
    "failed": {"queued", "gates", "waiting_for_independent_review", "blocked", "cancelled"},
    "cancelled": set(), "approved": set(), "rejected": set(),
}


def event(con, task_id, name, detail=None):
    con.execute("INSERT INTO events(task_id,event,detail,created_at) VALUES(?,?,?,?)",
                (task_id, name, json.dumps(detail or {}, ensure_ascii=False), now()))


def transition(con, task_id, target, detail=None):
    row = con.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row or target not in TRANSITIONS.get(row["status"], set()):
        raise ValueError(f"Invalid transition: {row['status'] if row else 'missing'} -> {target}")
    con.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (target, now(), task_id))
    event(con, task_id, target, detail)


def pid_alive(pid):
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return ctypes.get_last_error() == 5
        code = wintypes.DWORD()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return not ok or code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Store:
    def __init__(self, state: Path):
        self.state = state.resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / "tasks.sqlite3"
        self.initialize()

    @contextmanager
    def connection(self, write=False):
        con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            if write:
                con.commit()
        except BaseException:
            if write:
                con.rollback()
            raise
        finally:
            con.close()

    def backup(self):
        dest = self.state / "backups" / f"tasks-{time.time_ns()}-{uuid.uuid4().hex[:6]}.sqlite3"
        dest.parent.mkdir(exist_ok=True)
        with self.connection() as source:
            target = sqlite3.connect(dest)
            try:
                source.backup(target)
            finally:
                target.close()
        return dest

    def initialize(self):
        # A v1 backup is consistent even while WAL exists. Never copy just the main file.
        with self.connection() as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            current = 0
            if 'center_meta' in names:
                version = con.execute("SELECT value FROM center_meta WHERE key='schema_version'").fetchone()
                current = int(version[0]) if version else 0
            if current > 4:
                raise ValueError('Database schema is newer than this Center; use the matching application version')
            if current == 4:
                return  # Status/heartbeat calls must not acquire a migration write lock.
            legacy = "tasks" in names and current == 0
            required = {
                'projects': {'id', 'name', 'root_path', 'config_json', 'created_at', 'updated_at'},
                'tasks': {'id', 'project_id', 'status', 'updated_at', 'created_at', 'workspace', 'title', 'prompt', 'requested_provider', 'provider', 'reviewer', 'attempt', 'branch', 'worktree', 'run_dir', 'patch_hash', 'result', 'review_result', 'error', 'approved_at', 'approved_by'},
                'events': {'id', 'task_id', 'event', 'detail', 'created_at'},
                'provider_slots': {'provider', 'worker_pid', 'lease_until'},
            }
            for table, columns in required.items():
                if table in names and not columns <= {r[1] for r in con.execute(f'PRAGMA table_info({table})')}:
                    raise ValueError(f'Unsupported legacy {table} schema; preserve database and reconcile migration explicitly')
            if current and 'sessions' in names and con.execute('SELECT 1 FROM sessions LIMIT 1').fetchone():
                raise ValueError('Stop and reconcile all sessions before upgrading the database schema')
            if current:
                service = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
                if service and pid_alive(json.loads(service[0])['pid']):
                    raise ValueError('Stop the scheduler before upgrading the database schema')
            if legacy and "provider_slots" in names:
                if any(pid_alive(r["worker_pid"]) or r["lease_until"] > time.time()
                       for r in con.execute("SELECT * FROM provider_slots")):
                    raise ValueError("Legacy worker may still be active. Stop it before migrating; no process was killed.")
        if 'tasks' in names:
            self.backup()
        with self.connection() as con:
            # Python 3.13 here embeds SQLite 3.50.4, affected by the upstream
            # WAL-reset race. Use durable rollback journaling until a fixed
            # SQLite build is installed; transactions/claim atomicity remain.
            version = sqlite3.sqlite_version_info
            fixed = version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0) or (3, 44, 6) <= version < (3, 45, 0)
            con.execute("PRAGMA journal_mode=" + ("WAL" if fixed else "DELETE"))
        with self.connection(write=True) as con:
            statements = [
                "CREATE TABLE IF NOT EXISTS center_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,root_path TEXT UNIQUE NOT NULL,config_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,prompt TEXT NOT NULL,workspace TEXT NOT NULL,requested_provider TEXT NOT NULL,provider TEXT,reviewer TEXT,status TEXT NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,branch TEXT,worktree TEXT,run_dir TEXT,patch_hash TEXT,result TEXT,review_result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,approved_at TEXT,approved_by TEXT)",
                "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES tasks(id),event TEXT NOT NULL,detail TEXT,created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,task_id TEXT UNIQUE NOT NULL REFERENCES tasks(id),provider TEXT NOT NULL,role TEXT NOT NULL,adapter TEXT NOT NULL,owner_pid INTEGER NOT NULL,child_pid INTEGER,lease_until REAL NOT NULL,started_at TEXT,model TEXT,created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS authorship(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES tasks(id),session_id TEXT NOT NULL,provider TEXT NOT NULL,attempt INTEGER NOT NULL,created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES tasks(id),kind TEXT NOT NULL,base_rev TEXT NOT NULL,patch_hash TEXT NOT NULL,provider TEXT,session_id TEXT,simulated INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL,created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS provider_health(provider TEXT PRIMARY KEY,availability TEXT NOT NULL,reason TEXT NOT NULL,cooldown_until REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),turn_id TEXT NOT NULL,role TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,provider TEXT,task_id TEXT,created_at TEXT NOT NULL,UNIQUE(project_id,turn_id,role))",
                "CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id)",
                "CREATE INDEX IF NOT EXISTS sessions_provider ON sessions(provider,role)",
            ]
            for statement in statements:
                con.execute(statement)
            columns = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
            for name, decl in {
                "mode": "TEXT NOT NULL DEFAULT 'live'", "scope_json": "TEXT NOT NULL DEFAULT '[]'",
                "acceptance_json": "TEXT NOT NULL DEFAULT '[]'", "dependencies_json": "TEXT NOT NULL DEFAULT '[]'",
                "base_rev": "TEXT", "checkpoint": "TEXT", "not_before": "REAL NOT NULL DEFAULT 0",
                "complexity": "INTEGER NOT NULL DEFAULT 2", "max_attempts": "INTEGER NOT NULL DEFAULT 3",
                "cancel_requested": "INTEGER NOT NULL DEFAULT 0", "config_json": "TEXT NOT NULL DEFAULT '{}'",
                "review_attempt": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    con.execute(f"ALTER TABLE tasks ADD COLUMN {name} {decl}")
            if not con.execute("SELECT 1 FROM center_meta WHERE key='schema_version'").fetchone():
                # Preserve all legacy records, but never trust old ready/review claims as v2 evidence.
                for row in con.execute("SELECT id FROM tasks WHERE status NOT IN ('cancelled','approved')").fetchall():
                    con.execute("UPDATE tasks SET status='blocked',error='legacy_task_requires_reconciliation',updated_at=? WHERE id=?", (now(), row[0]))
                    event(con, row[0], "migration_blocked", {"reason": "legacy_task_requires_reconciliation"})
            con.execute("INSERT INTO center_meta VALUES('schema_version','4') ON CONFLICT(key) DO UPDATE SET value=excluded.value")

    def task(self, task_id):
        with self.connection() as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("Unknown task ID")
        return dict(row)

    def evidence(self, con, task, kind, payload, provider=None, session=None, simulated=False):
        con.execute("INSERT INTO evidence(task_id,kind,base_rev,patch_hash,provider,session_id,simulated,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (task["id"], kind, task["base_rev"], task["patch_hash"], provider, session, int(simulated), json.dumps(payload), now()))
