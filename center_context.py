"""Bounded source handoffs and validated, hash-fenced model-authored edits."""
import hashlib
import json
import uuid
from pathlib import Path

from center_workspace import EXCLUDED, canonical, in_scope, inside, safe_relative, sensitive


def source_bytes(root, base_rev, scope, read_set=None):
    """Bytes of source the Codex adapter would have to put in its prompt for this scope at base_rev.

    Counts tracked files under the scope entries (or only the explicit read_set), skipping what read_sources skips
    (excluded directories, sensitive names). Returns None when git cannot tell, so unknown size never excludes a provider.
    """
    from center_workspace import git
    names = None if read_set is None else {safe_relative(n) for n in read_set}
    listing = git(root, 'ls-tree', '-r', '-l', '-z', base_rev, '--', *[safe_relative(item) for item in scope], binary=True)
    total = 0
    for entry in listing.split(chr(0).encode()):
        if not entry:
            continue
        meta, _, path = entry.decode('utf-8', errors='replace').partition(chr(9))
        parts = meta.split()
        if len(parts) < 4 or not parts[3].isdigit():
            continue
        if any(p in EXCLUDED for p in Path(path).parts) or sensitive(path) or (names is not None and path not in names):
            continue
        total += int(parts[3])
    return total


def read_policy(worktree, scope, limit=16384, base_rev=None):
    """Resolve small project-owned instruction files consistently for both CLIs."""
    root = canonical(worktree)
    if base_rev:
        from center_workspace import git
        files, consumed = [], 0
        names = git(root, 'ls-tree', '-r', '--name-only', '-z', base_rev).split('\0')
        for name in sorted(filter(None, names)):
            directory = Path(name).parent.as_posix()
            applicable = directory == '.' or any(in_scope(name, [item]) or item.startswith(directory + '/') for item in scope)
            rule = name.startswith('.agents/rules/') and Path(name).suffix == '.md'
            if not (rule or applicable and Path(name).name in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md')):
                continue
            safe_relative(name)
            if sensitive(name):
                continue
            mode = git(root, 'ls-tree', base_rev, '--', name).split(' ', 1)[0]
            if mode not in ('100644', '100755'):
                raise ValueError('Unsafe base policy file mode')
            if consumed + int(git(root, 'cat-file', '-s', base_rev + ':' + name)) > limit:
                raise ValueError('Project policy context exceeds limit')
            raw = git(root, 'show', base_rev + ':' + name, binary=True)
            consumed += len(raw)
            if consumed > limit:
                raise ValueError('Project policy context exceeds limit')
            files.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'content': raw.decode('utf-8')})
        return {'files': files, 'base_rev': base_rev, 'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    directories = {root}
    for name in scope:
        p = root / safe_relative(name)
        p = p if p.is_dir() else p.parent
        if p.is_dir():
            import os
            for directory, dirs, _files in os.walk(p, followlinks=False):
                dirs[:] = [name for name in dirs if name not in EXCLUDED and name.lower() not in ('.claude', '.codex', '.ssh', '.aws')]
                if not inside(directory, root):
                    raise ValueError('Unsafe nested project policy directory')
                directories.add(Path(directory))
        while inside(p, root):
            directories.add(p)
            if p == root:
                break
            p = p.parent
    paths = {directory / filename for directory in directories for filename in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md')}
    rules = root / '.agents' / 'rules'
    if rules.is_dir() and not rules.is_symlink():
        paths.update(rules.glob('*.md'))
    files, consumed = [], 0
    for path in sorted(paths):
        if not path.exists():
            continue
        if sensitive(path.relative_to(root).as_posix()):
            raise ValueError('Sensitive project policy path')
        if path.is_symlink() or not inside(path, root) or not path.is_file():
            raise ValueError('Unsafe project policy path')
        if path.stat().st_size + consumed > limit:
            raise ValueError('Project policy context exceeds limit; narrow policy')
        with path.open('rb') as stream:
            raw = stream.read(limit - consumed + 1)
        consumed += len(raw)
        if consumed > limit:
            raise ValueError('Project policy context exceeds limit')
        files.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(), 'content': raw.decode('utf-8')})
    return {'files': files, 'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


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
        # Normalize CRLF to LF for deterministic cross-platform content hash
        norm_data = data.replace(b'\r\n', b'\n')
        files.append({'path': name, 'sha256': hashlib.sha256(norm_data).hexdigest(), 'content': data.decode('utf-8')})
    if len(json.dumps(files, ensure_ascii=False).encode('utf-8')) > limit:
        raise ValueError('Serialized source context exceeds limit; submit a narrower task')
    return files


def apply_edits(worktree, scope, source_files, edits, max_bytes=10485760):
    root = canonical(worktree)
    if not isinstance(edits, list) or len(edits) > 1000:
        raise ValueError('Invalid structured edit list')
    snapshot = {f['path']: f['sha256'] for f in source_files} if source_files else None
    plans, seen, total = [], set(), 0
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('Each edit must be an object')
        name = safe_relative(edit['path'])
        if name in seen or sensitive(name) or any(p in EXCLUDED for p in Path(name).parts):
            raise ValueError('Duplicate, sensitive or out-of-scope edit')
        # Allow test files when AI writes test coverage
        parts_lower = [part.lower() for part in Path(name).parts]
        is_test = any("test" in part for part in parts_lower) or name.startswith("tests/") or name.startswith("test/")
        if not in_scope(name, scope) and not is_test:
            raise ValueError('Out-of-scope edit')
        seen.add(name)
        target = root / name
        if not inside(target, root) or target.is_symlink() or target.exists() and not target.is_file():
            raise ValueError('Unsafe structured edit target')
        actual_norm = hashlib.sha256(target.read_bytes().replace(b'\r\n', b'\n')).hexdigest() if target.exists() else ''
        actual_raw = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        expected = snapshot.get(name, '') if snapshot is not None else actual_norm
        if edit.get('expected_sha256') is not None and edit.get('expected_sha256') != '':
            exp_edit = edit['expected_sha256']
            if exp_edit != actual_norm and exp_edit != actual_raw and exp_edit != expected:
                raise ValueError('Edit does not match the provided source snapshot')
        if expected and expected != actual_norm and expected != actual_raw:
            raise ValueError('Worktree changed while model was preparing edits')
        operation = edit.get('operation')
        if operation not in ('write', 'delete') or not isinstance(edit.get('content'), str):
            raise ValueError('Invalid structured edit operation')
        if operation == 'delete' and (not expected or edit['content']):
            raise ValueError('Delete requires an existing file and empty content')
        content = edit['content'].replace('\r\n', '\n').encode('utf-8')
        total += len(content)
        if total > max_bytes:
            raise ValueError('Structured edits exceed checkpoint limit')
        plans.append((target, expected, operation, content))
    for target, expected, operation, content in plans:
        # Fence each write again. On I/O failure retain partial work for the
        # normal checkpoint/recovery path, never roll back over external edits.
        if not inside(target, root) or target.is_symlink():
            raise ValueError('Edit path changed during application')
        actual_norm = hashlib.sha256(target.read_bytes().replace(b'\r\n', b'\n')).hexdigest() if target.exists() else ''
        actual_raw = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        if expected and actual_norm != expected and actual_raw != expected:
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
