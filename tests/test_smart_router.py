"""Integration tests use existing local Git history; never create commits."""
import json
import os
import shutil
import stat
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from center_runtime import Center
from center_store import Store, transition
from center_workspace import git, patch
from center_worker import classify_error


def make_project(destination, project_id, gate=None):
    destination.mkdir()
    subprocess.run(["git", "init", "--quiet", str(destination)], check=True, capture_output=True)
    shutil.copytree(ROOT / ".git/objects", destination / ".git/objects", dirs_exist_ok=True)
    revision = git(ROOT, "rev-parse", "HEAD")
    git(destination, "checkout", "--quiet", "--detach", revision)
    config = {"project_id": project_id, "name": project_id, "allowed_providers": ["codex", "claude"],
              "context_scope": ["src", "tests"], "approval_policy": "human_required", "auto_commit": False,
              "quality_gates": gate or [["python", "-c", "from pathlib import Path; assert Path('src/center_mock.txt').read_text() == 'Center mock implementation\\n'"]], "base_revision": "HEAD"}
    path = destination / ".git" / "center-project.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class CenterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="center_test_")).resolve()
        self.addCleanup(self.cleanup)
        test_config = json.loads((ROOT / 'center.config.json').read_text())
        test_config['live_execution'] = False
        test_config['ide_reserved_sessions'] = 0  # the shipped config reserves a slot for the IDE; these tests model the full capacity
        self.config_path = self.root / 'center.config.json'
        self.config_path.write_text(json.dumps(test_config))
        self.center = Center(self.root / "state", self.config_path)
        self.a = self.root / "project-a"
        self.b = self.root / "project-b"
        self.ca = make_project(self.a, "project-a")
        self.cb = make_project(self.b, "project-b")
        self.center.register("project-a", self.a, self.ca)
        self.center.register("project-b", self.b, self.cb)

    def cleanup(self):
        if self.root.parent != Path(tempfile.gettempdir()).resolve() or not self.root.name.startswith('center_test_'):
            raise ValueError('Unsafe test cleanup target')
        target = "\\\\?\\" + str(self.root) if os.name == "nt" else str(self.root)
        def writable_retry(func, path, error):
            if not isinstance(error, PermissionError):
                raise error
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(target, onexc=writable_retry)

    def task(self, project="project-a", mode="mock", provider="auto", mock=None):
        return self.center.submit(project, "Add scoped file", "Create the requested sample file", ["src"], ["Tests pass"], provider=provider, mode=mode, mock=mock)

    def claim_and_prepare(self, task, adapter="mock", provider="codex"):
        s = self.center.claim(task["id"], "implementation", adapter, provider)
        self.center.prepare(task["id"])
        self.center.started(s["id"], "test-fixture-process")
        return s

    def implement_manually(self, task, adapter="mock", provider="codex"):
        s = self.claim_and_prepare(task, adapter, provider)
        task = self.center.store.task(task["id"])
        target = Path(task["worktree"]) / "src/center_mock.txt"
        target.parent.mkdir(parents=True)
        target.write_text("Center mock implementation\n", encoding="utf-8")
        response = {"task_id": task["id"], "base_rev": task["base_rev"], "simulated": adapter == "mock"}
        self.center.complete(s["id"], response)
        return self.center.store.task(task["id"])

    def test_registration_isolation_and_id_binding(self):
        with self.assertRaises(ValueError):
            self.center.register("project-a", self.b, self.cb)
        with self.assertRaises(ValueError):
            self.center.register("nested", self.a / "src", self.ca)
        with self.assertRaises(ValueError):
            self.center.submit("missing", "x", "x", ["src"], ["x"])
        with self.assertRaises(ValueError):
            self.center.submit("project-a", "x", "x", ["../project-b"], ["x"])
        with self.assertRaises(ValueError):
            self.center.submit("project-a", "x", "x", ["server.js"], ["x"])

    def test_dirty_project_is_preserved_and_rejected(self):
        (self.a / "user-work.txt").write_text("keep")
        with self.assertRaises(ValueError):
            self.task()
        self.assertEqual((self.a / "user-work.txt").read_text(), "keep")

    def test_validated_transitions(self):
        t = self.task()
        with self.center.store.connection(write=True) as con:
            with self.assertRaises(ValueError):
                transition(con, t["id"], "approved")
        self.assertEqual(self.center.store.task(t["id"])["status"], "queued")

    def test_multi_session_capacity_and_no_double_claim(self):
        tasks = [self.task() for _ in range(5)]
        a = self.center.claim(tasks[0]["id"], "implementation", "mock", "codex")
        b = self.center.claim(tasks[1]["id"], "implementation", "mock", "codex")
        self.assertTrue(a and b)
        self.assertIsNone(self.center.claim(tasks[2]["id"], "implementation", "mock", "codex"))
        self.assertTrue(self.center.claim(tasks[2]["id"], "implementation", "mock", "claude"))
        self.assertTrue(self.center.claim(tasks[3]["id"], "implementation", "mock", "claude"))
        self.assertIsNone(self.center.claim(tasks[4]["id"], "implementation", "mock"))
        self.assertIsNone(self.center.claim(tasks[0]["id"], "implementation", "mock", "codex"))
        events = self.center.report(tasks[0]["id"])["events"]
        self.assertNotIn("worker_started", [e["event"] for e in events])

    def test_atomic_claim_across_processes(self):
        t = self.task()
        script = "from center_runtime import Center; import sys,json; c=Center(sys.argv[1]); s=c.claim(sys.argv[2],'implementation','mock','codex'); print(json.dumps(bool(s)))"
        ps = [subprocess.Popen([sys.executable, "-c", script, str(self.center.store.state), t["id"]], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        results = []
        for p in ps:
            out, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, err.decode())
            results.append(json.loads(out))
        self.assertEqual(sum(results), 1)

    def test_mock_maestro_pipeline_two_projects(self):
        initial_a = git(self.a, "rev-parse", "HEAD")
        initial_b = git(self.b, "rev-parse", "HEAD")
        for project in ("project-a", "project-b"):
            t = self.task(project)
            result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
            self.assertEqual(result["state"], "waiting_for_independent_review", result)
            review = self.center.run_phase(t["id"], "review", "mock", "claude")
            self.assertTrue(review["simulated"], review)
            report = self.center.report(t["id"])
            self.assertEqual(report["task"]["status"], "waiting_for_independent_review")
            self.assertNotEqual(report["task"]["provider"], report["task"]["reviewer"])
            self.assertIn("mock_pipeline_complete", [e["event"] for e in report["events"]])
            self.assertEqual(report["sessions"], [])
            with self.assertRaises(ValueError):
                self.center.approve(t["id"])
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), initial_a)
        self.assertEqual(git(self.b, "rev-parse", "HEAD"), initial_b)
        self.assertFalse((self.a / "src/center_mock.txt").exists())
        self.assertFalse((self.b / "src/center_mock.txt").exists())

    def test_patch_covers_new_binary_and_deleted_files(self):
        t = self.task()
        self.claim_and_prepare(t)
        t = self.center.store.task(t["id"])
        root = Path(t["worktree"])
        (root / "src").mkdir()
        p = root / "src/new.bin"
        p.write_bytes(b"\0one")
        a = self.center._task_patch(t)["patch_hash"]
        p.write_bytes(b"\0two")
        b = self.center._task_patch(t)["patch_hash"]
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            patch(root, t["base_rev"], ["tests"])
        (root / "src/.env").write_text("dummy-not-a-secret")
        with self.assertRaisesRegex(ValueError, "Sensitive"):
            self.center._task_patch(t)

    def test_out_of_scope_and_symlink_detection(self):
        t = self.task()
        self.claim_and_prepare(t)
        t = self.center.store.task(t["id"])
        root = Path(t["worktree"])
        (root / "outside.txt").write_text("out")
        with self.assertRaisesRegex(ValueError, "Out-of-scope"):
            self.center._task_patch(t)

    def test_gate_failure_cannot_be_ready(self):
        cfg = json.loads(self.ca.read_text())
        cfg["quality_gates"] = [["python", "-c", "raise SystemExit(9)"]]
        self.ca.write_text(json.dumps(cfg))
        self.center.register("project-a", self.a, self.ca, confirm_config_change=True)
        t = self.task()
        result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
        self.assertEqual(result["state"], "failed", result)
        self.assertEqual(self.center.report(t["id"])["evidence"], [])

    def test_missing_gate_tool_is_failure(self):
        cfg = json.loads(self.ca.read_text())
        cfg["quality_gates"] = [["center_missing_executable_012345"]]
        self.ca.write_text(json.dumps(cfg))
        self.center.register("project-a", self.a, self.ca, confirm_config_change=True)
        t = self.task()
        result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
        self.assertNotEqual(result["state"], "ready_for_human_approval")
        self.assertFalse(self.center.report(t["id"])["evidence"])

    def test_auth_config_model_errors_do_not_retry(self):
        for error in ("auth", "config", "invalid_model"):
            t = self.task(mock={"failures": [error]})
            result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
            self.assertEqual(result["state"], "blocked", result)
            self.assertEqual(self.center.store.task(t["id"])["provider"], "codex")
            self.assertTrue(self.center.store.task(t["id"])["checkpoint"])

    def test_retry_preserves_untracked_checkpoint_new_attempt(self):
        t = self.task(mock={"failures": ["worker_failure"]})
        result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
        self.assertEqual(result["state"], "retry_wait", result)
        old = self.center.store.task(t["id"])
        self.assertGreater(old["not_before"], time.time())
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET not_before=0 WHERE id=?", (t["id"],))
        result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
        new = self.center.store.task(t["id"])
        self.assertEqual(result["state"], "waiting_for_independent_review", result)
        self.assertNotEqual(old["worktree"], new["worktree"])
        self.assertTrue(Path(old["worktree"]).exists())
        self.assertTrue((Path(new["worktree"]) / "src/center_mock.txt").exists())

    def test_reassignment_keeps_all_authors_and_no_self_review(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        self.center.failure(s["id"], "auth")
        self.center.reconcile(t["id"], "explicit fallback after auth failure", True, "claude")
        result = self.center.run_phase(t["id"], "implementation", "mock", "claude")
        self.assertEqual(result["state"], "waiting_for_independent_review", result)
        with self.assertRaisesRegex(ValueError, "No eligible provider"):
            self.center.claim(t["id"], "review", "mock")
        self.assertEqual({r["provider"] for r in self.center.report(t["id"])["authorship"]}, {"codex", "claude"})

    def test_patch_change_invalidates_gates_and_review(self):
        t = self.implement_manually(self.task())
        p = Path(t["worktree"]) / "src/center_mock.txt"
        p.write_text("changed")
        with self.assertRaisesRegex(ValueError, "Patch changed"):
            self.center.validate_evidence(t["id"], False)
        self.assertNotEqual(self.center.store.task(t["id"])["status"], "ready_for_human_approval")

    def test_dependencies_are_same_project_and_must_be_approved(self):
        a = self.task()
        with self.assertRaises(ValueError):
            self.center.submit("project-b", "x", "x", ["src"], ["x"], mode="mock", dependencies=[a["id"]])
        b = self.center.submit("project-a", "x", "x", ["src"], ["x"], mode="mock", dependencies=[a["id"]])
        self.assertIsNone(self.center.claim(b["id"], "implementation", "mock"))

    def test_google_unavailable_quota_unknown_no_live_calls(self):
        # The shipped config now enables Google; this test models the exhausted-quota state explicitly.
        self.center.set_provider("google", "unavailable", "usage_exhausted")
        p = self.center.provider_status()["google"]
        self.assertEqual(p["availability"], "unavailable")
        self.assertEqual(p["reason"], "usage_exhausted")
        self.assertEqual(p["reset_at"], "unknown")
        self.assertEqual(p["quota"], "unknown")
        live = self.task(mode="live")
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.center.claim(live["id"], "implementation", "live", "codex")
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            self.center.claim(live["id"], "implementation", "mock", "codex")

    def test_rate_limit_cooldown_and_explicit_fallback(self):
        t = self.task(mock={"failures": ["rate_limit"]})
        result = self.center.run_phase(t["id"], "implementation", "mock", "codex")
        self.assertEqual(result["state"], "retry_wait", result)
        self.assertGreater(self.center.provider_status()["codex"]["cooldown_until"], time.time())
        self.assertNotIn("codex", self.center.candidates(self.center.store.task(t["id"]), "implementation"))

    def test_recovery_never_reclaims_living_or_handoff_worker(self):
        t = self.task()
        s = self.center.claim(t["id"], "implementation", "mock", "codex")
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE sessions SET lease_until=0 WHERE id=?", (s["id"],))
        self.center.recover()
        self.assertEqual(self.center.session(s["id"])["id"], s["id"])
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE sessions SET owner_pid=0 WHERE id=?", (s["id"],))
        self.center.recover()
        self.assertEqual(self.center.store.task(t["id"])["status"], "blocked")

    def test_cancel_running_process_cleanup(self):
        t = self.task(mock={"sleep": 8})
        args = [sys.executable, str(ROOT / "smart_router.py"), "--state-dir", str(self.center.store.state), "run", t["id"]]
        p = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 25
        child = None
        while time.monotonic() < deadline:
            report = self.center.report(t["id"])
            if report["sessions"] and report["sessions"][0]["started_at"]:
                child = report["sessions"][0]["child_pid"]
                break
            time.sleep(0.1)
        self.assertIsNotNone(child)
        self.center.cancel(t["id"])
        out, err = p.communicate(timeout=25)
        self.assertEqual(p.returncode, 0, (out, err))
        self.assertEqual(self.center.store.task(t["id"])["status"], "cancelled")
        self.assertEqual(self.center.report(t["id"])["sessions"], [])
        from center_store import pid_alive
        self.assertFalse(pid_alive(child))

    def test_handoff_requires_start_ack_and_human_tty(self):
        t = self.task(mode="live")
        s = self.center.claim(t["id"], "implementation", "handoff", "codex")
        self.center.prepare(t["id"])
        with self.assertRaisesRegex(ValueError, "started"):
            self.center.complete(s["id"], {"task_id": t["id"], "base_rev": t["base_rev"]})
        self.assertEqual(self.center.store.task(t["id"])["status"], "assigned")

    def test_backup_and_legacy_migration_preserve_records(self):
        state = self.root / "legacy"
        state.mkdir()
        con = sqlite3.connect(state / "tasks.sqlite3")
        schema = (ROOT / "tests/fixtures/legacy-schema.sql").read_text(encoding="utf-8")
        con.executescript(schema)
        con.execute("INSERT INTO tasks(id,title,prompt,workspace,requested_provider,status,created_at,updated_at) VALUES('legacy','x','x','x','codex','ready_for_human_approval','x','x')")
        con.commit()
        con.close()
        store = Store(state)
        self.assertEqual(store.task("legacy")["status"], "blocked")
        self.assertEqual(len(list((state / "backups").glob("*.sqlite3"))), 1)
        backup = store.backup()
        from contextlib import closing
        with closing(sqlite3.connect(backup)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)

    def test_error_classification(self):
        for message, expected in (("401 authentication failed", "auth"), ("unknown model", "invalid_model"), ("429 rate limit", "rate_limit"), ("unknown option", "config")):
            self.assertEqual(classify_error(message), expected)

    def test_live_handoff_review_binds_patch_and_refuses_piped_approval(self):
        t = self.implement_manually(self.task(mode="live"), "handoff", "codex")
        with self.assertRaises(ValueError):
            self.center.claim(t["id"], "review", "handoff", "codex")
        s = self.center.claim(t["id"], "review", "handoff", "claude")
        self.center.started(s["id"], "synthetic-review-fixture")
        response = {"task_id": t["id"], "base_rev": t["base_rev"], "patch_hash": "wrong", "verdict": "approved", "summary": "fixture", "simulated": False}
        with self.assertRaises(ValueError):
            self.center.complete(s["id"], response)
        response["patch_hash"] = t["patch_hash"]
        self.assertEqual(self.center.complete(s["id"], response)["state"], "ready_for_human_approval")
        with mock_patch('sys.stdin.isatty', return_value=False), self.assertRaisesRegex(ValueError, 'interactive terminal'):
            self.center.approve(t["id"])
        (Path(t["worktree"]) / "src/center_mock.txt").write_text("changed after review")
        with self.assertRaisesRegex(ValueError, 'Patch changed'):
            self.center.validate_evidence(t["id"])
        self.assertEqual(self.center.store.task(t["id"])["status"], "waiting_for_independent_review")

    def test_rejected_review_never_becomes_ready(self):
        t = self.implement_manually(self.task(mode="live"), "handoff", "codex")
        s = self.center.claim(t["id"], "review", "handoff", "claude")
        self.center.started(s["id"], "synthetic-rejection-fixture")
        response = {"task_id": t["id"], "base_rev": t["base_rev"], "patch_hash": t["patch_hash"], "verdict": "rejected", "summary": "fixture rejects", "simulated": False}
        self.assertEqual(self.center.complete(s["id"], response)["state"], "failed")

    def test_cross_project_connector_scope_is_enforced(self):
        t = self.task(project="project-b")
        r = subprocess.run([sys.executable, str(ROOT / 'smart_router.py'), '--state-dir', str(self.center.store.state), '--project-id', 'project-a', 'status', t['id']], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("another project's", r.stdout)
        self.assertNotIn(t['prompt'], r.stdout)

    def test_expired_handoff_keeps_slot_until_explicit_reconciliation(self):
        t = self.task(mode="live")
        s = self.center.claim(t['id'], 'implementation', 'handoff', 'codex')
        self.center.prepare(t['id'])
        self.center.started(s['id'], 'synthetic-ide-fixture')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE sessions SET lease_until=0 WHERE id=?', (s['id'],))
        self.center.recover()
        self.assertEqual(self.center.store.task(t['id'])['status'], 'blocked')
        self.assertEqual(self.center.session(s['id'])['id'], s['id'])
        self.assertFalse(self.center.heartbeat(s['id']))
        with self.assertRaises(ValueError):
            self.center.reconcile(t['id'], 'no stop proof', False, 'claude')
        self.center.reconcile(t['id'], 'fixture worker stopped', True, 'claude')
        self.assertEqual(self.center.store.task(t['id'])['requested_provider'], 'claude')

    def test_attempts_are_bounded_without_implicit_takeover(self):
        t = self.task()
        for i in range(3):
            s = self.claim_and_prepare(t)
            result = self.center.failure(s['id'], 'worker_failure')
            with self.center.store.connection(write=True) as con:
                con.execute('UPDATE tasks SET not_before=0 WHERE id=?', (t['id'],))
            self.assertEqual(result['state'], 'failed' if i == 2 else 'retry_wait')
        with self.assertRaisesRegex(ValueError, 'Attempt limit'):
            self.center.reconcile(t['id'], 'try beyond budget', True, 'claude')
        self.assertEqual(self.center.store.task(t['id'])['provider'], 'codex')

    def test_start_stop_restart_service_has_no_autostart(self):
        command = [sys.executable, str(ROOT / 'smart_router.py'), '--state-dir', str(self.center.store.state)]
        p = subprocess.Popen([*command, 'serve', '--mode', 'mock'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        from smart_router import service_status
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not service_status(self.center)['running']:
                time.sleep(0.1)
            self.assertTrue(service_status(self.center)['running'])
            status = service_status(self.center)
            (self.center.store.state / f"stop-{status['instance']}").touch()
            out, err = p.communicate(timeout=15)
            self.assertEqual(p.returncode, 0, (out, err))
            self.assertFalse(service_status(self.center)['running'])
        finally:
            if p.poll() is None:
                p.terminate()
                p.communicate(timeout=15)

    def test_timeout_terminates_owned_process(self):
        from center_process import execute
        from center_store import pid_alive
        result = execute([sys.executable, '-c', 'import time; time.sleep(30)'], self.root, self.root / 'timeout.log', 0.3, lambda: True, lambda pid: None)
        self.assertEqual(result['error'], 'timeout')
        self.assertFalse(pid_alive(result['pid']))

    def test_checkpoint_io_failure_settles_state_and_keeps_worktree(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        worktree = self.center.store.task(t['id'])['worktree']
        with mock_patch.object(self.center, 'save_checkpoint', side_effect=OSError('fixture I/O failure')):
            result = self.center.failure(s['id'], 'worker_failure')
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('checkpoint_failed:OSError', result['error'])
        self.assertEqual(self.center.report(t['id'])['sessions'], [])
        self.assertTrue(Path(worktree).exists())

    def test_orphan_active_task_is_recoverable(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        with self.center.store.connection(write=True) as con:
            con.execute('DELETE FROM sessions WHERE id=?', (s['id'],))
        self.center.recover()
        self.assertEqual(self.center.store.task(t['id'])['status'], 'blocked')
        self.assertEqual(self.center.store.task(t['id'])['error'], 'orphaned_active_task')

    def test_crash_between_second_claim_and_prepare_preserves_prior_checkpoint(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        self.center.failure(s['id'], 'worker_failure')
        previous = self.center.store.task(t['id'])
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET not_before=0 WHERE id=?', (t['id'],))
        s = self.center.claim(t['id'], 'implementation', 'mock', 'codex')
        current = self.center.store.task(t['id'])
        self.assertIsNone(current['worktree'])
        self.center.failure(s['id'], 'config')
        current = self.center.store.task(t['id'])
        self.assertEqual(current['checkpoint'], previous['checkpoint'])
        self.assertEqual(current['error'], 'config')
        self.assertTrue(Path(previous['worktree']).exists())

    def test_handoff_cancel_requires_stop_ack_and_cannot_be_requeued(self):
        t = self.task(mode='live')
        s = self.claim_and_prepare(t, 'handoff')
        self.center.cancel(t['id'])
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE sessions SET lease_until=0 WHERE id=?', (s['id'],))
        self.center.recover()
        with self.assertRaisesRegex(ValueError, 'Cancellation'):
            self.center.reconcile(t['id'], 'cannot discard cancellation', True, 'claude')
        result = self.center.acknowledge_stop(s['id'], 'IDE stopped editing and ended worker')
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(self.center.report(t['id'])['sessions'], [])

    def test_cancel_between_last_gate_and_settlement_is_final(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        current = self.center.store.task(t['id'])
        file = Path(current['worktree']) / 'src/center_mock.txt'
        file.parent.mkdir()
        file.write_text('Center mock implementation\n')
        original = self.center._task_patch
        def racing_patch(task):
            data = original(task)
            if self.center.store.task(task['id'])['status'] == 'gates':
                self.center.cancel(task['id'])
            return data
        with mock_patch.object(self.center, '_task_patch', side_effect=racing_patch):
            result = self.center.complete(s['id'], {'task_id': t['id'], 'base_rev': t['base_rev'], 'simulated': True})
        self.assertEqual(result['state'], 'cancelled')
        self.assertFalse(self.center.report(t['id'])['evidence'])

    def test_environment_allowlist_does_not_forward_credentials(self):
        from center_process import worker_env
        dummy = {'GH_TOKEN': 'fixture', 'GITHUB_TOKEN': 'fixture', 'AWS_SECRET_ACCESS_KEY': 'fixture', 'CUSTOM_PASSWORD': 'fixture', 'NPM_TOKEN': 'fixture', 'OPENAI_API_KEY': 'fixture'}
        with mock_patch.dict(os.environ, dummy):
            env = worker_env()
        self.assertFalse(set(dummy) & set(env))
        self.assertIn('PATH', {name.upper() for name in env})

    def test_literal_git_pathspec_and_ignored_scoped_file_checkpoint(self):
        t = self.task()
        s = self.claim_and_prepare(t)
        current = self.center.store.task(t['id'])
        root = Path(current['worktree'])
        (root / 'src').mkdir()
        route = root / 'src/[route].js'
        route.write_text('module.exports = 42;\n')
        git(root, 'add', '--', 'src/[route].js')
        (self.a / '.git/info/exclude').write_text('/src/ignored.txt\n')
        (root / 'src/ignored.txt').write_text('must survive retry')
        self.center.save_checkpoint(t['id'])
        before = self.center._task_patch(self.center.store.task(t['id']))
        self.assertIn('src/[route].js', before['diff'].decode())
        self.assertIn('src/ignored.txt', [m['path'] for m in before['manifest']])
        self.center.failure(s['id'], 'worker_failure')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET not_before=0 WHERE id=?', (t['id'],))
        self.center.claim(t['id'], 'implementation', 'mock', 'codex')
        restored = self.center.prepare(t['id'])
        self.assertEqual((Path(restored['worktree']) / 'src/ignored.txt').read_text(), 'must survive retry')
        self.assertEqual((Path(restored['worktree']) / 'src/[route].js').read_text(), route.read_text())

    def test_heartbeat_writes_only_at_configured_interval(self):
        t = self.task()
        s = self.center.claim(t['id'], 'implementation', 'mock', 'codex')
        self.assertTrue(self.center.heartbeat(s['id'], force=False))
        self.assertEqual(self.center.session(s['id'])['lease_until'], s['lease_until'])
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE sessions SET lease_until=? WHERE id=?', (time.time() + 20, s['id']))
        self.assertTrue(self.center.heartbeat(s['id'], force=False))
        self.assertGreater(self.center.session(s['id'])['lease_until'], time.time() + 25)

    def test_status_initialization_does_not_take_write_lock_and_future_schema_rejected(self):
        script = 'from center_store import Store;from pathlib import Path;import sys;Store(Path(sys.argv[1]));print("ok")'
        with self.center.store.connection(write=True):
            p = subprocess.run([sys.executable, '-c', script, str(self.center.store.state)], cwd=ROOT, capture_output=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
        with self.center.store.connection(write=True) as con:
            con.execute("UPDATE center_meta SET value='999' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError, 'newer'):
            Store(self.center.store.state)

    def test_project_status_filters_before_global_limit(self):
        t = self.task()
        with self.center.store.connection(write=True) as con:
            for i in range(110):
                con.execute("INSERT INTO tasks(id,project_id,title,prompt,workspace,requested_provider,status,created_at,updated_at) VALUES(?,?,'other','other',?,'auto','queued','9999','9999')", (f'other-{i}', 'project-b', str(self.b)))
        report = self.center.report(project_id='project-a')
        self.assertEqual([row['id'] for row in report['tasks']], [t['id']])

    def test_cleanup_kills_grandchild_after_root_has_exited(self):
        from center_process import execute
        from center_store import pid_alive
        marker = self.root / 'grandchild.pid'
        child_code = 'import time;time.sleep(30)'
        code = f'import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-c",{child_code!r}]);Path({str(marker)!r}).write_text(str(p.pid));time.sleep(0.5)'
        result = execute([sys.executable, '-c', code], self.root, self.root / 'tree.log', 10, lambda: True, lambda pid: None)
        self.assertEqual(result['code'], 0)
        grandchild = int(marker.read_text())
        deadline = time.monotonic() + 3
        while pid_alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(pid_alive(grandchild))

    def test_partial_edits_before_start_ack_keep_conservative_authorship(self):
        t = self.task()
        s = self.center.claim(t['id'], 'implementation', 'mock', 'codex')
        current = self.center.prepare(t['id'])
        file = Path(current['worktree']) / 'src/partial.txt'
        file.parent.mkdir()
        file.write_text('worker changed this before the parent saw its start marker')
        self.assertEqual(self.center.report(t['id'])['authorship'], [])
        self.center.failure(s['id'], 'config')
        authors = self.center.report(t['id'])['authorship']
        self.assertEqual([r['provider'] for r in authors], ['codex'])
        events = [r['event'] for r in self.center.report(t['id'])['events']]
        self.assertNotIn('worker_started', events)
        self.assertIn('unacknowledged_edits_attributed_conservatively', events)

    def test_gate_recheck_preserves_completed_implementation(self):
        flag = self.root / 'gate-ready'
        cfg = json.loads(self.ca.read_text())
        cfg['quality_gates'] = [['python', '-c', f'from pathlib import Path; assert Path({str(flag)!r}).exists()']]
        self.ca.write_text(json.dumps(cfg))
        self.center.register('project-a', self.a, self.ca, confirm_config_change=True)
        t = self.task()
        self.assertEqual(self.center.run_phase(t['id'], 'implementation', 'mock', 'codex')['state'], 'failed')
        before = self.center.store.task(t['id'])
        flag.touch()
        result = self.center.recheck_gates(t['id'], 'Required local test fixture became available')
        self.assertEqual(result['state'], 'waiting_for_independent_review')
        self.assertEqual(self.center.store.task(t['id'])['attempt'], before['attempt'])
        self.assertEqual(len([e for e in self.center.report(t['id'])['events'] if e['event']=='worker_started']), 1)

    def test_explicit_review_retry_does_not_reimplement_or_self_approve(self):
        t = self.implement_manually(self.task(mode='live'), 'handoff', 'codex')
        s = self.center.claim(t['id'], 'review', 'handoff', 'claude')
        self.center.started(s['id'], 'fixture-rejected-review')
        response = {'task_id': t['id'], 'base_rev': t['base_rev'], 'patch_hash': t['patch_hash'], 'verdict': 'rejected', 'summary': 'Need additional review context', 'simulated': False}
        self.center.complete(s['id'], response)
        result = self.center.retry_review(t['id'], 'Reviewer now has required scoped context')
        self.assertEqual(result['status'], 'waiting_for_independent_review')
        self.assertEqual(result['attempt'], 1)
        with self.assertRaises(ValueError):
            self.center.claim(t['id'], 'review', 'handoff', 'codex')
        self.assertIsNone(result['approved_at'])

    def test_only_python_cache_is_exempt_from_untracked_artifact_fence(self):
        root = self.root / 'minimal'
        cfg = make_project(root, 'minimal')
        oldest = git(ROOT, 'rev-list', '--max-parents=0', 'HEAD').splitlines()[0]
        git(root, 'checkout', '--quiet', '--detach', oldest)
        self.center.register('minimal', root, cfg)
        t = self.task(project='minimal')
        self.claim_and_prepare(t)
        task = self.center.store.task(t['id'])
        worktree = Path(task['worktree'])
        cache = worktree / 'src/__pycache__/cache.pyc'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'generated cache fixture')
        self.assertEqual(self.center._task_patch(task)['manifest'], [])
        disguised = cache.parent / 'unreviewed.js'
        disguised.write_text('ordinary input is not a Python bytecode cache')
        with self.assertRaisesRegex(ValueError, 'Generated/dependency'):
            self.center._task_patch(task)
        disguised.unlink()
        artifact = worktree / 'src/dist/unreviewed.js'
        artifact.parent.mkdir(parents=True)
        artifact.write_text('must not escape the patch hash fence')
        with self.assertRaisesRegex(ValueError, 'Generated/dependency'):
            self.center._task_patch(task)


if __name__ == "__main__":
    unittest.main()
