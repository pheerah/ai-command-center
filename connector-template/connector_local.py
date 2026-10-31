"""Small project-local connector; never takes over implementation on failure."""
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    config = json.loads((root / "project.config.json").read_text(encoding="utf-8"))
    if len(sys.argv) < 2:
        raise ValueError("Use health, register, submit, status, report, claim, worker-start, heartbeat, result, worker-fail, cancel")
    command, rest = sys.argv[1], sys.argv[2:]
    allowed = {"health", "register", "submit", "status", "report", "claim", "worker-start", "heartbeat", "result", "worker-fail", "worker-stopped", "cancel", "watch"}
    if command not in allowed:
        raise ValueError("Command is not supported by this project connector")
    if command == "health":
        args = ["health", '--mode', 'live']
    elif command == "register":
        if any(a not in ("--confirm-config-change",) for a in rest):
            raise ValueError("register only accepts --confirm-config-change")
        args = ["project", "register", "--id", config["project_id"], "--path", str(root), *rest]
    elif command == "submit":
        if "--project" in rest or "--state-dir" in rest or "--config" in rest:
            raise ValueError("Project identity is controlled by the connector config")
        args = ["submit", "--project", config["project_id"], *rest]
    else:
        args = [command, *rest]
    prefix = [config["center"]["python"], config["center"]["cli"], "--project-id", config["project_id"]]
    if config['center'].get('state_dir'):
        prefix += ['--state-dir', config['center']['state_dir']]
    if config['center'].get('config'):
        prefix += ['--config', config['center']['config']]
    if command == 'watch':
        if len(rest) != 1:
            raise ValueError('watch requires exactly one session ID')
        while True:
            proc = subprocess.run([*prefix, 'heartbeat', rest[0]], cwd=root, stdout=subprocess.PIPE, check=False)
            if proc.returncode:
                status = subprocess.run([*prefix, 'status'], cwd=root, stdout=subprocess.PIPE, check=False)
                if status.returncode == 0:
                    data = json.loads(status.stdout)
                    if not any(s['id'] == rest[0] for s in data.get('sessions', [])):
                        print(json.dumps({'state': 'finished', 'reason': 'assignment_has_ended'}))
                        return 0
                print(json.dumps({'state': 'blocked', 'reason': 'lease_lost_stop_editing', 'policy': 'no_silent_ide_takeover'}))
                return proc.returncode
            time.sleep(5)
    proc = subprocess.run([*prefix, *args], cwd=root, check=False)
    if proc.returncode:
        print(json.dumps({"state": "blocked", "reason": "center_command_failed", "policy": "no_silent_ide_takeover"}))
    return proc.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"state": "blocked", "reason": str(exc), "policy": "no_silent_ide_takeover"}))
        raise SystemExit(2)
