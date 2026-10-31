"""Maestro command-task adapter. Invoked only with a Center-generated request.

The parent owns leases/retries. This worker runs exactly one phase and never
reassigns, resumes another project's session, or approves a task itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from center_process import worker_env
from center_workspace import inside, safe_relative, sensitive
from center_context import apply_edits
from center_errors import classify_error, classify_failure  # noqa: F401  (re-exported for existing callers)

LOG_TAIL_BYTES = 1048576


def write_json(path, data):
    p = Path(path)
    temporary = p.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(p)


def cli_command(provider):
    """Resolve Windows npm shims without cmd.exe shell interpolation."""
    if provider == "google":
        agy = shutil.which("agy.exe") or shutil.which("agy")
        if agy and Path(agy).suffix.lower() not in (".cmd", ".bat", ".ps1"):
            return [agy]
        raise ValueError("Provider CLI unavailable; install its subscription CLI first")
    if os.name == "nt":
        npm = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"
        package = npm / ("@openai/codex/bin/codex.js" if provider == "codex" else "@anthropic-ai/claude-code/cli.js")
        if package.is_file() and shutil.which("node"):
            return [shutil.which("node"), str(package)]
        native = shutil.which(provider + ".exe")
        if native:
            return [native]
        # Native Claude installation can leave a one-line npm launcher. Parse
        # only this exact executable-only form; never evaluate batch scripts.
        shim = shutil.which(provider + ".cmd")
        if shim and Path(shim).stat().st_size < 2048:
            match = re.fullmatch(r'\s*@?"([A-Za-z]:\\[^"\r\n]+\.exe)"\s+%\*\s*', Path(shim).read_text(encoding="utf-8"))
            if match and Path(match[1]).is_file() and Path(match[1]).name.lower() == provider + ".exe":
                return [match[1]]
    found = shutil.which(provider)
    if found and Path(found).suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return [found]
    raise ValueError("Provider CLI unavailable; install its subscription CLI first")


def log_tail(path, limit=LOG_TAIL_BYTES):
    with Path(path).open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - limit))
        return handle.read().decode("utf-8", errors="replace")


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    directory = request_path.parent
    result = directory / "response.json"
    worktree = Path(request["worktree"]).resolve()
    if Path.cwd().resolve() != worktree or not worktree.is_dir():
        raise ValueError("Worker cwd mismatch")
    write_json(directory / "started.json", {"session_id": request["session_id"], "pid": os.getpid()})
    if request["adapter"] == "mock":
        action = request.get("mock", {})
        time.sleep(min(float(action.get("sleep", 0)), 60))
        if request["role"] == "implementation":
            filename = safe_relative(action.get("file", "src/center_mock.txt"))
            target = worktree / filename
            if sensitive(filename) or not inside(target, worktree) or target.is_symlink():
                raise ValueError("Unsafe mock target")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(action.get("content", "Center mock implementation\n"), encoding="utf-8")
        failures = action.get("failures", [])
        error = failures[request["attempt"] - 1] if len(failures) >= request["attempt"] else None
        payload = {"simulated": True, "summary": "mock adapter only", "error": error,
                   "verdict": action.get("verdict", "approved"), "task_id": request["task_id"],
                   "base_rev": request["base_rev"], "patch_hash": request.get("patch_hash")}
        write_json(result, payload)
        return 1 if error else 0
    if request["adapter"] != "live" or request["provider"] not in ("codex", "claude", "google"):
        raise ValueError("Unsupported live adapter")
    role = request["role"]
    properties = {'task_id': {'type': 'string'}, 'base_rev': {'type': 'string'}, 'summary': {'type': 'string'}}
    if role == 'review':
        properties.update({'patch_hash': {'type': 'string'}, 'verdict': {'type': 'string', 'enum': ['approved', 'rejected']}})
    else:
        properties['status'] = {'type': 'string', 'enum': ['completed', 'blocked']}
        if request['provider'] == 'codex':
            properties['edits'] = {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'properties': {'path': {'type': 'string'}, 'operation': {'type': 'string', 'enum': ['write', 'delete']},
                               'expected_sha256': {'type': 'string'}, 'content': {'type': 'string'}},
                'required': ['path', 'operation', 'expected_sha256', 'content']}}
    schema = {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': list(properties)}
    schema_path = directory / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    prompt = request["prompt"]
    final = directory / "provider-final.json"
    command = cli_command(request["provider"])
    if request["provider"] == "codex":
        command += ["exec", "--ignore-user-config", "--sandbox", "read-only",
                    "--output-schema", str(schema_path), "--output-last-message", str(final), "--json", "--color", "never", "-"]
    elif request["provider"] == "google":
        # agy takes the prompt as an argument and cannot prompt for permissions headlessly, so no shell commands are allowed:
        # send the task inline (short enough for the Windows command line) and tell it Center runs the gates.
        notice = ("You cannot run shell commands in this session; do not try. Use only file viewing/search and file editing tools. "
                  "Center runs the tests and gates after you finish. Your final answer must be only the JSON object the task asks for.")
        full = notice + " " + prompt
        if len(full) > 20000:
            raise ValueError("Task prompt too large for the Google adapter; narrow the task scope")
        command += ["--output-format", "json", "--mode", "plan" if role == "review" else "accept-edits",
                    "--json-schema", str(schema_path), "--add-dir", str(directory), "--print=" + full]
    else:
        tools = "Read,Glob,Grep" if role == "review" else "Read,Glob,Grep,Edit,Write"
        command += ["--print", "--restricted", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--tools", tools, "--allowedTools", tools, "--permission-mode", "manual" if role == "review" else "acceptEdits",
                    "--output-format", "json", "--json-schema", json.dumps(schema)]
        if role == 'review':
            command += ['--add-dir', str(directory)]
    if request.get("model"):
        command += ["--model", request["model"]]
    effort = request.get("effort")
    if effort and request["provider"] == "codex":
        command[command.index("exec") + 1:command.index("exec") + 1] = ["-c", f'model_reasoning_effort="{effort}"']
    elif effort and request["provider"] == "claude":
        command += ["--effort", effort]
    # No API credentials are injected; the CLI manages its own existing login.
    with (directory / "provider.log").open("wb") as out:
        # agy prints diagnostics on stderr; keep them out of the JSON envelope.
        stderr = (directory / "provider.err").open("wb") if request["provider"] == "google" else subprocess.STDOUT
        try:
            proc = subprocess.run(command, input=None if request["provider"] == "google" else prompt.encode(), stdout=out, stderr=stderr,
                                  stdin=subprocess.DEVNULL if request["provider"] == "google" else None, env=worker_env(), check=False)
        finally:
            if stderr is not subprocess.STDOUT:
                stderr.close()
    if proc.returncode:
        # Classify from JSON envelopes/log records; the log itself never leaves the worker.
        write_json(result, {"error": classify_error(log_tail(directory / "provider.log")), "simulated": False})
        return proc.returncode
    if request["provider"] == "codex":
        payload = json.loads(final.read_text(encoding="utf-8"))
        observations = []
        for line in (directory / 'provider.log').read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    observations.append(item)
            except ValueError:
                continue
        payload['provider_session_ref'] = next((o.get('thread_id') for o in observations if o.get('type') == 'thread.started'), None)
        payload['models_observed'] = sorted({o['model'] for o in observations if isinstance(o.get('model'), str)})
    else:
        raw = (directory / "provider.log").read_text(encoding="utf-8")
        envelope = json.loads(raw)
        if request["provider"] == "google":
            if envelope.get("status") != "SUCCESS":
                write_json(result, {"error": classify_error(raw), "simulated": False})
                return 1
            payload = envelope.get("structured_output")
            if not isinstance(payload, dict):
                write_json(result, {"error": "provider_blocked", "simulated": False, "summary": "no structured output"})
                return 1
            payload["provider_session_ref"] = envelope.get("conversation_id")
            payload["models_observed"] = [request["model"]] if request.get("model") else []
        elif envelope.get("is_error"):
            # Whole envelope, so structured status fields and quota text are both seen.
            write_json(result, {"error": classify_error(raw), "simulated": False})
            return 1
        if request["provider"] != "google":
            payload = envelope.get("structured_output")
            if not isinstance(payload, dict):
                payload = json.loads(envelope.get("result", "{}"))
            payload['provider_session_ref'] = envelope.get('session_id')
            payload['models_observed'] = list(envelope.get('modelUsage', {}))
    if role == 'implementation':
        if payload.get('status') != 'completed':
            write_json(result, {'error': 'provider_blocked', 'simulated': False, 'provider_session_ref': payload.get('provider_session_ref'), 'summary': payload.get('summary')})
            return 1
        if request['provider'] == 'codex':
            payload['applied_paths'] = apply_edits(worktree, request['scope'], request['source_files'], payload.get('edits'), request.get('max_edit_bytes', 10485760))
            payload.pop('edits', None)
    payload["simulated"] = False
    write_json(result, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        # Only a classification leaves the worker; provider logs stay local.
        print(f"Adapter error: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2)
