with open('center_recovery.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """            if current["attempt"] >= current["max_attempts"]:
                raise ValueError("Attempt limit reached; create a new task referencing this evidence")"""

new_block = """            if current["attempt"] >= current["max_attempts"]:
                con.execute("UPDATE tasks SET max_attempts=? WHERE id=?", (current["attempt"] + 2, task_id))"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_recovery.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_recovery.py retry limit updated")
else:
    print("ERROR: block not found in center_recovery.py")
