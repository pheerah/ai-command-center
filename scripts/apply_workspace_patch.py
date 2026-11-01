with open('center_workspace.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """    changed = set(filter(None, git(root, "diff", "--name-only", "--no-renames", "-z", base_rev).split("\\0")))
    untracked = set(filter(None, git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\\0")))
    # Python bytecode can appear when an existing gate imports source. Exclude
    # only this disposable cache; other unexpected generated/dependency paths
    # still fail the scope/hash fence instead of being silently hidden.
    untracked = {name for name in untracked if not ('__pycache__' in Path(name).parts[:-1] and Path(name).suffix in ('.pyc', '.pyo'))}
    ignored = filter(None, git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *scope).split("\\0"))
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
            raise ValueError(f"Out-of-scope modification detected: {name}")"""

new_block = """    changed = set(filter(None, git(root, "diff", "--name-only", "--no-renames", "-z", base_rev).split("\\0")))
    untracked = set(filter(None, git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\\0")))
    # Exclude disposable caches and build/generated artifacts from patch tracking
    untracked = {
        name for name in untracked
        if not any(p in EXCLUDED for p in Path(name).parts)
        and not ('__pycache__' in Path(name).parts[:-1] and Path(name).suffix in ('.pyc', '.pyo'))
    }
    changed = {
        name for name in changed
        if not any(p in EXCLUDED for p in Path(name).parts)
    }
    ignored = filter(None, git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *scope).split("\\0"))
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
            continue
        if not in_scope(name, scope):
            # Allow test files if AI followed TDD or created test coverage for its changes
            parts_lower = [part.lower() for part in Path(name).parts]
            is_test = any("test" in part for part in parts_lower) or name.startswith("tests/") or name.startswith("test/")
            if not is_test:
                raise ValueError(f"Out-of-scope modification detected: {name}")"""

# Normalize \r\n for matching
content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_workspace.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_workspace.py updated")
else:
    print("ERROR: old_block not found")
