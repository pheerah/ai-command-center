"""SQLite Center CLI; no model call without explicit live configuration."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from center_runtime import Center, ROOT
from center_store import now, pid_alive
from center_service import service_status


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _database_busy(error):
    """Retry only SQLite's explicit busy/locked conditions, never corruption."""
    code = getattr(error, 'sqlite_errorcode', None)
    if isinstance(code, int):
        return (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    message = str(error).lower()
    return message in ('database is locked', 'database is busy') or message.startswith(('database table is locked', 'database schema is locked'))


def _retry_pause(stop, delay):
    """Bounded monotonic wait that remains responsive to a stop request."""
    deadline = time.monotonic() + delay
    while not stop.exists():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))


def dispatch_ready(center, mode, pool, futures, last_project=None):
    """Submit ready phases fairly; a blocked row never consumes an executor slot.

    This is an advisory preflight, not an ownership claim. run_phase still
    performs the atomic claim, which resolves races with other dispatchers.
    """
    capacity = center.usable_capacity()
    if len(futures) >= capacity:
        return last_project
    with center.store.connection() as con:
        rows = con.execute("SELECT id,status,project_id FROM tasks WHERE mode=? AND status IN ('queued','retry_wait','waiting_for_independent_review') AND not_before<=? ORDER BY created_at,id", (mode, time.time())).fetchall()
    projects = {}
    for row in rows:
        projects.setdefault(row["project_id"], deque()).append(row)
    order = list(projects)
    if last_project in order:
        offset = order.index(last_project) + 1
        order = order[offset:] + order[:offset]
    # Interleave projects without changing age order inside a project.
    pending = []
    while any(projects.values()):
        for project in order:
            if projects[project]:
                pending.append(projects[project].popleft())
    project_limit = center.config.get("project_capacity", capacity)
    if type(project_limit) is not int or project_limit < 1:
        project_limit = capacity
    in_flight = {}
    for future in futures.values():
        project = getattr(future, "center_project_id", None)
        if project:
            in_flight[project] = in_flight.get(project, 0) + 1
    for row in pending:
        if len(futures) >= capacity:
            break
        project = row["project_id"]
        if row["id"] in futures or in_flight.get(project, 0) >= project_limit:
            continue
        role = "review" if row["status"] == "waiting_for_independent_review" else "implementation"
        if mode == "mock" and role == "review":
            with center.store.connection() as con:
                if con.execute("SELECT 1 FROM events WHERE task_id=? AND event='mock_pipeline_complete'", (row["id"],)).fetchone():
                    continue
        adapter = "mock" if mode == "mock" else "live"
        readiness = center.scheduling_readiness(row["id"], role, adapter)
        if not readiness["ready"]:
            continue
        provider = readiness.get("provider")
        future = pool.submit(center.run_phase, row["id"], role, adapter, provider)
        future.center_project_id = project
        futures[row["id"]] = future
        in_flight[project] = in_flight.get(project, 0) + 1
        last_project = project
    return last_project


def serve(center, mode):
    instance = uuid.uuid4().hex
    stop = center.store.state / f"stop-{instance}"
    with center.store.connection(write=True) as con:
        row = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
        if row and pid_alive(json.loads(row[0])["pid"]):
            raise ValueError("A service process is already alive; do not start a second supervisor")
        record = {"instance": instance, "pid": os.getpid(), "mode": mode, "heartbeat": time.time(), "started_at": now()}
        con.execute("INSERT INTO center_meta VALUES('service',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(record),))
    futures = {}
    last_project = None
    database_failures = 0
    if center.config.get('quota_routing') and mode == 'live':  # the meter spends a few plan tokens, so never in mock mode
        import threading
        import center_quota

        def watch_quota():
            while not stop.exists():
                center_quota.refresh(center.store.state)
                time.sleep(60)
        threading.Thread(target=watch_quota, name='quota-meter', daemon=True).start()
    try:
        with ThreadPoolExecutor(max_workers=max(1, center.usable_capacity())) as pool:
            while not stop.exists():
                try:
                    record["heartbeat"] = time.time()
                    with center.store.connection(write=True) as con:
                        con.execute("UPDATE center_meta SET value=? WHERE key='service'", (json.dumps(record),))
                    center.recover()
                    if center.config.get('auto_retry'):
                        center.auto_retry()
                    if center.config.get('auto_failover'):
                        center.auto_failover()
                    center.expire_stalled_queue()
                    for task_id in list(futures):
                        if futures[task_id].done():
                            try:
                                futures[task_id].result()
                            except Exception as exc:
                                print(f"Task {task_id}: {type(exc).__name__}", flush=True)
                            del futures[task_id]
                    last_project = dispatch_ready(center, mode, pool, futures, last_project)
                except sqlite3.Error as exc:
                    if not _database_busy(exc):
                        print_json({'event': 'scheduler_database_error', 'retrying': False, 'error_type': type(exc).__name__})
                        raise ValueError('Scheduler database failure; dispatch stopped') from None
                    database_failures += 1
                    delay = min(5.0, 0.5 * 2 ** min(database_failures - 1, 4))
                    print_json({'event': 'scheduler_database_busy', 'retrying': True, 'retry_seconds': delay, 'consecutive_failures': database_failures})
                    _retry_pause(stop, delay)
                    continue
                database_failures = 0
                time.sleep(0.5)
    finally:
        try:
            with center.store.connection(write=True) as con:
                row = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
                if row and json.loads(row[0])["instance"] == instance:
                    con.execute("DELETE FROM center_meta WHERE key='service'")
        except sqlite3.Error as exc:
            if not _database_busy(exc):
                print_json({'event': 'scheduler_database_cleanup_error', 'retrying': False, 'error_type': type(exc).__name__})
                raise ValueError('Scheduler database cleanup failed') from None
            # Preserve the unverified service record. Its heartbeat/PID makes it
            # unhealthy after this process exits; never clear another owner.
            print_json({'event': 'scheduler_database_cleanup_deferred', 'reason': 'database_busy'})
        finally:
            if stop.exists():
                stop.unlink()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Local SQLite AI Dev Command Center")
    parser.add_argument("--state-dir")
    parser.add_argument("--config", dest="center_config")
    parser.add_argument("--project-id", help="Connector project boundary for task/session commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect local tools without reading credentials or calling models")
    health = sub.add_parser("health", help="Require a running scheduler and registered connector project")
    health.add_argument("--mode", choices=["mock", "live"], help="Require this scheduler mode")
    project = sub.add_parser("project").add_subparsers(dest="project_command", required=True)
    register = project.add_parser("register")
    register.add_argument("--id", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--config")
    register.add_argument("--confirm-config-change", action="store_true", help="Explicitly accept a changed project/gate configuration")
    project.add_parser("list")
    project.add_parser("show").add_argument("id")
    for name in ("submit", "dispatch"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True)
        p.add_argument("--title", required=True)
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--prompt")
        group.add_argument("--prompt-file")
        p.add_argument("--scope", action="append", required=True)
        p.add_argument("--accept", action="append", required=True)
        p.add_argument("--provider", default="auto")
        p.add_argument("--mode", choices=["live", "mock"], default="live")
        p.add_argument("--depends-on", action="append", default=[])
        p.add_argument("--complexity", type=int, choices=range(1, 6), default=2)
        p.add_argument("--dependency-policy", choices=["ordering", "overlay"], default="ordering")
        p.add_argument("--read-file", action="append", default=None, help="Explicit source context within the task scope")
        p.add_argument("--hold-for-ide", action="store_true", help="Do not let the scheduler launch a CLI worker; an IDE session will claim this task")
        p.add_argument("--mock-json")
        if name == "dispatch":
            p.add_argument("--live", action="store_true")
    for name in ("run", "review"):
        p = sub.add_parser(name)
        p.add_argument("task_id")
        p.add_argument("--live", action="store_true")
        p.add_argument("--provider")
    p = sub.add_parser("claim", help="Explicit IDE handoff, no model launch")
    p.add_argument("task_id")
    p.add_argument("--provider", required=True)
    p.add_argument("--role", choices=["implementation", "review"], default="implementation")
    for name in ("worker-start", "heartbeat", "result", "worker-fail", "worker-stopped", "finish-gates"):
        p = sub.add_parser(name)
        p.add_argument("session_id")
        if name == "worker-start":
            p.add_argument("--reference", required=True)
        if name == "result":
            p.add_argument("--file", required=True)
        if name == "worker-fail":
            p.add_argument("--reason", choices=["auth", "config", "invalid_model", "rate_limit", "quota_exhausted", "worker_failure"], required=True)
            p.add_argument("--worker-stopped", action="store_true")
        if name == 'worker-stopped':
            p.add_argument('--reason', required=True)
    for name in ("status", "report"):
        p = sub.add_parser(name)
        p.add_argument("task_id", nargs="?")
        if name == 'status':
            p.add_argument('--usage', action='store_true', help='Include read-only token activity from Center CLI output')
    for name in ("cancel", "checkpoint"):
        sub.add_parser(name).add_argument("task_id")
    appr_p = sub.add_parser("approve")
    appr_p.add_argument("task_id")
    appr_p.add_argument("--yes", "-y", action="store_true", help="Non-interactive approval from web UI")
    for name in ('check-gates', 'retry-review'):
        recheck = sub.add_parser(name)
        recheck.add_argument('task_id')
        recheck.add_argument('--reason', required=True)
    resume = sub.add_parser('resume-review', help='Resume a blocked review without re-implementation')
    resume.add_argument('task_id')
    resume.add_argument('--reason', required=True)
    human = sub.add_parser('human-review', help='Record independent human review in an interactive terminal')
    human.add_argument('task_id')
    human.add_argument('--reason', required=True)
    retry = sub.add_parser("retry")
    retry.add_argument("task_id")
    retry.add_argument("--reason", required=True)
    retry.add_argument("--worker-stopped", action="store_true")
    retry.add_argument("--provider")
    retry.add_argument("--rebuild-overlay", action="store_true", help="Explicitly rebuild a changed dependency overlay while preserving previous attempts")
    drift = sub.add_parser('adopt-drift', help='Explicitly attribute preserved worktree drift to its provider')
    drift.add_argument('task_id')
    drift.add_argument('--provider', required=True)
    drift.add_argument('--reason', required=True)
    drift.add_argument('--worker-stopped', action='store_true')
    refresh = sub.add_parser('refresh-policy', help='Explicitly accept current project policy and invalidate old evidence')
    refresh.add_argument('task_id')
    refresh.add_argument('--reason', required=True)
    sub.add_parser("recover")
    backup = sub.add_parser("backup")
    backup.add_argument("--verify", action="store_true", help="Verify backup integrity after creating it")
    sub.add_parser("maintenance", help="Inspect backup, disk, artifact and worktree retention without deleting files")
    drill = sub.add_parser("restore-drill", help="Restore a backup into a separate new directory for verification")
    drill.add_argument("backup")
    drill.add_argument("--destination", required=True)
    provider = sub.add_parser("provider").add_subparsers(dest="provider_command", required=True)
    provider.add_parser("status")
    attest = provider.add_parser("attest", help="Record, in an interactive terminal, that Google uses your personal subscription (Center cannot verify it)")
    attest.add_argument("provider")
    attest.add_argument("--plan", required=True, help="Plan name you are paying for, e.g. 'Google AI Pro'")
    p = provider.add_parser("set")
    p.add_argument("provider")
    p.add_argument("--availability", choices=["available", "unavailable", "unknown"], required=True)
    p.add_argument("--reason", required=True)
    for name in ("start", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--mode", choices=["mock", "live"], default="mock")
    sub.add_parser("stop")
    sub.add_parser("service-status")
    api = sub.add_parser("api-call", help="Project API bridge: one JSON request on stdin, path-free JSON answer (used by server.js)")
    token = sub.add_parser("token", help="Manage per-project API tokens").add_subparsers(dest="token_command", required=True)
    created = token.add_parser("create")
    created.add_argument("--project", required=True)
    created.add_argument("--label", default="")
    token.add_parser("list")
    token.add_parser("revoke").add_argument("token_id")
    args = parser.parse_args()
    try:
        center = Center(args.state_dir, args.center_config)
        cmd = args.command
        if args.project_id:
            task_id = getattr(args, "task_id", None)
            if getattr(args, "session_id", None):
                task_id = center.session(args.session_id)["task_id"]
            if task_id and center.store.task(task_id)["project_id"] != args.project_id:
                raise ValueError("Connector cannot access another project's task/session")
            if cmd in ("submit", "dispatch") and args.project != args.project_id:
                raise ValueError("Connector project mismatch")
            if cmd == "project" and getattr(args, "id", args.project_id) != args.project_id:
                raise ValueError("Connector project mismatch")
        if cmd in ("doctor", "health"):
            from importlib.metadata import version, PackageNotFoundError
            try:
                maestro_version = version("maestro-ai-cli")
            except PackageNotFoundError:
                maestro_version = "missing"
            checks = {"python": sys.version.split()[0], "git": bool(shutil.which("git")), "maestro": maestro_version,
                      "sqlite": "ok", "live_execution": center.config["live_execution"], "provider_auth": "not_checked",
                      "google": center.provider_status().get("google"), "service": service_status(center)}
            if cmd == "health":
                registered = bool(center.project(args.project_id)) if args.project_id else None
                checks["project_registered"] = registered
                checks["ok"] = bool(checks["git"] and maestro_version != "missing" and checks["service"]["running"])
                checks["reason"] = "ready" if checks["ok"] else checks["service"]["reason"] if not checks["service"]["running"] else "required_tool_missing"
                if args.mode and checks["service"]["running"] and checks["service"].get("mode") != args.mode:
                    checks["ok"], checks["reason"] = False, "scheduler_mode_mismatch"
                print_json(checks)
                return 0 if checks["ok"] else 1
            print_json(checks)
            return 0 if checks["git"] and maestro_version != "missing" else 1
        if cmd == "project":
            if args.project_command == "register":
                print_json(center.register(args.id, args.path, args.config, confirm_config_change=args.confirm_config_change))
            elif args.project_command == "show":
                print_json(center.project(args.id))
            else:
                print_json(center.report()["projects"])
        elif cmd in ("submit", "dispatch"):
            prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
            task = center.submit(args.project, args.title, prompt, args.scope, args.accept, args.provider, args.mode, args.depends_on, args.complexity,
                                 json.loads(args.mock_json) if args.mock_json else None,
                                 dependency_policy=args.dependency_policy, read_set=args.read_file, hold_for_ide=args.hold_for_ide)
            print_json(task)
            if cmd == "dispatch":
                if task["mode"] == "live" and not args.live:
                    raise ValueError("Task queued. Real execution requires --live and live_execution=true")
                print_json(center.run_phase(task["id"], "implementation", "live" if args.live else "mock"))
        elif cmd in ("run", "review"):
            print_json(center.run_phase(args.task_id, "review" if cmd == "review" else "implementation", "live" if args.live else "mock", args.provider))
        elif cmd == "claim":
            session = center.claim(args.task_id, args.role, "handoff", args.provider)
            if session and args.role == "implementation":
                try:
                    center.prepare(args.task_id)
                except Exception:
                    center.failure(session['id'], 'config')
                    raise
            print_json({"session": session, "task": center.store.task(args.task_id), "verification": "pending_live_verification"})
        elif cmd == "worker-start":
            center.started(args.session_id, args.reference)
            print_json({"started": True})
        elif cmd == "heartbeat":
            ok = center.heartbeat(args.session_id)
            print_json({"renewed": ok})
            return 0 if ok else 1
        elif cmd == "result":
            session = center.session(args.session_id)
            if session["adapter"] != "handoff":
                raise ValueError("Only IDE handoff sessions may submit result files")
            from center_workspace import inside, sensitive
            supplied = Path(args.file)
            file = supplied.resolve()
            if supplied.is_symlink() or not inside(file, session['artifact_dir']) or sensitive(file.name) or file.suffix != '.json' or file.stat().st_size > 1048576:
                raise ValueError('Result must be a non-secret JSON file inside the assigned session artifact directory')
            print_json(center.complete(args.session_id, json.loads(file.read_text(encoding="utf-8"))))
        elif cmd == 'worker-stopped':
            print_json(center.acknowledge_stop(args.session_id, args.reason))
        elif cmd == 'finish-gates':
            print_json(center.finish_gates(args.session_id))
        elif cmd == "worker-fail":
            if center.session(args.session_id)['adapter'] == 'handoff' and not args.worker_stopped:
                raise ValueError('Stop the IDE worker first and acknowledge with --worker-stopped')
            print_json(center.failure(args.session_id, args.reason))
        elif cmd in ("status", "report"):
            report = center.report(args.task_id, args.project_id)
            if cmd == 'status' and args.usage and not args.task_id and not args.project_id:
                from center_usage import usage_report
                report['usage'] = usage_report(center.store.state, ROOT)
            print_json(report)
        elif cmd == "checkpoint":
            print_json({"checkpoint": center.save_checkpoint(args.task_id)})
        elif cmd == 'check-gates':
            print_json(center.recheck_gates(args.task_id, args.reason))
        elif cmd == 'retry-review':
            print_json(center.retry_review(args.task_id, args.reason))
        elif cmd == 'resume-review':
            print_json(center.resume_review(args.task_id, args.reason))
        elif cmd == 'human-review':
            print_json(center.human_review(args.task_id, args.reason))
        elif cmd == "cancel":
            print_json(center.cancel(args.task_id))
        elif cmd == "recover":
            print_json(center.recover())
        elif cmd == "retry":
            print_json(center.reconcile(args.task_id, args.reason, args.worker_stopped, args.provider, rebuild_overlay=args.rebuild_overlay))
        elif cmd == 'adopt-drift':
            print_json(center.adopt_drift(args.task_id, args.provider, args.reason, args.worker_stopped))
        elif cmd == 'refresh-policy':
            print_json(center.refresh_policy(args.task_id, args.reason))
        elif cmd == "approve":
            approved = center.approve(args.task_id, interactive=not getattr(args, "yes", False))
            applied = center.auto_apply(args.task_id)
            print_json({"approved": approved["status"], "applied": applied})
        elif cmd == "backup":
            if args.verify:
                from center_operations import verified_backup
                print_json(verified_backup(center))
            else:
                print_json({"backup": str(center.store.backup())})
        elif cmd == "maintenance":
            from center_operations import maintenance_report
            print_json(maintenance_report(center))
        elif cmd == "restore-drill":
            from center_operations import restore_drill
            print_json(restore_drill(args.backup, args.destination))
        elif cmd == "provider":
            if args.provider_command == "set":
                center.set_provider(args.provider, args.availability, args.reason)
            elif args.provider_command == "attest":
                print_json({"attested": center.attest_provider(args.provider, args.plan)})
                return 0
            print_json(center.provider_status())
        elif cmd == "api-call":
            import center_api
            if not args.project_id:
                raise ValueError("api-call requires --project-id")
            print(json.dumps(center_api.run(center, args.project_id, json.loads(sys.stdin.read(70000) or "{}")), ensure_ascii=False))
        elif cmd == "token":
            import center_api
            if args.token_command == "create":
                center.project(args.project)  # only registered projects can receive a token
                print_json({"project_id": args.project, "token": center_api.create_token(center.store.state, args.project, args.label),
                            "note": "Shown once; only a hash is stored. Put it in the project's config, never in git."})
            elif args.token_command == "list":
                print_json({"tokens": center_api.list_tokens(center.store.state)})
            else:
                print_json(center_api.revoke_token(center.store.state, args.token_id))
        elif cmd == "service-status":
            print_json(service_status(center))
        elif cmd == "serve":
            if args.mode == "live" and not center.config["live_execution"]:
                raise ValueError("Live execution is disabled")
            serve(center, args.mode)
        elif cmd == "start":
            if args.mode == "live" and not center.config["live_execution"]:
                raise ValueError("Live execution is disabled")
            if service_status(center)["running"]:
                print_json(service_status(center))
                return 0
            command = [sys.executable, str(ROOT / "smart_router.py"), "--state-dir", str(center.store.state)]
            if args.center_config:
                command += ["--config", args.center_config]
            command += ["serve", "--mode", args.mode]
            with (center.store.state / "service.log").open("ab") as log:
                subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=((subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0), start_new_session=os.name != "nt")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                status = service_status(center)
                if status["running"]:
                    print_json(status)
                    return 0
                time.sleep(0.1)
            raise ValueError("Service did not become ready; inspect service.log")
        elif cmd == "stop":
            status = service_status(center)
            if status.get("instance"):
                (center.store.state / f"stop-{status['instance']}").touch()
            print_json({"stop_requested": bool(status.get("running")), "policy": "stop dispatch, drain active phases, preserve all worktrees"})
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print_json({"error": str(exc), "state": "blocked"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
