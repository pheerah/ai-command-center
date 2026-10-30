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


def write_json(path, data):
    p = Path(path)
    temporary = p.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(p)


def cli_command(provider):
    """Resolve Windows npm shims without cmd.exe shell interpolation."""
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


def classify_error(text):
    value = text.lower()
    if any(x in value for x in ("unauthorized", "not logged in", "authentication", "invalid api key", "401", "403")):
        return "auth"
    if any(x in value for x in ("invalid model", "model not found", "unknown model", "unsupported model")):
        return "invalid_model"
    if any(x in value for x in ("quota", "usage limit", "rate limit", "429", "usage_exhausted", "hit your limit", "hit the limit")):
        return "rate_limit"
    if any(x in value for x in ("unknown option", "unrecognized argument", "invalid configuration", "permission denied")):
        return "config"
    return "worker_failure"


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
    if request["adapter"] != "live" or request["provider"] not in ("codex", "claude"):
        raise ValueError("Unsupported live adapter; Google requires explicit IDE handoff")
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
    else:
        tools = "Read,Glob,Grep" if role == "review" else "Read,Glob,Grep,Edit,Write"
        command += ["--print", "--restricted", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--tools", tools, "--allowedTools", tools, "--permission-mode", "manual" if role == "review" else "acceptEdits",
                    "--output-format", "json", "--json-schema", json.dumps(schema)]
        if role == 'review':
            command += ['--add-dir', str(directory)]
    if request.get("model"):
        command += ["--model", request["model"]]
    # No API credentials are injected; the CLI manages its own existing login.
    with (directory / "provider.log").open("wb") as out:
        proc = subprocess.run(command, input=prompt.encode(), stdout=out, stderr=subprocess.STDOUT, env=worker_env(), check=False)
    if proc.returncode:
        tail = (directory / "provider.log").read_bytes()[-16000:].decode("utf-8", errors="replace")
        write_json(result, {"error": classify_error(tail), "simulated": False})
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
        envelope = json.loads((directory / "provider.log").read_text(encoding="utf-8"))
        if envelope.get("is_error"):
            write_json(result, {"error": classify_error(str(envelope.get('result', ''))), "simulated": False})
            return 1
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
