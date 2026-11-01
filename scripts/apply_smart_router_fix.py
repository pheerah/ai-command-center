with open('smart_router.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_start = """            command = [sys.executable, str(ROOT / "smart_router.py"), "--state-dir", str(center.store.state)]"""
new_start = """            venv_py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            py_exec = str(venv_py) if venv_py.is_file() else sys.executable
            command = [py_exec, str(ROOT / "smart_router.py"), "--state-dir", str(center.store.state)]"""

content_norm = content.replace('\r\n', '\n')
if old_start in content_norm:
    content_norm = content_norm.replace(old_start, new_start)
    with open('smart_router.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: smart_router.py py_exec updated")
else:
    print("ERROR: old_start not found in smart_router.py")
