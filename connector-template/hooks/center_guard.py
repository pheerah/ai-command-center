"""Claude Code PreToolUse hook guarding project files against direct edits."""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time

GUARDED_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# Files that control this guard or the Center connection. They are protected even outside context_scope and even
# during an override window, otherwise an agent could simply write its own override or remove the hook.
PROTECTED_NAMES = (".center-direct-edit.json", "connector.py", "center.connection.json", "project.config.json")
PROTECTED_PREFIXES = (os.path.join(".claude", "hooks"), os.path.join(".claude", "settings"))
BASH_CONTROL_PATTERN = re.compile(r"allow-direct|center-direct-edit|\.claude[\\/]+(hooks|settings)|settings\.local\.json|center_guard|center\.connection", re.IGNORECASE)
# Reading these is fine; combined with a write-looking command they count as tampering with the guard itself.
BASH_CONTROL_FILES = re.compile(r"project\.config|connector\.py|\.claude[\\/]", re.IGNORECASE)
# A shell command that both names a guarded path and looks like a write is refused. This is a heuristic for the obvious
# cases (redirects, tee, sed -i, mv/cp/rm, Set-Content ...); a determined agent can still write through the shell in ways
# a pattern cannot see, so the hook narrows the door but is not a sandbox.
BASH_WRITE_PATTERN = re.compile(r">|\btee\b|\bsed\s+-i|\b(mv|cp|rm|del|move|copy|touch|mkdir|ren|rename)\b|Set-Content|Add-Content|Out-File|\bpatch\b|\bgit\s+(apply|checkout|restore|stash)\b|\bpython\d*\s+-c\b|\bnode\s+-e\b", re.IGNORECASE)

# Commands that rewrite files without naming them (a patch file decides what changes), so no path can be matched against the scope.
TARGETLESS_WRITERS = re.compile(r"\bgit\s+(?:apply|restore|stash)\b|\bgit\s+checkout\s+(?:--|\.)|(?<![\w-])patch\s", re.IGNORECASE)
# Harmless stderr/stdout plumbing such as 2>&1 or >/dev/null is not a write into the project.
REDIRECT_NOISE = re.compile(r"\d*>&\d+|\d*>>?\s*/dev/null|\d*>>?\s*nul\b", re.IGNORECASE)
# The project's own connector is the sanctioned route to the Center: a plain `python connector.py <subcommand> ...` call is
# allowed whatever words its quoted --prompt/--title text contains. Chaining (; & | < > ` $ ( ) or a line break) outside
# quotes disables this shortcut, so it cannot smuggle a second command.
CONNECTOR_CALL = re.compile(r"^\s*(?:python[\d.]*|py)\s+(?:\.[\\/])?connector\.py\s+(?:health|submit|list|status|report|cancel|patch|wait|apply)(?:\s[^;&|<>`$()\r\n]*)?$", re.IGNORECASE)
QUOTED_TEXT = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")

PROTECTED_MESSAGE = (
    "This file controls the AI Command Center guard or connection and cannot be changed by the agent. "
    "Only the user may open a direct-edit window: they run python connector.py allow-direct --minutes 30 --reason \"...\" themselves in a terminal."
)

DENY_MESSAGE = (
    "This project sends code changes through the AI Command Center; "
    "submit the task with python connector.py submit ...; "
    "or ask the user to run python connector.py allow-direct --minutes 30 --reason \"...\" "
    "for a time-limited direct edit."
)


def _is_numeric(val: object) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def _find_project_root(start_dir: str) -> str | None:
    current = os.path.realpath(start_dir)
    while True:
        candidate = os.path.join(current, "project.config.json")
        if os.path.isfile(candidate):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _anchor_root(start_dir: str) -> str | None:
    """The project root, anchored on where this hook is installed (<root>/.claude/hooks/center_guard.py).

    Anchoring on the script keeps the guard working even if project.config.json is deleted; only a hook that is not
    installed in that layout falls back to searching for project.config.json upward from the working directory.
    """
    here = os.path.realpath(os.path.abspath(__file__))
    hooks = os.path.dirname(here)
    claude = os.path.dirname(hooks)
    if os.path.basename(hooks).lower() == "hooks" and os.path.basename(claude).lower() == ".claude":
        return os.path.dirname(claude)
    return _find_project_root(start_dir)


def _scope_entries(root: str) -> list:
    """context_scope entries (forward-slash, lower-case), or [''] meaning the whole project when the config is unreadable."""
    try:
        with open(os.path.join(root, "project.config.json"), "r", encoding="utf-8") as handle:
            scope = json.load(handle).get("context_scope")
        if isinstance(scope, list):
            return [e.replace("\\", "/").strip("/").lower() for e in scope if isinstance(e, str) and e.strip("/\\ ")]
    except Exception:
        pass
    return [""]


def _is_connector_call(command: str) -> bool:
    return bool(CONNECTOR_CALL.match(QUOTED_TEXT.sub('""', command)))


def _split_commands(command: str) -> list:
    """Split a shell line on unquoted ; & | and line breaks so that every piece is judged on its own.

    A chain such as `ls src | head && python connector.py submit ...` must not make the harmless connector call
    inherit the verdict of its neighbour (or the other way round): each piece is allowed or refused by itself.
    """
    pieces, current, quote, i = [], [], None, 0
    while i < len(command):
        char = command[i]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and i + 1 < len(command):
                i += 1
                current.append(command[i])
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char in ";&|\r\n":
            pieces.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    pieces.append("".join(current))
    return [piece for piece in pieces if piece.strip()]


def _bash_verdict(command: str, anchor, now: float):
    """(exit code, message) for a shell command; (0, '') when it is allowed."""
    for piece in _split_commands(REDIRECT_NOISE.sub(" ", command)):
        if _is_connector_call(piece):
            continue
        control = BASH_CONTROL_FILES.search(piece)
        write = BASH_WRITE_PATTERN.search(piece)
        if control and write:
            return 2, PROTECTED_MESSAGE + f" (blocked part: {piece.strip()[:90]!r}; matched {control.group(0)!r} with {write.group(0)!r})"
        if anchor and write and _bash_writes_into_scope(piece, anchor) and not _check_override(anchor, now):
            return 2, DENY_MESSAGE + f" (blocked part: {piece.strip()[:90]!r}; matched {write.group(0)!r})"
        blind = TARGETLESS_WRITERS.search(piece)
        if anchor and blind and not _check_override(anchor, now):
            return 2, DENY_MESSAGE + f" (blocked part: {piece.strip()[:90]!r}; {blind.group(0)!r} changes files without naming them)"
    return 0, ""


def _bash_writes_into_scope(command: str, root: str) -> bool:
    if not BASH_WRITE_PATTERN.search(command):
        return False
    text = command.replace("\\", "/").lower()
    return any(entry == "" or entry in text for entry in _scope_entries(root))


def _is_contained_in(child_norm: str, parent_norm: str) -> bool:
    try:
        rel = os.path.relpath(child_norm, parent_norm)
    except ValueError:
        return False
    if rel == ".." or rel.startswith(".." + os.sep) or rel.startswith("../") or os.path.isabs(rel):
        return False
    return True


def _check_override(project_root: str, now: float) -> bool:
    override_file = os.path.join(project_root, ".center-direct-edit.json")
    if not os.path.isfile(override_file):
        return False
    try:
        with open(override_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        created_at = data.get("created_at")
        expires_at = data.get("expires_at")
        if not _is_numeric(created_at) or not _is_numeric(expires_at):
            return False
        # expires_at in the future, expires no more than 4 hours (14400s) after created_at
        if expires_at > now and created_at <= expires_at <= created_at + 14400:
            return True
        return False
    except Exception:
        return False


def main(argv=None, stdin=None, stderr=None, now=None) -> int:
    if stdin is None:
        stdin = sys.stdin
    if stderr is None:
        stderr = sys.stderr
    if now is None:
        now = time.time()

    try:
        raw = stdin.read()
    except Exception as exc:
        if stderr is not None:
            stderr.write(f"Warning: failed to read stdin: {exc}\n")
        return 1

    if not raw or not raw.strip():
        if stderr is not None:
            stderr.write("Warning: empty stdin\n")
        return 1

    try:
        payload = json.loads(raw)
    except Exception as exc:
        if stderr is not None:
            stderr.write(f"Warning: malformed JSON on stdin: {exc}\n")
        return 1

    if not isinstance(payload, dict):
        if stderr is not None:
            stderr.write("Warning: stdin is not a JSON object\n")
        return 1

    try:
        tool_name = payload.get("tool_name")
        if tool_name == "Bash":
            # Best effort only: a shell command that names the control files or the override command is refused,
            # so the agent cannot open its own direct-edit window. It cannot catch every possible shell trick.
            command = (payload.get("tool_input") or {}).get("command") if isinstance(payload.get("tool_input"), dict) else None
            if not isinstance(command, str):
                return 0
            if BASH_CONTROL_PATTERN.search(command):
                stderr.write(PROTECTED_MESSAGE + "\n")
                return 2
            anchor = _anchor_root(payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd())
            code, message = _bash_verdict(command, anchor, now)
            if code:
                stderr.write(message + "\n")
            return code
        if tool_name not in GUARDED_TOOLS:
            return 0

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0

        if tool_name == "NotebookEdit":
            raw_target = tool_input.get("notebook_path")
        else:
            raw_target = tool_input.get("file_path")

        if not raw_target or not isinstance(raw_target, str):
            return 0

        cwd = payload.get("cwd")
        if not cwd or not isinstance(cwd, str):
            cwd = os.getcwd()

        claude_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if claude_project_dir:
            start_dir = (
                claude_project_dir
                if os.path.isabs(claude_project_dir)
                else os.path.join(cwd, claude_project_dir)
            )
        else:
            start_dir = cwd

        project_root = _anchor_root(start_dir)
        if project_root is None:
            return 0

        resolved_root = os.path.realpath(project_root)

        if os.path.isabs(raw_target):
            resolved_target = os.path.realpath(raw_target)
        else:
            resolved_target = os.path.realpath(os.path.join(cwd, raw_target))

        norm_root = os.path.normcase(resolved_root)
        norm_target = os.path.normcase(resolved_target)

        # Target outside project root is allowed
        if not _is_contained_in(norm_target, norm_root):
            return 0

        relative = os.path.relpath(norm_target, norm_root)
        protected = relative in tuple(os.path.normcase(n) for n in PROTECTED_NAMES) \
            or any(relative.startswith(os.path.normcase(prefix)) for prefix in PROTECTED_PREFIXES)
        if protected:
            stderr.write(PROTECTED_MESSAGE + "\n")
            return 2

        # Fail closed: an unreadable or odd project.config.json guards the whole project instead of none of it.
        in_scope = True
        try:
            with open(os.path.join(resolved_root, "project.config.json"), "r", encoding="utf-8") as f:
                config = json.load(f)
            context_scope = config.get("context_scope") if isinstance(config, dict) else None
            if isinstance(context_scope, list):
                in_scope = False
                for entry in context_scope:
                    if isinstance(entry, str) and _is_contained_in(norm_target, os.path.normcase(os.path.realpath(os.path.join(resolved_root, entry)))):
                        in_scope = True
                        break
        except Exception:
            in_scope = True

        if not in_scope:
            return 0

        if _check_override(resolved_root, now):
            return 0

        if stderr is not None:
            stderr.write(DENY_MESSAGE + "\n")
        return 2

    except Exception as exc:
        # A guard that crashes must not become an open door for the tools it protects.
        if stderr is not None:
            stderr.write(f"Blocked: the edit guard failed unexpectedly ({type(exc).__name__}); ask the user to check it.\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
