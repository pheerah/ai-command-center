"""Project connector for the AI Dev Command Center, speaking only to its HTTP API.

It never reads or writes anything inside the Center. Connection details come from
center.connection.json (git-excluded, created by the Center's installer) or from the
CENTER_URL / CENTER_TOKEN environment variables. Stdlib only.

Commands: health | submit | list | status ID | report ID | cancel ID | patch ID | wait ID | apply ID
          allow-direct --minutes N --reason TEXT | revoke-direct   (time-limited direct editing; the edit-guard hook honours it)
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
FINAL = ('ready_for_human_approval', 'approved', 'failed', 'blocked', 'cancelled', 'rejected')


def blocked(reason):
    print(json.dumps({'state': 'blocked', 'reason': reason, 'policy': 'no_silent_ide_takeover'}, ensure_ascii=False))
    return 2


def connection():
    url, token = os.environ.get('CENTER_URL'), os.environ.get('CENTER_TOKEN')
    if not (url and token):
        data = json.loads((ROOT / 'center.connection.json').read_text(encoding='utf-8'))
        url, token = data['url'], data['token']
    host = urllib.parse.urlparse(url).hostname
    if host not in ('127.0.0.1', 'localhost', '::1'):
        # The token is a bearer secret: it is only ever sent to this machine's Center.
        raise ValueError('The Center URL must be loopback (127.0.0.1 / localhost)')
    return url.rstrip('/'), token


def request(method, path, body=None, attempts=1):
    url, token = connection()
    data = json.dumps(body).encode('utf-8') if body is not None else None
    for attempt in range(attempts):
        req = urllib.request.Request(url + path, data=data, method=method,
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read()).get('error', '')
            except ValueError:
                message = ''
            if exc.code == 503 and attempt + 1 < attempts:  # busy Center: retry with the same request id
                time.sleep(3)
                continue
            raise RuntimeError(f'Center answered {exc.code}: {message}') from exc
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 >= attempts:
                raise
            time.sleep(3)


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=False)


def safe_target(relative):
    """A patch path must stay a plain relative path inside this project (no .., drive, absolute or .git)."""
    pure = PurePosixPath(relative.replace(chr(92), '/'))
    if pure.is_absolute() or not pure.parts or '..' in pure.parts or '.git' in pure.parts or ':' in relative:
        raise RuntimeError('Unsafe path in patch: ' + relative)
    return ROOT.joinpath(*pure.parts)


def write_new_file(relative, data):
    """Create a file exclusively (never follows or replaces an existing path) after re-checking its parents at write time."""
    target = safe_target(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if ROOT not in Path(os.path.realpath(target.parent)).parents and Path(os.path.realpath(target.parent)) != ROOT:
        raise RuntimeError('Refusing to write outside the project: ' + relative)
    with open(target, 'xb') as stream:
        stream.write(data)


DIRECT_EDIT = ROOT / '.center-direct-edit.json'
MAX_DIRECT_MINUTES = 240


def allow_direct(minutes, reason):
    """Open a short, recorded window in which the edit-guard hook lets Claude Code edit this checkout directly."""
    if not 1 <= minutes <= MAX_DIRECT_MINUTES or not reason.strip():
        raise RuntimeError(f'minutes must be 1-{MAX_DIRECT_MINUTES} and a reason is required')
    created = time.time()
    DIRECT_EDIT.write_text(json.dumps({'created_at': created, 'expires_at': created + minutes * 60, 'reason': reason.strip()[:300]}), encoding='utf-8')
    return {'direct_edit_until_epoch': created + minutes * 60, 'minutes': minutes, 'reason': reason.strip()[:300],
            'note': 'Direct edits skip the Center pipeline (no gates, no independent review). Use revoke-direct to close the window early.'}


def revoke_direct():
    existed = DIRECT_EDIT.exists()
    if existed:
        DIRECT_EDIT.unlink()
    return {'revoked': existed}


def apply_patch(task_id, dry_run):
    patch = request('GET', f'/api/v1/tasks/{task_id}/patch')
    if not patch['approved'] and not dry_run:
        raise RuntimeError('Task is not approved yet; the user approves in the Center terminal first (use --dry-run to preview)')
    if git('rev-parse', 'HEAD').stdout.strip() != patch['base_rev']:
        raise RuntimeError('This checkout is not at the patch base revision; update or rebase before applying')
    paths = [item['path'] for item in patch['files']]
    for item in patch['files']:
        data = base64.b64decode(item['content_base64'])
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise RuntimeError('Patch file failed its integrity check')
        target = safe_target(item['path'])
        if target.exists() or target.is_symlink():
            raise RuntimeError('Refusing to overwrite or write outside the project: ' + item['path'])
    tracked = base64.b64decode(patch['tracked_patch_base64'])  # bytes: a git patch need not be valid UTF-8
    with tempfile.NamedTemporaryFile('wb', suffix='.patch', delete=False) as handle:
        handle.write(tracked)
        name = handle.name
    try:
        if tracked.strip():
            check = git('apply', '--check', name)
            if check.returncode:
                raise RuntimeError('Patch does not apply cleanly: ' + check.stderr.strip()[:300])
            if not dry_run:
                applied = git('apply', name)
                if applied.returncode:
                    raise RuntimeError('git apply failed: ' + applied.stderr.strip()[:300])
    finally:
        os.unlink(name)
    if not dry_run:
        for item in patch['files']:
            write_new_file(item['path'], base64.b64decode(item['content_base64']))
    return {'task_id': task_id, 'applied': not dry_run, 'dry_run': dry_run, 'new_files': paths,
            'tracked_patch_bytes': len(tracked), 'note': 'Nothing was committed; review the diff and commit yourself.'}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('health')
    commands.add_parser('list')
    submit = commands.add_parser('submit')
    submit.add_argument('--title', required=True)
    submit.add_argument('--prompt', required=True)
    submit.add_argument('--scope', action='append', required=True)
    submit.add_argument('--accept', action='append', required=True)
    submit.add_argument('--provider', default='auto')
    submit.add_argument('--complexity', type=int, default=2, choices=range(1, 6))
    submit.add_argument('--depends-on', action='append', default=[])
    submit.add_argument('--read-file', action='append', default=[], help='A file inside --scope the AI must read (keeps its context small)')
    for name in ('status', 'report', 'cancel', 'patch'):
        commands.add_parser(name).add_argument('task_id')
    wait = commands.add_parser('wait')
    wait.add_argument('task_id')
    wait.add_argument('--timeout', type=int, default=1800)
    direct = commands.add_parser('allow-direct')
    direct.add_argument('--minutes', type=int, default=30)
    direct.add_argument('--reason', required=True)
    commands.add_parser('revoke-direct')
    apply = commands.add_parser('apply')
    apply.add_argument('task_id')
    apply.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'health':
            result = request('GET', '/api/v1/health')
        elif args.command == 'list':
            result = request('GET', '/api/v1/tasks')
        elif args.command == 'submit':
            # One request id per command, reused on retries, so a timeout never creates a duplicate task.
            result = request('POST', '/api/v1/tasks', {'title': args.title, 'prompt': args.prompt, 'scope': args.scope, 'accept': args.accept,
                                                       'provider': args.provider, 'complexity': args.complexity, 'depends_on': args.depends_on, 'read_files': args.read_file,
                                                       'request_id': uuid.uuid4().hex}, attempts=3)
        elif args.command in ('status', 'report'):
            result = request('GET', f'/api/v1/tasks/{args.task_id}')
            if args.command == 'status':
                result = result['task']
        elif args.command == 'cancel':
            result = request('POST', f'/api/v1/tasks/{args.task_id}/cancel', {})
        elif args.command == 'patch':
            result = request('GET', f'/api/v1/tasks/{args.task_id}/patch')
        elif args.command == 'apply':
            result = apply_patch(args.task_id, args.dry_run)
        elif args.command == 'allow-direct':
            result = allow_direct(args.minutes, args.reason)
        elif args.command == 'revoke-direct':
            result = revoke_direct()
        else:
            deadline = time.time() + args.timeout
            while True:
                result = request('GET', f'/api/v1/tasks/{args.task_id}')['task']
                if result['status'] in FINAL or time.time() > deadline:
                    break
                time.sleep(10)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return blocked(str(exc)[:300])


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
