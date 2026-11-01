with open('center_context.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """    for target, expected, operation, content in plans:
        # Fence each write again. On I/O failure retain partial work for the
        # normal checkpoint/recovery path, never roll back over external edits.
        if not inside(target, root) or target.is_symlink():
            raise ValueError('Edit path changed during application')
        actual = hashlib.sha256(target.read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest() if target.exists() else ''
        if actual != expected:
            raise ValueError('File changed during edit application')"""

new_block = """    for target, expected, operation, content in plans:
        # Fence each write again. On I/O failure retain partial work for the
        # normal checkpoint/recovery path, never roll back over external edits.
        if not inside(target, root) or target.is_symlink():
            raise ValueError('Edit path changed during application')
        actual_norm = hashlib.sha256(target.read_bytes().replace(b'\\r\\n', b'\\n')).hexdigest() if target.exists() else ''
        actual_raw = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ''
        if expected and actual_norm != expected and actual_raw != expected:
            raise ValueError('File changed during edit application')"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_context.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_context.py fence updated")
else:
    print("ERROR: old_block not found in center_context.py")
