with open('connector-template/connector.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """    if not center_dir:
        center_dir = str(ROOT.parent)"""

new_block = """    if not center_dir:
        candidate = ROOT.parent / "AI-command-center"
        if (candidate / "center_planner.py").is_file():
            center_dir = str(candidate)
        else:
            center_dir = str(ROOT.parent)"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('connector-template/connector.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: connector-template/connector.py center_planner path updated")
else:
    print("ERROR: old_block not found in connector-template/connector.py")
