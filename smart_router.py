"""SQLite Center CLI; no model call without explicit live configuration."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from center_runtime import Center, ROOT
from center_store import now, pid_alive


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def service_status(center):
    with center.store.connection() as con:
        row = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
    if not row:
        return {"running": False}
    record = json.loads(row[0])
    record["running"] = pid_alive(record["pid"]) and time.time() - record["heartbeat"] < 20
    return record


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
    try:
        with ThreadPoolExecutor(max_workers=center.config["global_capacity"]) as pool:
            while not stop.exists():
                record["heartbeat"] = time.time()
                with center.store.connection(write=True) as con:
                    con.execute("UPDATE center_meta SET value=? WHERE key='service'", (json.dumps(record),))
                center.recover()
                for task_id in list(futures):
                    if futures[task_id].done():
                        try:
                            futures[task_id].result()
                        except Exception as exc:
                            print(f"Task {task_id}: {type(exc).__name__}", flush=True)
                        del futures[task_id]
                if len(futures) < center.config["global_capacity"]:
                    with center.store.connection() as con:
                        rows = con.execute("SELECT id,status FROM tasks WHERE mode=? AND status IN ('queued','retry_wait','waiting_for_independent_review') AND not_before<=? ORDER BY created_at", (mode, time.time())).fetchall()
                    for row in rows:
                        if row["id"] in futures or len(futures) >= center.config["global_capacity"]:
                            continue
                        role = "review" if row["status"] == "waiting_for_independent_review" else "implementation"
                        with center.store.connection() as con:
                            simulated_done = con.execute("SELECT 1 FROM events WHERE task_id=? AND event='mock_pipeline_complete'", (row["id"],)).fetchone()
                        if mode == "mock" and role == "review" and simulated_done:
                            continue
                        task = center.store.task(row["id"])
                        options = center.candidates(task, role)
                        if mode == "live":
                            health = center.provider_status()
                            options = [p for p in options if p in ('codex', 'claude') and health[p]['availability'] == 'available']
                        if not options:
                            continue
                        futures[row["id"]] = pool.submit(center.run_phase, row["id"], role, "mock" if mode == "mock" else "live")
                time.sleep(0.5)
    finally:
        with center.store.connection(write=True) as con:
            row = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
            if row and json.loads(row[0])["instance"] == instance:
                con.execute("DELETE FROM center_meta WHERE key='service'")
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
    project = sub.add_parser("project").add_subparsers(dest="project_command", required=True)
    register = project.add_parser("register")
    register.add_argument("--id", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--config")
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
    for name in ("worker-start", "heartbeat", "result", "worker-fail", "worker-stopped"):
        p = sub.add_parser(name)
        p.add_argument("session_id")
        if name == "worker-start":
            p.add_argument("--reference", required=True)
        if name == "result":
            p.add_argument("--file", required=True)
        if name == "worker-fail":
            p.add_argument("--reason", choices=["auth", "config", "invalid_model", "rate_limit", "worker_failure"], required=True)
            p.add_argument("--worker-stopped", action="store_true")
        if name == 'worker-stopped':
            p.add_argument('--reason', required=True)
    for name in ("status", "report"):
        p = sub.add_parser(name)
        p.add_argument("task_id", nargs="?")
        if name == 'status':
            p.add_argument('--usage', action='store_true', help='Include read-only token activity from Center CLI output')
    for name in ("cancel", "approve", "checkpoint"):
        sub.add_parser(name).add_argument("task_id")
    for name in ('check-gates', 'retry-review'):
        recheck = sub.add_parser(name)
        recheck.add_argument('task_id')
        recheck.add_argument('--reason', required=True)
    retry = sub.add_parser("retry")
    retry.add_argument("task_id")
    retry.add_argument("--reason", required=True)
    retry.add_argument("--worker-stopped", action="store_true")
    retry.add_argument("--provider")
    sub.add_parser("recover")
    sub.add_parser("backup")
    provider = sub.add_parser("provider").add_subparsers(dest="provider_command", required=True)
    provider.add_parser("status")
    p = provider.add_parser("set")
    p.add_argument("provider")
    p.add_argument("--availability", choices=["available", "unavailable", "unknown"], required=True)
    p.add_argument("--reason", required=True)
    for name in ("start", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--mode", choices=["mock", "live"], default="mock")
    sub.add_parser("stop")
    sub.add_parser("service-status")
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
        if cmd == "doctor":
            from importlib.metadata import version, PackageNotFoundError
            try:
                maestro_version = version("maestro-ai-cli")
            except PackageNotFoundError:
                maestro_version = "missing"
            checks = {"python": sys.version.split()[0], "git": bool(shutil.which("git")), "maestro": maestro_version,
                      "sqlite": "ok", "live_execution": center.config["live_execution"], "provider_auth": "not_checked",
                      "google": center.provider_status().get("google"), "service": service_status(center)}
            print_json(checks)
            return 0 if checks["git"] and maestro_version != "missing" else 1
        if cmd == "project":
            if args.project_command == "register":
                print_json(center.register(args.id, args.path, args.config))
            elif args.project_command == "show":
                print_json(center.project(args.id))
            else:
                print_json(center.report()["projects"])
        elif cmd in ("submit", "dispatch"):
            prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
            task = center.submit(args.project, args.title, prompt, args.scope, args.accept, args.provider, args.mode, args.depends_on, args.complexity,
                                 json.loads(args.mock_json) if args.mock_json else None)
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
        elif cmd == "cancel":
            print_json(center.cancel(args.task_id))
        elif cmd == "recover":
            print_json(center.recover())
        elif cmd == "retry":
            print_json(center.reconcile(args.task_id, args.reason, args.worker_stopped, args.provider))
        elif cmd == "approve":
            print_json(center.approve(args.task_id))
        elif cmd == "backup":
            print_json({"backup": str(center.store.backup())})
        elif cmd == "provider":
            if args.provider_command == "set":
                center.set_provider(args.provider, args.availability, args.reason)
            print_json(center.provider_status())
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
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=os.name != "nt")
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
