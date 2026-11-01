"""Canonical project paths, patch identities and recoverable task worktrees.

Worktrees separate changes, not security boundaries. These checks detect scope
violations after a worker; OS/provider permissions enforce only their own limits.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


EXCLUDED = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".ai-team", ".worktrees", "dist", "coverage", "test-results", "playwright-report"}


def canonical(path):
    return Path(path).expanduser().resolve()


def inside(path, root):
    return canonical(path).is_relative_to(canonical(root))


def valid_id(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise ValueError("ID must contain only letters, numbers, '-' and '_'")
    return value


def git(root, *args, binary=False):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(["git", "--literal-pathspecs", "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, env=env)
    if proc.returncode:
        raise ValueError(f"Git operation failed ({args[0]}); inspect repository state")
    return proc.stdout if binary else proc.stdout.decode("utf-8", errors="strict").strip()


def safe_relative(value):
    p = Path(value)
    if not value or p.is_absolute() or ".." in p.parts or ":" in value or "\\" in value:
        raise ValueError("Scope and artifact paths must be relative POSIX paths without traversal")
    return p.as_posix()


def sensitive(name):
    parts = Path(name).parts
    filename = Path(name).name.lower()
    return (any(p.lower() in {".aws", ".ssh", ".codex", ".claude"} for p in parts)
            or filename == ".env" or filename.startswith(".env.") and filename != ".env.example"
            or any(x in filename for x in ("credential", "secret", "token"))
            or filename.endswith((".pem", ".key", ".p12", ".pfx")))


def in_scope(name, scope):
    return any(name == item or name.startswith(item.rstrip("/") + "/") for item in scope)


def patch(root, base_rev, scope, max_bytes=10 * 1024 * 1024):
    root = canonical(root)
    if git(root, "rev-parse", "HEAD") != base_rev:
        raise ValueError("Base revision changed; worker commits are not allowed")
    changed = set(filter(None, git(root, "diff", "--name-only", "--no-renames", "-z", base_rev).split("\0")))
    untracked = set(filter(None, git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")))
    # Python bytecode can appear when an existing gate imports source. Exclude
    # only this disposable cache; other unexpected generated/dependency paths
    # still fail the scope/hash fence instead of being silently hidden.
    untracked = {name for name in untracked if not ('__pycache__' in Path(name).parts[:-1] and Path(name).suffix in ('.pyc', '.pyo'))}
    ignored = filter(None, git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *scope).split("\0"))
    for name in ignored:
        if any(p in EXCLUDED for p in Path(name).parts):
            continue
        if sensitive(name):
            raise ValueError("Sensitive ignored path detected; file contents were not read")
        untracked.add(name)
    names = sorted(changed | untracked)
    manifest, total = [], 0
    for name in names:
        safe_relative(name)
        if sensitive(name):
            raise ValueError("Sensitive path detected; file contents were not read")
        if any(p in EXCLUDED for p in Path(name).parts):
            raise ValueError("Generated/dependency path in patch")
        if not in_scope(name, scope):
            # Allow test files if AI followed TDD or created test coverage for its changes
            parts_lower = [part.lower() for part in Path(name).parts]
            is_test = any("test" in part for part in parts_lower) or name.startswith("tests/") or name.startswith("test/")
            if not is_test:
                raise ValueError(f"Out-of-scope modification detected: {name}")
        p = root / name
        if not inside(p, root) or p.is_symlink():
            raise ValueError("Linked path escapes or aliases the worktree")
        if p.exists() and not p.is_file():
            raise ValueError("Unsupported non-file patch path")
        raw = p.read_bytes() if p.exists() else b""
        normalized = raw.replace(b'\r\n', b'\n')
        size = len(normalized) if p.exists() else 0
        total += size
        if total > max_bytes:
            raise ValueError("Checkpoint size limit exceeded; no partial checkpoint accepted")
        content_hash = hashlib.sha256(normalized).hexdigest() if p.exists() else None
        manifest.append({"path": name, "sha256": content_hash, "size": size, "untracked": name in untracked})
    diff = git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-renames", base_rev, "--", *sorted(changed), binary=True) if changed else b""
    if len(diff) + sum(item["size"] for item in manifest if item["untracked"]) > max_bytes:
        raise ValueError("Checkpoint diff exceeds configured size limit")
    payload = json.dumps({"base_rev": base_rev, "manifest": manifest}, sort_keys=True, separators=(",", ":")).encode()
    identity = hashlib.sha256(payload + b"\0" + diff).hexdigest()
    return {"base_rev": base_rev, "patch_hash": identity, "manifest": manifest, "diff": diff}


def checkpoint(root, data, destination):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "tracked.patch").write_bytes(data["diff"])
    for item in data["manifest"]:
        if item["untracked"]:
            target = destination / "files" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / item["path"], target)
    (destination / "manifest.json").write_text(json.dumps({k: v for k, v in data.items() if k != "diff"}, indent=2), encoding="utf-8")
    # Catch concurrent changes during the copy; evidence is only valid for one exact patch.
    for item in data["manifest"]:
        if item["untracked"] and hashlib.sha256((destination / "files" / item["path"]).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != item["sha256"]:
            raise ValueError("File changed during checkpoint")
    return str(destination)


def restore(root, saved, expected_base):
    saved = canonical(saved)
    manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
    if manifest["base_rev"] != expected_base:
        raise ValueError("Checkpoint base mismatch")
    tracked = saved / "tracked.patch"
    if tracked.stat().st_size:
        git(root, "apply", "--check", "--index", str(tracked))
        git(root, "apply", "--index", str(tracked))
    for item in manifest["manifest"]:
        if item["untracked"]:
            name = safe_relative(item["path"])
            source, target = saved / "files" / name, root / name
            if sensitive(name) or not inside(source, saved) or source.is_symlink() or not inside(target, root):
                raise ValueError("Unsafe checkpoint path")
            if hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != item["sha256"]:
                raise ValueError("Checkpoint integrity mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def ensure_worktree(task, project, worktree_root, restore_checkpoint=True):
    expected = canonical(worktree_root / task["project_id"] / task["id"] / f"attempt-{task['attempt']}")
    if not inside(expected, worktree_root):
        raise ValueError("Worktree path escapes configured root")
    if canonical(task["workspace"]) != canonical(project["root"]):
        raise ValueError("Task/project ownership mismatch")
    branch = f"codex/center/{task['project_id']}/{task['id']}/{task['attempt']}"
    if expected.exists():
        try:
            git(project["root"], "worktree", "remove", "--force", str(expected))
        except Exception:
            pass
        if expected.exists():
            shutil.rmtree(expected, ignore_errors=True)
        try:
            git(project["root"], "branch", "-D", branch)
        except Exception:
            pass
    expected.parent.mkdir(parents=True, exist_ok=True)
    git(project["root"], "worktree", "add", "-b", branch, str(expected), task["base_rev"])
    if restore_checkpoint and task.get("checkpoint"):
        restore(expected, Path(task["checkpoint"]), task["base_rev"])
    return expected, branch
