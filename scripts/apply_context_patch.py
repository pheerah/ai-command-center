with open('center_context.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """        with p.open('rb') as stream:
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
    snapshot = {f['path']: f['sha256'] for f in source_files} if source_files else None
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
        expected = snapshot.get(name, '') if snapshot is not None else (hashlib.sha256(target.read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest() if target.exists() else '')
        if edit.get('expected_sha256') is not None and edit.get('expected_sha256') != '' and edit.get('expected_sha256') != expected:
            raise ValueError('Edit does not match the provided source snapshot')
        actual = hashlib.sha256(target.read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest() if target.exists() else ''
        if actual != expected:
            raise ValueError('Worktree changed while model was preparing edits')"""

new_block = """        with p.open('rb') as stream:
            data = stream.read(limit - consumed + 1)
        consumed += len(data)
        if consumed > limit:
            raise ValueError('Source changed beyond context limit while reading')
        # Normalize CRLF to LF for deterministic cross-platform content hash
        norm_data = data.replace(b'\\r\\n', b'\\n')
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
        actual_norm = hashlib.sha256(target.read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest() if target.exists() else ''
        actual_raw = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        expected = snapshot.get(name, '') if snapshot is not None else actual_norm
        if edit.get('expected_sha256') is not None and edit.get('expected_sha256') != '':
            exp_edit = edit['expected_sha256']
            if exp_edit != actual_norm and exp_edit != actual_raw and exp_edit != expected:
                raise ValueError('Edit does not match the provided source snapshot')
        if expected and expected != actual_norm and expected != actual_raw:
            raise ValueError('Worktree changed while model was preparing edits')"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_context.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_context.py updated")
else:
    print("ERROR: old_block not found in center_context.py")
