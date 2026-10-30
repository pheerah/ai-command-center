"""Bounded source handoffs and validated, hash-fenced model-authored edits."""
import hashlib
import json
import uuid
from pathlib import Path

from center_workspace import EXCLUDED, canonical, in_scope, inside, safe_relative, sensitive


def read_sources(worktree, scope, limit=65536, names=None):
    root = canonical(worktree)
    selected = set()
    if names is not None:
        selected.update(names)
    else:
        for item in scope:
            relative = safe_relative(item)
            p = root / relative
            if not inside(p, root) or p.is_symlink():
                raise ValueError('Context path aliases or escapes worktree')
            if p.is_dir():
                # Do not follow links, inspect dependency contents or silently
                # truncate a source snapshot. Narrow the task if it is too big.
                import os
                for directory, dirs, files in os.walk(p, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in EXCLUDED]
                    for d in dirs:
                        if (Path(directory) / d).is_symlink():
                            raise ValueError('Linked context directory is not supported')
                    selected.update((Path(directory) / f).relative_to(root).as_posix() for f in files)
            elif p.exists():
                selected.add(relative)
    files, consumed = [], 0
    for name in sorted(selected):
        safe_relative(name)
        if not in_scope(name, scope) or sensitive(name) or any(p in EXCLUDED for p in Path(name).parts):
            raise ValueError('Unsafe or out-of-scope source context')
        p = root / name
        if not inside(p, root) or p.is_symlink():
            raise ValueError('Linked source context is not supported')
        if not p.exists():
            files.append({'path': name, 'sha256': '', 'deleted': True, 'content': ''})
            continue
        if consumed + p.stat().st_size > limit:
            raise ValueError('Scoped source exceeds context limit; submit a narrower task')
        with p.open('rb') as stream:
            data = stream.read(limit - consumed + 1)
        consumed += len(data)
        if consumed > limit:
            raise ValueError('Source changed beyond context limit while reading')
        files.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'content': data.decode('utf-8')})
    if len(json.dumps(files, ensure_ascii=False).encode('utf-8')) > limit:
        raise ValueError('Serialized source context exceeds limit; submit a narrower task')
    return files


def apply_edits(worktree, scope, source_files, edits, max_bytes=10485760):
    root = canonical(worktree)
    if not isinstance(edits, list) or len(edits) > 1000:
        raise ValueError('Invalid structured edit list')
    snapshot = {f['path']: f['sha256'] for f in source_files}
    plans, seen, total = [], set(), 0
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('Each edit must be an object')
        name = safe_relative(edit['path'])
        if name in seen or sensitive(name) or not in_scope(name, scope) or any(p in EXCLUDED for p in Path(name).parts):
            raise ValueError('Duplicate, sensitive or out-of-scope edit')
        seen.add(name)
        target = root / name
        if not inside(target, root) or target.is_symlink() or target.exists() and not target.is_file():
            raise ValueError('Unsafe structured edit target')
        expected = snapshot.get(name, '')
        if edit.get('expected_sha256') != expected:
            raise ValueError('Edit does not match the provided source snapshot')
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        if actual != expected:
            raise ValueError('Worktree changed while model was preparing edits')
        operation = edit.get('operation')
        if operation not in ('write', 'delete') or not isinstance(edit.get('content'), str):
            raise ValueError('Invalid structured edit operation')
        if operation == 'delete' and (not expected or edit['content']):
            raise ValueError('Delete requires an existing file and empty content')
        content = edit['content'].encode('utf-8')
        total += len(content)
        if total > max_bytes:
            raise ValueError('Structured edits exceed checkpoint limit')
        plans.append((target, expected, operation, content))
    for target, expected, operation, content in plans:
        # Fence each write again. On I/O failure retain partial work for the
        # normal checkpoint/recovery path, never roll back over external edits.
        if not inside(target, root) or target.is_symlink():
            raise ValueError('Edit path changed during application')
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        if actual != expected:
            raise ValueError('File changed during edit application')
        if operation == 'delete':
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name('.center-edit-' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
    return [p.relative_to(root).as_posix() for p, _, _, _ in plans]
