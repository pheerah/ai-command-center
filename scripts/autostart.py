"""Windows auto-start task management for AI Command Center."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

TASK_SCHEDULER = "AI Command Center Scheduler"
TASK_DASHBOARD = "AI Command Center Dashboard"
TASKS = [TASK_SCHEDULER, TASK_DASHBOARD]

ROOT = Path(__file__).resolve().parents[1]


def get_python(root: Path = ROOT) -> str:
    """Resolve python executable: ROOT/.venv/Scripts/python.exe if present, else sys.executable."""
    venv_python = Path(root) / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def build_commands(root: Path | str = ROOT, python: str | None = None, node: str = "node") -> list[list[str]]:
    """Return argv lists for schtasks /Create for Scheduler and Dashboard.

    Pure function: constructs two schtasks /Create commands with /SC ONLOGON /RL LIMITED /F
    and a quoted /TR value that changes directory to root first.
    Never uses /RU SYSTEM or /RL HIGHEST.
    """
    if root is None:
        root = ROOT
    if python is None:
        python = get_python(Path(root))
    if node is None:
        node = "node"

    root_str, py_str, node_str = str(root), str(python), str(node)
    for value in (root_str, py_str, node_str):
        # A quote, percent sign or line break inside a path could break out of the quoted cmd.exe command line.
        if any(char in value for char in '"%\r\n'):
            raise ValueError('Paths for scheduled tasks must not contain quotes, % or line breaks: ' + value)
    node_cmd = f'"{node_str}"' if " " in node_str else node_str

    tr_scheduler = f'cmd.exe /c "cd /d "{root_str}" && "{py_str}" backend\\smart_router.py start --mode live"'
    tr_dashboard = f'cmd.exe /c "cd /d "{root_str}" && {node_cmd} server.js"'

    return [
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_SCHEDULER,
            "/TR",
            tr_scheduler,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_DASHBOARD,
            "/TR",
            tr_dashboard,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
    ]


def build_uninstall_commands() -> list[list[str]]:
    return [["schtasks", "/Delete", "/TN", task, "/F"] for task in TASKS]


def build_status_commands() -> list[list[str]]:
    return [["schtasks", "/Query", "/TN", task] for task in TASKS]


def _print_commands(commands: list[list[str]], file=sys.stdout) -> None:
    for cmd in commands:
        print(subprocess.list2cmdline(cmd), file=file)


def _run_commands(commands: list[list[str]]) -> int:
    exit_code = 0
    for cmd in commands:
        res = subprocess.run(cmd)
        if res is not None:
            rc = getattr(res, "returncode", 0)
            if isinstance(rc, int) and rc != 0 and exit_code == 0:
                exit_code = rc
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage Windows auto-start scheduled tasks for AI Command Center."
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser("print", help="Show scheduled task commands without running them")

    install_parser = subparsers.add_parser("install", help="Install scheduled tasks (Windows only)")
    install_parser.add_argument("--yes", action="store_true", help="Confirm installation")

    subparsers.add_parser("uninstall", help="Remove scheduled tasks")
    subparsers.add_parser("status", help="Query status of scheduled tasks")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 1

    python = get_python(ROOT)
    commands = build_commands(ROOT, python, "node")

    if args.subcommand == "print":
        _print_commands(commands, file=sys.stdout)
        return 0

    if args.subcommand == "install":
        # Refusal path 1: missing --yes
        if not args.yes:
            _print_commands(commands, file=sys.stderr)
            print("Error: --yes is required to install scheduled tasks.", file=sys.stderr)
            return 1

        # Refusal path 2: non-Windows platform
        if sys.platform != "win32":
            _print_commands(commands, file=sys.stderr)
            print("Error: Scheduled tasks can only be installed on Windows (sys.platform == 'win32').", file=sys.stderr)
            return 1

        return _run_commands(commands)

    if args.subcommand == "uninstall":
        return _run_commands(build_uninstall_commands())

    if args.subcommand == "status":
        return _run_commands(build_status_commands())

    return 1


if __name__ == "__main__":
    sys.exit(main())
