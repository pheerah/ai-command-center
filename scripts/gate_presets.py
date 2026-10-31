"""Quality-gate detection helper for AI Dev Command Center.

Proposes quality-gate commands for a project directory without inventing anything:
it returns only commands the project really defines. Standard library only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

NODE_SCRIPTS_ORDER = ("lint", "typecheck", "test", "build")


def _detect_node_gates(project_dir: Path) -> list[tuple[list[str], str]]:
    """Detect Node.js quality-gate commands from package.json."""
    pkg_file = project_dir / "package.json"
    if not pkg_file.is_file():
        return []

    try:
        content = pkg_file.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []

    detected: list[tuple[list[str], str]] = []

    for name in NODE_SCRIPTS_ORDER:
        if name in scripts and isinstance(scripts[name], str):
            detected.append((["npm", "run", name], "package.json"))

    if "test:e2e" in scripts and isinstance(scripts["test:e2e"], str):
        detected.append((["npm", "run", "test:e2e"], "package.json"))

    return detected


def _find_test_file(project_dir: Path) -> str | None:
    """Find the first test_*.py file in tests directory supporting unittest gate.

    Returns the relative POSIX path from project_dir (e.g. 'tests/test_main.py'),
    or None if no matching test file exists.
    """
    tests_dir = project_dir / "tests"
    if not tests_dir.is_dir():
        return None
    try:
        candidates = sorted(
            [p for p in tests_dir.rglob("test_*.py") if p.is_file()],
            key=lambda p: p.relative_to(project_dir).as_posix(),
        )
        if candidates:
            return candidates[0].relative_to(project_dir).as_posix()
    except Exception:
        pass
    return None


def _is_valid_pyproject(pyproject_path: Path) -> bool:
    """Check if pyproject.toml exists and is valid TOML."""
    if not pyproject_path.is_file():
        return False
    try:
        content = pyproject_path.read_text(encoding="utf-8")
        import tomllib
        parsed = tomllib.loads(content)
        return isinstance(parsed, dict)
    except Exception:
        return False


def _has_tool_pytest(pyproject_path: Path) -> bool:
    """Check if pyproject.toml has a [tool.pytest] or [tool.pytest.*] section.

    Never raises for a missing or malformed file: malformed TOML skips that source.
    """
    if not pyproject_path.is_file():
        return False
    try:
        content = pyproject_path.read_text(encoding="utf-8")
        import tomllib
        parsed = tomllib.loads(content)
    except Exception:
        return False

    if not isinstance(parsed, dict):
        return False

    tool = parsed.get("tool")
    if not isinstance(tool, dict):
        return False

    return "pytest" in tool


def _find_pytest_requirements(project_dir: Path) -> str | None:
    """Find the first requirements*.txt containing the word pytest."""
    try:
        candidates = sorted(project_dir.glob("requirements*.txt"), key=lambda p: p.as_posix())
    except Exception:
        return None

    for req in candidates:
        if not req.is_file():
            continue
        try:
            content = req.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if re.search(r"\bpytest\b", content, re.IGNORECASE):
            return req.name
    return None


def _is_valid_ini(path: Path) -> bool:
    """A pytest.ini counts only when it really parses as an INI file."""
    if not path.is_file():
        return False
    import configparser
    try:
        configparser.RawConfigParser().read_string(path.read_text(encoding="utf-8"))
        return True
    except (configparser.Error, OSError, UnicodeDecodeError):
        return False


def _detect_python_gates(project_dir: Path) -> list[tuple[list[str], str]]:
    """Detect Python quality-gate commands."""
    pyproject = project_dir / "pyproject.toml"
    setup_cfg = project_dir / "setup.cfg"
    pytest_ini = project_dir / "pytest.ini"
    pytest_ini_ok = _is_valid_ini(pytest_ini)
    test_file = _find_test_file(project_dir)
    req_pytest = _find_pytest_requirements(project_dir)

    is_python_project = (
        _is_valid_pyproject(pyproject)
        or setup_cfg.is_file()
        or pytest_ini_ok
        or (test_file is not None)
    )  # requirements*.txt alone is not a Python-project marker; it only decides pytest vs unittest

    if not is_python_project:
        return []

    # 1. pytest.ini
    if pytest_ini_ok:
        return [(["python", "-m", "pytest", "-q"], "pytest.ini")]

    # 2. [tool.pytest] section in pyproject.toml
    if _has_tool_pytest(pyproject):
        return [(["python", "-m", "pytest", "-q"], "pyproject.toml")]

    # 3. the word pytest in requirements*.txt
    if req_pytest is not None:
        return [(["python", "-m", "pytest", "-q"], req_pytest)]

    # Otherwise unittest when a tests directory with test_*.py exists
    if test_file is not None:
        return [(["python", "-m", "unittest", "discover", "-s", "tests"], test_file)]

    return []


def _detect_entries(project_path: Path | str) -> list[tuple[list[str], str]]:
    """Internal helper to detect gate commands and their source files."""
    try:
        path = Path(project_path)
    except Exception:
        return []

    if not path.is_dir():
        return []

    results: list[tuple[list[str], str]] = []
    results.extend(_detect_node_gates(path))
    results.extend(_detect_python_gates(path))
    return results


def detect_gates(project_path: Path | str) -> list[list[str]]:
    """Propose quality-gate commands for a project directory without inventing anything.

    Returns a list of argv lists (each a list of strings).
    """
    return [cmd for cmd, _ in _detect_entries(project_path)]


def explain(project_path: Path | str) -> dict[str, Any]:
    """Return a dict with detected commands and the file each came from."""
    entries = _detect_entries(project_path)
    return {
        "commands": [
            {
                "command": cmd,
                "file": source,
                "source": source,
            }
            for cmd, source in entries
        ]
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose quality-gate commands for a project directory.")
    parser.add_argument("project_path", help="Path to project directory")
    args = parser.parse_args(argv)

    result = explain(args.project_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
